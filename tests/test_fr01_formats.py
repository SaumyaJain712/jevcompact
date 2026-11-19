"""FR1: load a session from OpenAI or Anthropic JSON, or capture it live."""
import json

import pytest
from factories import checkout_session

from jevcompact import CompactionConfig, FormatError, JevCompactMiddleware, compact, detect_format, parse_session
from jevcompact.formats import UPLOAD_ERROR, validate_messages


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
def test_parse_both_formats(fmt):
    msgs = checkout_session(fmt)
    assert detect_format(msgs) == fmt
    s = parse_session(msgs)
    tools = [it for it in s.items if it.role in ("TOOL", "ERROR")]
    assert len(tools) == 9
    assert tools[0].title == "ls node_modules"
    assert any(it.role == "ERROR" and "TypeError" in it.text for it in s.items)
    assert [it.text for it in s.items if it.role == "USER"][0].startswith("Fix the checkout")


def test_parse_from_json_string():
    s = parse_session(json.dumps(checkout_session("openai")))
    assert s.format == "openai"


@pytest.mark.parametrize("bad", [{"role": "user"}, [], [1, 2], [{"content": "x"}], "not json", [{"role": "user", "content": 5}]])
def test_invalid_upload_rejected_with_gui_message(bad):
    with pytest.raises(FormatError) as e:
        validate_messages(bad)
    assert str(e.value) == UPLOAD_ERROR


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
async def test_output_keeps_input_format(fmt, judge, summarizer, store):
    msgs = checkout_session(fmt)
    res = await compact(msgs, CompactionConfig(budget=3000), judge=judge, summarizer=summarizer, recall_store=store)
    assert res.format == fmt
    assert detect_format(res.messages) == fmt
    # every tool call still has its result, and vice versa
    s = parse_session(res.messages)
    if fmt == "openai":
        call_ids = {tc["id"] for m in res.messages for tc in m.get("tool_calls") or []}
        result_ids = {m["tool_call_id"] for m in res.messages if m["role"] == "tool"}
    else:
        call_ids = {b["id"] for m in res.messages if isinstance(m["content"], list)
                    for b in m["content"] if b.get("type") == "tool_use"}
        result_ids = {b["tool_use_id"] for m in res.messages if isinstance(m["content"], list)
                      for b in m["content"] if b.get("type") == "tool_result"}
    assert call_ids == result_ids
    assert s.items


def test_input_not_mutated(judge, summarizer, store):
    from jevcompact import compact_sync

    msgs = checkout_session("openai")
    snapshot = json.dumps(msgs)
    compact_sync(msgs, CompactionConfig(budget=3000), judge=judge, summarizer=summarizer, recall_store=store)
    assert json.dumps(msgs) == snapshot


async def test_live_capture_through_library(judge, summarizer, store):
    mw = JevCompactMiddleware(CompactionConfig(budget=10**9), judge=judge, summarizer=summarizer, recall_store=store)
    for m in checkout_session("openai"):
        mw.record(m)
    assert len(mw.messages) == len(checkout_session("openai"))
    assert parse_session(mw.messages).format == "openai"
