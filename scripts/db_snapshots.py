"""Three snapshots of the JevCompact SQLite database for the report.

    python scripts/db_snapshots.py [path/to/jevcompact.db]

Default database: .e2e-data/shots/jevcompact.db, written by `SHOTS_REAL=1 npm run screenshots`
(real samples, Cloudflare judge standing in for Jev). Writes to docs/report_assets/:
  db_snapshot_1_sessions.{html,md,png}, db_snapshot_2_runs.{html,md,png}, db_snapshot_3_decisions.{html,md,png}
PNGs are rendered with the dashboard's Playwright Chromium (node dashboard/scripts/html_to_png.mjs).
Large columns (message content, output JSON) are left out; ids are shortened.
"""
from __future__ import annotations

import html
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "report_assets"
sys.path.insert(0, str(ROOT))

from jevcompact.judges.cloudflare import judge_label  # noqa: E402

CSS = """
body{font:13px/1.45 Inter,system-ui,sans-serif;color:#0b0b0b;background:#fcfcfb;margin:24px}
h1{font-size:18px;margin:0 0 4px} p{color:#52514e;margin:0 0 14px;max-width:1200px}
table{border-collapse:collapse;background:#fff;box-shadow:0 0 0 1px #e4e3df;border-radius:6px;overflow:hidden}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid #eeede9;white-space:nowrap}
th{background:#f3f2ee;font-weight:600;color:#33322f} td.num{text-align:right;font-variant-numeric:tabular-nums}
td.mono,th.mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px}
.wrap{white-space:normal;max-width:420px}
"""


def short(v) -> str:
    return (v[:8] + "…") if isinstance(v, str) and len(v) == 12 and v.isalnum() else v


def fmt(v, col: str) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:.4f}" if col in ("jev_cost_usd",) else f"{v:.2f}"
    return str(short(v))


def render(name: str, title: str, note: str, cols: list[str], rows: list[sqlite3.Row], wrap=()) -> None:
    num = {c for c in cols if rows and isinstance(rows[0][c], (int, float)) and rows[0][c] is not None}
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(
        f"<td class='{'num' if c in num else ''} {'wrap' if c in wrap else ''} {'mono' if c in ('id', 'title', 'item_id', 'run_id', 'session_id', 'current_run_id') else ''}'>"
        f"{html.escape(fmt(r[c], c))}</td>" for c in cols) + "</tr>" for r in rows)
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style>"
            f"<h1>{html.escape(title)}</h1><p>{html.escape(note)}</p><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>")
    (OUT / f"{name}.html").write_text(page)
    md = [f"# {title}", "", note, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(fmt(r[c], c).replace("|", "\\|") for c in cols) + " |" for r in rows]
    (OUT / f"{name}.md").write_text("\n".join(md) + "\n")


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".e2e-data" / "shots" / "jevcompact.db"
    if not db_path.exists():
        sys.exit(f"No database at {db_path}. Run `SHOTS_REAL=1 npm run screenshots` in dashboard/ first.")
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    judges = {r["judge"]: json.loads(r["config_json"] or "{}") for r in con.execute("SELECT judge, config_json FROM runs")}
    jl = ", ".join(judge_label(c.get("cf_judge_model", "")) if j == "cloudflare" else j for j, c in judges.items())

    sessions = con.execute("SELECT id, name, format, message_count, tokens_before, tokens_after, status, "
                           "current_run_id, created_at FROM sessions ORDER BY created_at").fetchall()
    render("db_snapshot_1_sessions", "Snapshot 1 — sessions",
           f"One row per uploaded session; the original messages live in `messages` and are never modified. "
           f"Judge: {jl}.", list(sessions[0].keys()), sessions)

    runs = con.execute("SELECT r.id, s.name AS session, r.seq, r.kind, r.preset, r.keep_threshold, r.drop_threshold, "
                       "r.budget, r.judge, r.summarizer, r.status, r.tokens_before, r.tokens_after, r.jev_requests "
                       "AS judge_requests, r.judge_neurons, r.neurons AS summary_neurons, r.jev_cost_usd, "
                       "r.latency_ms, r.fallback_reason FROM runs r JOIN sessions s ON s.id = r.session_id "
                       "ORDER BY r.created_at").fetchall()
    render("db_snapshot_2_runs", "Snapshot 2 — runs (one per compaction or restore; each is a version)",
           f"judge = cloudflare is the {jl}: cost is in judge_neurons, so jev_cost_usd is 0. "
           "summary_neurons is the Cloudflare summarizer's cost (0 when pruning alone got under the budget).",
           list(runs[0].keys()), runs, wrap=("fallback_reason",))

    sid = next((s["id"] for s in sessions if s["name"] == "checkout-bugfix-0412"), sessions[0]["id"])
    run_id = con.execute("SELECT current_run_id FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    decs = con.execute("SELECT item_index, role, title, score, action, reason, tokens, tokens_after, summarized, "
                       "restored FROM decisions WHERE run_id = ? ORDER BY item_index", (run_id,)).fetchall()
    render("db_snapshot_3_decisions", "Snapshot 3 — decisions for checkout-bugfix-0412 (the FR9 decision log)",
           f"One row per item per run: the judge's score ({jl}), the action and why. "
           "Pinned items (task, user messages, latest turn, errors) are never scored.",
           list(decs[0].keys()), decs, wrap=("reason",))

    names = [f"db_snapshot_{i}" for i in ("1_sessions", "2_runs", "3_decisions")]
    subprocess.run(["node", str(ROOT / "dashboard" / "scripts" / "html_to_png.mjs"),
                    *[str(OUT / f"{n}.html") for n in names]], check=True, cwd=ROOT / "dashboard")
    print("wrote", ", ".join(f"docs/report_assets/{n}.png" for n in names))


if __name__ == "__main__":
    main()
