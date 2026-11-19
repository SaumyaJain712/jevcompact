"""Parse OpenAI / Anthropic message arrays into a Session and render them back.

The output always uses the input's format. Tool results keep their ids and
positions, so tool_call/tool_result pairs stay valid for both APIs.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Iterable

from .models import Format, Group, Item, Session
from .tokens import count_tokens

UPLOAD_ERROR = "This file isn't a message list. We expected a JSON array of {role, content}."


class FormatError(ValueError):
    def __init__(self, message: str = UPLOAD_ERROR):
        super().__init__(message)


# --- error detection -------------------------------------------------------

ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"\b[A-Z][A-Za-z]*(?:Error|Exception)\b:",
    r"\bError:",
    r"(?m:^\s*(?:Error|ERROR)\b)",
    r"\bFAILED\b",
    r"(?m:^\s*FAIL\s)",
    r"npm ERR!",
    r"(?i:\bexit(?:ed)?(?: with)? (?:code|status)[:=]?\s*[1-9]\d*)",
    r"(?i:non-zero exit)",
    r'"exit_?code"\s*:\s*[1-9]',
    r"\bpanic:",
    r"\bSegmentation fault\b",
]
_ERROR_RE = re.compile("|".join(f"(?:{p})" for p in ERROR_PATTERNS))
_ERROR_LINE_RE = re.compile(r"(?i)error|exception|fail|traceback")


def is_error_output(text: str) -> bool:
    return bool(_ERROR_RE.search(text or ""))


def first_error_line(text: str) -> str | None:
    for line in (text or "").splitlines():
        if _ERROR_RE.search(line) or _ERROR_LINE_RE.search(line):
            return line
    return None


# --- validation + detection -------------------------------------------------

def validate_messages(data: Any) -> list[dict]:
    """Accept a JSON array of {role, content} objects (or a JSON string of one)."""
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except (ValueError, TypeError) as exc:
            raise FormatError() from exc
    if not isinstance(data, list) or not data:
        raise FormatError()
    for m in data:
        if not isinstance(m, dict) or not isinstance(m.get("role"), str):
            raise FormatError()
        if "content" not in m and not m.get("tool_calls"):
            raise FormatError()
        c = m.get("content")
        if c is not None and not isinstance(c, (str, list)):
            raise FormatError()
    return data


def detect_format(messages: list[dict]) -> Format:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result") for b in c
        ):
            return "anthropic"
        if m.get("role") in ("tool", "function") or m.get("tool_calls"):
            return "openai"
    return "openai"


# --- text helpers -----------------------------------------------------------

def text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                t = b.get("type")
                if t in ("text", "input_text", "output_text"):
                    parts.append(b.get("text", ""))
                elif t == "tool_use":
                    parts.append(f"{b.get('name', '')} {json.dumps(b.get('input', {}))}")
                elif t == "tool_result":
                    parts.append(text_of(b.get("content")))
        return "\n".join(p for p in parts if p)
    return str(content)


def message_text(m: dict) -> str:
    txt = text_of(m.get("content"))
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function", {})
        txt += f"\n{fn.get('name', '')} {fn.get('arguments', '')}"
    return txt


def message_tokens(m: dict) -> int:
    return count_tokens(message_text(m)) + 4


def _human_text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return "\n".join(
            b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") in ("text", "input_text")
        )
    return text_of(c)


def _title_for(name: str, args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return f"{name} {args}".strip()[:120]
    if isinstance(args, dict):
        for key in ("command", "cmd"):
            if args.get(key):
                v = args[key]
                return (" ".join(v) if isinstance(v, list) else str(v))[:120]
        for key in ("pattern", "query", "path", "file_path", "file", "url"):
            if args.get(key):
                return f"{name} {args[key]}"[:120]
    return name or "tool output"


def _tool_calls(m: dict, fmt: Format) -> Iterable[tuple[str, str]]:
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function", {})
        yield tc.get("id", ""), _title_for(fn.get("name", ""), fn.get("arguments"))
    c = m.get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b.get("id", ""), _title_for(b.get("name", ""), b.get("input"))


def _first_line(text: str, n: int = 80) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:n] + ("…" if len(line) > n else "")


# --- parse ------------------------------------------------------------------

def parse_session(messages: Any, fmt: Format | None = None) -> Session:
    messages = validate_messages(messages)
    fmt = fmt or detect_format(messages)
    items: list[Item] = []
    groups: list[Group] = []
    msg_group: list[int] = []
    msg_tokens: list[int] = []
    titles: dict[str, str] = {}
    current: Group | None = None

    def new_group(kind) -> Group:
        g = Group(len(groups), kind)
        groups.append(g)
        return g

    def add_item(g: Group, **kw) -> None:
        text = kw["text"]
        role = kw.pop("role")
        if role == "TOOL" and (kw.pop("is_error", False) or is_error_output(text)):
            role = "ERROR"
        kw.pop("is_error", None)
        it = Item(index=len(items), role=role, tokens=count_tokens(text), group=g.index, **kw)
        items.append(it)
        g.items.append(it.index)

    for i, m in enumerate(messages):
        role = m["role"]
        msg_tokens.append(message_tokens(m))
        if role == "assistant":
            titles.update(dict(_tool_calls(m, fmt)))
            g = current = new_group("turn")
            g.msg_indices.append(i)
        elif role in ("tool", "function"):
            g = current or new_group("turn")
            current = g
            g.msg_indices.append(i)
            tid = m.get("tool_call_id")
            add_item(g, msg_index=i, block_index=None, role="TOOL",
                     title=titles.get(tid) or m.get("name") or "tool output",
                     text=text_of(m.get("content")), tool_call_id=tid)
        elif role == "user":
            c = m.get("content")
            tool_blocks = [(bi, b) for bi, b in enumerate(c) if isinstance(b, dict) and b.get("type") == "tool_result"] \
                if isinstance(c, list) else []
            human = _human_text(m)
            if tool_blocks:
                g = current or new_group("turn")
                current = g
                g.msg_indices.append(i)
                for bi, b in tool_blocks:
                    tid = b.get("tool_use_id")
                    add_item(g, msg_index=i, block_index=bi, role="TOOL",
                             title=titles.get(tid) or "tool output", text=text_of(b.get("content")),
                             tool_call_id=tid, is_error=bool(b.get("is_error")))
                if human.strip():
                    add_item(g, msg_index=i, block_index=None, role="USER", title=_first_line(human), text=human)
            else:
                g = new_group("user")
                current = None
                g.msg_indices.append(i)
                add_item(g, msg_index=i, block_index=None, role="USER", title=_first_line(human), text=human)
        else:  # system, developer and anything unknown is never touched
            g = new_group("system" if role in ("system", "developer") else "other")
            current = None
            g.msg_indices.append(i)
        msg_group.append(g.index)

    return Session(fmt, messages, items, groups, msg_tokens, msg_group)


# --- render -----------------------------------------------------------------

SUMMARY_HEADER = "[JevCompact summary of {n} earlier messages]"


def summary_message(fmt: Format, text: str) -> dict:
    if fmt == "anthropic":
        return {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return {"role": "assistant", "content": text}


def set_item_content(msg: dict, block_index: int | None, new_text: str) -> None:
    if block_index is None:
        msg["content"] = new_text
    else:
        msg["content"][block_index]["content"] = new_text


def render(session: Session, replacements: dict[int, str], removed_groups: set[int],
           summary_text: str | None) -> tuple[list[dict], list[int | None]]:
    by_msg: dict[int, list[Item]] = {}
    for idx in replacements:
        it = session.items[idx]
        by_msg.setdefault(it.msg_index, []).append(it)
    out: list[dict] = []
    index_map: list[int | None] = [None] * len(session.messages)
    inserted = False
    for i, m in enumerate(session.messages):
        if session.msg_group[i] in removed_groups:
            if summary_text is not None and not inserted:
                out.append(summary_message(session.format, summary_text))
                inserted = True
            continue
        m2 = copy.deepcopy(m)
        for it in by_msg.get(i, []):
            set_item_content(m2, it.block_index, replacements[it.index])
        index_map[i] = len(out)
        out.append(m2)
    return out, index_map


# --- user message accounting -------------------------------------------------

def human_user_texts(messages: list[dict]) -> list[str]:
    texts = []
    for m in messages:
        if m.get("role") == "user":
            t = _human_text(m)
            if t.strip():
                texts.append(t)
    return texts


def user_messages_lost(before: list[dict], after: list[dict]) -> int:
    """How many human user messages from `before` are missing (verbatim, in order) from `after`."""
    after_texts = human_user_texts(after)
    lost, j = 0, 0
    for t in human_user_texts(before):
        k = j
        while k < len(after_texts) and after_texts[k] != t:
            k += 1
        if k >= len(after_texts):
            lost += 1
        else:
            j = k + 1
    return lost


def total_tokens(messages: list[dict]) -> int:
    return sum(message_tokens(m) for m in messages)
