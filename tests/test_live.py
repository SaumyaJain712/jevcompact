"""Live measurements against real Jev / Cloudflare. Skipped unless keys are set.

Each test writes a JSON file to docs/measurements/ with "source": "real".
Run:  JEV_API_KEY=... CF_ACCOUNT_ID=... CF_API_TOKEN=... pytest -m live
"""
import json
import os
import time
from statistics import quantiles

import pytest
from factories import Step, build, filler
from test_nfr import MEASURE_DIR, session_with_candidate_tokens

from jevcompact import CompactionConfig, MemoryRecallStore, MockJudge, MockSummarizer, compact
from jevcompact.batching import effective_cap, pack
from jevcompact.judges.base import KEEP_QUESTION, Question
from jevcompact.judges.cloudflare import CloudflareJudge, judge_label
from jevcompact.judges.jev import JevJudge
from jevcompact.summarizers import SummaryEntry, SummaryRequest
from jevcompact.summarizers.cloudflare import CloudflareSummarizer

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

HAS_JEV = bool(os.environ.get("JEV_API_KEY"))
HAS_CF = bool(os.environ.get("CF_ACCOUNT_ID") and os.environ.get("CF_API_TOKEN"))
needs_jev = pytest.mark.skipif(not HAS_JEV, reason="JEV_API_KEY not set")
needs_cf = pytest.mark.skipif(not HAS_CF, reason="CF_ACCOUNT_ID / CF_API_TOKEN not set")
pytestmark = pytest.mark.live


def _write(name, data):
    MEASURE_DIR.mkdir(parents=True, exist_ok=True)
    (MEASURE_DIR / name).write_text(json.dumps({"source": "real", **data}, indent=2))


def _jev():
    return JevJudge.from_config(CompactionConfig.from_env(judge="jev"))


def _cf():
    return CloudflareSummarizer.from_config(CompactionConfig.from_env(summarizer="cloudflare"))


def _cf_judge():
    return CloudflareJudge.from_config(CompactionConfig.from_env(judge="cloudflare"))


@needs_jev
async def test_live_jev_noul():
    res = await _jev().evaluate("The npm test run failed with TypeError: total is undefined (cart.ts:88).",
                                [Question("err", "keep", "Does this output show a failing test?")])
    assert res.scores["err"] > 0.5 and res.input_tokens > 0


@needs_jev
async def test_live_token_calibration():
    """Compare our cl100k estimate of a packed request with Jev's billed usage.input_tokens."""
    cfg = CompactionConfig()
    blocks = []
    for i in range(140):
        q = Question(f"t{i}", "keep", KEEP_QUESTION.format(qid=f"t{i}"))
        blocks.append((f"[t{i}] cat src/c{i}.ts\n{filler(190, f'c{i}')}", q))
    req = pack("TASK:\nFix the checkout total bug.\n\nOLDER TOOL OUTPUTS:\n", blocks, effective_cap(32_000))[0]
    res = await _jev().evaluate(req.state, req.questions)
    _write("jev_token_calibration.json", {
        "our_estimate_tokens": req.tokens, "jev_billed_input_tokens": res.input_tokens,
        "ratio_billed_to_estimate": round(res.input_tokens / req.tokens, 4),
        "fill_margin": 0.95, "cap": 32_000, "questions": len(req.questions)})
    assert res.input_tokens <= 32_000, "95% fill margin is too loose for Jev's tokenizer"


@needs_jev
async def test_live_tc_p1_and_cost_real_jev():
    msgs = session_with_candidate_tokens(32_000)
    scoring, total, billed, cost = [], [], [], []
    for _ in range(10):
        res = await compact(msgs, CompactionConfig.from_env(judge="jev", budget=8_000), judge=_jev(),
                            summarizer=MockSummarizer(), recall_store=MemoryRecallStore())
        assert res.status == "Compacted", res.fallback_reason
        scoring.append(res.scoring_latency_ms)
        total.append(res.latency_ms)
        billed.append(res.jev_input_tokens)
        cost.append(res.jev_cost_usd)
    p95 = lambda xs: quantiles(xs, n=20)[-1]  # noqa: E731
    _write("tc_p1_latency_real.json", {
        "judge": "jev (real)", "summarizer": "mock (no summarizer time)", "runs": len(scoring),
        "candidate_tokens": 32_000, "p95_scoring_ms": round(p95(scoring), 1),
        "p95_prune_check_ms": round(p95(total), 1), "scoring_ms": scoring, "prune_check_ms": total})
    _write("cost_real.json", {"judge": "jev (real, billed usage.input_tokens)", "candidate_tokens": 32_000,
                              "billed_input_tokens": billed, "jev_cost_usd": cost, "max_cost_usd": max(cost)})
    assert p95(scoring) < 1000
    assert max(cost) <= 0.002


