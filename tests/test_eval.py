"""The evaluation code itself (FIFO baseline, metrics, sweep, neuron guard), on factory sessions only."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from factories import Step, build, filler

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
ev = importlib.util.module_from_spec(spec)
sys.modules["run_eval"] = ev
spec.loader.exec_module(ev)

from jevcompact import MockJudge, MockSummarizer, user_messages_lost  # noqa: E402
from jevcompact.formats import total_tokens  # noqa: E402


def sample(fmt="openai"):
    steps = [Step(f"cat src/f{i}.ts", filler(15_000, f"e{i}"), user_after="note" if i == 2 else None) for i in range(12)]
    msgs = build(steps, fmt)
    labels = {"items": [{"tool_call_id": f"call_{i}", "command": f"cat src/f{i}.ts", "needed": i in (0, 11),
                         "reason": "test"} for i in range(12)]}
    return ev.Sample("t", msgs, labels)


def test_fifo_drops_oldest_and_loses_user_messages():
    s = sample()
    out = ev.fifo(s.messages, 120_000)
    assert total_tokens(out) <= 120_000
    assert out[0]["role"] == "system"
    assert user_messages_lost(s.messages, out) >= 1  # the task message goes first
    m = ev.score_output(s, out)
    assert m["needed_kept"] == 1 and m["needed_items"] == 2  # call_0 dropped, call_11 (latest turn) kept


def test_score_output_counts_verbatim_only():
    s = sample()
    m = ev.score_output(s, s.messages)
    assert m["needed_kept_pct"] == 100.0 and m["unneeded_removed_pct"] == 0.0


@pytest.mark.parametrize("method", ev.METHODS)
def test_run_method_mock(method):
    s = sample("anthropic")
    summ = ev.EvalSummarizer(MockSummarizer(), None, "test-mock")
    row, _ = asyncio.run(ev.run_method(s, method, "mock", lambda: MockJudge(), summ, "mock", "mock"))
    assert row.mode == "mock" and row.method == method
    assert row.tokens_after < row.tokens_before
    if method != "fifo":
        assert row.user_messages_lost == 0


def test_sweep_uses_recorded_scores():
    s = sample()
    summ = ev.EvalSummarizer(MockSummarizer(), None, "test-mock")
    _, res = asyncio.run(ev.run_method(s, "prune_only", "mock", lambda: MockJudge(), summ, "mock", "mock"))
    rows = ev.sweep_rows("mock", {"t": res}, [s])
    assert {r["preset"] for r in rows} >= {"conservative", "balanced", "aggressive"}
    assert all(r["keep"] > r["drop"] for r in rows)
    lo = next(r for r in rows if r["keep"] == 0.3 and r["drop"] == 0.0)
    hi = next(r for r in rows if r["keep"] == 0.9 and r["drop"] == 0.3)
    assert lo["needed_kept_pct"] >= hi["needed_kept_pct"]
    assert hi["tool_tokens_saved_pct"] >= lo["tool_tokens_saved_pct"]


def test_neuron_guard_stops_before_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "CACHE", tmp_path)

    class Fake:
        name, model = "cloudflare", "@cf/zai-org/glm-4.7-flash"

        async def summarize(self, req):
            raise AssertionError("must not be called")

    ledger = ev.NeuronLedger(limit=50)
    summ = ev.EvalSummarizer(Fake(), ledger, "real")
    req = ev.SummaryRequest("task", [ev.build_request.__globals__["SummaryEntry"]("cat a", filler(20_000, "z"))])
    with pytest.raises(ev.BudgetExceeded):
        asyncio.run(summ.summarize(req))
