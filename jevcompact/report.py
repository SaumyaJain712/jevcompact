"""FR12: export the compacted session (JSON) and a savings report (JSON and CSV)."""
from __future__ import annotations

import csv
import io
import json

from .models import CompactionResult

CSV_COLUMNS = ["item_id", "message_index", "role", "title", "score", "action", "reason",
               "tokens_before", "tokens_after", "summarized"]


def export_json(result: CompactionResult, indent: int | None = 2) -> str:
    """The compacted message array, in the same format as the input."""
    return json.dumps(result.messages, indent=indent, ensure_ascii=False)


def savings_report(result: CompactionResult) -> dict:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "format": result.format,
        "tokens_before": result.tokens_before,
        "tokens_after": result.tokens_after,
        "tokens_saved": result.tokens_saved,
        "percent_saved": round(result.percent_saved, 2),
        "items": {a: result.count(a) for a in ("Pinned", "Kept", "Cut", "Dropped")},
        "items_summarized": sum(1 for d in result.decisions if d.summarized),
        "user_messages_touched": result.user_messages_lost,
        "summary_lines_removed": len(result.summary.lines_removed) if result.summary else 0,
        "judge": result.judge,
        "summarizer": result.summarizer,
        "jev_requests": result.jev_requests,
        "jev_input_tokens": result.jev_input_tokens,
        "jev_cost_usd": result.jev_cost_usd,
        "cloudflare_neurons": result.summarizer_neurons,
        "judge_neurons": result.judge_neurons,
        "latency_ms": result.latency_ms,
        "fallback_reason": result.fallback_reason,
        "warnings": result.warnings,
        "created_at": result.created_at,
        "decisions": [d.to_dict() for d in result.decisions],
    }


def report_csv(result: CompactionResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for d in result.decisions:
        w.writerow([d.item_id, d.message_index, d.role, d.title,
                    "" if d.score is None else f"{d.score:.3f}", d.action, d.reason,
                    d.tokens, d.tokens_after, d.summarized])
    w.writerow(["TOTAL", "", "", f"status={result.status}", "", "", f"jev_cost_usd={result.jev_cost_usd}",
                result.tokens_before, result.tokens_after, ""])
    return buf.getvalue()
