"""The Summarizer protocol, plus a content-hash cache shared by all summarizers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class SummaryEntry:
    heading: str  # e.g. the command, or "assistant"
    text: str


@dataclass
class SummaryRequest:
    task: str
    entries: list[SummaryEntry] = field(default_factory=list)

    def key(self, namespace: str) -> str:
        blob = json.dumps({"ns": namespace, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class SummaryResult:
    text: str
    neurons: float = 0.0
    cached: bool = False
    input_tokens: int = 0


class SummarizerError(RuntimeError):
    pass


@runtime_checkable
class Summarizer(Protocol):
    name: str

    async def summarize(self, request: SummaryRequest) -> SummaryResult: ...

    async def test_connection(self) -> bool: ...


class CachingSummarizer:
    """Caches summaries by content hash (memory, optionally on disk).

    Cloudflare's free tier is 10,000 neurons/day, so identical inputs are
    never summarized twice.
    """

    def __init__(self, inner: Summarizer, cache_dir: str | Path | None = None):
        self.inner = inner
        self.name = inner.name
        self._mem: dict[str, SummaryResult] = {}
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def _ns(self) -> str:
        return f"{self.inner.name}:{getattr(self.inner, 'model', '')}"

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        key = request.key(self._ns())
        if key in self._mem:
            return SummaryResult(self._mem[key].text, 0.0, True, self._mem[key].input_tokens)
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            data = json.loads(path.read_text())
            res = SummaryResult(data["text"], 0.0, True, data.get("input_tokens", 0))
            self._mem[key] = res
            return res
        res = await self.inner.summarize(request)
        self._mem[key] = res
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": res.text, "input_tokens": res.input_tokens}))
        return res

    async def test_connection(self) -> bool:
        return await self.inner.test_connection()
