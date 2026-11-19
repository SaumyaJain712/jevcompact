"""FR5 + TC-05: keep / truncate / drop by threshold; drops go to the recall cache."""
import pytest
from conftest import const_judge
from factories import Step, build, checkout_session

from jevcompact import PRESETS, CompactionConfig, compact, recall
from jevcompact.prune import classify, truncate


def _one_old_item_session(output: str):
    return build([Step("cat big.log", output), Step("npm run build", "ok"), Step("echo hi", "hi")])


async def test_tc05_score_005_dropped_and_cached(store, summarizer):
    full = "line\n" * 2000
    msgs = _one_old_item_session(full)
    res = await compact(msgs, CompactionConfig(budget=500), judge=const_judge(0.05), summarizer=summarizer,
                        recall_store=store)
    d = next(d for d in res.decisions if d.title == "cat big.log")
    assert d.action == "Dropped" and d.score == pytest.approx(0.05)
    assert recall(d.item_id, store) == full
    out_tool = next(m for m in res.messages if m.get("tool_call_id") == "call_0")
    assert "dropped" in out_tool["content"] and d.item_id in out_tool["content"]


@pytest.mark.parametrize("score,action", [(0.93, "Kept"), (0.50, "Kept"), (0.38, "Cut"), (0.10, "Cut"),
                                          (0.0999, "Dropped"), (0.04, "Dropped")])
def test_balanced_thresholds(score, action):
    assert classify(score, CompactionConfig()) == action


def test_keep_when_unsure_option():
    assert classify(0.3, CompactionConfig(keep_when_unsure=True)) == "Kept"


def test_presets():
    assert PRESETS == {"conservative": (0.30, 0.05), "balanced": (0.50, 0.10), "aggressive": (0.70, 0.20)}
    c = CompactionConfig(preset="aggressive")
    assert (c.keep_threshold, c.drop_threshold) == (0.70, 0.20)
    assert CompactionConfig().preset == "balanced"


def test_truncate_keeps_first_lines_and_error_line():
    text = "\n".join(f"line {i}" for i in range(100)) + "\nWARNING: deprecated\nTypeError: boom\nmore"
    cfg = CompactionConfig()
    out = truncate(text, cfg, "r-1")
    assert out.startswith("line 0\nline 1")
    assert "line 9" in out and "line 10\n" not in out
    assert "TypeError: boom" in out
    assert "Recall id: r-1" in out
    head = out.split("\n…")[0].split("\n[JevCompact")[0]
    assert len(head) <= cfg.cut_chars


async def test_cut_item_in_session(store, summarizer):
    full = "\n".join(f"row {i}" for i in range(300))
    res = await compact(_one_old_item_session(full), CompactionConfig(budget=300), judge=const_judge(0.38),
                        summarizer=summarizer, recall_store=store)
    d = next(d for d in res.decisions if d.title == "cat big.log")
    assert d.action == "Cut" and d.tokens_after < d.tokens
    assert recall(d.item_id, store) == full


async def test_mock_judge_heuristics(store, summarizer):
    res = await compact(checkout_session(), CompactionConfig(budget=3000), judge=None or __import__(
        "jevcompact").MockJudge(), summarizer=summarizer, recall_store=store)
    by_title = {}
    for d in res.decisions:
        by_title.setdefault(d.title, d)
    assert by_title["ls node_modules"].action == "Dropped"
    assert by_title["cat package-lock.json"].action == "Dropped"
    assert by_title["npm test"].action == "Pinned"  # the failing run is an error
