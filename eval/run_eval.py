"""Evaluate four compaction methods on every sample session.

    python eval/run_eval.py --mode real --plan   # estimate Cloudflare neurons first, run nothing paid
    python eval/run_eval.py --mode real          # main run: Cloudflare judge (JUDGE=cloudflare) + Cloudflare summarizer
    python eval/run_eval.py --mode mock          # secondary run: MockJudge + MockSummarizer

Methods: FIFO sliding window, plain summary only, prune only (judge), JevCompact hybrid.
The judge in real mode is chosen with JUDGE=jev|cloudflare (default cloudflare: the free
"Cloudflare (<model>) judge, standing in for Jev"). JUDGE=mock is refused in real mode.

Real and mock results are written to separate files and never combined:
  eval/results.csv (real), eval/results_mock.csv (mock), and clipping_ / threshold_sweep_ /
  threshold_loso_ files per mode. Then eval/report.py builds eval/results.md and docs/figures/*.png.

Compaction point: every sample ends with the agent's final "done" answer. Compaction fires
mid-task in practice (FR2), and a judge asked "is this still needed to finish the task?" after
the task is finished answers "no" for everything, so each session is evaluated at the point
just before that final answer (the one closing assistant message is left out, for every
method; labels are unchanged). See PROGRESS.md, design deviations.

Thresholds: every judge method runs with the default keep/drop thresholds (0.50 / 0.10) and,
because the Cloudflare judge's scores are not calibrated like Jev's, again with thresholds
tuned by the sweep over the recorded scores. A leave-one-session-out check shows how well the
tuned thresholds carry over to a session they were not tuned on.

Cost safety: judge replies and summaries are cached on disk by request hash, so re-runs and
the second (tuned) pass only pay for requests not seen before. A daily neuron ledger
(UTC day, like Cloudflare's free allocation) stops the run before --neuron-limit is passed;
re-running the next day resumes from the cache.

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
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jevcompact import CompactionConfig, MemoryRecallStore, MockJudge, MockSummarizer, compact  # noqa: E402
from jevcompact.batching import effective_cap, question_cost  # noqa: E402
from jevcompact.formats import parse_session, total_tokens, user_messages_lost  # noqa: E402
from jevcompact.judges.base import JudgeError, JudgeResponse, Question, request_cap  # noqa: E402
from jevcompact.prune import classify, drop_stub, score_items, truncate  # noqa: E402
from jevcompact.ratelimit import RateLimiter  # noqa: E402
from jevcompact.summarize import build_request, select_groups  # noqa: E402
from jevcompact.summarizers import SummarizerError, SummaryRequest, SummaryResult  # noqa: E402
from jevcompact.tokens import count_tokens  # noqa: E402

SAMPLES = ROOT / "data" / "samples"
EVAL = ROOT / "eval"
CACHE = EVAL / ".cache"
METHODS = ["fifo", "plain", "prune_only", "hybrid"]
JUDGE_METHODS = ["prune_only", "hybrid"]
METHOD_LABEL = {"fifo": "FIFO sliding window", "plain": "Plain summary only", "prune_only": "Prune only (judge)",
                "hybrid": "JevCompact hybrid"}
FREE_NEURONS_PER_DAY = 10_000
CLIPS = [300, 1000, None]  # None = unclipped
DEFAULT_KEEP, DEFAULT_DROP = 0.50, 0.10
TARGET_KEPT = 95.0
CHECK_REQUESTS_EST = 2  # summary check: ~12k tokens of sources, at most two requests


# --- data ------------------------------------------------------------------------

@dataclass
class Sample:
    name: str
    messages: list[dict]
    labels: dict

    @property
    def needed(self) -> dict[str, bool]:
        return {i["tool_call_id"]: i["needed"] for i in self.labels["items"]}


def is_final_answer(m: dict) -> bool:
    """An assistant message with no tool call: the agent's closing answer."""
    if m.get("role") != "assistant" or m.get("tool_calls"):
        return False
    c = m.get("content")
    return not (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in c))


