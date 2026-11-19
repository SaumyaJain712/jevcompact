"""FR2: compaction starts automatically when the context passes the budget."""
from factories import checkout_session

from jevcompact import CompactionConfig, JevCompactMiddleware, compact
from jevcompact.formats import total_tokens


async def test_under_budget_is_untouched(judge, summarizer, store):
    msgs = checkout_session()
    res = await compact(msgs, CompactionConfig(budget=10**6), judge=judge, summarizer=summarizer, recall_store=store)
    assert res.status == "Under budget"
    assert res.messages == msgs
    assert judge.calls == []


async def test_middleware_triggers_at_budget(judge, summarizer, store):
    msgs = checkout_session()
    budget = total_tokens(msgs[:8]) + 10
    mw = JevCompactMiddleware(CompactionConfig(budget=budget), judge=judge, summarizer=summarizer, recall_store=store)
    seen = []

    async def llm(messages):
        seen.append(total_tokens(messages))
        return {"role": "assistant", "content": "ok"}

    step = mw.wrap(llm)
    await step(msgs[:6])  # under budget: no compaction
    assert mw.results == []
    await step(msgs)  # over budget: compacts before calling the model
    assert len(mw.results) == 1
    assert mw.results[0].status in ("Compacted", "Fell back")
    assert seen[-1] <= mw.results[0].tokens_after + 1
    assert mw.messages[-1] == {"role": "assistant", "content": "ok"}


def test_default_budget_is_120k():
    assert CompactionConfig().budget == 120_000
