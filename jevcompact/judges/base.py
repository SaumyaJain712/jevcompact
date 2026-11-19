"""The Judge protocol. Jev and MockJudge both implement it.

A Judge answers one request: a state plus noul questions ("is this statement
true?"), returning a probability in [0, 1] per question. Batching, rate
limiting and timeouts are handled by jevcompact.batching, so every Judge gets
the same treatment.
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


class JudgeError(RuntimeError):
    """Raised when the judge fails, times out or returns an unusable answer."""


@runtime_checkable
class Judge(Protocol):
    name: str

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse: ...

    async def test_connection(self) -> bool: ...
