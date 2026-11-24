# Evaluation results

Four methods on every sample in `data/samples/`: FIFO sliding window, plain summary only, prune only (judge), and the full JevCompact hybrid. Real and mock runs are reported separately and never combined.

**Judge.** Paid Jev is not used. The real run's judge is the **Cloudflare (Granite) judge, standing in for Jev**: a Workers AI chat model asked Jev's yes/no questions and returning strict JSON scores (see PROGRESS.md, design deviations). Its scores are not calibrated like Jev's, so results are shown at the default thresholds and at thresholds tuned by the sweep.

**Compaction point.** Each session is compacted just before the agent's final "done" answer (the one closing assistant message is left out for every method), because compaction fires mid-task and a judge asked what is "still needed to finish the task" after it is finished answers "nothing".

**Metrics.** *Needed items kept*: hand-labelled needed tool results (`eval/LABELS.md`) still present word for word in the compacted session (pinned or kept; truncated, dropped or summarized do not count). *Invented lines removed*: summary lines the judge's check found no source for (hybrid only). *Judge neurons*: Cloudflare cost of the judge requests (first generation; replies are cached, so a re-run costs nothing; the hybrid's prune step reuses the prune-only replies). *Summary neurons*: Cloudflare cost of the summary. Mock tables show the Jev cost estimate from tiktoken counts instead.

## Main results (real) — real: Cloudflare (Granite) judge, standing in for Jev + Cloudflare summarizer (@cf/zai-org/glm-4.7-flash)

Run on 2026-11-24 (UTC) / 2026-11-25 (local) · judge: **Cloudflare (Granite) judge, standing in for Jev** · summarizer: Cloudflare summarizer (@cf/zai-org/glm-4.7-flash) · budget 120,000 tokens · compaction point: before the agent's final answer (closing assistant message left out).

Cloudflare neurons on UTC day 2026-11-24: 8,231 of the 10,000 free (stop limit 9,000). 8,231 = all Cloudflare use on UTC day 2026-11-24: judge bake-off and prompt debugging (~2,300), live tests (~280), the evaluation, plus estimates for calls that timed out or returned empty (they may still be billed).

### Averages over the 5 sessions above the 120k budget — default thresholds 0.50 / 0.10 (real: Cloudflare (Granite) judge, standing in for Jev)

| Method | Tokens saved | Needed items kept | User msgs lost | Invented lines removed | Latency | Judge neurons | Summary neurons | Fell back |
|---|---|---|---|---|---|---|---|---|
| FIFO sliding window (real) | 49.3% | 60.5% | 6 | n/a | 0.1 s | 0.0 | 0 | 0 |
| Plain summary only (real) | 36.0% | 76.3% | 0 | n/a | 38.7 s | 0.0 | 416 | 0 |
| Prune only (judge) (real) | 81.0% | 57.9% | 0 | n/a | 0.0 s | 7.7 | 0 | 0 |
| JevCompact hybrid (real) | 81.0% | 57.9% | 0 | 0 | 0.0 s | 7.7 | 0 | 0 |

**Note:** the plain summary failed on api-refactor-long (GLM-4.7-flash returned an empty reply three times: its reasoning used the whole output budget, even at 4,096 tokens). That session was left unsummarized, so its plain row counts 0% saved and every item kept, which flatters plain's 'needed items kept'. Averages over the other 4 sessions:

| Method | Tokens saved | Needed items kept | User msgs lost | Invented lines removed | Latency | Judge neurons | Summary neurons | Fell back |
|---|---|---|---|---|---|---|---|---|
| FIFO sliding window · excl. failed summary (real) | 44.5% | 66.7% | 4 | n/a | 0.1 s | 0.0 | 0 | 0 |
| Plain summary only · excl. failed summary (real) | 45.0% | 70.0% | 0 | n/a | 0.0 s | 0.0 | 520 | 0 |
| Prune only (judge) · excl. failed summary (real) | 77.0% | 56.7% | 0 | n/a | 0.0 s | 7.3 | 0 | 0 |
| JevCompact hybrid · excl. failed summary (real) | 77.0% | 56.7% | 0 | 0 | 0.0 s | 7.3 | 0 | 0 |

