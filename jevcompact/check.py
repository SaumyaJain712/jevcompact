"""Step 4, Check: ask the judge whether each summary line has a source in the tool outputs."""
from __future__ import annotations

from dataclasses import dataclass, field

from .batching import JudgeRequest, effective_cap, question_cost, run_requests
from .config import CompactionConfig
from .judges.base import SOURCE_QUESTION, Judge, Question
from .ratelimit import RateLimiter
from .tokens import clip_to_tokens, count_tokens

HEADER = "TOOL OUTPUTS (the only allowed sources):\n\n"


@dataclass
class CheckOutcome:
    kept: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    line_scores: list[tuple[str, float | None]] = field(default_factory=list)
    requests: int = 0
    input_tokens: int = 0


def summary_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _source_chunks(sources: list[tuple[str, str]], total_cap: int, chunk_cap: int) -> list[str]:
    per_item = max(120, total_cap // max(1, len(sources)))
    blocks = [f"[{title}]\n{clip_to_tokens(text, per_item)}" for title, text in sources]
    chunks, cur, cur_tokens = [], [], 0
    for b in blocks:
        t = count_tokens(b)
        if cur and cur_tokens + t > chunk_cap:
            chunks.append("\n\n".join(cur))
            cur, cur_tokens = [], 0
        cur.append(clip_to_tokens(b, chunk_cap))
        cur_tokens += min(t, chunk_cap)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks or ["(no tool outputs)"]


async def check_summary(summary: str, sources: list[tuple[str, str]], config: CompactionConfig,
                        judge: Judge, limiter: RateLimiter) -> CheckOutcome:
    lines = summary_lines(summary)
    out = CheckOutcome()
    if not lines:
        return out
    cap = effective_cap(config.jev_max_request_tokens)
    questions = [Question(f"l{j}", "source", SOURCE_QUESTION.format(line=ln.strip()[:600]), ln)
                 for j, ln in enumerate(lines)]
    # Questions take at most a quarter of each request; sources fill the rest.
    q_groups, cur, cur_t = [], [], 0
    for q in questions:
        c = question_cost(q)
        if cur and cur_t + c > cap // 4:
            q_groups.append(cur)
            cur, cur_t = [], 0
        cur.append(q)
        cur_t += c
    q_groups.append(cur)
    chunk_cap = cap - cap // 4 - count_tokens(HEADER) - 64
    chunks = _source_chunks(sources, config.check_source_max_tokens, chunk_cap)

    requests = []
    for qs in q_groups:
        q_tokens = sum(question_cost(q) for q in qs)
        for ch in chunks:
            state = HEADER + ch
            requests.append(JudgeRequest(state, qs, count_tokens(state) + q_tokens))
    res = await run_requests(judge, requests, limiter, config.jev_timeout_s)

    # A line is supported if any source chunk supports it (max over chunks).
    best: dict[str, float] = {}
    for req in requests:
        for q in req.questions:
            best[q.id] = max(best.get(q.id, 0.0), res.scores[q.id])
    for q, ln in zip(questions, lines):
        s = best[q.id]
        out.line_scores.append((ln, s))
        (out.kept if s >= config.check_threshold else out.removed).append(ln)
    out.requests, out.input_tokens = res.requests, res.input_tokens
    return out
