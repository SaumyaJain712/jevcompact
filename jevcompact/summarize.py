"""Step 3, Summarize: the oldest unpinned turns, only while still over budget."""
from __future__ import annotations

from .formats import text_of
from .models import Group, Session
from .summarizers.base import SummaryEntry, SummaryRequest


def select_groups(session: Session, msg_tokens_now: list[int], budget: int, reserve: int) -> list[Group]:
    """Oldest summarizable turns first, until the projected total fits the budget.

    Turns holding a pinned item (user text, error output, latest turn) are
    never selected, so user messages can't be lost.
    """
    total = sum(msg_tokens_now)
    chosen: list[Group] = []
    for g in session.groups:
        if total + (reserve if chosen else 0) <= budget:
            break
        if session.group_locked(g):
            continue
        chosen.append(g)
        total -= sum(msg_tokens_now[i] for i in g.msg_indices)
    return chosen


def assistant_text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return text_of(c)


def build_request(session: Session, groups: list[Group], item_text_now: dict[int, str]) -> SummaryRequest:
    users = [it for it in session.items if it.role == "USER"]
    req = SummaryRequest(task=users[0].text if users else "")
    for g in groups:
        for mi in g.msg_indices:
            m = session.messages[mi]
            if m["role"] == "assistant":
                t = assistant_text(m)
                if t.strip():
                    req.entries.append(SummaryEntry("assistant", t))
        for idx in g.items:
            it = session.items[idx]
            req.entries.append(SummaryEntry(it.title, item_text_now.get(idx, it.text)))
    return req


def sources_for(session: Session, groups: list[Group]) -> list[tuple[str, str]]:
    """Original tool outputs (with their commands) for the summary check."""
    return [(session.items[i].title, session.items[i].text) for g in groups for i in g.items]