### First-call latency (real)

First-generation wall time per compaction, from the evaluation run logs (later rows reuse cached judge replies and summaries, so their latency is ~0). plain = one GLM summary (the two 60 s failures were before the summarizer timeout was raised to 180 s); prune_only = Granite judge scoring. Plain rows show the attempt with the 180 s timeout where one succeeded.

| Session | Method | Wall time | Result |
|---|---|---|---|
| api-refactor-long | Plain summary only | 193.7 s | summarizer failed (empty reply, 3 attempts) |
| auth-session-expiry | Plain summary only | 52.8 s | ok |
| checkout-bugfix-0412 | Plain summary only | 44.1 s | ok |
| data-pipeline-test | Plain summary only | 81.3 s | ok |
| flaky-ci-timeout | Plain summary only | 62.9 s | ok |
| api-refactor-long | Prune only (judge) | 4.8 s | ok |
| auth-session-expiry | Prune only (judge) | 4.8 s | ok |
| checkout-bugfix-0412 | Prune only (judge) | 6.1 s | ok |
| data-pipeline-test | Prune only (judge) | 6.2 s | ok |
| flaky-ci-timeout | Prune only (judge) | 3.3 s | ok |

The *Latency* column in the tables above is ~0 s for the judge methods and for cached summaries because the replies come from the cache; use this table for timing.

### Default vs tuned thresholds (real: Cloudflare (Granite) judge, standing in for Jev)

| Method | Tokens saved | Needed items kept | User msgs lost | Invented lines removed | Latency | Judge neurons | Summary neurons | Fell back |
|---|---|---|---|---|---|---|---|---|
| Prune only (judge) · default 0.50/0.10 (real) | 81.0% | 57.9% | 0 | n/a | 0.0 s | 7.7 | 0 | 0 |
| JevCompact hybrid · default 0.50/0.10 (real) | 81.0% | 57.9% | 0 | 0 | 0.0 s | 7.7 | 0 | 0 |
| Prune only (judge) · tuned 0.5/0.1 (real) | 81.1% | 57.9% | 0 | n/a | 0.0 s | 7.7 | 0 | 0 |
| JevCompact hybrid · tuned 0.5/0.1 (real) | 81.0% | 57.9% | 0 | 0 | 0.0 s | 7.7 | 0 | 0 |

### Per session (real: Cloudflare (Granite) judge, standing in for Jev)

