"""JevCompactMiddleware: capture a session live and compact it when it passes the budget."""
from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from .config import CompactionConfig
from .formats import total_tokens
from .judges import Judge
from .models import CompactionResult
from .pipeline import compact
from .recall import RecallStore
from .summarizers import Summarizer


class JevCompactMiddleware:
    """Wraps an agent loop.

        mw = JevCompactMiddleware(CompactionConfig(budget=120_000))
        call_llm = mw.wrap(call_llm)        # compacts before each call if needed
        mw.record({"role": "user", "content": "..."})   # live capture (FR1)
    """

    def __init__(self, config: CompactionConfig | None = None, *, judge: Judge | None = None,
                 summarizer: Summarizer | None = None, recall_store: RecallStore | None = None,
                 on_compact: Callable[[CompactionResult], Any] | None = None):
        self.config = config or CompactionConfig.from_env()
        self.judge, self.summarizer, self.recall_store = judge, summarizer, recall_store
        self.on_compact = on_compact
        self.messages: list[dict] = []
        self.results: list[CompactionResult] = []

    def record(self, *messages: dict) -> None:
        self.messages.extend(messages)

    @property
    def tokens(self) -> int:
        return total_tokens(self.messages) if self.messages else 0

    async def maybe_compact(self) -> CompactionResult | None:
        if not self.messages or self.tokens <= self.config.budget:
            return None
        result = await compact(self.messages, self.config, judge=self.judge, summarizer=self.summarizer,
                               recall_store=self.recall_store)
        self.messages = result.messages
        self.results.append(result)
        if self.on_compact:
            self.on_compact(result)
        return result

    def wrap(self, call: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        """Return an async version of `call(messages, **kw)` that compacts first.

        If `messages` is passed it replaces the captured history; the call's
        return value is recorded when it is a message dict.
        """

        async def wrapped(messages: list[dict] | None = None, **kwargs):
            if messages is not None:
                self.messages = list(messages)
            await self.maybe_compact()
            reply = call(self.messages, **kwargs)
            if inspect.isawaitable(reply):
                reply = await reply
            if isinstance(reply, dict) and "role" in reply:
                self.record(reply)
            return reply

        return wrapped
