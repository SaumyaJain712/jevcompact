"""FR6: summarize only while still over budget.  FR7: remove unsupported summary lines."""
from conftest import const_judge
from factories import Step, build, filler

from jevcompact import CompactionConfig, MockJudge, MockSummarizer, compact
from jevcompact.formats import SUMMARY_HEADER
from jevcompact.summarizers.mock import INVENTED_LINE


def big_session(n=10, size=800):
    return build([Step(f"cat src/mod{i}.ts", filler(size, f"m{i}")) for i in range(n)])


async def test_no_summary_when_prune_is_enough(store):
    summ = MockSummarizer()
    res = await compact(big_session(), CompactionConfig(budget=3000), judge=const_judge(0.01), summarizer=summ,
                        recall_store=store)
    assert res.tokens_after <= 3000
    assert summ.calls == 0 and res.summary is None


async def test_summary_when_still_over_budget(store):
    summ = MockSummarizer()
    res = await compact(big_session(), CompactionConfig(budget=3000), judge=const_judge(0.9), summarizer=summ,
                        recall_store=store, method="hybrid")
    # everything kept -> saves < 10% -> fell back to plain summary, which still summarizes
    assert summ.calls == 1
    assert res.status == "Fell back"


async def test_summary_after_prune(store):
    summ = MockSummarizer()
    # scores ~0.38 (Cut) still leaves it over a tiny budget -> summarize the oldest turns
    res = await compact(big_session(20, 800), CompactionConfig(budget=1500), judge=const_judge(0.38),
                        summarizer=summ, recall_store=store)
    assert res.status == "Compacted"
    assert summ.calls == 1 and res.summary is not None
    assert any(d.summarized for d in res.decisions)
    header = SUMMARY_HEADER.format(n=res.summary.summarized_messages)
    assert any(isinstance(m["content"], str) and m["content"].startswith(header) for m in res.messages)


async def test_fr07_invented_line_removed(store):
    summ = MockSummarizer(invent=True)
    res = await compact(big_session(20, 800), CompactionConfig(budget=1500), judge=MockJudge(), summarizer=summ,
                        recall_store=store)
    assert res.summary is not None and res.summary.checked
    assert INVENTED_LINE in res.summary.lines_removed
    assert INVENTED_LINE not in "\n".join(m["content"] for m in res.messages if isinstance(m["content"], str))
    assert len(res.summary.lines_kept) >= 1


async def test_check_threshold_is_configurable(store):
    res = await compact(big_session(20, 800), CompactionConfig(budget=1500, check_threshold=0.0),
                        judge=MockJudge(), summarizer=MockSummarizer(invent=True), recall_store=store)
    assert res.summary.lines_removed == []
