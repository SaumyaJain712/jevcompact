"""Command line: `jevcompact compact in.json -o out.json --preset balanced`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import PRESETS, CompactionConfig
from .formats import FormatError
from .pipeline import CompactionError, compact_sync
from .report import export_json, report_csv, savings_report


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover
        pass


def cmd_compact(args: argparse.Namespace) -> int:
    overrides = {}
    if args.budget:
        overrides["budget"] = args.budget
    if args.judge:
        overrides["judge"] = args.judge
    if args.summarizer:
        overrides["summarizer"] = args.summarizer
    keep, drop = PRESETS[args.preset]
    config = CompactionConfig.from_env(preset=args.preset, keep_threshold=keep, drop_threshold=drop, **overrides)
    try:
        messages = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = compact_sync(messages, config)
    except (FormatError, json.JSONDecodeError) as exc:
        print(f"error: {exc if isinstance(exc, FormatError) else FormatError()}", file=sys.stderr)
        return 2
    except CompactionError as exc:
        print(f"error: compaction failed and fallback is off: {exc}", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.write_text(export_json(result), encoding="utf-8")
    if args.report:
        Path(args.report).write_text(json.dumps(savings_report(result), indent=2), encoding="utf-8")
    if args.csv:
        Path(args.csv).write_text(report_csv(result), encoding="utf-8")
    print(f"{result.status}: {result.tokens_before:,} → {result.tokens_after:,} tokens "
          f"({result.percent_saved:.0f}% smaller) · Jev cost ${result.jev_cost_usd:.4f} · "
          f"{result.latency_ms / 1000:.2f} s · kept {result.count('Kept')}, cut {result.count('Cut')}, "
          f"dropped {result.count('Dropped')}, pinned {result.count('Pinned')} · judge={result.judge}, "
          f"summarizer={result.summarizer}")
    if result.fallback_reason:
        print(f"fell back: {result.fallback_reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jevcompact", description="Session Compaction using Jev")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compact", help="compact a session JSON file")
    c.add_argument("input")
    c.add_argument("-o", "--output", required=True)
    c.add_argument("--preset", choices=sorted(PRESETS), default="balanced")
    c.add_argument("--budget", type=int)
    c.add_argument("--judge", choices=["jev", "mock"])
    c.add_argument("--summarizer", choices=["cloudflare", "mock"])
    c.add_argument("--report", help="write the savings report as JSON")
    c.add_argument("--csv", help="write the savings report as CSV")
    c.set_defaults(func=cmd_compact)
    return p


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
