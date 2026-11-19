"""Data classes shared by the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Format = Literal["openai", "anthropic"]
Action = Literal["Pinned", "Kept", "Cut", "Dropped"]
Status = Literal["Compacted", "Fell back", "Under budget"]
RoleTag = Literal["USER", "TOOL", "ERROR"]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Item:
    """A reviewable unit: a human user message or one tool result."""

    index: int
    msg_index: int
    block_index: int | None
    role: RoleTag
    title: str
    text: str
    tokens: int
    group: int
    tool_call_id: str | None = None
    is_task: bool = False
    pinned: bool = False
    pin_reason: str = ""


@dataclass
class Group:
    """Messages that must be kept or removed together.

    A 'turn' is an assistant message plus the tool results that answer its
    tool calls, so summarizing never leaves an orphaned tool call or result.
    """

    index: int
    kind: Literal["system", "user", "turn", "other"]
    msg_indices: list[int] = field(default_factory=list)
    items: list[int] = field(default_factory=list)


@dataclass
class Session:
    format: Format
    messages: list[dict]
    items: list[Item]
    groups: list[Group]
    msg_tokens: list[int]
    msg_group: list[int]

    @property
    def tokens(self) -> int:
        return sum(self.msg_tokens)

    def group_locked(self, g: Group) -> bool:
        return g.kind != "turn" or any(self.items[i].pinned for i in g.items)


@dataclass
class Decision:
    item_id: str
    item_index: int
    message_index: int
    block_index: int | None
    role: RoleTag
    title: str
    score: float | None
    action: Action
    reason: str
    tokens: int
    tokens_after: int
    summarized: bool = False
    tool_call_id: str | None = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryInfo:
    text: str
    lines_kept: list[str]
    lines_removed: list[str]
    line_scores: list[tuple[str, float | None]]
    summarized_messages: int
    neurons: float = 0.0
    checked: bool = True
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompactionResult:
    run_id: str
    status: Status
    format: Format
    messages: list[dict]
    tokens_before: int
    tokens_after: int
    decisions: list[Decision]
    summary: SummaryInfo | None
    judge: str
    summarizer: str
    jev_requests: int = 0
    jev_input_tokens: int = 0
    jev_cost_usd: float = 0.0
    summarizer_neurons: float = 0.0
    latency_ms: float = 0.0
    scoring_latency_ms: float = 0.0
    fallback_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    user_messages_lost: int = 0
    index_map: list[int | None] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def percent_saved(self) -> float:
        return 0.0 if not self.tokens_before else 100.0 * self.tokens_saved / self.tokens_before

    def count(self, action: Action) -> int:
        return sum(1 for d in self.decisions if d.action == action)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tokens_saved"] = self.tokens_saved
        d["percent_saved"] = round(self.percent_saved, 2)
        return d
