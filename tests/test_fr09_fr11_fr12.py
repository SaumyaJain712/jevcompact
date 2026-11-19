"""FR9 decision log, FR11 / TC-11 restore verbatim, FR12 export JSON + report JSON/CSV."""
import csv
import io
import json
from datetime import datetime

import pytest
from conftest import const_judge
from factories import Step, build, checkout_session

from jevcompact import (CompactionConfig, MockJudge, compact, export_json, recall, report_csv, restore_item,
                        savings_report)
from jevcompact.cli import main


async def test_fr09_every_item_logged(store, summarizer):
    res = await compact(checkout_session(), CompactionConfig(budget=3000), judge=MockJudge(), summarizer=summarizer,
                        recall_store=store)
    from jevcompact import parse_session

    assert len(res.decisions) == len(parse_session(checkout_session()).items)
    for d in res.decisions:
        assert d.item_id and d.action in ("Pinned", "Kept", "Cut", "Dropped")
        assert d.reason
        datetime.fromisoformat(d.created_at)
        if d.action != "Pinned":
            assert d.score is not None and 0 <= d.score <= 1


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
async def test_tc11_restored_item_returns_verbatim(fmt, store, summarizer):
    full = "\n".join(f"price row {i}: {i * 1.5:.2f}" for i in range(500))
    msgs = build([Step("grep price", full), Step("npm run lint", "ok"), Step("echo hi", "hi")], fmt)
    res = await compact(msgs, CompactionConfig(budget=500), judge=const_judge(0.02), summarizer=summarizer,
                        recall_store=store)
    d = next(d for d in res.decisions if d.title == "grep price")
    assert d.action == "Dropped"
    assert recall(d.item_id, store) == full
    restored = restore_item(res, d.item_id, store)
    if fmt == "openai":
        assert next(m for m in restored if m.get("tool_call_id") == "call_0")["content"] == full
    else:
        blocks = [b for m in restored if isinstance(m["content"], list) for b in m["content"]
                  if b.get("type") == "tool_result" and b["tool_use_id"] == "call_0"]
        assert blocks[0]["content"] == full
    assert res.messages != restored  # the result itself is not modified


def test_recall_unknown_id(store):
    with pytest.raises(KeyError):
        recall("nope", store)


async def test_fr12_export_and_reports(store, summarizer):
    res = await compact(checkout_session(), CompactionConfig(budget=3000), judge=MockJudge(), summarizer=summarizer,
                        recall_store=store)
    assert json.loads(export_json(res)) == res.messages
    rep = savings_report(res)
    assert rep["tokens_before"] > rep["tokens_after"]
    assert rep["user_messages_touched"] == 0
    assert set(rep["items"]) == {"Pinned", "Kept", "Cut", "Dropped"}
    rows = list(csv.reader(io.StringIO(report_csv(res))))
    assert rows[0][:6] == ["item_id", "message_index", "role", "title", "score", "action"]
    assert len(rows) == len(res.decisions) + 2 and rows[-1][0] == "TOTAL"


def test_cli_compact(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JUDGE", "mock")
    monkeypatch.setenv("SUMMARIZER", "mock")
    inp, out = tmp_path / "in.json", tmp_path / "out.json"
    inp.write_text(json.dumps(checkout_session()))
    code = main(["compact", str(inp), "-o", str(out), "--preset", "balanced", "--budget", "3000",
                 "--report", str(tmp_path / "r.json"), "--csv", str(tmp_path / "r.csv")])
    assert code == 0
    assert isinstance(json.loads(out.read_text()), list)
    assert json.loads((tmp_path / "r.json").read_text())["status"] in ("Compacted", "Fell back")
    assert (tmp_path / "r.csv").read_text().startswith("item_id")
    assert "tokens" in capsys.readouterr().out


def test_cli_rejects_bad_file(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a list"}')
    assert main(["compact", str(bad), "-o", str(tmp_path / "o.json")]) == 2
    assert "isn't a message list" in capsys.readouterr().err


def test_sqlite_recall_store_persists(tmp_path):
    from jevcompact import SqliteRecallStore

    path = tmp_path / "recall.db"
    SqliteRecallStore(path).put("r1-3", "r1", "full text\nverbatim")
    assert recall("r1-3", SqliteRecallStore(path)) == "full text\nverbatim"
