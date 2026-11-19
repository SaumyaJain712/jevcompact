"""Token-bucket limiter for requests/s and tokens/s (Jev: 80 req/s, 100k tok/s)."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    def __init__(self, requests_per_s: float, tokens_per_s: float):
        self.rps = requests_per_s
        self.tps = tokens_per_s
        self._req = requests_per_s
        self._tok = tokens_per_s
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        self._req = min(self.rps, self._req + dt * self.rps)
        self._tok = min(self.tps, self._tok + dt * self.tps)

    async def acquire(self, tokens: int) -> None:
        tokens = min(tokens, self.tps)
        async with self._lock:
            while True:
                self._refill()
                if self._req >= 1 and self._tok >= tokens:
                    self._req -= 1
                    self._tok -= tokens
                    return
                wait = max((1 - self._req) / self.rps, (tokens - self._tok) / self.tps, 0.001)
                await asyncio.sleep(wait)
