"""NFRs: performance (TC-P1), cost, reliability (property test), maintainability."""
import json
import random
from pathlib import Path
from statistics import quantiles

import pytest
from factories import Step, build, filler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from jevcompact import (CompactionConfig, Judge, MemoryRecallStore, MockJudge, MockSummarizer, Summarizer, compact,
                        parse_session, user_messages_lost)
from jevcompact.judges.base import JudgeError
from jevcompact.tokens import count_tokens

MEASURE_DIR = Path(__file__).resolve().parents[1] / "docs" / "measurements"


def _p95(xs):
    return quantiles(xs, n=20)[-1]


def session_with_candidate_tokens(target: int):
    steps, total, i = [], 0, 0
    while total < target:
        out = filler(280, f"c{i}")
        total += min(count_tokens(out), 300)
        steps.append(Step(f"cat src/c{i}.ts", out))
        i += 1
    steps.append(Step("echo done", "done"))
    return build(steps)


@pytest.mark.perf
async def test_tc_p1_p95_under_1s_with_jev_latency():
    """TC-P1: 32k tokens of candidates, MockJudge latency uniform in Jev's 70-500 ms range."""
    msgs = session_with_candidate_tokens(32_000)
    scoring, total = [], []
    for seed in range(30):
        judge = MockJudge(latency_ms=(70, 500), seed=seed)
        res = await compact(msgs, CompactionConfig(budget=8_000), judge=judge, summarizer=MockSummarizer(),
                            recall_store=MemoryRecallStore())
        scoring.append(res.scoring_latency_ms)
        total.append(res.latency_ms)
    p95_scoring, p95_total = _p95(scoring), _p95(total)
    MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    (MEASURE_DIR / "tc_p1_latency.json").write_text(json.dumps({
        "source": "mock", "judge": "mock (latency 70-500 ms uniform)",
        "summarizer": "mock (no summarizer time)", "runs": len(scoring), "candidate_tokens": 32_000,
        "p95_scoring_ms": round(p95_scoring, 1), "p95_prune_check_ms": round(p95_total, 1),
        "scoring_ms": scoring, "prune_check_ms": total}, indent=2))
    assert p95_scoring < 1000


@pytest.mark.perf
async def test_cost_per_compaction_under_002():
    """180k-token session: Jev spend must stay at or under $0.002."""
    steps = [Step(f"cat src/big{i}.ts", filler(1500, f"b{i}")) for i in range(118)]
    steps.append(Step("echo done", "done"))
    msgs = build(steps)
    res = await compact(msgs, CompactionConfig(), judge=MockJudge(), summarizer=MockSummarizer(),
                        recall_store=MemoryRecallStore())
    assert res.tokens_before > 170_000
    MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    (MEASURE_DIR / "cost.json").write_text(json.dumps({
        "source": "mock", "judge": "mock (tiktoken counts, not Jev-billed usage)", "tokens_before": res.tokens_before,
        "jev_input_tokens": res.jev_input_tokens, "jev_cost_usd": res.jev_cost_usd,
        "price_per_m_input": 0.042}, indent=2))
    assert res.jev_cost_usd <= 0.002


class RandomJudge:
    name = "random"

    def __init__(self, seed: int, fail_rate: float):
        self.rng = random.Random(seed)
        self.fail_rate = fail_rate

    async def evaluate(self, state, questions):
        from jevcompact.judges.base import JudgeResponse

        if self.rng.random() < self.fail_rate:
            raise JudgeError("random failure")
        return JudgeResponse({q.id: self.rng.random() for q in questions}, input_tokens=10)

    async def test_connection(self):
        return True


step_st = st.builds(
    Step,
    command=st.sampled_from(["ls node_modules", "cat src/a.ts", "grep price", "npm test", "cat README.md"]),
    output=st.integers(1, 400).map(lambda n: "data line\n" * n),
    is_error=st.booleans(),
    user_after=st.one_of(st.none(), st.text(min_size=1, max_size=40).filter(lambda s: s.strip())),
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(steps=st.lists(step_st, min_size=1, max_size=25), fmt=st.sampled_from(["openai", "anthropic"]),
       budget=st.integers(50, 6000), seed=st.integers(0, 10**6), fail_rate=st.sampled_from([0.0, 0.0, 0.3, 1.0]),
       preset=st.sampled_from(["conservative", "balanced", "aggressive"]), invent=st.booleans())
async def test_reliability_zero_user_messages_lost(steps, fmt, budget, seed, fail_rate, preset, invent):
    msgs = build(steps, fmt)
    res = await compact(msgs, CompactionConfig(budget=budget, preset=preset), judge=RandomJudge(seed, fail_rate),
                        summarizer=MockSummarizer(invent=invent), recall_store=MemoryRecallStore())
    assert user_messages_lost(msgs, res.messages) == 0
    assert res.status in ("Compacted", "Fell back", "Under budget")
    assert all(d.action == "Pinned" for d in res.decisions if d.role in ("USER", "ERROR"))
    parse_session(res.messages)  # output is still a valid session


def test_providers_swappable_behind_protocols():
    assert isinstance(MockJudge(), Judge)
    assert isinstance(RandomJudge(0, 0), Judge)
    assert isinstance(MockSummarizer(), Summarizer)
