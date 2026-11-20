"""Evaluate four compaction methods on every sample session.

    python eval/run_eval.py --mode real --plan   # estimate Cloudflare neurons first, run nothing paid
    python eval/run_eval.py --mode real          # main run: real Jev + real Cloudflare
    python eval/run_eval.py --mode mock          # secondary run: MockJudge + MockSummarizer

Methods: FIFO sliding window, plain summary only, Jev prune only, JevCompact hybrid.
Real and mock results are written to separate files and never combined:
  eval/results.csv (real), eval/results_mock.csv (mock), and clipping_/threshold_sweep_ files per mode.
Then eval/report.py builds eval/results.md and docs/figures/*.png.

Labels come from data/samples/*.labels.json (written before any judge run).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jevcompact import CompactionConfig, MemoryRecallStore, MockJudge, MockSummarizer, compact  # noqa: E402
from jevcompact.formats import parse_session, total_tokens, user_messages_lost  # noqa: E402
from jevcompact.prune import classify, drop_stub, truncate  # noqa: E402
from jevcompact.summarize import build_request, select_groups  # noqa: E402
from jevcompact.summarizers import SummarizerError, SummaryRequest, SummaryResult  # noqa: E402
from jevcompact.tokens import count_tokens  # noqa: E402

SAMPLES = ROOT / "data" / "samples"
EVAL = ROOT / "eval"
CACHE = EVAL / ".cache"
METHODS = ["fifo", "plain", "prune_only", "hybrid"]
METHOD_LABEL = {"fifo": "FIFO sliding window", "plain": "Plain summary only", "prune_only": "Jev prune only",
                "hybrid": "JevCompact hybrid"}
FREE_NEURONS_PER_DAY = 10_000
CLIPS = [300, 1000, None]  # None = unclipped


# --- data ------------------------------------------------------------------------

@dataclass
class Sample:
    name: str
    messages: list[dict]
    labels: dict

    @property
    def needed(self) -> dict[str, bool]:
        return {i["tool_call_id"]: i["needed"] for i in self.labels["items"]}


def load_samples(only: list[str] | None = None) -> list[Sample]:
    out = []
    for p in sorted(SAMPLES.glob("*.json")):
        if p.name.endswith(".labels.json") or (only and p.stem not in only):
            continue
        out.append(Sample(p.stem, json.loads(p.read_text()), json.loads((SAMPLES / f"{p.stem}.labels.json").read_text())))
    return out


# --- FIFO baseline ---------------------------------------------------------------

def fifo(messages: list[dict], budget: int) -> list[dict]:
    """Drop the oldest messages (whole turns, so tool calls stay paired) until under budget.

    Like a plain sliding window it keeps system messages and the latest turn, and drops user
    messages as readily as anything else.
    """
    s = parse_session(messages)
    total = sum(s.msg_tokens)
    removed: set[int] = set()
    movable = [g for g in s.groups if g.kind != "system"][:-1]
    for g in movable:
        if total <= budget:
            break
        removed.add(g.index)
        total -= sum(s.msg_tokens[i] for i in g.msg_indices)
    return [copy.deepcopy(m) for i, m in enumerate(messages) if s.msg_group[i] not in removed]


# --- Cloudflare guard + cache ------------------------------------------------------

class NeuronLedger:
    """Neurons spent per UTC day, persisted, so runs on the same day add up."""

    def __init__(self, limit: float):
        self.limit = limit
        self.path = CACHE / f"neurons-{date.today().isoformat()}.json"
        self.spent = json.loads(self.path.read_text())["spent"] if self.path.exists() else 0.0

    def add(self, n: float) -> None:
        self.spent += n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"spent": round(self.spent, 2), "limit": self.limit}))


class BudgetExceeded(RuntimeError):
    pass


def estimate_neurons(req: SummaryRequest, model_spec: dict) -> float:
    tokens = sum(count_tokens(e.text) + count_tokens(e.heading) for e in req.entries) + count_tokens(req.task) + 300
    return tokens * model_spec["in"] / 1e6 + model_spec.get("max_out", 512) * model_spec["out"] / 1e6


class EvalSummarizer:
    """Disk cache keyed by request hash (text + neurons of the first generation) and a daily neuron guard."""

    def __init__(self, inner, ledger: NeuronLedger | None, mode: str):
        self.inner = inner
        self.name = inner.name
        self.model = getattr(inner, "model", "mock")
        self.ledger = ledger
        self.dir = CACHE / "summaries" / mode
        self.calls = 0

    async def summarize(self, req: SummaryRequest) -> SummaryResult:
        key = req.key(f"{self.name}:{self.model}")
        path = self.dir / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text())
            return SummaryResult(d["text"], d["neurons"], True, d.get("input_tokens", 0))
        if self.ledger is not None:
            from jevcompact.summarizers.cloudflare import MODELS

            est = estimate_neurons(req, MODELS.get(self.model, {"in": 25_608, "out": 75_147}))
            if self.ledger.spent + est > self.ledger.limit:
                raise BudgetExceeded(f"Summary needs ~{est:.0f} neurons; {self.ledger.spent:.0f} of "
                                     f"{self.ledger.limit:.0f} already spent today. Stopping before the free tier is exceeded.")
        res = await self.inner.summarize(req)
        self.calls += 1
        if self.ledger is not None:
            self.ledger.add(res.neurons)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": res.text, "neurons": res.neurons, "input_tokens": res.input_tokens}))
        return SummaryResult(res.text, res.neurons, False, res.input_tokens)

    async def test_connection(self) -> bool:
        return await self.inner.test_connection()


# --- metrics -----------------------------------------------------------------------

def tool_texts(messages: list[dict]) -> dict[str, str]:
    return {it.tool_call_id: it.text for it in parse_session(messages).items if it.tool_call_id}


def score_output(sample: Sample, out: list[dict]) -> dict:
    before = tool_texts(sample.messages)
    after = tool_texts(out)
    needed = [k for k, v in sample.needed.items() if v]
    unneeded = [k for k, v in sample.needed.items() if not v]
    kept = lambda k: after.get(k) == before[k]  # noqa: E731  verbatim
    return {
        "needed_items": len(needed),
        "needed_kept": sum(kept(k) for k in needed),
        "needed_kept_pct": round(100 * sum(kept(k) for k in needed) / max(1, len(needed)), 1),
        "needed_truncated": sum(1 for k in needed if k in after and not kept(k) and "truncated" in after[k]),
        "needed_removed": sum(1 for k in needed if k not in after or "dropped this tool output" in after[k]),
        "unneeded_removed_pct": round(100 * sum(not kept(k) for k in unneeded) / max(1, len(unneeded)), 1),
        "user_messages_lost": user_messages_lost(sample.messages, out),
    }


@dataclass
class Row:
    mode: str
    session: str
    method: str
    status: str
    tokens_before: int
    tokens_after: int
    pct_saved: float
    needed_items: int
    needed_kept: int
    needed_kept_pct: float
    needed_truncated: int
    needed_removed: int
    unneeded_removed_pct: float
    user_messages_lost: int
    summary_lines: int | str
    invented_lines_removed: int | str
    latency_ms: float
    scoring_latency_ms: float
    jev_requests: int
    jev_input_tokens: int
    jev_cost_usd: float
    cf_neurons: float
    summary_cached: bool
    judge: str
    summarizer: str
    fallback_reason: str = ""


# --- runs ---------------------------------------------------------------------------

def providers(mode: str, ledger: NeuronLedger | None):
    if mode == "mock":
        return (lambda: MockJudge()), EvalSummarizer(MockSummarizer(invent=False), None, "mock"), "mock", "mock"
    from jevcompact.judges.jev import JevJudge
    from jevcompact.summarizers.cloudflare import CloudflareSummarizer

    cfg = CompactionConfig.from_env(judge="jev", summarizer="cloudflare")
    summ = EvalSummarizer(CloudflareSummarizer.from_config(cfg), ledger, "real")
    return (lambda: JevJudge.from_config(cfg)), summ, f"jev ({cfg.jev_model})", f"cloudflare ({cfg.cf_model})"


async def run_method(sample: Sample, method: str, mode: str, make_judge, summ, judge_label, summ_label,
                     clip: int | None = 300) -> tuple[Row, object]:
    cfg = CompactionConfig(jev_item_max_tokens=clip or 10_000_000)
    before = total_tokens(sample.messages)
    if method == "fifo":
        t = time.perf_counter()
        out = fifo(sample.messages, cfg.budget)
        ms = (time.perf_counter() - t) * 1000
        m = score_output(sample, out)
        after = total_tokens(out)
        return Row(mode, sample.name, method, "Under budget" if before <= cfg.budget else "Compacted", before, after,
                   round(100 * (before - after) / before, 1), **m, summary_lines="n/a", invented_lines_removed="n/a",
                   latency_ms=round(ms, 1), scoring_latency_ms=0, jev_requests=0, jev_input_tokens=0, jev_cost_usd=0,
                   cf_neurons=0, summary_cached=False, judge="none", summarizer="none"), None
    res = await compact(sample.messages, cfg, judge=make_judge(), summarizer=summ, recall_store=MemoryRecallStore(),
                        method=method)
    m = score_output(sample, res.messages)
    s = res.summary
    return Row(mode, sample.name, method, res.status, res.tokens_before, res.tokens_after, round(res.percent_saved, 1),
               **m, summary_lines=len(s.lines_kept) if s else 0,
               invented_lines_removed=(len(s.lines_removed) if s and s.checked else ("n/a" if method == "plain" or not s else 0)),
               latency_ms=res.latency_ms, scoring_latency_ms=res.scoring_latency_ms, jev_requests=res.jev_requests,
               jev_input_tokens=res.jev_input_tokens, jev_cost_usd=res.jev_cost_usd, cf_neurons=res.summarizer_neurons,
               summary_cached=bool(s and s.cached),
               judge="none" if method == "plain" else judge_label, summarizer="none" if method == "prune_only" else summ_label,
               fallback_reason=res.fallback_reason or ""), res


def sweep_rows(mode: str, results: dict[str, object], samples: list[Sample]) -> list[dict]:
    """Re-classify the recorded Jev scores at other thresholds (no new Jev calls)."""
    rows = []
    keeps = [round(0.30 + 0.05 * i, 2) for i in range(13)]  # 0.30 .. 0.90
    drops = [round(0.0 + 0.05 * i, 2) for i in range(7)]  # 0.00 .. 0.30
    for keep in keeps:
        for drop in drops:
            if keep <= drop:
                continue
            cfg = CompactionConfig(keep_threshold=keep, drop_threshold=drop, preset="custom")
            needed = kept = 0
            before = after = 0
            for sample in samples:
                res = results.get(sample.name)
                if res is None:
                    continue
                labels = sample.needed
                items = parse_session(sample.messages).items
                for d in res.decisions:
                    it = items[d.item_index]
                    if it.role not in ("TOOL", "ERROR"):
                        continue
                    before += d.tokens
                    if d.action == "Pinned" or d.score is None:
                        action, tok = "Kept", d.tokens
                    else:
                        action = classify(d.score, cfg)
                        tok = (d.tokens if action == "Kept" else count_tokens(truncate(it.text, cfg, d.item_id))
                               if action == "Cut" else count_tokens(drop_stub(it, d.score, d.item_id)))
                    after += tok
                    if labels.get(it.tool_call_id):
                        needed += 1
                        kept += action == "Kept"
            rows.append({"mode": mode, "keep": keep, "drop": drop,
                         "preset": next((n for n, v in {"conservative": (0.3, 0.05), "balanced": (0.5, 0.1),
                                                         "aggressive": (0.7, 0.2)}.items() if v == (keep, drop)), ""),
                         "needed_kept_pct": round(100 * kept / max(1, needed), 1),
                         "tool_tokens_saved_pct": round(100 * (before - after) / max(1, before), 1)})
    return rows


def write_csv(path: Path, rows: list) -> None:
    rows = [asdict(r) if not isinstance(r, dict) else r for r in rows]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def plan(samples: list[Sample]) -> float:
    """Upper-bound estimate of Cloudflare neurons for a real run (only summaries cost neurons)."""
    from jevcompact.pinning import apply_pins
    from jevcompact.summarizers.cloudflare import MODELS

    cfg = CompactionConfig.from_env(summarizer="cloudflare")
    spec = MODELS.get(cfg.cf_model, {"in": 25_608, "out": 75_147, "max_out": 512})
    total = 0.0
    print(f"Cloudflare model: {cfg.cf_model}")
    for s in samples:
        session = parse_session(s.messages)
        apply_pins(session, cfg)
        if session.tokens <= cfg.budget:
            print(f"  {s.name:22} under budget: no summary")
            continue
        groups = select_groups(session, session.msg_tokens, cfg.budget, cfg.summary_reserve_tokens)
        req = build_request(session, groups, {})
        cached = (CACHE / "summaries" / "real" / f"{req.key(f'cloudflare:{cfg.cf_model}')}.json").exists()
        est = 0.0 if cached else estimate_neurons(req, spec)
        # hybrid summarizes at most what plain does, after pruning (smaller), so <= 2x plain in total
        total += 2 * est
        print(f"  {s.name:22} plain summary input ~{sum(count_tokens(e.text) for e in req.entries):>7,} tokens "
              f"-> ~{est:,.0f} neurons{' (cached)' if cached else ''}; hybrid at most the same")
    print(f"Upper bound for this run: ~{total:,.0f} neurons (free tier {FREE_NEURONS_PER_DAY:,}/day)")
    return total


async def main_async(args) -> None:
    samples = load_samples(args.only)
    if args.plan:  # calls nothing paid, so it works without keys
        plan(samples)
        return
    if args.mode == "real":
        missing = [k for k in ("JEV_API_KEY", "CF_ACCOUNT_ID", "CF_API_TOKEN") if not os.environ.get(k)]
        if missing:
            sys.exit(f"Real mode needs {', '.join(missing)} (in .env). Not falling back to mock: the two are never mixed.")
    ledger = NeuronLedger(args.neuron_limit) if args.mode == "real" else None
    make_judge, summ, jl, sl = providers(args.mode, ledger)
    suffix = "" if args.mode == "real" else "_mock"
    rows, clip_rows, scored = [], [], {}
    started = time.time()
    for s in samples:
        for method in METHODS:
            row, res = await run_method(s, method, args.mode, make_judge, summ, jl, sl)
            rows.append(row)
            if method == "prune_only" and res is not None and res.status == "Compacted":
                scored[s.name] = res
            print(f"[{args.mode}] {s.name:22} {method:10} {row.status:12} {row.pct_saved:5.1f}% saved  "
                  f"needed kept {row.needed_kept_pct:5.1f}%  ${row.jev_cost_usd:.4f}  {row.latency_ms:7.0f} ms")
        if not args.skip_clipping:
            for clip in CLIPS:
                row, res = await run_method(s, "prune_only", args.mode, make_judge, summ, jl, sl, clip=clip)
                clip_rows.append({"mode": args.mode, "session": s.name, "clip": clip or "unclipped",
                                  "status": row.status, "needed_kept_pct": row.needed_kept_pct,
                                  "pct_saved": row.pct_saved, "jev_input_tokens": row.jev_input_tokens,
                                  "jev_cost_usd": row.jev_cost_usd, "scoring_latency_ms": row.scoring_latency_ms})
    write_csv(EVAL / f"results{suffix}.csv", rows)
    if clip_rows:
        write_csv(EVAL / f"clipping{suffix}.csv", clip_rows)
    if scored:
        write_csv(EVAL / f"threshold_sweep{suffix}.csv", sweep_rows(args.mode, scored, samples))
    meta = {"mode": args.mode, "judge": jl, "summarizer": sl, "date": date.today().isoformat(),
            "duration_s": round(time.time() - started, 1), "budget": CompactionConfig().budget,
            "summaries_generated": summ.calls, "neurons_spent_today": ledger.spent if ledger else 0}
    (EVAL / f"run{suffix}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["real", "mock"], required=True)
    p.add_argument("--plan", action="store_true", help="estimate Cloudflare neurons and exit")
    p.add_argument("--only", nargs="*", help="limit to these sessions")
    p.add_argument("--skip-clipping", action="store_true")
    p.add_argument("--neuron-limit", type=float, default=9_000, help="stop before spending more today (default 9,000)")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except BudgetExceeded as exc:
        sys.exit(f"STOPPED: {exc}")
    except SummarizerError as exc:
        sys.exit(f"Cloudflare error: {exc}")


if __name__ == "__main__":
    main()
