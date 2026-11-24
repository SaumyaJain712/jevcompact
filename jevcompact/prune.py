"""Step 2, Prune: score every older tool result with the judge, then keep / cut / drop."""
from __future__ import annotations

from dataclasses import dataclass, field

from .batching import BatchOutcome, effective_cap, pack, question_cost, run_requests
from .config import CompactionConfig
from .formats import first_error_line
from .summarize import assistant_text
from .judges.base import KEEP_QUESTION, Judge, Question, request_cap, request_timeout
from .models import Action, Item, Session
from .ratelimit import RateLimiter
from .tokens import clip_to_tokens, count_tokens


def is_probably_english(text: str) -> bool:
    """Jev accepts English text only; mostly non-Latin text is not sent."""
    letters = [c for c in text[:5000] if c.isalpha()]
    if not letters:
        return True
    return sum(1 for c in letters if ord(c) > 0x24F) / len(letters) < 0.3


def build_context(session: Session, config: CompactionConfig) -> str:
    users = [it for it in session.items if it.role == "USER"]
    task = clip_to_tokens(users[0].text, 1500) if users else "(no task message)"
    latest_user = clip_to_tokens(users[-1].text, 500) if len(users) > 1 else "(same as task)"
    recent_parts: list[str] = []
    turns = [g for g in session.groups if g.kind == "turn"]
    for g in turns[-(config.pin_last_turns + 2):]:
        for mi in g.msg_indices:
            m = session.messages[mi]
            if m["role"] == "assistant":
                t = assistant_text(m)
                if t.strip():
                    recent_parts.append(t.strip())
        recent_parts.extend(f"ran: {session.items[i].title}" for i in g.items)
    recent = clip_to_tokens("\n".join(recent_parts), 1500) or "(none)"
    return (f"TASK:\n{task}\n\nLATEST USER MESSAGE:\n{latest_user}\n\n"
            f"RECENT ACTIVITY:\n{recent}\n\nOLDER TOOL OUTPUTS:\n")


@dataclass
class ScoreOutcome:
    scores: dict[int, float] = field(default_factory=dict)  # item index -> keep probability
    skipped: dict[int, str] = field(default_factory=dict)  # item index -> reason not scored
    requests: int = 0
    input_tokens: int = 0
    neurons: float = 0.0
    latency_ms: float = 0.0


async def score_items(session: Session, config: CompactionConfig, judge: Judge,
                      limiter: RateLimiter) -> ScoreOutcome:
    out = ScoreOutcome()
    tool_items = [it for it in session.items if it.role in ("TOOL", "ERROR")]
    candidates: list[Item] = []
    for it in tool_items:
        if it.pinned:
            continue
        if not is_probably_english(it.text):
            out.skipped[it.index] = "not English: Jev was not asked, kept verbatim"
        else:
            candidates.append(it)
    if not candidates:
        return out

    header = build_context(session, config)
    cap = effective_cap(request_cap(judge, config))
    n = max(1, len(tool_items) - 1)
    rank = {it.index: r for r, it in enumerate(tool_items)}
    later_titles: dict[int, bool] = {}
    seen: set[str] = set()
    for it in reversed(tool_items):
        later_titles[it.index] = it.title in seen
        seen.add(it.title)

    blocks: list[tuple[str, Question]] = []
    for it in candidates:
        qid = f"t{it.index}"
        q = Question(qid, "keep", KEEP_QUESTION.format(qid=qid, title=it.title), it.text,
                     {"title": it.title, "age": rank[it.index] / n, "superseded": later_titles[it.index]})
        room = cap - count_tokens(header) - question_cost(q) - 32
        body = clip_to_tokens(it.text, max(50, min(config.jev_item_max_tokens, room)))
        blocks.append((f"[{qid}] {it.title}\n{body}", q))

    requests = pack(header, blocks, cap)
    res: BatchOutcome = await run_requests(judge, requests, limiter, request_timeout(judge, config))
    out.scores = {int(k[1:]): v for k, v in res.scores.items()}
    out.requests, out.input_tokens, out.latency_ms = res.requests, res.input_tokens, res.latency_ms
    out.neurons = res.neurons
    return out


def classify(score: float, config: CompactionConfig) -> Action:
    if score >= config.keep_threshold:
        return "Kept"
    if score < config.drop_threshold:
        return "Dropped"
    return "Kept" if config.keep_when_unsure else "Cut"


def truncate(text: str, config: CompactionConfig, item_id: str) -> str:
    """First N lines (max cut_chars characters), plus the error line if any."""
    lines = text.splitlines()
    head = "\n".join(lines[: config.cut_lines])[: config.cut_chars]
    if len(head) >= len(text):
        return text
    err = first_error_line(text)
    extra = f"\n…\n{err.strip()[:200]}" if err and err.strip() not in head else ""
    shown = head.count("\n") + 1
    return (f"{head}{extra}\n[JevCompact truncated this output: showing {shown} of {len(lines)} lines. "
            f"Recall id: {item_id}]")


def drop_stub(item: Item, score: float, item_id: str) -> str:
    return (f"[JevCompact dropped this tool output ({item.title}, {item.tokens} tokens, score {score:.2f}). "
            f"Recall id: {item_id}]")