| Session | Method | Thresholds | Status | Tokens before | Tokens after | Saved | Needed kept | Needed cut | Needed removed | User msgs lost | Invented removed | Latency | Judge cost | Summary neurons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| api-refactor-long | FIFO sliding window (real) | n/a | Compacted | 185,006 | 58,145 | 68.6% | 3/8 | 0 | 5 | 2 | n/a | 0.3 s | 0.0 n | 0 |
| api-refactor-long | Plain summary only (real) | n/a | Compacted | 185,006 | 185,006 | 0.0% | 8/8 | 0 | 0 | 0 | n/a | 193.7 s | 0.0 n | 0 |
| api-refactor-long | Prune only (judge) (real) | default | Compacted | 185,006 | 5,414 | 97.1% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 9.4 n | 0 |
| api-refactor-long | JevCompact hybrid (real) | default | Compacted | 185,006 | 5,414 | 97.1% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 9.4 n | 0 |
| auth-session-expiry | FIFO sliding window (real) | n/a | Compacted | 177,932 | 107,617 | 39.5% | 5/8 | 0 | 3 | 1 | n/a | 0.1 s | 0.0 n | 0 |
| auth-session-expiry | Plain summary only (real) | n/a | Compacted | 177,932 | 107,792 | 39.4% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 0.0 n | 471 |
| auth-session-expiry | Prune only (judge) (real) | default | Compacted | 177,932 | 1,054 | 99.4% | 3/8 | 0 | 5 | 0 | n/a | 0.0 s | 6.3 n | 0 |
| auth-session-expiry | JevCompact hybrid (real) | default | Compacted | 177,932 | 1,054 | 99.4% | 3/8 | 0 | 5 | 0 | n/a | 0.0 s | 6.3 n | 0 |
| checkout-bugfix-0412 | FIFO sliding window (real) | n/a | Compacted | 179,254 | 104,002 | 42.0% | 8/8 | 0 | 0 | 1 | n/a | 0.1 s | 0.0 n | 0 |
| checkout-bugfix-0412 | Plain summary only (real) | n/a | Compacted | 179,254 | 104,194 | 41.9% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 468 |
| checkout-bugfix-0412 | Prune only (judge) (real) | default | Compacted | 179,254 | 102,322 | 42.9% | 7/8 | 0 | 1 | 0 | n/a | 0.0 s | 9.2 n | 0 |
| checkout-bugfix-0412 | JevCompact hybrid (real) | default | Compacted | 179,254 | 102,322 | 42.9% | 7/8 | 0 | 1 | 0 | n/a | 0.0 s | 9.2 n | 0 |
| data-pipeline-test | FIFO sliding window (real) | n/a | Compacted | 147,694 | 68,592 | 53.6% | 4/8 | 0 | 4 | 1 | n/a | 0.1 s | 0.0 n | 0 |
| data-pipeline-test | Plain summary only (real) | n/a | Compacted | 147,694 | 69,142 | 53.2% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 0.0 n | 530 |
| data-pipeline-test | Prune only (judge) (real) | default | Compacted | 147,694 | 1,411 | 99.0% | 4/8 | 0 | 4 | 0 | n/a | 0.0 s | 7.6 n | 0 |
| data-pipeline-test | JevCompact hybrid (real) | default | Compacted | 147,694 | 1,411 | 99.0% | 4/8 | 0 | 4 | 0 | n/a | 0.0 s | 7.6 n | 0 |
| docs-migration | FIFO sliding window (real) | n/a | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.1 s | 0.0 n | 0 |
| docs-migration | Plain summary only (real) | n/a | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 0 |
| docs-migration | Prune only (judge) (real) | default | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 0 |
| docs-migration | JevCompact hybrid (real) | default | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 0 |
| flaky-ci-timeout | FIFO sliding window (real) | n/a | Compacted | 209,701 | 119,816 | 42.9% | 3/6 | 0 | 3 | 1 | n/a | 0.1 s | 0.0 n | 0 |
| flaky-ci-timeout | Plain summary only (real) | n/a | Compacted | 209,701 | 114,433 | 45.4% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | 0.0 n | 610 |
| flaky-ci-timeout | Prune only (judge) (real) | default | Compacted | 209,701 | 69,734 | 66.7% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | 6.0 n | 0 |
| flaky-ci-timeout | JevCompact hybrid (real) | default | Compacted | 209,701 | 69,734 | 66.7% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | 6.0 n | 0 |
| api-refactor-long | Prune only (judge) (real) | tuned | Compacted | 185,006 | 5,414 | 97.1% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 9.4 n | 0 |
| api-refactor-long | JevCompact hybrid (real) | tuned | Compacted | 185,006 | 5,400 | 97.1% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | 9.4 n | 0 |
| auth-session-expiry | Prune only (judge) (real) | tuned | Compacted | 177,932 | 1,066 | 99.4% | 3/8 | 0 | 5 | 0 | n/a | 0.0 s | 6.3 n | 0 |
| auth-session-expiry | JevCompact hybrid (real) | tuned | Compacted | 177,932 | 1,066 | 99.4% | 3/8 | 0 | 5 | 0 | n/a | 0.0 s | 6.3 n | 0 |
| checkout-bugfix-0412 | Prune only (judge) (real) | tuned | Compacted | 179,254 | 102,315 | 42.9% | 7/8 | 0 | 1 | 0 | n/a | 0.0 s | 9.2 n | 0 |
| checkout-bugfix-0412 | JevCompact hybrid (real) | tuned | Compacted | 179,254 | 102,322 | 42.9% | 7/8 | 0 | 1 | 0 | n/a | 0.0 s | 9.2 n | 0 |
| data-pipeline-test | Prune only (judge) (real) | tuned | Compacted | 147,694 | 1,385 | 99.1% | 4/8 | 0 | 4 | 0 | n/a | 0.0 s | 7.6 n | 0 |
| data-pipeline-test | JevCompact hybrid (real) | tuned | Compacted | 147,694 | 1,411 | 99.0% | 4/8 | 0 | 4 | 0 | n/a | 0.0 s | 7.6 n | 0 |
| docs-migration | Prune only (judge) (real) | tuned | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 0 |
| docs-migration | JevCompact hybrid (real) | tuned | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | 0.0 n | 0 |
| flaky-ci-timeout | Prune only (judge) (real) | tuned | Compacted | 209,701 | 69,723 | 66.8% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | 6.0 n | 0 |
| flaky-ci-timeout | JevCompact hybrid (real) | tuned | Compacted | 209,701 | 69,734 | 66.7% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | 6.0 n | 0 |

