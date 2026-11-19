"""FR4 + TC-04: score every old tool result, split into parallel requests under 32k tokens."""
import asyncio

from factories import Step, build, filler

from jevcompact import CompactionConfig, MockJudge, compact
from jevcompact.batching import JudgeFailure, effective_cap, pack, run_requests
from jevcompact.judges.base import JudgeResponse, Question
from jevcompact.ratelimit import RateLimiter
from jevcompact.tokens import count_tokens


def fifty_k_session():
    # 250 tool outputs of ~200 tokens (under the per-item clip) = ~50k candidate tokens
    steps = [Step(f"cat notes/part_{i}.md", filler(190, f"p{i}")) for i in range(250)]
    steps.append(Step("echo done", "done"))
    return build(steps)


async def test_tc04_50k_tokens_split_into_two_requests(store, summarizer):
    msgs = fifty_k_session()
    judge = MockJudge()
    res = await compact(msgs, CompactionConfig(budget=20_000), judge=judge, summarizer=summarizer, recall_store=store)
    keep_calls = [(s, qs) for s, qs in judge.calls if qs[0].kind == "keep"]
    candidate_tokens = sum(count_tokens(q.subject) for _, qs in keep_calls for q in qs)
    assert 45_000 <= candidate_tokens <= 55_000
    assert len(keep_calls) == 2
    for state, qs in keep_calls:
        assert count_tokens(state) + sum(count_tokens(q.text) for q in qs) < 32_000
    scored = {q.id for _, qs in keep_calls for q in qs}
    assert len(scored) == 250  # every old tool result scored (the last turn is pinned)
    assert res.jev_requests >= 2


async def test_requests_run_in_parallel():
    judge = MockJudge(latency_ms=(200, 200))
    qs = [Question(f"t{i}", "keep", "q", "x") for i in range(4)]
    reqs = pack("H", [("block " * 2000, q) for q in qs], cap=3000)
    assert len(reqs) == 4
    t = asyncio.get_running_loop().time()
    await run_requests(judge, reqs, RateLimiter(80, 100_000), 5)
    assert asyncio.get_running_loop().time() - t < 0.6  # 4 x 200 ms in parallel, not 800 ms


def test_effective_cap_below_32k():
    assert effective_cap(32_000) < 32_000


async def test_missing_answer_is_failure():
    class Bad:
        name = "bad"

        async def evaluate(self, state, questions):
            return JudgeResponse(scores={})

    reqs = pack("H", [("b", Question("t1", "keep", "q"))], 1000)
    try:
        await run_requests(Bad(), reqs, RateLimiter(80, 100_000), 5)
    except JudgeFailure as e:
        assert "no answer" in str(e)
    else:
        raise AssertionError("expected JudgeFailure")


async def test_rate_limiter_enforces_requests_per_second():
    lim = RateLimiter(requests_per_s=10, tokens_per_s=10**9)
    loop = asyncio.get_running_loop()
    t = loop.time()
    for _ in range(15):
        await lim.acquire(1)
    assert loop.time() - t >= 0.4  # 10 burst, then 5 more at 10/s
