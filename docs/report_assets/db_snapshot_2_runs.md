# Snapshot 2 — runs (one per compaction or restore; each is a version)

judge = cloudflare is the Cloudflare (Granite) judge, standing in for Jev: cost is in judge_neurons, so jev_cost_usd is 0. summary_neurons is the Cloudflare summarizer's cost (0 when pruning alone got under the budget).

| id | session | seq | kind | preset | keep_threshold | drop_threshold | budget | judge | summarizer | status | tokens_before | tokens_after | judge_requests | judge_neurons | summary_neurons | jev_cost_usd | latency_ms | fallback_reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1085f063… | docs-migration | 1 | run | balanced | 0.50 | 0.10 | 120000 | cloudflare | cloudflare | Under budget | 64443 | 64443 | 0 | 0.00 | 0.00 | 0.0000 | 0.30 | NULL |
| 3998699e… | data-pipeline-test | 1 | run | balanced | 0.50 | 0.10 | 120000 | cloudflare | cloudflare | Compacted | 147727 | 1431 | 1 | 7.65 | 0.00 | 0.0000 | 5090.90 | NULL |
| e065d0dc… | api-refactor-long | 1 | run | balanced | 0.50 | 0.10 | 120000 | cloudflare | cloudflare | Compacted | 185045 | 5425 | 1 | 9.48 | 0.00 | 0.0000 | 4789.90 | NULL |
| 77420de0… | checkout-bugfix-0412 | 1 | run | balanced | 0.50 | 0.10 | 120000 | cloudflare | cloudflare | Compacted | 179293 | 66514 | 2 | 19.29 | 344.75 | 0.0000 | 49859.00 | NULL |
| af049b5b… | checkout-bugfix-0412 | 2 | restore | balanced | 0.50 | 0.10 | 120000 | cloudflare | cloudflare | Compacted | 179293 | 66567 | 0 | 0.00 | 0.00 | 0.0000 | 0.00 | NULL |
