"""The Judge protocol. JevJudge, CloudflareJudge and MockJudge implement it.

A Judge answers one request: a state plus noul questions ("is this statement
true?"), returning a probability in [0, 1] per question. Batching, rate
limiting and timeouts are handled by jevcompact.batching, so every Judge gets
the same treatment.

A judge may declare `max_request_tokens` (smaller than Jev's 32k cap) and
`request_timeout_s` (longer than Jev's 5 s); callers use them when present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# Both are yes/no questions sent as Jev `noul` questions (field `instructions`);
# the returned `noul` value is the score.
KEEP_QUESTION = "Is tool output [{qid}] still needed to finish the task?"
SOURCE_QUESTION = 'Is this summary line supported by the tool outputs? Line: "{line}"'


@dataclass(frozen=True)
class Question:
    id: str
    kind: Literal["keep", "source"]
    text: str
    subject: str = ""  # item text or summary line; used by MockJudge only
    meta: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass
class JudgeResponse:
    scores: dict[str, float]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    neurons: float = 0.0  # Cloudflare judge only (Jev bills tokens, see input_tokens)
    attempts: int = 1  # Cloudflare judge: 2 when the first reply was invalid JSON


class JudgeError(RuntimeError):
    """Raised when the judge fails, times out or returns an unusable answer."""


def request_cap(judge, config) -> int:
    """Token cap per judge request: the config's Jev cap, or the judge's own if smaller."""
    own = getattr(judge, "max_request_tokens", None)
    return min(config.jev_max_request_tokens, own) if own else config.jev_max_request_tokens


def request_timeout(judge, config) -> float:
    """Per-request timeout: the judge's own if it declares one, else the config's Jev timeout."""
    return getattr(judge, "request_timeout_s", None) or config.jev_timeout_s


@runtime_checkable
class Judge(Protocol):
    name: str

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse: ...

    async def test_connection(self) -> bool: ...
