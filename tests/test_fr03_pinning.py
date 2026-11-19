"""FR3 + TC-03: the task, user messages, latest turn and error outputs are pinned."""
import pytest
from conftest import const_judge
from factories import Step, build, checkout_session

from jevcompact import CompactionConfig, compact, parse_session, user_messages_lost
from jevcompact.formats import is_error_output
from jevcompact.pinning import apply_pins


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
def test_pins(fmt):
    s = parse_session(checkout_session(fmt))
    apply_pins(s, CompactionConfig())
    users = [it for it in s.items if it.role == "USER"]
    assert users[0].is_task and users[0].pin_reason.startswith("task")
    assert all(u.pinned for u in users) and len(users) == 2
    err = [it for it in s.items if it.role == "ERROR"]
    assert err and all(e.pinned and e.pin_reason == "error output" for e in err)
    last_tool = [it for it in s.items if it.role in ("TOOL", "ERROR")][-1]
    assert last_tool.pinned and last_tool.pin_reason == "latest turn"
    assert not s.items[1].pinned  # ls node_modules


@pytest.mark.parametrize("text", [
    "Traceback (most recent call last):\n  File x", "TypeError: total is undefined (cart.ts:88)",
    "Tests: 3 FAILED", "npm ERR! code ELIFECYCLE", "Process exited with code 1", '{"exit_code": 2}',
    "Error: ENOENT: no such file",
])
def test_error_detection(text):
    assert is_error_output(text)


@pytest.mark.parametrize("text", ["exit code 0", "all good", "src/errors.ts", "PASS src/cart.test.ts"])
def test_not_errors(text):
    assert not is_error_output(text)


async def test_pinned_items_not_sent_to_judge(store, summarizer):
    judge = const_judge(0.0)
    await compact(checkout_session(), CompactionConfig(budget=3000), judge=judge, summarizer=summarizer,
                  recall_store=store)
    sent = [q.subject for _, qs in judge.calls for q in qs if q.kind == "keep"]
    assert sent
    assert not any("TypeError" in t for t in sent)
    assert not any(t.startswith("Fix the checkout") for t in sent)


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
async def test_tc03_user_message_never_dropped(fmt, store, summarizer):
    """TC-03: even when Jev scores everything 0.0 and the budget is tiny."""
    msgs = build([Step(f"cat file{i}.txt", "x\n" * 400, user_after=f"user note {i}" if i % 3 == 0 else None)
                  for i in range(12)], fmt)
    res = await compact(msgs, CompactionConfig(budget=200), judge=const_judge(0.0), summarizer=summarizer,
                        recall_store=store)
    assert user_messages_lost(msgs, res.messages) == 0
    assert res.user_messages_lost == 0
    for d in res.decisions:
        if d.role == "USER":
            assert d.action == "Pinned" and not d.summarized