Warnings: api-refactor-long / Plain summary only: Summarizer failed, session left unsummarized: Cloudflare returned an empty summary (output budget used up by reasoning?); Still over budget: pinned content alone exceeds the budget.

### Clipping trade-off — prune only, default thresholds (real: Cloudflare (Granite) judge, standing in for Jev)

| jev_item_max_tokens | Needed kept (mean) | Tokens saved | Judge requests | Judge input tokens | Judge cost | Scoring latency |
|---|---|---|---|---|---|---|
| 300 | 57.5% | 81.1% | 1.0 | 4,244 | 7.7 neurons | 0.0 s |
| 1000 | 57.5% | 70.9% | 1.0 | 11,102 | 18.3 neurons | 0.0 s |
| unclipped | 39.2% | 88.9% | 7.8 | 90,644 | 141.3 neurons | 9.6 s |

### Threshold sweep — recorded prune-only scores re-classified, no extra calls (real: Cloudflare (Granite) judge, standing in for Jev)

| Setting | Keep | Drop | Needed kept | Tool tokens saved |
|---|---|---|---|---|
| default (balanced) | 0.5 | 0.1 | 57.9% | 80.2% |
| conservative | 0.3 | 0.05 | 57.9% | 80.2% |
| aggressive | 0.7 | 0.2 | 57.9% | 80.2% |
| tuned (picked by the sweep) | 0.5 | 0.1 | 57.9% | 80.2% |

Rule for *tuned*: the most tool-output tokens saved with ≥ 95% of needed items kept; if no setting reaches 95%, the most needed items kept (ties: closest to the default). Best needed-kept anywhere on the grid: 57.9%. Full grid: `eval/threshold_sweep.csv`.

Every grid point keeps the same share of needed items: the judge's scores are effectively binary (0 or 1), so moving the thresholds only changes whether 0-scored items are cut or dropped, never whether they are kept verbatim.

**Leave-one-session-out check** — thresholds tuned on the other sessions, applied to the held-out one (real: Cloudflare (Granite) judge, standing in for Jev):

| Held-out session | Tuned keep/drop | Needed kept (tuned) | Tool tokens saved (tuned) | Needed kept (default) | Tool tokens saved (default) |
|---|---|---|---|---|---|
| api-refactor-long | 0.5/0.1 | 62.5% | 97.4% | 62.5% | 97.4% |
| auth-session-expiry | 0.5/0.1 | 37.5% | 99.7% | 37.5% | 99.7% |
| checkout-bugfix-0412 | 0.5/0.1 | 87.5% | 43.1% | 87.5% | 43.1% |
| data-pipeline-test | 0.5/0.1 | 50.0% | 99.4% | 50.0% | 99.4% |
| flaky-ci-timeout | 0.5/0.1 | 50.0% | 66.9% | 50.0% | 66.9% |

