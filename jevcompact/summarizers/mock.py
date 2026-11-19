"""MockSummarizer: deterministic, extractive, no network.

One line per entry: the command plus its first informative output line.
With `invent=True` it appends one plausible but unsupported line, so the
check step (FR7) has something to catch in tests and the evaluation.
"""
from __future__ import annotations

from ..tokens import count_tokens
from .base import SummaryRequest, SummaryResult

INVENTED_LINE = "- Updated `src/config/featureFlags.ts` to enable the new checkout flow."


def _informative(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if len(s) > 3 and not s.startswith("[JevCompact"):
            return s[:140]
    return "(no output)"


class MockSummarizer:
    name = "mock"
    model = "mock"

    def __init__(self, invent: bool = False, fail: bool = False):
        self.invent = invent
        self.fail = fail
        self.calls = 0

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        from .base import SummarizerError

        self.calls += 1
        if self.fail:
            raise SummarizerError("MockSummarizer configured to fail")
        lines = []
        for e in request.entries:
            if e.heading != "assistant":  # extractive: only tool outputs are summarized
                lines.append(f"- `{e.heading}`: {_informative(e.text)}")
        if self.invent:
            lines.append(INVENTED_LINE)
        tokens = sum(count_tokens(e.text) for e in request.entries)
        return SummaryResult(text="\n".join(lines), neurons=0.0, input_tokens=tokens)

    async def test_connection(self) -> bool:
        return not self.fail