def compaction_point(messages: list[dict]) -> list[dict]:
    """The session as it was just before the agent's final answer (see module docstring)."""
    return messages[:-1] if messages and is_final_answer(messages[-1]) else messages


def load_samples(only: list[str] | None = None) -> list[Sample]:
    out = []
    for p in sorted(SAMPLES.glob("*.json")):
        if p.name.endswith(".labels.json") or (only and p.stem not in only):
            continue
        out.append(Sample(p.stem, compaction_point(json.loads(p.read_text())),
                          json.loads((SAMPLES / f"{p.stem}.labels.json").read_text())))
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

def utc_day() -> str:
    """Cloudflare's free allocation resets at 00:00 UTC, so the ledger uses the UTC date."""
    return datetime.now(timezone.utc).date().isoformat()


class NeuronLedger:
    """Neurons spent per UTC day, persisted, so runs on the same day add up."""

    def __init__(self, limit: float):
        self.limit = limit
        self.path = CACHE / f"neurons-{utc_day()}.json"
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


def judge_spec(model: str) -> dict:
    from jevcompact.judges.cloudflare import JUDGE_MODELS

    return JUDGE_MODELS.get(model, {"in": 25_608, "out": 75_147})


def estimate_judge_neurons(tokens: int, n_questions: int, spec: dict) -> float:
    """Upper-bound-ish: input tokens plus the JSON reply (reasoning models: their reasoning budget)."""
    out = (4_000 + 40 * n_questions) if spec.get("reasoning") else (64 + 14 * n_questions)
    return (tokens * spec["in"] + out * spec["out"]) / 1e6


def judge_key(model: str, state: str, questions: list[Question]) -> str:
    from jevcompact.judges.cloudflare import SYSTEM_PROMPT

    payload = [model, SYSTEM_PROMPT, state, [(q.id, q.text, q.meta.get("title")) for q in questions]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:32]


class EvalJudge:
    """Wraps a real judge: disk cache of replies (temperature 0) and the daily neuron guard.

    A cache hit returns the scores and the neurons of the first generation (so each row shows
    what its requests cost), but adds nothing to the ledger. When the guard trips, the judge
    raises JudgeError (which the pipeline would turn into a fallback) and records `stop`;
    run_method then discards that result and stops the run.
    """

    def __init__(self, inner, ledger: NeuronLedger | None, mode: str):
        self.inner = inner
        self.name = inner.name
        self.model = getattr(inner, "model", inner.name)
        self.max_request_tokens = getattr(inner, "max_request_tokens", None)
        self.request_timeout_s = getattr(inner, "request_timeout_s", None)
        self.ledger = ledger
        self.dir = CACHE / "judge" / mode
        self.stop: BudgetExceeded | None = None
        self.calls = self.cache_hits = self.retries = self.failures = 0
        self.spent = 0.0

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse:
        path = self.dir / f"{judge_key(self.model, state, questions)}.json"
        if path.exists():
            d = json.loads(path.read_text())
            self.cache_hits += 1
            return JudgeResponse(d["scores"], d["input_tokens"], d["output_tokens"], d["model"], d["neurons"])
        est = 0.0
        if self.ledger is not None:
            tokens = count_tokens(state) + sum(question_cost(q) for q in questions)
            est = estimate_judge_neurons(tokens, len(questions), judge_spec(self.model))
            if self.ledger.spent + est > self.ledger.limit:
                self.stop = BudgetExceeded(
                    f"Judge request needs ~{est:.0f} neurons; {self.ledger.spent:.0f} of {self.ledger.limit:.0f} "
                    "already spent today. Stopping before the free tier is exceeded.")
                raise JudgeError(str(self.stop))
        self.calls += 1
        try:
            res = await self.inner.evaluate(state, questions)
        except JudgeError as exc:
            self.failures += 1
            spent = getattr(exc, "neurons", None)
            if self.ledger is not None:  # a timed-out call may still be billed: count the estimate
                self.ledger.add(spent if spent is not None else est)
            raise
        self.retries += res.attempts - 1
        self.spent += res.neurons
        if self.ledger is not None:
            self.ledger.add(res.neurons)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"scores": res.scores, "input_tokens": res.input_tokens,
                                    "output_tokens": res.output_tokens, "model": res.model,
                                    "neurons": res.neurons, "attempts": res.attempts}))
        return res

    async def test_connection(self) -> bool:
        return await self.inner.test_connection()


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
    needed = [k for k, v in sample.needed.items() if v and k in before]
    unneeded = [k for k, v in sample.needed.items() if not v and k in before]
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
    thresholds: str  # "default" or "tuned"
    keep: float | str
    drop: float | str
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
    judge_requests: int
    judge_input_tokens: int
    jev_cost_usd: float
    judge_neurons: float
    cf_neurons: float
    judge_retries: int
    summary_cached: bool
    judge: str
    summarizer: str
    fallback_reason: str = ""