@needs_cf
async def test_live_cloudflare_summary_and_full_compaction_time():
    cf = _cf()
    t = time.perf_counter()
    res = await cf.summarize(SummaryRequest("Fix the checkout total bug in src/cart.ts.", [
        SummaryEntry("cat src/cart.ts", "export function cartTotal(items) {\n  let total;\n  return total;\n}"),
        SummaryEntry("npm test", "FAIL src/cart.test.ts\nTypeError: total is undefined (cart.ts:88)")]))
    summarizer_ms = (time.perf_counter() - t) * 1000
    assert res.text.strip()

    judge = _jev() if HAS_JEV else _cf_judge()  # no paid Jev: the Cloudflare judge stands in for it
    msgs = build([Step(f"cat src/f{i}.ts", filler(600, f"f{i}")) for i in range(30)])
    full = await compact(msgs, CompactionConfig.from_env(budget=6_000), judge=judge, summarizer=cf,
                         recall_store=MemoryRecallStore())
    _write("summarizer_latency_real.json", {
        "summarizer": f"cloudflare {cf.model} (real)",
        "judge": "jev (real)" if HAS_JEV else f"{judge_label(judge.model)} (real, {judge.model})",
        "full_compaction_judge_neurons": full.judge_neurons,
        "single_summary_ms": round(summarizer_ms, 1), "single_summary_neurons": res.neurons,
        "full_compaction_ms": full.latency_ms, "full_compaction_status": full.status,
        "full_compaction_neurons": full.summarizer_neurons})


# --- Cloudflare judge (free stand-in for Jev) ------------------------------------

@needs_cf
async def test_live_cloudflare_judge_strict_json():
    j = _cf_judge()
    res = await j.evaluate("TASK:\nFix the checkout total bug in src/cart.ts.\n\nOLDER TOOL OUTPUTS:\n"
                           "[t1] npm test\nFAIL src/cart.test.ts\nTypeError: total is undefined (cart.ts:88)\n\n"
                           "[t2] ls node_modules\n@babel  eslint  jest  react  typescript",
                           [Question("t1", "keep", KEEP_QUESTION.format(qid="t1"), meta={"title": "npm test"}),
                            Question("t2", "keep", KEEP_QUESTION.format(qid="t2"), meta={"title": "ls node_modules"})])
    assert set(res.scores) == {"t1", "t2"} and all(0 <= v <= 1 for v in res.scores.values())
    assert res.scores["t1"] >= res.scores["t2"]
    assert res.neurons > 0


@needs_cf
async def test_live_tc_p1_and_neurons_cloudflare_judge():
    """TC-P1 setup (32k tokens of candidates) with the Cloudflare judge. Recorded, not asserted against
    the 1 s Jev target: an LLM on Workers AI is slower than Jev (see the report)."""
    msgs = session_with_candidate_tokens(32_000)
    j = _cf_judge()
    scoring, total, neurons, requests = [], [], [], []
    for _ in range(3):
        res = await compact(msgs, CompactionConfig.from_env(judge="cloudflare", budget=8_000), judge=j,
                            summarizer=MockSummarizer(), recall_store=MemoryRecallStore())
        assert res.status in ("Compacted", "Fell back")
        if res.status == "Fell back":  # recorded; the fallback path itself is what FR8 needs
            assert res.user_messages_lost == 0
        scoring.append(res.scoring_latency_ms)
        total.append(res.latency_ms)
        neurons.append(res.judge_neurons)
        requests.append(res.jev_requests)
    _write("tc_p1_latency_cf_judge_real.json", {
        "judge": f"{judge_label(j.model)} (real, {j.model})", "summarizer": "mock (no summarizer time)",
        "runs": len(scoring), "candidate_tokens": 32_000, "request_cap_tokens": j.max_request_tokens,
        "max_scoring_ms": max(scoring), "median_scoring_ms": sorted(scoring)[len(scoring) // 2],
        "scoring_ms": scoring, "prune_check_ms": total, "judge_requests": requests, "judge_neurons": neurons,
        "jev_target_p95_ms": 1000, "note": "3 runs only (free tier); P95 of 3 runs is the max."})
