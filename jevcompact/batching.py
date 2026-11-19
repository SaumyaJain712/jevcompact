"""Pack judge questions into requests under the token cap and run them in parallel."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .judges.base import Judge, Question
from .ratelimit import RateLimiter
from .tokens import count_tokens

# Our token counts use cl100k_base; Jev's tokenizer may differ, so requests
# are packed to 95% of the 32k cap to stay safely under the real limit.
SAFETY = 0.95  # recalibrated against Jev usage.input_tokens in phase (b)
QUESTION_OVERHEAD = 8  # JSON key + type per question


class JudgeFailure(RuntimeError):
    """Any judge error or timeout. The pipeline answers it by falling back."""


def effective_cap(max_request_tokens: int) -> int:
    return int(max_request_tokens * SAFETY)


def question_cost(q: Question) -> int:
    return count_tokens(q.text) + QUESTION_OVERHEAD


@dataclass
class JudgeRequest:
    state: str
    questions: list[Question]
    tokens: int


def pack(header: str, blocks: list[tuple[str, Question]], cap: int, sep: str = "\n\n") -> list[JudgeRequest]:
    """Greedily pack (state block, question) pairs into requests of at most `cap` tokens.

    Callers clip each block beforehand so that header + one block + its
    question always fits.
    """
    header_tokens = count_tokens(header)
    sep_tokens = count_tokens(sep)
    requests: list[JudgeRequest] = []
    cur_blocks: list[str] = []
    cur_qs: list[Question] = []
    cur = header_tokens

    def flush():
        nonlocal cur_blocks, cur_qs, cur
        if cur_qs:
            requests.append(JudgeRequest(header + sep.join(cur_blocks), cur_qs, cur))
        cur_blocks, cur_qs, cur = [], [], header_tokens

    for block, q in blocks:
        cost = count_tokens(block) + sep_tokens + question_cost(q)
        if cur_qs and cur + cost > cap:
            flush()
        cur_blocks.append(block)
        cur_qs.append(q)
        cur += cost
    flush()
    return requests


@dataclass
class BatchOutcome:
    scores: dict[str, float] = field(default_factory=dict)
    requests: int = 0
    input_tokens: int = 0
    latency_ms: float = 0.0


async def run_requests(judge: Judge, requests: list[JudgeRequest], limiter: RateLimiter,
                       timeout_s: float) -> BatchOutcome:
    """Send all requests in parallel; any failure or timeout raises JudgeFailure."""
    out = BatchOutcome(requests=len(requests))
    t0 = time.perf_counter()

    async def one(req: JudgeRequest):
        await limiter.acquire(req.tokens)
        return await asyncio.wait_for(judge.evaluate(req.state, req.questions), timeout_s)

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(one(r)) for r in requests]
    except* (asyncio.TimeoutError, TimeoutError) as eg:
        raise JudgeFailure(f"Jev didn't respond in {timeout_s:g} s") from eg.exceptions[0]
    except* Exception as eg:
        raise JudgeFailure(f"Jev request failed: {eg.exceptions[0]}") from eg.exceptions[0]

    for req, task in zip(requests, tasks):
        resp = task.result()
        missing = [q.id for q in req.questions if q.id not in resp.scores]
        if missing:
            raise JudgeFailure(f"Jev returned no answer for {missing[:3]}")
        for q in req.questions:
            out.scores[q.id] = min(1.0, max(0.0, float(resp.scores[q.id])))
        out.input_tokens += resp.input_tokens or req.tokens
    out.latency_ms = (time.perf_counter() - t0) * 1000
    return out