# --- runs ---------------------------------------------------------------------------

def real_judge_kind() -> str:
    """JUDGE=jev|cloudflare picks the real judge. Unset, or JUDGE=mock (the server's setting in .env),
    gives the evaluation default, cloudflare: mock results only ever come from --mode mock."""
    kind = (os.environ.get("JUDGE") or "").strip()
    if kind in ("cloudflare", "jev"):
        return kind
    if kind and kind != "mock":
        sys.exit(f"Unknown JUDGE={kind}; use jev, cloudflare or mock.")
    if kind == "mock":
        print("Note: JUDGE=mock in the environment; real mode uses the evaluation default JUDGE=cloudflare.")
    return "cloudflare"


def judge_name(cfg: CompactionConfig, kind: str) -> str:
    if kind == "cloudflare":
        from jevcompact.judges.cloudflare import judge_label

        return judge_label(cfg.cf_judge_model)
    return f"Jev ({cfg.jev_model})"


def providers(mode: str, ledger: NeuronLedger | None):
    if mode == "mock":
        return (lambda: MockJudge()), EvalSummarizer(MockSummarizer(invent=False), None, "mock"), "mock", "mock"
    from jevcompact.summarizers.cloudflare import CloudflareSummarizer

    kind = real_judge_kind()
    cfg = CompactionConfig.from_env(judge=kind, summarizer="cloudflare")
    summ = EvalSummarizer(CloudflareSummarizer.from_config(cfg), ledger, "real")
    if kind == "cloudflare":
        from jevcompact.judges.cloudflare import CloudflareJudge

        make = lambda: EvalJudge(CloudflareJudge.from_config(cfg), ledger, "real")  # noqa: E731
    else:
        from jevcompact.judges.jev import JevJudge

        make = lambda: EvalJudge(JevJudge.from_config(cfg), None, "real-jev")  # noqa: E731  billed in USD
    return make, summ, judge_name(cfg, kind), f"Cloudflare summarizer ({cfg.cf_model})"


