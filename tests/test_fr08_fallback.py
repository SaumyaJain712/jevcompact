"""FR8 + TC-08: fall back to the plain summary when Jev fails, times out or saves too little."""
import pytest
from conftest import const_judge
from factories import Step, build, filler

from jevcompact import CompactionConfig, CompactionError, MockJudge, MockSummarizer, compact, user_messages_lost


def session():
    return build([Step(f"cat src/f{i}.ts", filler(600, f"f{i}"), user_after="keep going" if i == 3 else None)
                  for i in range(12)])


async def test_tc08_jev_timeout_uses_plain_summary(store):
    summ = MockSummarizer()
    cfg = CompactionConfig(budget=2000, jev_timeout_s=0.2)
    res = await compact(session(), cfg, judge=MockJudge(timeout=True), summarizer=summ, recall_store=store)
    assert res.status == "Fell back"
    assert "didn't respond in 0.2 s" in res.fallback_reason
    assert summ.calls == 1 and res.summary is not None and not res.summary.checked
    assert user_messages_lost(session(), res.messages) == 0
    assert res.tokens_after < res.tokens_before


async def test_default_timeout_is_5s():
    assert CompactionConfig().jev_timeout_s == 5.0


async def test_jev_error_falls_back(store):
    res = await compact(session(), CompactionConfig(budget=2000), judge=MockJudge(fail=True),
                        summarizer=MockSummarizer(), recall_store=store)
    assert res.status == "Fell back" and "failed" in res.fallback_reason
    assert all(d.action in ("Pinned", "Kept") and d.score is None for d in res.decisions)


async def test_low_savings_falls_back(store):
    res = await compact(session(), CompactionConfig(budget=2000), judge=const_judge(0.99),
                        summarizer=MockSummarizer(), recall_store=store)
    assert res.status == "Fell back"
    assert "saved only 0%" in res.fallback_reason


async def test_check_failure_falls_back(store):
    class FailOnCheck(MockJudge):
        async def evaluate(self, state, questions):
            if questions[0].kind == "source":
                raise RuntimeError("boom")
            return await super().evaluate(state, questions)

    res = await compact(session(), CompactionConfig(budget=1200), judge=FailOnCheck(score_fn=lambda q, s: 0.3),
                        summarizer=MockSummarizer(), recall_store=store)
    assert res.status == "Fell back" and "Summary check failed" in res.fallback_reason


async def test_fallback_disabled_raises(store):
    with pytest.raises(CompactionError):
        await compact(session(), CompactionConfig(budget=2000, fallback_enabled=False),
                      judge=MockJudge(fail=True), summarizer=MockSummarizer(), recall_store=store)
