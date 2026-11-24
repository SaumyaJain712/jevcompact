# JevCompact — results summary for the project report

*Session Compaction using Jev. Evaluation run on 24 November 2026 (UTC).*

## 1. What was built
JevCompact compacts long AI coding-agent sessions before they overflow the model's context. It has four parts:
- a Python library;
- a FastAPI server with SQLite;
- a React dashboard;
- an evaluation harness.

How it compacts a session:
1. It pins what must never be lost: the task, every user message, the latest turn and error outputs.
2. It asks a judge one yes/no question about every older tool result.
3. Based on the score it keeps, truncates or drops each result.
4. Only if the session is still over budget, it summarizes the oldest turns and checks every summary line against the tool outputs.

Anything removed can be restored in one click. Every decision is logged.

All 12 functional requirements are implemented and tested: 166 Python tests and 21 Playwright UI tests.
Architecture: `docs/diagrams/architecture.png`. Pipeline: `pipeline.png`. Sequence: `sequence.png`. Database: `er.png`.

## 2. Change of plan: the judge
Paid Jev was not used. In every table, chart and screenshot the judge is labelled **"Cloudflare (Granite) judge, standing in for Jev"**.

- **What it is.** IBM Granite 4.0 micro on Cloudflare Workers AI's free tier. It gets Jev's exact yes/no questions and must reply with strict JSON scores from 0 to 1 at temperature 0. An invalid reply is retried once. A second invalid reply counts as a judge failure, so the plain-summary fallback still works.
- **Why Granite.** It is the cheapest model that returned valid JSON on every request in a bake-off on a held-out session (`docs/measurements/judge_model_bakeoff.json`).
  - GLM-4.7-flash (the summarizer's model) scored every item 0 with its reasoning off.
  - With reasoning on, GLM worked, but cost about 6× more and often took over 60 s.
- **Caveat.** Granite's scores are not calibrated like Jev's. In practice they are almost always exactly 0 or 1.

## 3. Method
- **Data.** Six realistic sessions (64k–210k tokens; OpenAI and Anthropic formats). Every tool result was hand-labelled needed or not before any judge ran (`eval/LABELS.md`).
- **Budget.** 120k tokens, so five sessions need compaction.
- **Methods compared.** FIFO sliding window, plain summary only, prune only (judge), and the full JevCompact hybrid.
- **Compaction point.** Each session is compacted just before the agent's final "done" message. Compaction fires mid-task in practice. Asked after the task is finished what is "still needed to finish the task", the judge says "nothing".
- **Main metric.** *Needed items kept*: hand-labelled needed tool results still present word for word. The target was ≥ 95%.

## 4. Results (real run, 5 sessions over budget, default thresholds 0.50 / 0.10)

| Method | Tokens saved | Needed items kept | User messages lost | Cost per session |
|---|---|---|---|---|
| FIFO sliding window | 49.3% | 60.5% | **6** | free |
| Plain summary only | 36.0% (45.0%¹) | **76.3%** (70.0%¹) | 0 | ~416 neurons (520¹), 44–81 s |
| Prune only (Cloudflare (Granite) judge, standing in for Jev) | **81.0%** | 57.9% | 0 | ~8 neurons, 3–6 s |
| JevCompact hybrid (same judge) | **81.0%** | 57.9% | 0 | ~8 neurons, 3–6 s |

¹ The plain summary failed on one session (api-refactor-long). GLM returned an empty reply three times, so that session was left unsummarized. The figures in brackets exclude it.

Figures: `docs/figures/tokens_saved_real.png`, `needed_kept_real.png`. Full tables: `eval/results.md`.

**Thresholds: default vs tuned.** The sweep over the recorded scores picked keep 0.50 / drop 0.10, the same as the default. Every point on the grid keeps the same 57.9% of needed items, because a score of exactly 0 or 1 can never fall between thresholds. A leave-one-session-out check gives the same result for every session. Tuning thresholds cannot fix this judge.

**Clipping trade-off** (prune only; how much of each tool output the judge sees):

| Tokens per output shown to the judge | Needed kept | Judge neurons per session |
|---|---|---|
| 300 (default) | 57.5% | 8 |
| 1000 | 57.5% | 18 |
| unclipped | 39.2% | 141 |

Showing the judge more text did not help, and showing it everything made it worse: 7–8 requests per session instead of 1.

**Secondary run (mock judge, clearly separate).** Prune only and the hybrid saved 82.9% and kept 71.1% of needed items, against 60.5% for FIFO and 63.2% for the plain summary. So the pipeline itself works as designed. The weak point in the real run is the stand-in judge.

## 5. What the results show, in plain English
- **JevCompact saves the most space and never loses a user message.** It cut sessions by 81% on average. FIFO cut 49% but threw away 6 user messages, including tasks. The plain summary cut 36–45%.
- **It is cheap and fast.** About 8 neurons and 3–6 seconds per session. The plain summary needed 416–520 neurons and 44–81 seconds, and failed outright once.
- **Where JevCompact does worse: it keeps fewer of the items the agent actually needs.** It kept 57.9% of needed items. The plain summary kept 70–76% and FIFO 60.5%. On auth-session-expiry it kept 3 of 8 needed items, while both baselines kept 5.
- **Why.** The free judge marks most tool outputs as "not needed" (score 0), including some that are. Everything scored 0 is dropped. The 95% target for needed items is not met, and no threshold setting can reach it with this judge.
- **The hybrid never had to summarize** in this run: pruning alone always got under the budget. So the summary-check step (removing invented lines) was not exercised by the real evaluation. It is covered by tests and by the mock run.

## 6. Requirements status
| Requirement | Status |
|---|---|
| FR1–FR12 | Implemented and tested (library, API, UI) |
| Performance: scoring P95 < 1 s | Met with the mock at Jev's latency. **Not met** by the Cloudflare judge: ~15 s for 32k tokens of candidates (`docs/measurements/tc_p1_latency_cf_judge_real.json`). |
| Cost ≤ $0.002 per compaction | Met in mock ($0.0002). The real judge is free within 10,000 neurons/day (~8 neurons per session). |
| Accuracy ≥ 95% needed items kept | **Not met** with the stand-in judge (57.9%); 71.1% with the mock |
| Reliability (fallback, no user message lost) | Met: 0 user messages lost in every judge run; fallback tested |
| Security, maintainability | Met (encrypted keys, localhost only, swappable judges) |
| Portability | Setup scripts for Windows, macOS and Linux; tested on Linux only |

## 7. Limitations and next steps
- Run the same evaluation with real Jev (`JUDGE=jev`); the harness is ready.
- Or try GLM-4.7-flash with reasoning as the judge (`CF_JUDGE_MODEL`). It found needed items in the bake-off, at about 6× the cost.
- More sessions and independent labellers; six sessions labelled by the team is a small evidence base.
- Free-tier budget: the evaluation, live tests and judge selection used about 8,600 of the 10,000 daily neurons. That figure includes conservative estimates for calls that timed out.

## 8. Assets in this folder and elsewhere
| Asset | Path |
|---|---|
| Screenshots 01–08 (real samples, Cloudflare judge; 05 uses the mock to force a real timeout) | `docs/screenshots/` |
| Database snapshots: sessions, runs (incl. a restore version), decision log | `docs/report_assets/db_snapshot_1_sessions.png`, `_2_runs.png`, `_3_decisions.png` (+ `.md`) |
| Charts | `docs/figures/` |
| Diagrams | `docs/diagrams/*.png` (Mermaid sources `*.mmd`) |
| Full results and CSVs | `eval/results.md`, `eval/results.csv`, `eval/clipping.csv`, `eval/threshold_sweep.csv`, `eval/threshold_loso.csv` |
| Measurements (each marked mock or real) | `docs/measurements/` |
| Design deviations | `PROGRESS.md` |