async def run_method(sample: Sample, method: str, mode: str, make_judge, summ, judge_label, summ_label,
                     clip: int | None = 300, keep: float = DEFAULT_KEEP, drop: float = DEFAULT_DROP,
                     thresholds: str = "default") -> tuple[Row, object]:
    cfg = CompactionConfig(jev_item_max_tokens=clip or 10_000_000, keep_threshold=keep, drop_threshold=drop,
                           preset="custom" if thresholds == "tuned" else "balanced")
    before = total_tokens(sample.messages)
    if method == "fifo":
        t = time.perf_counter()
        out = fifo(sample.messages, cfg.budget)
        ms = (time.perf_counter() - t) * 1000
        m = score_output(sample, out)
        after = total_tokens(out)
        return Row(mode, sample.name, method, "n/a", "n/a", "n/a",
                   "Under budget" if before <= cfg.budget else "Compacted", before, after,
                   round(100 * (before - after) / before, 1), **m, summary_lines="n/a", invented_lines_removed="n/a",
                   latency_ms=round(ms, 1), scoring_latency_ms=0, judge_requests=0, judge_input_tokens=0,
                   jev_cost_usd=0, judge_neurons=0, cf_neurons=0, judge_retries=0, summary_cached=False,
                   judge="none", summarizer="none"), None
    judge = make_judge()
    res = await compact(sample.messages, cfg, judge=judge, summarizer=summ, recall_store=MemoryRecallStore(),
                        method=method)
    if getattr(judge, "stop", None) is not None:
        raise judge.stop
    m = score_output(sample, res.messages)
    s = res.summary
    uses_judge = method != "plain"
    return Row(mode, sample.name, method, thresholds if uses_judge else "n/a", keep if uses_judge else "n/a",
               drop if uses_judge else "n/a", res.status, res.tokens_before, res.tokens_after,
               round(res.percent_saved, 1), **m, summary_lines=len(s.lines_kept) if s else 0,
               invented_lines_removed=(len(s.lines_removed) if s and s.checked else ("n/a" if method == "plain" or not s else 0)),
               latency_ms=res.latency_ms, scoring_latency_ms=res.scoring_latency_ms, judge_requests=res.jev_requests,
               judge_input_tokens=res.jev_input_tokens, jev_cost_usd=res.jev_cost_usd,
               judge_neurons=round(res.judge_neurons, 2), cf_neurons=res.summarizer_neurons,
               judge_retries=getattr(judge, "retries", 0), summary_cached=bool(s and s.cached),
               judge="none" if not uses_judge else judge_label, summarizer="none" if method == "prune_only" else summ_label,
               fallback_reason=res.fallback_reason or ""), res


# --- threshold sweep ----------------------------------------------------------------

def _grid() -> list[tuple[float, float]]:
    keeps = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 .. 0.95
    drops = [round(0.05 * i, 2) for i in range(0, 11)]  # 0.00 .. 0.50
    return [(k, d) for k in keeps for d in drops if k > d]


PRESET_OF = {(0.3, 0.05): "conservative", (0.5, 0.1): "balanced", (0.7, 0.2): "aggressive"}


def sweep_point(results: dict[str, object], samples: list[Sample], keep: float, drop: float) -> dict:
    """Re-classify recorded scores at (keep, drop): needed items kept verbatim and tool tokens saved."""
    cfg = CompactionConfig(keep_threshold=keep, drop_threshold=drop, preset="custom")
    needed = kept = before = after = 0
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
    return {"needed": needed, "needed_kept": kept, "needed_kept_pct": round(100 * kept / max(1, needed), 1),
            "tool_tokens_saved_pct": round(100 * (before - after) / max(1, before), 1)}


def sweep_rows(mode: str, results: dict[str, object], samples: list[Sample]) -> list[dict]:
    """The keep/drop grid over the recorded judge scores (no new judge calls)."""
    rows = []
    for keep, drop in _grid():
        p = sweep_point(results, samples, keep, drop)
        rows.append({"mode": mode, "keep": keep, "drop": drop, "preset": PRESET_OF.get((keep, drop), ""),
                     "needed_kept_pct": p["needed_kept_pct"], "tool_tokens_saved_pct": p["tool_tokens_saved_pct"]})
    return rows


def pick_tuned(rows: list[dict]) -> dict:
    """Most tool tokens saved with >= 95% of needed items kept; if no setting reaches 95%, the most
    needed items kept. Ties go to the setting closest to the default (0.50 / 0.10)."""
    def closeness(r):
        return abs(r["keep"] - DEFAULT_KEEP) + abs(r["drop"] - DEFAULT_DROP)

    ok = [r for r in rows if r["needed_kept_pct"] >= TARGET_KEPT]
    if ok:
        return min(ok, key=lambda r: (-r["tool_tokens_saved_pct"], -r["needed_kept_pct"], closeness(r)))
    return min(rows, key=lambda r: (-r["needed_kept_pct"], -r["tool_tokens_saved_pct"], closeness(r)))