Figures: `docs/figures/tokens_saved_real.png`, `needed_kept_real.png`, `clipping_real.png`, `threshold_sweep_real.png`.

## Secondary results (mock) — mock: MockJudge + MockSummarizer

Run on 2026-11-25 · judge: **mock** · summarizer: mock · budget 120,000 tokens · compaction point: before the agent's final answer (closing assistant message left out).

### Averages over the 5 sessions above the 120k budget — default thresholds 0.50 / 0.10 (mock: MockJudge + MockSummarizer)

| Method | Tokens saved | Needed items kept | User msgs lost | Invented lines removed | Latency | Jev cost (mock estimate) | Summary neurons | Fell back |
|---|---|---|---|---|---|---|---|---|
| FIFO sliding window (mock) | 49.3% | 60.5% | 6 | n/a | 0.0 s | $0.0000 | 0 | 0 |
| Plain summary only (mock) | 49.7% | 63.2% | 0 | n/a | 0.0 s | $0.0000 | 0 | 0 |
| Prune only (judge) (mock) | 82.9% | 71.1% | 0 | n/a | 0.0 s | $0.0002 | 0 | 0 |
| JevCompact hybrid (mock) | 82.9% | 71.1% | 0 | 0 | 0.0 s | $0.0002 | 0 | 0 |

### Default vs tuned thresholds (mock: MockJudge + MockSummarizer)

| Method | Tokens saved | Needed items kept | User msgs lost | Invented lines removed | Latency | Jev cost (mock estimate) | Summary neurons | Fell back |
|---|---|---|---|---|---|---|---|---|
| Prune only (judge) · default 0.50/0.10 (mock) | 82.9% | 71.1% | 0 | n/a | 0.0 s | $0.0002 | 0 | 0 |
| JevCompact hybrid · default 0.50/0.10 (mock) | 82.9% | 71.1% | 0 | 0 | 0.0 s | $0.0002 | 0 | 0 |
| Prune only (judge) · tuned 0.05/0.0 (mock) | 26.0% | 100.0% | 0 | n/a | 0.0 s | $0.0002 | 0 | 0 |
| JevCompact hybrid · tuned 0.05/0.0 (mock) | 49.3% | 63.2% | 0 | 0 | 0.0 s | $0.0003 | 0 | 1 |

### Per session (mock: MockJudge + MockSummarizer)

