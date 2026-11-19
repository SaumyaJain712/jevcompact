# Measurements

Every file has a `source` field: `mock` (MockJudge / MockSummarizer, tiktoken counts) or `real` (live Jev / Cloudflare, billed usage).

| File | Source | What |
|---|---|---|
| tc_p1_latency.json | mock | TC-P1: P95 of the Jev scoring step and of prune + check (no summarizer), MockJudge latency 70–500 ms |
| cost.json | mock | Jev cost per compaction from tiktoken counts × $0.042/M |
| tc_p1_latency_real.json | real | Same as TC-P1 with real Jev (written by `pytest -m live`) |
| cost_real.json | real | Cost from Jev's billed `usage.input_tokens` |
| jev_token_calibration.json | real | Our cl100k estimate vs Jev's billed tokens for one packed request (checks the 95% fill margin) |
| summarizer_latency_real.json | real | Cloudflare summary time and neurons; full compaction time with the real summarizer |

Real files appear only after running the live tests with keys set.