def loso_rows(mode: str, results: dict[str, object], samples: list[Sample]) -> list[dict]:
    """Leave one session out: tune on the others, apply to the held-out session."""
    out = []
    names = [s.name for s in samples if s.name in results]
    for held in names:
        train = [s for s in samples if s.name in results and s.name != held]
        test = [s for s in samples if s.name == held]
        t = pick_tuned(sweep_rows(mode, results, train))
        p = sweep_point(results, test, t["keep"], t["drop"])
        d = sweep_point(results, test, DEFAULT_KEEP, DEFAULT_DROP)
        out.append({"mode": mode, "held_out": held, "keep": t["keep"], "drop": t["drop"],
                    "needed_kept_pct": p["needed_kept_pct"], "tool_tokens_saved_pct": p["tool_tokens_saved_pct"],
                    "default_needed_kept_pct": d["needed_kept_pct"],
                    "default_tool_tokens_saved_pct": d["tool_tokens_saved_pct"]})
    return out


def write_csv(path: Path, rows: list) -> None:
    rows = [asdict(r) if not isinstance(r, dict) else r for r in rows]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# --- plan ------------------------------------------------------------------------------

class _Recorder:
    """Records the judge requests the prune step would send, without sending them."""

    name = "recorder"

    def __init__(self, cap: int):
        self.max_request_tokens = cap
        self.requests: list[tuple[str, list[Question]]] = []

    async def evaluate(self, state, questions):
        self.requests.append((state, questions))
        return JudgeResponse({q.id: 0.5 for q in questions})

    async def test_connection(self):
        return True


