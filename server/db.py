"""SQLite access (sqlite3). Schema: server/db/schema.sql."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from jevcompact.formats import message_tokens, parse_session
from jevcompact.models import CompactionResult, utcnow

SCHEMA = Path(__file__).parent / "db" / "schema.sql"
FINISHED = ("Compacted", "Fell back", "Under budget")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA.read_text())
            self.conn.execute("PRAGMA foreign_keys = ON")
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(runs)")}
            if "judge_neurons" not in cols:  # databases created before the Cloudflare judge
                self.conn.execute("ALTER TABLE runs ADD COLUMN judge_neurons REAL NOT NULL DEFAULT 0")
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL")

    # --- helpers -------------------------------------------------------------
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def x(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.lock, self.conn:
            self.conn.execute(sql, tuple(params))

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # --- sessions ------------------------------------------------------------
    def create_session(self, name: str, messages: list[dict]) -> str:
        session = parse_session(messages)
        sid = uuid.uuid4().hex[:12]
        tokens = [message_tokens(m) for m in messages]
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO sessions (id, name, format, message_count, tokens_before, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, name, session.format, len(messages), sum(tokens), utcnow()))
            self.conn.executemany(
                'INSERT INTO messages (session_id, "index", role, content, tokens) VALUES (?, ?, ?, ?, ?)',
                [(sid, i, m["role"], json.dumps(m, ensure_ascii=False), t) for i, (m, t) in
                 enumerate(zip(messages, tokens))])
        return sid

    def list_sessions(self, q: str | None = None, status: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM sessions WHERE 1=1", []
        if q:
            sql += " AND name LIKE ?"
            params.append(f"%{q}%")
        if status:
            sql += " AND status = ?"
            params.append(status)
        return [dict(r) for r in self.q(sql + " ORDER BY created_at DESC", params)]

    def get_session(self, sid: str) -> dict | None:
        r = self.one("SELECT * FROM sessions WHERE id = ?", (sid,))
        return dict(r) if r else None

    def delete_session(self, sid: str) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        return cur.rowcount > 0

    def get_messages(self, sid: str) -> list[dict]:
        rows = self.q('SELECT content FROM messages WHERE session_id = ? ORDER BY "index"', (sid,))
        return [json.loads(r["content"]) for r in rows]

    def message_token_list(self, sid: str) -> list[int]:
        return [r["tokens"] for r in self.q('SELECT tokens FROM messages WHERE session_id = ? ORDER BY "index"', (sid,))]

    # --- runs ----------------------------------------------------------------
    def next_seq(self, sid: str) -> int:
        r = self.one("SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM runs WHERE session_id = ?", (sid,))
        return int(r["s"])

    def insert_run(self, run_id: str, sid: str, *, preset: str, keep: float, drop: float, budget: int,
                   judge: str, summarizer: str, config: dict, kind: str = "run",
                   parent_run_id: str | None = None, status: str = "Running") -> None:
        with self.lock, self.conn:
            seq = self.next_seq(sid)
            self.conn.execute(
                "INSERT INTO runs (id, session_id, seq, kind, parent_run_id, preset, keep_threshold, drop_threshold, "
                "budget, judge, summarizer, status, config_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, sid, seq, kind, parent_run_id, preset, keep, drop, budget, judge, summarizer, status,
                 json.dumps(config), utcnow()))

    def save_result(self, run_id: str, r: CompactionResult) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE runs SET status=?, jev_cost_usd=?, jev_input_tokens=?, jev_requests=?, neurons=?, judge_neurons=?, latency_ms=?, "
                "scoring_latency_ms=?, tokens_before=?, tokens_after=?, user_messages_lost=?, fallback_reason=?, "
                "output_json=?, index_map_json=?, judge=?, summarizer=? WHERE id=?",
                (r.status, r.jev_cost_usd, r.jev_input_tokens, r.jev_requests, r.summarizer_neurons, r.judge_neurons, r.latency_ms,
                 r.scoring_latency_ms, r.tokens_before, r.tokens_after, r.user_messages_lost, r.fallback_reason,
                 json.dumps(r.messages, ensure_ascii=False), json.dumps(r.index_map), r.judge, r.summarizer, run_id))
            self.conn.executemany(
                "INSERT INTO decisions (run_id, message_index, item_id, item_index, block_index, role, title, score, "
                "action, reason, tokens, tokens_after, summarized, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, d.message_index, d.item_id, d.item_index, d.block_index, d.role, d.title, d.score,
                  d.action, d.reason, d.tokens, d.tokens_after, int(d.summarized), d.created_at)
                 for d in r.decisions])
            if r.summary is not None:
                self.conn.execute(
                    "INSERT INTO summaries (run_id, text, lines_removed, removed_lines_json, checked) VALUES (?,?,?,?,?)",
                    (run_id, "\n".join(r.summary.lines_kept), len(r.summary.lines_removed),
                     json.dumps(r.summary.lines_removed), int(r.summary.checked)))

    def mark_run(self, run_id: str, status: str, error: str | None = None) -> None:
        self.x("UPDATE runs SET status = ?, error = ? WHERE id = ?", (status, error, run_id))

    def get_run(self, run_id: str) -> dict | None:
        r = self.one("SELECT * FROM runs WHERE id = ?", (run_id,))
        return dict(r) if r else None

    def list_runs(self, sid: str) -> list[dict]:
        cols = ("id, seq, kind, parent_run_id, preset, keep_threshold, drop_threshold, budget, judge, summarizer, "
                "status, tokens_before, tokens_after, jev_cost_usd, judge_neurons, latency_ms, superseded, created_at")
        return [dict(r) for r in self.q(f"SELECT {cols} FROM runs WHERE session_id = ? ORDER BY seq", (sid,))]

    def history(self, sid: str) -> list[dict]:
        """Finished, non-superseded runs: the undo/redo timeline."""
        return [r for r in self.list_runs(sid) if r["status"] in FINISHED and not r["superseded"]]

    def timeline(self, sid: str) -> list[str | None]:
        """Undo/redo timeline: version 0 (None = the original upload) then finished runs."""
        hist = [r["id"] for r in self.history(sid)]
        return [None, *hist] if hist else []

    def set_current(self, sid: str, run_id: str | None, supersede_after: bool) -> None:
        """Point the session at a version (None = the original). A new version discards the redo branch."""
        with self.lock, self.conn:
            if supersede_after:
                cur = self.one("SELECT current_run_id FROM sessions WHERE id = ?", (sid,))
                cur_run = self.get_run(cur["current_run_id"]) if cur and cur["current_run_id"] else None
                cur_seq = cur_run["seq"] if cur_run else 0  # at version 0 every other run is "after"
                self.conn.execute("UPDATE runs SET superseded = 1 WHERE session_id = ? AND seq > ? AND id != ?",
                                  (sid, cur_seq, run_id))
            if run_id is None:
                self.conn.execute("UPDATE sessions SET current_run_id = NULL, status = 'Original', "
                                  "tokens_after = tokens_before WHERE id = ?", (sid,))
            else:
                run = self.get_run(run_id)
                self.conn.execute("UPDATE sessions SET current_run_id = ?, status = ?, tokens_after = ? WHERE id = ?",
                                  (run_id, run["status"], run["tokens_after"], sid))

    # --- decisions / summaries / recall ----------------------------------------
    def decisions(self, run_id: str) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM decisions WHERE run_id = ? ORDER BY item_index", (run_id,))]

    def summary(self, run_id: str) -> dict | None:
        r = self.one("SELECT * FROM summaries WHERE run_id = ?", (run_id,))
        return dict(r) if r else None

    def recall_put(self, item_id: str, run_id: str, content: str) -> None:
        self.x("INSERT OR REPLACE INTO recall_cache (item_id, run_id, full_content) VALUES (?, ?, ?)",
               (item_id, run_id, content))

    def recall_get(self, item_id: str) -> str | None:
        r = self.one("SELECT full_content FROM recall_cache WHERE item_id = ?", (item_id,))
        return r["full_content"] if r else None

    # --- settings ------------------------------------------------------------
    def setting_rows(self) -> dict[str, tuple[str, bool]]:
        return {r["key"]: (r["value"], bool(r["encrypted"])) for r in self.q("SELECT * FROM settings")}

    def set_setting(self, key: str, value: str, encrypted: bool = False) -> None:
        self.x("INSERT OR REPLACE INTO settings (key, value, encrypted) VALUES (?, ?, ?)", (key, value, int(encrypted)))

    def delete_setting(self, key: str) -> None:
        self.x("DELETE FROM settings WHERE key = ?", (key,))


class DbRecallStore:
    """Library RecallStore backed by the recall_cache table."""

    def __init__(self, db: Database):
        self.db = db

    def put(self, item_id: str, run_id: str, content: str) -> None:
        self.db.recall_put(item_id, run_id, content)

    def get(self, item_id: str) -> str | None:
        return self.db.recall_get(item_id)
