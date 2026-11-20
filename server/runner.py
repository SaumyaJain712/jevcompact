"""Runs compactions in the background and manages versions (restore, undo, redo)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from jevcompact import compact
from jevcompact.formats import set_item_content, total_tokens
from jevcompact.judges import JudgeError, build_judge
from jevcompact.models import utcnow
from jevcompact.pipeline import CompactionError
from jevcompact.summarizers import SummarizerError, build_summarizer

from .db import Database, DbRecallStore
from .settings import RunParams, SettingsStore

log = logging.getLogger(__name__)


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class RunManager:
    def __init__(self, db: Database, settings: SettingsStore, cache_dir: Path):
        self.db = db
        self.settings = settings
        self.cache_dir = cache_dir
        self.tasks: dict[str, asyncio.Task] = {}

    async def start(self, session_id: str, params: RunParams | None = None, wait: bool = False) -> str:
        if not self.db.get_session(session_id):
            raise RunError(404, "Session not found")
        try:
            config = self.settings.build_config(params)
        except ValueError as exc:
            raise RunError(422, str(exc)) from exc
        run_id = uuid.uuid4().hex[:12]
        self.db.insert_run(run_id, session_id, preset=config.preset, keep=config.keep_threshold,
                           drop=config.drop_threshold, budget=config.budget, judge=config.judge,
                           summarizer=config.summarizer, config=config.public_dict())
        coro = self._execute(run_id, session_id, config)
        if wait:
            await coro
        else:
            task = asyncio.create_task(coro)
            self.tasks[run_id] = task
            task.add_done_callback(lambda _t: self.tasks.pop(run_id, None))
        return run_id

    async def _execute(self, run_id: str, session_id: str, config) -> None:
        try:
            judge = build_judge(config)
            summarizer = build_summarizer(config, cache_dir=self.cache_dir)
            result = await compact(self.db.get_messages(session_id), config, judge=judge, summarizer=summarizer,
                                   recall_store=DbRecallStore(self.db), run_id=run_id)
            self.db.save_result(run_id, result)
            self.db.set_current(session_id, run_id, supersede_after=True)
        except asyncio.CancelledError:
            self.db.mark_run(run_id, "Cancelled")
            raise
        except (CompactionError, JudgeError, SummarizerError, ValueError) as exc:
            self.db.mark_run(run_id, "Failed", str(exc))
        except Exception as exc:  # keep the server alive; message only, no secrets in our errors
            log.exception("run %s failed", run_id)
            self.db.mark_run(run_id, "Failed", f"{type(exc).__name__}: {exc}")

    def cancel(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    # --- versions ------------------------------------------------------------
    def restore(self, run_id: str, item_id: str) -> str:
        run = self.db.get_run(run_id)
        if not run or run["status"] not in ("Compacted", "Fell back", "Under budget"):
            raise RunError(404, "Run not found or not finished")
        decisions = self.db.decisions(run_id)
        d = next((d for d in decisions if d["item_id"] == item_id), None)
        if d is None:
            raise RunError(404, "Item not found in this run")
        if d["action"] not in ("Dropped", "Cut"):
            raise RunError(409, f"Only dropped or cut items can be restored (this one is {d['action']})")
        full = self.db.recall_get(item_id)
        if full is None:
            raise RunError(404, "No recall entry for this item")
        out = json.loads(run["output_json"])
        index_map = json.loads(run["index_map_json"])
        oi = index_map[d["message_index"]]
        if oi is None:
            raise RunError(409, "This item was folded into the summary, so it can't be put back in place.")
        set_item_content(out[oi], d["block_index"], full)

        new_id = uuid.uuid4().hex[:12]
        sid = run["session_id"]
        self.db.insert_run(new_id, sid, preset=run["preset"], keep=run["keep_threshold"], drop=run["drop_threshold"],
                           budget=run["budget"], judge=run["judge"], summarizer=run["summarizer"],
                           config=json.loads(run["config_json"] or "{}"), kind="restore", parent_run_id=run_id,
                           status=run["status"])
        now = utcnow()
        with self.db.lock, self.db.conn:
            self.db.conn.execute(
                "UPDATE runs SET jev_cost_usd=0, latency_ms=0, tokens_before=?, tokens_after=?, user_messages_lost=?, "
                "fallback_reason=?, output_json=?, index_map_json=? WHERE id=?",
                (run["tokens_before"], total_tokens(out), run["user_messages_lost"], run["fallback_reason"],
                 json.dumps(out, ensure_ascii=False), run["index_map_json"], new_id))
            for x in decisions:
                restored = x["item_id"] == item_id or bool(x["restored"])
                action = "Kept" if x["item_id"] == item_id else x["action"]
                reason = (f"restored by user (was {x['action']}, score {x['score']:.2f})"
                          if x["item_id"] == item_id else x["reason"])
                tokens_after = x["tokens"] if x["item_id"] == item_id else x["tokens_after"]
                self.db.conn.execute(
                    "INSERT INTO decisions (run_id, message_index, item_id, item_index, block_index, role, title, "
                    "score, action, reason, tokens, tokens_after, summarized, restored, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id, x["message_index"], x["item_id"], x["item_index"], x["block_index"], x["role"],
                     x["title"], x["score"], action, reason, x["tokens"], tokens_after, x["summarized"],
                     int(restored), now if x["item_id"] == item_id else x["created_at"]))
            s = self.db.summary(run_id)
            if s:
                self.db.conn.execute("INSERT INTO summaries VALUES (?,?,?,?,?)",
                                     (new_id, s["text"], s["lines_removed"], s["removed_lines_json"], s["checked"]))
        self.db.set_current(sid, new_id, supersede_after=True)
        return new_id

    def _move(self, session_id: str, step: int) -> str:
        sess = self.db.get_session(session_id)
        if not sess:
            raise RunError(404, "Session not found")
        hist = self.db.history(session_id)
        ids = [r["id"] for r in hist]
        if sess["current_run_id"] not in ids:
            raise RunError(409, "Nothing to undo" if step < 0 else "Nothing to redo")
        i = ids.index(sess["current_run_id"]) + step
        if not 0 <= i < len(ids):
            raise RunError(409, "Nothing to undo" if step < 0 else "Nothing to redo")
        self.db.set_current(session_id, ids[i], supersede_after=False)
        return ids[i]

    def undo(self, session_id: str) -> str:
        return self._move(session_id, -1)

    def redo(self, session_id: str) -> str:
        return self._move(session_id, +1)