async def plan(samples: list[Sample]) -> dict:
    """Estimate Cloudflare neurons for a real run: judge requests (exact, from the real packing) and
    summaries (upper bound). Cached requests cost nothing."""
    from jevcompact.pinning import apply_pins
    from jevcompact.summarizers.cloudflare import MODELS

    kind = real_judge_kind()
    env_cfg = CompactionConfig.from_env(judge=kind, summarizer="cloudflare")
    sspec = MODELS.get(env_cfg.cf_model, {"in": 25_608, "out": 75_147, "max_out": 512})
    jspec = judge_spec(env_cfg.cf_judge_model)
    print(f"Judge: {judge_name(env_cfg, kind)}  ({env_cfg.cf_judge_model if kind == 'cloudflare' else env_cfg.jev_model})")
    print(f"Summarizer: Cloudflare {env_cfg.cf_model}")
    per_session = {}
    for s in samples:
        cfg = CompactionConfig(budget=env_cfg.budget)
        session = parse_session(s.messages)
        apply_pins(session, cfg)
        if session.tokens <= cfg.budget:
            print(f"  {s.name:22} {session.tokens:>7,} tokens: under budget, nothing paid")
            continue
        row = {}
        for clip in CLIPS:
            c = CompactionConfig(budget=cfg.budget, jev_item_max_tokens=clip or 10_000_000)
            rec = _Recorder(env_cfg.cf_judge_max_request_tokens)
            await score_items(session, c, rec, RateLimiter(1e9, 1e12))
            n = 0.0
            tok = 0
            for state, qs in rec.requests:
                t = count_tokens(state) + sum(question_cost(q) for q in qs)
                tok += t
                cached = (CACHE / "judge" / "real" / f"{judge_key(env_cfg.cf_judge_model, state, qs)}.json").exists()
                n += 0 if cached or kind != "cloudflare" else estimate_judge_neurons(t, len(qs), jspec)
            row[f"judge_{clip or 'unclipped'}"] = n
            row[f"judge_{clip or 'unclipped'}_requests"] = len(rec.requests)
            row[f"judge_{clip or 'unclipped'}_tokens"] = tok
        cap = effective_cap(request_cap(_Recorder(env_cfg.cf_judge_max_request_tokens), cfg))
        row["check"] = 0 if kind != "cloudflare" else CHECK_REQUESTS_EST * estimate_judge_neurons(cap, 25, jspec)
        groups = select_groups(session, session.msg_tokens, cfg.budget, cfg.summary_reserve_tokens)
        req = build_request(session, groups, {})
        cached = (CACHE / "summaries" / "real" / f"{req.key(f'cloudflare:{env_cfg.cf_model}')}.json").exists()
        row["summary"] = 0.0 if cached else estimate_neurons(req, sspec)
        per_session[s.name] = row
        print(f"  {s.name:22} {session.tokens:>7,} tokens | judge prune: 300 -> {row['judge_300']:5.0f} n "
              f"({row['judge_300_requests']} req, {row['judge_300_tokens']:,} tok), 1000 -> {row['judge_1000']:5.0f} n "
              f"({row['judge_1000_requests']} req), unclipped -> {row['judge_unclipped']:5.0f} n "
              f"({row['judge_unclipped_requests']} req, {row['judge_unclipped_tokens']:,} tok) | "
              f"summary check ~{row['check']:.0f} n | one summary <= {row['summary']:,.0f} n")
    # Phases: judge replies are cached, so prune-only and the hybrid's prune step share requests,
    # and the clip-300 run reuses the main run's replies.
    ph = {
        "A. main run, default thresholds (plain + prune + hybrid, clip 300)":
            sum(r["summary"] * 2 + r["judge_300"] + r["check"] for r in per_session.values()),
        "B. tuned thresholds (hybrid: new summaries + checks; prune replies cached)":
            sum(r["summary"] + r["check"] for r in per_session.values()),
        "C. clipping at 1000": sum(r["judge_1000"] for r in per_session.values()),
        "D. clipping unclipped": sum(r["judge_unclipped"] for r in per_session.values()),
    }
    print("\nPlan (neurons; summaries are upper bounds, B is 0 if the tuned thresholds equal the default):")
    for k, v in ph.items():
        print(f"  {k:78} ~{v:7,.0f}")
    total = sum(ph.values())
    print(f"  {'Total':78} ~{total:7,.0f}   (stop limit 9,000/day; free tier {FREE_NEURONS_PER_DAY:,}/day)")
    ledger = NeuronLedger(9_000)
    print(f"Spent so far today (UTC {utc_day()}): {ledger.spent:,.0f}; left under 9,000: {9_000 - ledger.spent:,.0f}")
    return {"phases": ph, "total": total, "sessions": per_session}


# --- main ------------------------------------------------------------------------------

