"""MockJudge: deterministic heuristic scores so everything runs without keys.

Keep questions:  errors / recent / referenced files score high;
ls, node_modules, lockfiles, huge repeated and superseded outputs score low.
Source questions: a summary line scores high only if its identifiers (paths,
numbers, code names) and most of its words appear in the tool outputs.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
from typing import Callable

from ..tokens import count_tokens
from .base import JudgeError, JudgeResponse, Question

_PATH_RE = re.compile(r"[\w@.-]+(?:/[\w@.-]+)+|[\w-]+\.(?:ts|tsx|js|jsx|py|json|md|yml|yaml|toml|css|html|sql|go|rs|java|rb|sh|txt)\b")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_IDENT_RE = re.compile(r"`([^`]+)`|\b[\w-]+(?:[./][\w-]+)+\b|\b\d+(?:\.\d+)?\b|\b[a-z]+[A-Z]\w*\b")
_STOP = {"this", "that", "with", "from", "were", "have", "been", "into", "then", "than", "when", "which",
         "ran", "output", "file", "files", "line", "lines", "tool", "returned", "shows", "showed", "found"}


def _jitter(key: str, spread: float = 0.02) -> float:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return ((h % 1000) / 999 - 0.5) * 2 * spread


def keep_score(q: Question, state: str) -> float:
    title = str(q.meta.get("title", "")).lower()
    text = q.subject
    lines = text.splitlines() or [""]
    age = float(q.meta.get("age", 0.5))  # 0 = oldest, 1 = newest
    context = state.split("OLDER TOOL OUTPUTS:")[0].lower()

    cmd = title.split()[0] if title.split() else ""
    if "node_modules" in title or (cmd in ("ls", "find", "tree", "du") and "node_modules" in text[:4000]):
        base = 0.03
    elif any(k in title for k in ("package-lock", "yarn.lock", "pnpm-lock", "poetry.lock")):
        base = 0.04
    elif len(lines) > 50 and len(set(lines)) / len(lines) < 0.3:
        base = 0.05  # huge repeated output
    elif q.meta.get("superseded"):
        base = 0.08  # same command ran again later
    else:
        paths = {p.lower() for p in _PATH_RE.findall(title)}
        referenced = any(p in context for p in paths) or any(
            w in context for w in (title.split()[1:2] if cmd in ("grep", "rg") else [])
        )
        if referenced:
            base = 0.93
        elif cmd in ("ls", "find", "tree", "pwd", "which", "echo"):
            base = 0.22
        else:
            base = 0.30 + 0.32 * age  # older -> unsure, recent -> keep
    return round(min(0.99, max(0.01, base + _jitter(q.id + title))), 3)


def source_score(q: Question, state: str) -> float:
    line = q.subject.strip().lstrip("-*• ").strip()
    if not line:
        return 0.95
    low_state = state.lower()
    idents = [m.group(1) or m.group(0) for m in _IDENT_RE.finditer(line)]
    if any(i.lower() not in low_state for i in idents):
        return round(0.04 + abs(_jitter(line, 0.03)), 3)
    words = [w.lower() for w in _WORD_RE.findall(line) if w.lower() not in _STOP]
    if not words:
        return 0.9
    overlap = sum(1 for w in words if w in low_state) / len(words)
    return round(min(0.98, 0.1 + overlap * 0.9), 3)


class MockJudge:
    name = "mock"

    def __init__(
        self,
        latency_ms: tuple[float, float] = (0.0, 0.0),
        fail: bool = False,
        timeout: bool = False,
        seed: int = 0,
        score_fn: Callable[[Question, str], float] | None = None,
    ):
        self.latency_ms = latency_ms
        self.fail = fail
        self.timeout = timeout
        self.score_fn = score_fn
        self._rng = random.Random(seed)
        self.calls: list[tuple[str, list[Question]]] = []

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse:
        self.calls.append((state, questions))
        if self.fail:
            raise JudgeError("MockJudge configured to fail")
        if self.timeout:
            await asyncio.sleep(3600)
        lo, hi = self.latency_ms
        if hi > 0:
            await asyncio.sleep(self._rng.uniform(lo, hi) / 1000)
        scores = {}
        for q in questions:
            if self.score_fn is not None:
                scores[q.id] = float(self.score_fn(q, state))
            elif q.kind == "keep":
                scores[q.id] = keep_score(q, state)
            else:
                scores[q.id] = source_score(q, state)
        tokens = count_tokens(state) + sum(count_tokens(q.text) for q in questions)
        return JudgeResponse(scores=scores, input_tokens=tokens, output_tokens=8 * len(questions), model="mock")

    async def test_connection(self) -> bool:
        return not self.fail