| Session | Method | Thresholds | Status | Tokens before | Tokens after | Saved | Needed kept | Needed cut | Needed removed | User msgs lost | Invented removed | Latency | Judge cost | Summary neurons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| api-refactor-long | FIFO sliding window (mock) | n/a | Compacted | 185,006 | 58,145 | 68.6% | 3/8 | 0 | 5 | 2 | n/a | 0.1 s | $0.0000 | 0 |
| api-refactor-long | Plain summary only (mock) | n/a | Compacted | 185,006 | 58,475 | 68.4% | 3/8 | 0 | 5 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| api-refactor-long | Prune only (judge) (mock) | default | Compacted | 185,006 | 34,318 | 81.5% | 5/8 | 2 | 1 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| api-refactor-long | JevCompact hybrid (mock) | default | Compacted | 185,006 | 34,296 | 81.5% | 5/8 | 2 | 1 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| auth-session-expiry | FIFO sliding window (mock) | n/a | Compacted | 177,932 | 107,617 | 39.5% | 5/8 | 0 | 3 | 1 | n/a | 0.0 s | $0.0000 | 0 |
| auth-session-expiry | Plain summary only (mock) | n/a | Compacted | 177,932 | 107,754 | 39.4% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| auth-session-expiry | Prune only (judge) (mock) | default | Compacted | 177,932 | 7,847 | 95.6% | 6/8 | 2 | 0 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| auth-session-expiry | JevCompact hybrid (mock) | default | Compacted | 177,932 | 7,840 | 95.6% | 6/8 | 2 | 0 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| checkout-bugfix-0412 | FIFO sliding window (mock) | n/a | Compacted | 179,254 | 104,002 | 42.0% | 8/8 | 0 | 0 | 1 | n/a | 0.0 s | $0.0000 | 0 |
| checkout-bugfix-0412 | Plain summary only (mock) | n/a | Compacted | 179,254 | 104,105 | 41.9% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| checkout-bugfix-0412 | Prune only (judge) (mock) | default | Compacted | 179,254 | 18,177 | 89.9% | 5/8 | 3 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| checkout-bugfix-0412 | JevCompact hybrid (mock) | default | Compacted | 179,254 | 18,151 | 89.9% | 5/8 | 3 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| data-pipeline-test | FIFO sliding window (mock) | n/a | Compacted | 147,694 | 68,592 | 53.6% | 4/8 | 0 | 4 | 1 | n/a | 0.0 s | $0.0000 | 0 |
| data-pipeline-test | Plain summary only (mock) | n/a | Compacted | 147,694 | 69,031 | 53.3% | 5/8 | 0 | 3 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| data-pipeline-test | Prune only (judge) (mock) | default | Compacted | 147,694 | 19,675 | 86.7% | 6/8 | 2 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| data-pipeline-test | JevCompact hybrid (mock) | default | Compacted | 147,694 | 19,675 | 86.7% | 6/8 | 2 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| docs-migration | FIFO sliding window (mock) | n/a | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| docs-migration | Plain summary only (mock) | n/a | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| docs-migration | Prune only (judge) (mock) | default | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| docs-migration | JevCompact hybrid (mock) | default | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| flaky-ci-timeout | FIFO sliding window (mock) | n/a | Compacted | 209,701 | 119,816 | 42.9% | 3/6 | 0 | 3 | 1 | n/a | 0.0 s | $0.0000 | 0 |
| flaky-ci-timeout | Plain summary only (mock) | n/a | Compacted | 209,701 | 114,458 | 45.4% | 3/6 | 0 | 3 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| flaky-ci-timeout | Prune only (judge) (mock) | default | Compacted | 209,701 | 81,693 | 61.0% | 5/6 | 0 | 1 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| flaky-ci-timeout | JevCompact hybrid (mock) | default | Compacted | 209,701 | 81,699 | 61.0% | 5/6 | 0 | 1 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| api-refactor-long | Prune only (judge) (mock) | tuned | Compacted | 185,006 | 147,034 | 20.5% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| api-refactor-long | JevCompact hybrid (mock) | tuned | Compacted | 185,006 | 111,116 | 39.9% | 3/8 | 0 | 5 | 0 | 0 | 0.0 s | $0.0006 | 0 |
| auth-session-expiry | Prune only (judge) (mock) | tuned | Compacted | 177,932 | 133,435 | 25.0% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| auth-session-expiry | JevCompact hybrid (mock) | tuned | Compacted | 177,932 | 97,985 | 44.9% | 5/8 | 0 | 3 | 0 | 0 | 0.0 s | $0.0003 | 0 |
| checkout-bugfix-0412 | Prune only (judge) (mock) | tuned | Compacted | 179,254 | 66,323 | 63.0% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| checkout-bugfix-0412 | JevCompact hybrid (mock) | tuned | Compacted | 179,254 | 66,331 | 63.0% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| data-pipeline-test | Prune only (judge) (mock) | tuned | Compacted | 147,694 | 147,694 | 0.0% | 8/8 | 0 | 0 | 0 | n/a | 0.0 s | $0.0002 | 0 |
| data-pipeline-test | JevCompact hybrid (mock) | tuned | Fell back | 147,694 | 69,031 | 53.3% | 5/8 | 0 | 3 | 0 | 0 | 0.0 s | $0.0002 | 0 |
| docs-migration | Prune only (judge) (mock) | tuned | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| docs-migration | JevCompact hybrid (mock) | tuned | Under budget | 64,419 | 64,419 | 0.0% | 9/9 | 0 | 0 | 0 | n/a | 0.0 s | $0.0000 | 0 |
| flaky-ci-timeout | Prune only (judge) (mock) | tuned | Compacted | 209,701 | 164,614 | 21.5% | 6/6 | 0 | 0 | 0 | n/a | 0.0 s | $0.0001 | 0 |
| flaky-ci-timeout | JevCompact hybrid (mock) | tuned | Compacted | 209,701 | 114,458 | 45.4% | 3/6 | 0 | 3 | 0 | 0 | 0.0 s | $0.0005 | 0 |