async def main_async(args) -> None:
    samples = load_samples(args.only)
    if args.plan:  # calls nothing paid
        await plan(samples)
        return
    if args.mode == "real":
        kind = real_judge_kind()
        need = ["CF_ACCOUNT_ID", "CF_API_TOKEN"] + (["JEV_API_KEY"] if kind == "jev" else [])
        missing = [k for k in need if not os.environ.get(k)]
        if missing:
            sys.exit(f"Real mode needs {', '.join(missing)} (in .env). Not falling back to mock: the two are never mixed.")
    ledger = NeuronLedger(args.neuron_limit) if args.mode == "real" else None
    make_judge, summ, jl, sl = providers(args.mode, ledger)
    suffix = "" if args.mode == "real" else "_mock"
    clips = [c for c in CLIPS if not (c is None and args.skip_unclipped)]
    rows, clip_rows, scored = [], [], {}
    started = time.time()

    def log(row):
        print(f"[{args.mode}] {row.session:22} {row.method:10} {row.thresholds:7} {row.status:12} "
              f"{row.pct_saved:5.1f}% saved  needed kept {row.needed_kept_pct:5.1f}%  "
              f"judge {row.judge_neurons:6.1f} n  summary {row.cf_neurons:6.1f} n  {row.latency_ms:7.0f} ms", flush=True)

    # 1. Default thresholds, all methods.
    for s in samples:
        for method in METHODS:
            row, res = await run_method(s, method, args.mode, make_judge, summ, jl, sl)
            rows.append(row)
            log(row)
            if method == "prune_only" and res is not None and res.status == "Compacted":
                scored[s.name] = res
    # 2. Sweep over the recorded scores; tuned thresholds; leave-one-session-out check.
    sweep = sweep_rows(args.mode, scored, samples) if scored else []
    tuned = pick_tuned(sweep) if sweep else None
    if sweep:
        write_csv(EVAL / f"threshold_sweep{suffix}.csv", sweep)
        write_csv(EVAL / f"threshold_loso{suffix}.csv", loso_rows(args.mode, scored, samples))
    # 3. Judge methods again with the tuned thresholds (prune replies come from the cache).
    if tuned:
        for s in samples:
            for method in JUDGE_METHODS:
                row, _ = await run_method(s, method, args.mode, make_judge, summ, jl, sl,
                                          keep=tuned["keep"], drop=tuned["drop"], thresholds="tuned")
                rows.append(row)
                log(row)
    # 4. Clipping trade-off (prune only, default thresholds).
    if not args.skip_clipping:
        for s in samples:
            for clip in clips:
                row, _ = await run_method(s, "prune_only", args.mode, make_judge, summ, jl, sl, clip=clip)
                clip_rows.append({"mode": args.mode, "session": s.name, "clip": clip or "unclipped",
                                  "status": row.status, "needed_kept_pct": row.needed_kept_pct,
                                  "pct_saved": row.pct_saved, "judge_requests": row.judge_requests,
                                  "judge_input_tokens": row.judge_input_tokens, "jev_cost_usd": row.jev_cost_usd,
                                  "judge_neurons": row.judge_neurons, "scoring_latency_ms": row.scoring_latency_ms})
                print(f"[{args.mode}] {s.name:22} clip {str(clip or 'unclipped'):9} needed kept "
                      f"{row.needed_kept_pct:5.1f}%  judge {row.judge_neurons:6.1f} n  {row.judge_input_tokens:,} tok",
                      flush=True)
    write_csv(EVAL / f"results{suffix}.csv", rows)
    if clip_rows:
        write_csv(EVAL / f"clipping{suffix}.csv", clip_rows)
    meta = {"mode": args.mode, "judge": jl, "summarizer": sl, "date": date.today().isoformat(),
            "duration_s": round(time.time() - started, 1), "budget": CompactionConfig().budget,
            "compaction_point": "before the agent's final answer (closing assistant message left out)",
            "default_thresholds": [DEFAULT_KEEP, DEFAULT_DROP],
            "tuned_thresholds": [tuned["keep"], tuned["drop"]] if tuned else None,
            "tuned_on": "all sessions' recorded prune-only scores (see threshold_loso for a held-out check)",
            "clips": [c or "unclipped" for c in clips],
            "unclipped_dropped": bool(args.skip_unclipped),
            "summaries_generated": summ.calls, "neurons_spent_today": round(ledger.spent, 1) if ledger else 0}
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
    p.add_argument("--skip-unclipped", action="store_true", help="clipping trade-off at 300 and 1000 only")
    p.add_argument("--neuron-limit", type=float, default=9_000, help="stop before spending more today (default 9,000)")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except BudgetExceeded as exc:
        sys.exit(f"STOPPED: {exc}\nEverything generated so far is cached; re-run after 00:00 UTC to continue.")
    except SummarizerError as exc:
        sys.exit(f"Cloudflare error: {exc}")


if __name__ == "__main__":
    main()
