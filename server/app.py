"""JevCompact API (FastAPI). OpenAPI docs at /docs.

Run: `jevcompact serve` (binds 127.0.0.1 by default; data stays local).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

import jevcompact
from jevcompact.formats import UPLOAD_ERROR, FormatError, message_tokens, parse_session, text_of, validate_messages
from jevcompact.judges.jev import JevJudge
from jevcompact.report import CSV_COLUMNS
from jevcompact.summarizers.cloudflare import CloudflareSummarizer

from .crypto import SecretBox, load_fernet
from .db import Database
from .runner import SUMMARY_PREFIX, RunError, RunManager
from .settings import RunParams, SettingsIn, SettingsStore

log = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DASHBOARD_DIST = Path(__file__).resolve().parents[1] / "dashboard" / "dist"


class SecretRedactor(logging.Filter):
    """Removes saved API keys from any log record (defence in depth)."""

    def __init__(self, settings: SettingsStore):
        super().__init__()
        self.settings = settings

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for k in ("jev_api_key", "cf_api_token"):
            v = self.settings.secret(k)
            if v and v in msg:
                record.msg, record.args = msg.replace(v, "[redacted]"), ()
                msg = record.msg
        return True


class JevTestIn(BaseModel):
    api_key: str | None = None


class CloudflareTestIn(BaseModel):
    account_id: str | None = None
    api_token: str | None = None


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def create_app(db_path: str | Path | None = None, data_dir: str | Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("JEVCOMPACT_DATA", ".jevcompact"))
    db = Database(db_path or os.environ.get("JEVCOMPACT_DB") or data_dir / "jevcompact.db")
    settings = SettingsStore(db, SecretBox(load_fernet(data_dir)))
    runs = RunManager(db, settings, data_dir / "summary_cache")
    redactor = SecretRedactor(settings)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "server", "jevcompact"):
        logging.getLogger(name).addFilter(redactor)

    app = FastAPI(title="JevCompact API", version=jevcompact.__version__,
                  description="Session Compaction using Jev. All data stays in a local SQLite database.")
    app.state.db, app.state.settings, app.state.runs = db, settings, runs
    api = APIRouter(prefix="/api")
    parsed_cache: dict[str, Any] = {}

    @app.exception_handler(RunError)
    async def _run_error(_req, exc: RunError):
        return _err(exc.status, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(req: Request, exc: RequestValidationError):
        msgs = [e.get("msg", "") for e in exc.errors()]
        detail = next((m.removeprefix("Value error, ") for m in msgs if "Keep threshold" in m), None)
        return JSONResponse({"detail": detail or exc.errors()}, status_code=422)

    # --- helpers -------------------------------------------------------------
    def session_or_404(sid: str) -> dict:
        s = db.get_session(sid)
        if not s:
            raise RunError(404, "Session not found")
        return s

    def run_or_404(run_id: str) -> dict:
        r = db.get_run(run_id)
        if not r:
            raise RunError(404, "Run not found")
        return r

    def parsed(sid: str):
        if sid not in parsed_cache:
            parsed_cache[sid] = parse_session(db.get_messages(sid))
        return parsed_cache[sid]

    def run_view(r: dict | None) -> dict | None:
        if r is None:
            return None
        out = {k: v for k, v in r.items() if k not in ("output_json", "index_map_json", "config_json")}
        out["config"] = json.loads(r["config_json"] or "{}")
        tb, ta = r.get("tokens_before"), r.get("tokens_after")
        out["percent_saved"] = round(100 * (tb - ta) / tb, 1) if tb and ta is not None else None
        decs = db.decisions(r["id"])
        out["counts"] = {a: sum(1 for d in decs if d["action"] == a) for a in ("Pinned", "Kept", "Cut", "Dropped")}
        out["summary"] = db.summary(r["id"])
        if out["summary"]:
            out["summary"]["removed_lines"] = json.loads(out["summary"].pop("removed_lines_json"))
        return out

    # --- health --------------------------------------------------------------
    @api.get("/health")
    def health():
        judge, summ = settings.providers()
        return {"ok": True, "version": jevcompact.__version__, "judge": judge, "summarizer": summ}

    # --- sessions ------------------------------------------------------------
    @api.get("/sessions")
    def list_sessions(q: str | None = None, status: str | None = Query(None, pattern="^(Compacted|Fell back|Under budget)$")):
        return db.list_sessions(q, status)

    @api.post("/sessions", status_code=201)
    async def upload_session(request: Request, auto_run: bool = True, wait: bool = False, name: str | None = None):
        """Upload a session: multipart `file` (.json) or a JSON body (the message array, or {name, messages})."""
        ctype = request.headers.get("content-type", "")
        filename = None
        try:
            if ctype.startswith("multipart/form-data"):
                form = await request.form()
                f = form.get("file")
                if f is None or not hasattr(f, "read"):
                    return _err(422, UPLOAD_ERROR)
                filename = f.filename or "session.json"
                if not filename.lower().endswith(".json"):
                    return _err(422, UPLOAD_ERROR)
                raw = await f.read()
                if len(raw) > MAX_UPLOAD_BYTES:
                    return _err(413, "File is larger than 50 MB.")
                data = json.loads(raw.decode("utf-8"))
            else:
                data = await request.json()
            if isinstance(data, dict) and "messages" in data:
                name = name or data.get("name")
                data = data["messages"]
            messages = validate_messages(data)
            parse_session(messages)
        except (ValueError, UnicodeDecodeError, FormatError):
            return _err(422, UPLOAD_ERROR)
        name = name or (Path(filename).stem if filename else "session")
        sid = db.create_session(name, messages)
        run_id = await runs.start(sid, None, wait=wait) if auto_run else None
        return {**db.get_session(sid), "run_id": run_id}

    @api.get("/sessions/{sid}")
    def get_session(sid: str):
        s = session_or_404(sid)
        hist = [r["id"] for r in db.history(sid)]
        cur = s["current_run_id"]
        i = hist.index(cur) if cur in hist else -1
        return {**s, "current_run": run_view(db.get_run(cur)) if cur else None, "runs": db.list_runs(sid),
                "can_undo": i > 0, "can_redo": 0 <= i < len(hist) - 1}

    @api.delete("/sessions/{sid}", status_code=204)
    def delete_session(sid: str):
        session_or_404(sid)
        for r in db.list_runs(sid):
            runs.cancel(r["id"])
        db.delete_session(sid)
        parsed_cache.pop(sid, None)
        return Response(status_code=204)

    @api.get("/sessions/{sid}/messages")
    def original_messages(sid: str):
        session_or_404(sid)
        return db.get_messages(sid)

    @api.post("/sessions/{sid}/runs", status_code=202)
    async def start_run(sid: str, params: RunParams | None = None, wait: bool = False):
        session_or_404(sid)
        run_id = await runs.start(sid, params, wait=wait)
        return run_view(db.get_run(run_id))

    @api.get("/sessions/{sid}/runs")
    def list_runs(sid: str):
        session_or_404(sid)
        return db.list_runs(sid)

    @api.post("/sessions/{sid}/undo")
    def undo(sid: str):
        return {"current_run_id": runs.undo(sid)}

    @api.post("/sessions/{sid}/redo")
    def redo(sid: str):
        return {"current_run_id": runs.redo(sid)}

    # --- runs ----------------------------------------------------------------
    @api.get("/runs/{run_id}")
    def get_run(run_id: str):
        return run_view(run_or_404(run_id))

    @api.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        r = run_or_404(run_id)
        if r["status"] != "Running" or not runs.cancel(run_id):
            raise RunError(409, "This run is not running")
        return {"cancelled": True}

    @api.get("/runs/{run_id}/decisions")
    def decisions(run_id: str):
        r = run_or_404(run_id)
        items = parsed(r["session_id"]).items
        out = json.loads(r["output_json"]) if r["output_json"] else []
        index_map = json.loads(r["index_map_json"]) if r["index_map_json"] else []
        rows = []
        for d in db.decisions(run_id):
            content_after = None
            oi = index_map[d["message_index"]] if index_map else None
            if oi is not None:
                m = out[oi]
                content_after = (text_of(m["content"][d["block_index"]].get("content"))
                                 if d["block_index"] is not None else text_of(m.get("content")))
            rows.append({**d, "summarized": bool(d["summarized"]), "restored": bool(d["restored"]),
                         "content": items[d["item_index"]].text, "content_after": content_after})
        return rows

    @api.post("/runs/{run_id}/items/{item_id}/restore", status_code=201)
    def restore(run_id: str, item_id: str):
        new_id = runs.restore(run_id, item_id)
        return run_view(db.get_run(new_id))

    @api.get("/runs/{run_id}/recall/{item_id}", response_class=PlainTextResponse)
    def recall_item(run_id: str, item_id: str):
        run_or_404(run_id)
        text = db.recall_get(item_id)
        if text is None:
            raise RunError(404, "No recall entry for this item")
        return text

    @api.get("/runs/{run_id}/compare")
    def compare(run_id: str):
        r = run_or_404(run_id)
        if not r["output_json"]:
            raise RunError(409, "Run has no output yet")
        sid = r["session_id"]
        original = db.get_messages(sid)
        before_tokens = db.message_token_list(sid)
        out = json.loads(r["output_json"])
        index_map = json.loads(r["index_map_json"])
        session = parsed(sid)
        all_decs = db.decisions(run_id)
        decs: dict[int, list[dict]] = {}
        for d in all_decs:
            decs.setdefault(d["message_index"], []).append(d)

        def describe(m: dict, i: int | None) -> dict:
            role = m["role"].upper()
            items = [it for it in session.items if it.msg_index == i] if i is not None else []
            if items:
                role = "ERROR" if any(it.role == "ERROR" for it in items) else items[0].role
                title = " · ".join(it.title for it in items)
            else:
                title = (text_of(m.get("content")) or "")[:80] or ", ".join(
                    tc.get("function", {}).get("name", "") for tc in m.get("tool_calls") or [])
            return {"role": role, "title": title}

        summary_pos = next((k for k, m in enumerate(out)
                            if text_of(m.get("content")).startswith(SUMMARY_PREFIX)), None)
        rows, summary_shown = [], summary_pos is None
        for i, m in enumerate(original):
            oi = index_map[i]
            marker = None
            ds = decs.get(i, [])
            if oi is None:
                marker = "Summarized"
            elif any(d["restored"] and d["summarized"] for d in ds):
                marker = "Restored"
            elif any(d["action"] == "Dropped" for d in ds):
                marker = "Dropped"
            elif any(d["action"] == "Cut" for d in ds):
                marker = "Truncated"
            if not summary_shown and (oi is None or oi > summary_pos):
                sm = out[summary_pos]
                rows.append({"before": None, "after": {"role": "SUMMARY", "title": "Summary of earlier steps",
                                                       "tokens": message_tokens(sm),
                                                       "text": text_of(sm.get("content"))}, "marker": "Summary"})
                summary_shown = True
            after = None if oi is None else {**describe(out[oi], i), "tokens": message_tokens(out[oi])}
            rows.append({"before": {**describe(m, i), "tokens": before_tokens[i], "index": i},
                         "after": after, "marker": marker})
        return {
            "run_id": run_id, "session_id": sid, "status": r["status"],
            "tokens_before": r["tokens_before"], "tokens_after": r["tokens_after"],
            "jev_cost_usd": r["jev_cost_usd"], "latency_ms": r["latency_ms"], "neurons": r["neurons"],
            "dropped": sum(1 for d in all_decs if d["action"] == "Dropped"),
            "truncated": sum(1 for d in all_decs if d["action"] == "Cut"),
            "user_messages_touched": r["user_messages_lost"], "rows": rows,
        }

    def _filename(r: dict, ext: str) -> str:
        s = db.get_session(r["session_id"]) or {"name": "session"}
        return f'{s["name"]}-compacted-{r["seq"]}.{ext}'

    @api.get("/runs/{run_id}/export.json")
    def export_json(run_id: str):
        r = run_or_404(run_id)
        if not r["output_json"]:
            raise RunError(409, "Run has no output yet")
        return Response(json.dumps(json.loads(r["output_json"]), indent=2, ensure_ascii=False),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{_filename(r, "json")}"'})

    @api.get("/runs/{run_id}/report.json")
    def report_json(run_id: str):
        r = run_or_404(run_id)
        view = run_view(r)
        view["decisions"] = db.decisions(run_id)
        view["user_messages_touched"] = r["user_messages_lost"]
        return view

    @api.get("/runs/{run_id}/report.csv")
    def report_csv(run_id: str):
        r = run_or_404(run_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_COLUMNS)
        for d in db.decisions(run_id):
            w.writerow([d["item_id"], d["message_index"], d["role"], d["title"],
                        "" if d["score"] is None else f'{d["score"]:.3f}', d["action"], d["reason"],
                        d["tokens"], d["tokens_after"], bool(d["summarized"])])
        w.writerow(["TOTAL", "", "", f'status={r["status"]}', "", "", f'jev_cost_usd={r["jev_cost_usd"]}',
                    r["tokens_before"], r["tokens_after"], ""])
        name = _filename(r, "csv").replace("-compacted-", "-report-")
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # --- settings ------------------------------------------------------------
    @api.get("/settings")
    def get_settings():
        return settings.public()

    @api.put("/settings")
    def save_settings(body: dict):
        try:
            s = SettingsIn(**body)
        except ValidationError as exc:
            msgs = [e["msg"].removeprefix("Value error, ") for e in exc.errors()]
            return _err(422, next((m for m in msgs if "Keep threshold" in m), "; ".join(msgs)))
        return settings.save(s)

    @api.post("/settings/reset")
    def reset_settings():
        return settings.reset()

    @api.post("/settings/test/jev")
    async def test_jev(body: JevTestIn | None = None):
        key = (body.api_key if body and body.api_key else None) or settings.secret("jev_api_key") \
            or os.environ.get("JEV_API_KEY")
        if not key:
            return {"ok": False, "message": "No Jev API key saved."}
        cfg = settings.build_config()
        try:
            await JevJudge(key, cfg.jev_base_url, cfg.jev_model, cfg.jev_timeout_s).test_connection()
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "Connected"}

    @api.post("/settings/test/cloudflare")
    async def test_cloudflare(body: CloudflareTestIn | None = None):
        acc = (body.account_id if body and body.account_id else None) or settings.secret("cf_account_id") \
            or os.environ.get("CF_ACCOUNT_ID")
        tok = (body.api_token if body and body.api_token else None) or settings.secret("cf_api_token") \
            or os.environ.get("CF_API_TOKEN")
        if not acc or not tok:
            return {"ok": False, "message": "Cloudflare account ID and API token are both needed."}
        try:
            await CloudflareSummarizer(acc, tok, settings.build_config().cf_model, timeout_s=20).test_connection()
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "Connected"}

    app.include_router(api)

    # Built dashboard (phase d) is served from / when present.
    if DASHBOARD_DIST.exists():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = DASHBOARD_DIST / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(DASHBOARD_DIST / "index.html")

    return app


def get_app() -> FastAPI:
    """Factory for `uvicorn server.app:get_app --factory`."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    return create_app()
