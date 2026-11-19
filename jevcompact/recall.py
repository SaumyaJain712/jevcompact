"""Recall cache: full text of every dropped (or cut) item, restorable verbatim."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Protocol


class RecallStore(Protocol):
    def put(self, item_id: str, run_id: str, content: str) -> None: ...

    def get(self, item_id: str) -> str | None: ...


class MemoryRecallStore:
    def __init__(self):
        self._data: dict[str, tuple[str, str]] = {}

    def put(self, item_id: str, run_id: str, content: str) -> None:
        self._data[item_id] = (run_id, content)

    def get(self, item_id: str) -> str | None:
        v = self._data.get(item_id)
        return v[1] if v else None


class SqliteRecallStore:
    """Standalone SQLite store (the server uses its own recall_cache table)."""

    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS recall_cache (item_id TEXT PRIMARY KEY, run_id TEXT, full_content TEXT)"
        )

    def put(self, item_id: str, run_id: str, content: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO recall_cache VALUES (?, ?, ?)", (item_id, run_id, content))

    def get(self, item_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT full_content FROM recall_cache WHERE item_id = ?", (item_id,)).fetchone()
        return row[0] if row else None


_default_store: RecallStore = MemoryRecallStore()


def default_store() -> RecallStore:
    return _default_store


def set_default_store(store: RecallStore) -> None:
    global _default_store
    _default_store = store


def recall(item_id: str, store: RecallStore | None = None) -> str:
    """Return the full, original text of a dropped item."""
    content = (store or _default_store).get(item_id)
    if content is None:
        raise KeyError(f"No recalled item with id {item_id!r}")
    return content
