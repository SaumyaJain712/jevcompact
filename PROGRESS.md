# JevCompact progress

Ticked only when the linked test passes. Phase in brackets.

## Functional requirements
- [x] FR1 Load OpenAI / Anthropic JSON, live capture via library — `tests/test_fr01_formats.py` (a)
- [x] FR2 Auto-start past a configurable budget — `tests/test_fr02_budget_trigger.py` (a)
- [x] FR3 Pin task, user messages, latest turn, errors — `tests/test_fr03_pinning.py` (a)
- [x] FR4 Score old tool results in parallel requests < 32k — `tests/test_fr04_batching.py` (a); Jev client `tests/test_clients.py` (b, mocked HTTP; live test pending keys)
- [x] FR5 Keep / truncate / drop + recall cache — `tests/test_fr05_thresholds.py` (a)
- [x] FR6 Summarize only when still over budget — `tests/test_fr06_fr07_summary.py` (a); Cloudflare client `tests/test_clients.py` (b, mocked HTTP; live test pending keys)
- [x] FR7 Check summary lines, remove unsupported — `tests/test_fr06_fr07_summary.py` (a)
- [x] FR8 Fall back on error / timeout / low savings — `tests/test_fr08_fallback.py` (a)
- [x] FR9 Log every decision (item, score, action, time) — library side `tests/test_fr09_fr11_fr12.py` (a); DB log in (c)
- [ ] FR10 Dashboard: sessions, scores, tokens before/after (d, e)
- [ ] FR11 Change thresholds, re-run, restore — library `restore_item` + `recall` tested (a); API + UI pending (c, d)
- [x] FR12 Export JSON + savings report JSON/CSV — library + CLI `tests/test_fr09_fr11_fr12.py` (a); API export in (c)

## Non-functional requirements
- [x] Performance (mock): TC-P1 scoring-step P95 < 1 s with MockJudge at 70–500 ms — `tests/test_nfr.py`, `docs/measurements/tc_p1_latency.json` (also records prune + check P95).
- [ ] Performance (real): real-Jev scoring P95, prune + check P95, and time with the real summarizer — `tests/test_live.py`, needs keys.
- [x] Cost (mock) ≤ $0.002 per compaction (tiktoken counts, 175k-token session) — `docs/measurements/cost.json`.
- [ ] Cost (real) from Jev-billed `usage.input_tokens` — `tests/test_live.py`, needs keys. Cloudflare cost reported as neurons.
- [x] Reliability: automatic fallback + property test (200 generated sessions, 0 user messages lost) — `tests/test_nfr.py`
- [ ] Accuracy ≥ 95% needed items kept (f)
- [ ] Security: Fernet-encrypted keys, masked, never logged (c)
- [x] Maintainability: Judge / Summarizer protocols, mocks swappable — `tests/test_nfr.py`
- [ ] Portability: Windows / macOS / Linux, no GPU (g: README + scripts; only Linux tested so far)

## Test cases
- [x] TC-03 user message never dropped
- [x] TC-04 50k tokens of candidates → 2 Jev requests
- [x] TC-05 score 0.05 dropped and cached
- [x] TC-08 Jev timeout → plain summary
- [ ] TC-10 score shown for every item (Playwright, e)
- [x] TC-11 restored item returns verbatim
- [x] TC-P1 P95 under 1 s
- [x] Settings validation (library config) — `tests/test_config.py`; UI validation pending (d, e)

## Phases
- [x] (a) Library core with mocks + tests
- [x] (b) Cloudflare + Jev clients (mocked-HTTP tests pass; live tests skipped: no keys yet)
- [ ] (c) Database + FastAPI
- [ ] (d) React dashboard
- [ ] (e) Playwright tests + screenshots
- [ ] (f) Sample data + evaluation
- [ ] (g) Docs and diagrams

## Design deviations
- **Jev input clipped to 300 tokens per tool output** (`jev_item_max_tokens`, head + tail). Reason: cost. Sending full outputs of a 180k-token session costs ~$0.006 per compaction, over the $0.002 NFR; clipped it costs ~$0.0016. Phase (f) evaluates 300 / 1000 / unclipped for accuracy vs cost.
- **Cloudflare default model changed** from `@cf/meta/llama-3.1-8b-instruct` (deprecated by Cloudflare on 2026-05-30, changelog 2026-05-08) to `@cf/meta/llama-3.1-8b-instruct-fp8`, as instructed. Note: the fp8 model page lists a planned deprecation on 2026-11-20 — awaiting decision on a replacement. Model stays configurable (`CF_MODEL`).

## Notes / decisions
- Python 3.11 venv created with uv (machine default is 3.10).
- Jev limits (32k tokens/request, 80 req/s, 100k tok/s, English only, $0.042/M input) are configurable defaults from our SRS (TypeSafe models page, Oct 2026); the quickstart does not state them.
- Both Jev questions are `noul` questions (`instructions` field, per the OpenAPI spec), phrased as the spec's yes/no questions; thresholds apply directly to the noul value.
- Jev via OpenRouter: same System One API at `https://openrouter.ai/api/v1` (set `JEV_BASE_URL`, `JEV_MODEL=~typesafe/jev-latest`).
- TypeSafe docs give 64k tokens per request / 32k per question by default; our 32k per request (SRS) is stricter, so no contradiction. Rate limits are per organisation (console); 80 req/s and 100k tok/s stay as SRS defaults. English-only is not stated in the docs; kept from the SRS.
- Each tool output is clipped to 300 tokens (head + tail) inside the Jev state (`jev_item_max_tokens`), which keeps a 180k-token session near $0.0016. Outputs under 300 tokens are sent whole, so TC-04 sends 50k real tokens.
- Requests are packed to 95% of 32k because our tokenizer (cl100k) may differ from Jev's.
- "Dropped" tool results are replaced by a one-line stub with a recall id, not deleted, so tool_call/tool_result pairs stay valid in both APIs.
- Fallback on low savings fires only when Jev saved < 10% **and** the session is still over budget.