Warnings: api-refactor-long / Prune only (judge): Still over budget: pinned content alone exceeds the budget.; auth-session-expiry / Prune only (judge): Still over budget: pinned content alone exceeds the budget.; data-pipeline-test / Prune only (judge): Still over budget: pinned content alone exceeds the budget.; flaky-ci-timeout / Prune only (judge): Still over budget: pinned content alone exceeds the budget.

Fallbacks: data-pipeline-test / JevCompact hybrid: Jev saved only 0% (minimum 10%)

### Clipping trade-off — prune only, default thresholds (mock: MockJudge + MockSummarizer)

| jev_item_max_tokens | Needed kept (mean) | Tokens saved | Judge requests | Judge input tokens | Judge cost | Scoring latency |
|---|---|---|---|---|---|---|
| 300 | 71.7% | 82.9% | 1.0 | 3,948 | $0.0002 | 0.0 s |
| 1000 | 71.7% | 82.9% | 1.0 | 10,806 | $0.0005 | 0.0 s |
| unclipped | 71.7% | 82.9% | 5.0 | 124,796 | $0.0052 | 0.3 s |

### Threshold sweep — recorded prune-only scores re-classified, no extra calls (mock: MockJudge + MockSummarizer)

| Setting | Keep | Drop | Needed kept | Tool tokens saved |
|---|---|---|---|---|
| default (balanced) | 0.5 | 0.1 | 68.4% | 82.3% |
| conservative | 0.3 | 0.05 | 94.7% | 35.3% |
| aggressive | 0.7 | 0.2 | 63.2% | 88.2% |
| tuned (picked by the sweep) | 0.05 | 0.0 | 100.0% | 26.8% |

Rule for *tuned*: the most tool-output tokens saved with ≥ 95% of needed items kept; if no setting reaches 95%, the most needed items kept (ties: closest to the default). Best needed-kept anywhere on the grid: 100.0%. Full grid: `eval/threshold_sweep_mock.csv`.

**Leave-one-session-out check** — thresholds tuned on the other sessions, applied to the held-out one (mock: MockJudge + MockSummarizer):

| Held-out session | Tuned keep/drop | Needed kept (tuned) | Tool tokens saved (tuned) | Needed kept (default) | Tool tokens saved (default) |
|---|---|---|---|---|---|
| api-refactor-long | 0.3/0.1 | 87.5% | 27.2% | 62.5% | 81.7% |
| auth-session-expiry | 0.05/0.0 | 100.0% | 25.1% | 62.5% | 95.8% |
| checkout-bugfix-0412 | 0.05/0.0 | 100.0% | 63.2% | 62.5% | 90.2% |
| data-pipeline-test | 0.05/0.0 | 100.0% | 0.0% | 75.0% | 87.0% |
| flaky-ci-timeout | 0.3/0.1 | 83.3% | 49.7% | 83.3% | 61.2% |

Figures: `docs/figures/tokens_saved_mock.png`, `needed_kept_mock.png`, `clipping_mock.png`, `threshold_sweep_mock.png`.

