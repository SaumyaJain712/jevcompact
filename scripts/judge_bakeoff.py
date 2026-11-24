"""Pick the Cloudflare judge model: the cheapest one that follows the strict JSON format reliably.

    python scripts/judge_bakeoff.py            # real Cloudflare calls (~600 neurons in total)

Uses a held-out probe session built here (not one of the evaluation samples in
data/samples/, so the choice is not tuned on the evaluation set). For each
candidate model it sends the same packed keep-question requests the pipeline
would send (real batching, 16k-token requests) plus one summary-check request,
REPEATS times, and records: replies that were valid strict JSON on the first try,
replies that needed the one retry, requests that failed twice, neurons, latency,
and how well the scores separate the needed items from the rest.

Writes docs/measurements/judge_model_bakeoff.json ("source": "real").
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from content import (eslint_output, find_files, git_log, jest_pass, lcov, log_lines, ls_node_modules,  # noqa: E402
                     markdown_doc, package_lock, ts_module)
from generate_samples import Scenario, Step, build  # noqa: E402

from jevcompact import CompactionConfig  # noqa: E402
from jevcompact.batching import effective_cap, pack  # noqa: E402
from jevcompact.formats import parse_session  # noqa: E402
from jevcompact.judges.base import JudgeError, Question  # noqa: E402
from jevcompact.judges.cloudflare import JUDGE_MODELS, CloudflareJudge  # noqa: E402
from jevcompact.pinning import apply_pins  # noqa: E402
from jevcompact.prune import build_context  # noqa: E402
from jevcompact.judges.base import KEEP_QUESTION  # noqa: E402
from jevcompact.tokens import clip_to_tokens  # noqa: E402

# (label, model key in JUDGE_MODELS, session ending). Cheapest first by input neurons per M:
# Granite 4.0 micro 1,542; GLM-4.7-flash 5,500. Llama 3.2 11B (4,410) needs a licence agreement
# accepted on the account first, which we did not do, so it is listed as not tested.
MID_TASK = "Next I will change formatDue in src/utils/date.ts to format in the given time zone, then re-run the test."
FINISHED = "Fixed: formatDue now formats the date in the account time zone with Intl.DateTimeFormat; the date test passes."
CANDIDATES = [
    ("granite-4.0-h-micro (chosen)", "@cf/ibm-granite/granite-4.0-h-micro", MID_TASK, 2),
    ("glm-4.7-flash, reasoning off", "@cf/zai-org/glm-4.7-flash:no-reasoning", MID_TASK, 2),
    ("glm-4.7-flash, reasoning on", "@cf/zai-org/glm-4.7-flash", MID_TASK, 2),
    ("glm-4.7-flash, reasoning on, session already finished", "@cf/zai-org/glm-4.7-flash", FINISHED, 1),
]
NOT_TESTED = [{"model": "@cf/meta/llama-3.2-11b-vision-instruct", "neurons_per_m_in": 4410,
               "reason": "HTTP 403: the model's licence agreement must be accepted on the account first"}]
OUT = ROOT / "docs" / "measurements" / "judge_model_bakeoff.json"


def date_ts(fixed: bool = False) -> str:
    body = ts_module("dateFormat", 6, seed="probe-date")
    bug = ("export function formatDue(d: Date, tz: string): string {\n"
           "  // BUG: uses local time instead of the given time zone\n"
           "  return d.toLocaleDateString('en-GB');\n}\n")
    return body + "\n" + bug


def probe(ending: str = MID_TASK) -> tuple[list[dict], dict]:
    files = [f"src/utils/{n}.ts" for n in ("date", "money", "strings", "http", "cache", "queue")]
    steps = [
        Step("ls node_modules", ls_node_modules(500, "p-nm"), False, "dependency listing"),
        Step("cat package-lock.json", package_lock(400, "p-lock"), False, "lockfile"),
        Step("git log --oneline -n 80", git_log(80, "p-git"), False, "history"),
        Step("cat src/utils/date.ts", date_ts(), True, "the file to fix"),
        Step("cat src/utils/money.ts", ts_module("money", 8, seed="p-money"), False, "unrelated module"),
        Step("cat README.md", markdown_doc("Billing service", 6, seed="p-readme"), False, "readme"),
        Step("npx eslint src", eslint_output(files, seed="p-eslint"), False, "lint noise"),
        Step("cat src/utils/date.test.ts",
             "import { formatDue } from './date';\n\n"
             "test('formats due date in the account time zone', () => {\n"
             "  const d = new Date('2026-03-01T23:30:00Z');\n"
             "  expect(formatDue(d, 'Asia/Kolkata')).toBe('02/03/2026');\n});\n" + jest_pass(["date"], 3)[:400],
             True, "the failing test's source"),
        Step("cat coverage/lcov.info", lcov(files, seed="p-lcov"), False, "coverage dump"),
        Step("find src -name '*.ts'", find_files(files + [f"src/pages/p{i}.tsx" for i in range(40)]), False, "file list"),
        Step("cat logs/billing.log", log_lines(300, "billing", "p-log"), False, "service log"),
        Step("cat src/utils/strings.ts", ts_module("strings", 8, seed="p-str"), False, "unrelated module"),
        Step("cat tsconfig.json", '{\n  "compilerOptions": {\n    "target": "ES2022",\n    "strict": true\n  }\n}',
             False, "config"),
        Step("cat src/utils/http.ts", ts_module("http", 8, seed="p-http"), False, "unrelated module"),
        Step("grep -rn formatDue src", "src/utils/date.ts:41:export function formatDue(d: Date, tz: string)\n"
             "src/invoices/render.ts:88:  const due = formatDue(inv.dueAt, account.timeZone);\n"
             "src/utils/date.test.ts:1:import { formatDue } from './date';", True, "where the function is used"),
        Step("cat src/utils/cache.ts", ts_module("cache", 8, seed="p-cache"), False, "unrelated module"),
        Step("cat CHANGELOG.md", markdown_doc("Changelog", 8, seed="p-chg"), False, "changelog"),
        Step("npm test -- date", "FAIL src/utils/date.test.ts\n  ● formats due date in the account time zone\n"
             "    Expected: \"02/03/2026\"\n    Received: \"01/03/2026\"", True, "the failure", is_error=True),
        Step("cat src/utils/queue.ts", ts_module("queue", 8, seed="p-queue"), False, "unrelated module"),
    ]
    # More unrelated reads so a request carries ~50 questions, like a real 180k-token session.
    for i, name in enumerate(["auth", "session", "orders", "users", "search", "mailer", "pdf", "metrics", "flags",
                              "retry", "uploads", "webhooks", "tax", "currency", "locale", "audit", "export",
                              "import", "billing", "plans", "reports", "jobs", "notify", "theme", "router",
                              "store", "forms", "table", "modal", "toast"]):
        steps.insert(3 + i, Step(f"cat src/modules/{name}.ts", ts_module(name, 5, seed=f"p-{name}"), False,
                                 "unrelated module"))
    steps.append(Step("echo done", "done", False, "latest turn"))
    sc = Scenario("probe-date-tz", "openai", "The invoice due date is a day off for customers in India. "
                  "Fix formatDue in src/utils/date.ts so it uses the account time zone, and make the test pass.",
                  steps, ending)
    return build(sc)


def keep_requests(cap: int, ending: str = MID_TASK) -> tuple[list, dict[str, bool]]:
    msgs, labels = probe(ending)
    cfg = CompactionConfig(budget=1000)
    s = parse_session(msgs)
    apply_pins(s, cfg)
    header = build_context(s, cfg)
    needed = {i["tool_call_id"]: i["needed"] for i in labels["items"]}
    blocks, truth = [], {}
    for it in s.items:
        if it.role not in ("TOOL", "ERROR") or it.pinned:
            continue
        qid = f"t{it.index}"
        q = Question(qid, "keep", KEEP_QUESTION.format(qid=qid), meta={"title": it.title})
        blocks.append((f"[{qid}] {it.title}\n{clip_to_tokens(it.text, 300)}", q))
        truth[qid] = needed[it.tool_call_id]
    return pack(header, blocks, cap), truth


SOURCE_STATE = ("TOOL OUTPUTS (the only allowed sources):\n\n[npm test -- date]\nFAIL src/utils/date.test.ts\n"
                "Expected: \"02/03/2026\"\nReceived: \"01/03/2026\"\n\n[grep -rn formatDue src]\n"
                "src/invoices/render.ts:88:  const due = formatDue(inv.dueAt, account.timeZone);")
SOURCE_LINES = [("- `npm test -- date` failed: expected \"02/03/2026\", received \"01/03/2026\".", True),
                ("- formatDue is called from src/invoices/render.ts line 88.", True),
                ("- The test suite passed with 42 tests.", False),
                ("- The bug was introduced in PR #2041 by a time zone refactor.", False)]


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


async def run_model(label: str, model: str, ending: str, repeats: int, account: str, token: str) -> dict:
    judge = CloudflareJudge(account, token, model)
    reqs, truth = keep_requests(effective_cap(judge.max_request_tokens), ending)
    src_q = [Question(f"l{j}", "source", f'Is this summary line supported by the tool outputs? Line: "{ln}"')
             for j, (ln, _) in enumerate(SOURCE_LINES)]
    stats = {"label": label, "model": model, "session_ending": ending, "repeats": repeats, "neurons_per_m_in": JUDGE_MODELS[model]["in"],
             "neurons_per_m_out": JUDGE_MODELS[model]["out"], "requests": 0, "valid_first_try": 0,
             "needed_retry": 0, "failed_twice": 0, "errors": [], "neurons": 0.0, "latency_ms": [],
             "keep_auc": [], "source_correct": 0, "source_total": 0, "mean_needed": [], "mean_not_needed": []}
    for rep in range(repeats):
        pos, neg = [], []
        for state, qs, is_src in [(r.state, r.questions, False) for r in reqs] + [(SOURCE_STATE, src_q, True)]:
            stats["requests"] += 1
            t = time.perf_counter()
            try:
                res = await judge.evaluate(state, qs)
            except JudgeError as exc:
                stats["failed_twice"] += 1
                stats["errors"].append(str(exc)[:200])
                continue
            stats["latency_ms"].append(round((time.perf_counter() - t) * 1000))
            stats["neurons"] += res.neurons
            stats["valid_first_try" if res.attempts == 1 else "needed_retry"] += 1
            if is_src:
                for q, (_, ok) in zip(qs, SOURCE_LINES):
                    stats["source_total"] += 1
                    stats["source_correct"] += (res.scores[q.id] >= 0.5) == ok
            else:
                for q in qs:
                    (pos if truth[q.id] else neg).append(res.scores[q.id])
        stats["keep_auc"].append(auc(pos, neg))
        if pos:
            stats["mean_needed"].append(round(sum(pos) / len(pos), 3))
        if neg:
            stats["mean_not_needed"].append(round(sum(neg) / len(neg), 3))
    stats["neurons"] = round(stats["neurons"], 1)
    stats["valid_json_rate"] = round(stats["valid_first_try"] / max(1, stats["requests"]), 3)
    stats["keep_requests_per_repeat"] = len(reqs)
    stats["keep_request_tokens"] = [r.tokens for r in reqs]
    return stats


async def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover
        pass
    cfg = CompactionConfig.from_env()
    if not (cfg.cf_account_id and cfg.cf_api_token):
        sys.exit("CF_ACCOUNT_ID and CF_API_TOKEN are needed")
    results = []
    for label, model, ending, repeats in CANDIDATES:
        r = await run_model(label, model, ending, repeats, cfg.cf_account_id, cfg.cf_api_token)
        print(json.dumps({k: v for k, v in r.items() if k not in ("latency_ms", "keep_request_tokens", "session_ending")}))
        results.append(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "real", "probe": "held-out probe session (scripts/judge_bakeoff.py), "
                               "not an evaluation sample; 48 keep questions (3 needed) in one 16k-token request "
                               "plus one summary-check request with 4 lines (2 unsupported)",
                               "results": results, "not_tested": NOT_TESTED,
                               "total_neurons": round(sum(r["neurons"] for r in results), 1)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
