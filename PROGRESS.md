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
- [x] FR9 Log every decision (item, score, action, time) — library `tests/test_fr09_fr11_fr12.py` (a); `decisions` table `tests/test_api.py::test_decisions_logged_in_db` (c)
- [ ] FR10 Dashboard: sessions, scores, tokens before/after — API data done and tested (`/api/sessions`, `/decisions`, `/compare`) (c); UI pending (d, e)
- [ ] FR11 Change thresholds, re-run, restore — library (a); API re-run, cancel, restore, undo/redo tested `tests/test_api.py` (c); UI pending (d, e)
- [x] FR12 Export JSON + savings report JSON/CSV — library + CLI (a); API `/export.json`, `/report.json`, `/report.csv` `tests/test_api.py::test_exports` (c)

## Non-functional requirements
- [x] Performance (mock): TC-P1 scoring-step P95 < 1 s with MockJudge at 70–500 ms — `tests/test_nfr.py`, `docs/measurements/tc_p1_latency.json` (also records prune + check P95).
- [ ] Performance (real): real-Jev scoring P95, prune + check P95, and time with the real summarizer — `tests/test_live.py`, needs keys.
- [x] Cost (mock) ≤ $0.002 per compaction (tiktoken counts, 175k-token session) — `docs/measurements/cost.json`.
- [ ] Cost (real) from Jev-billed `usage.input_tokens` — `tests/test_live.py`, needs keys. Cloudflare cost reported as neurons.
- [x] Reliability: automatic fallback + property test (200 generated sessions, 0 user messages lost) — `tests/test_nfr.py`
- [ ] Accuracy ≥ 95% needed items kept (f)
- [ ] Security: Fernet-encrypted at rest, masked in API responses, redacted from logs, server binds 127.0.0.1 — `tests/test_api.py::test_keys_encrypted_masked_never_returned` (c); UI masking pending (d)
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
- [x] Settings validation — library `tests/test_config.py` (a); API `tests/test_api.py::test_settings_validation` (c); UI pending (d, e)

## Phases
- [x] (a) Library core with mocks + tests
- [x] (b) Cloudflare + Jev clients (mocked-HTTP tests pass; live tests skipped: no keys yet)
- [x] (c) Database + FastAPI (live provider tests still pending keys)
- [ ] (d) React dashboard
- [ ] (e) Playwright tests + screenshots
- [ ] (f) Sample data + evaluation
- [ ] (g) Docs and diagrams

## Design deviations
- **Jev input clipped to 300 tokens per tool output** (`jev_item_max_tokens`, head + tail). Reason: cost. Sending full outputs of a 180k-token session costs ~$0.006 per compaction, over the $0.002 NFR; clipped it costs ~$0.0016. Phase (f) evaluates 300 / 1000 / unclipped for accuracy vs cost.
- **Cloudflare default model changed** from the spec's `@cf/meta/llama-3.1-8b-instruct` to `@cf/zai-org/glm-4.7-flash` (decided 2026-11-20). Reason: both Llama 3.1 8B variants are deprecated — the base model on 2026-05-30 (Cloudflare changelog 2026-05-08) and `-fp8` on 2026-11-20 (its model page). GLM-4.7-flash is Cloudflare's recommended replacement, has a 131,072-token context, and is not marked for deprecation. Still configurable via `CF_MODEL`.
  - GLM-4.7-flash is a reasoning model: we send `max_completion_tokens=2048` (its `max_tokens` is deprecated), strip `<think>` blocks, and treat an empty reply as a summarizer error (the pruned session is kept).
  - Cost (pricing page): 5,500 neurons per M input tokens, 36,400 per M output tokens. Per summary: ~65 neurons for 5k input + 1k output (~155 summaries/day on the free 10,000 neurons), ~165 neurons for 20k + 1.5k (~60/day), ~735 neurons for a full 120k + 2k (~13/day). Real numbers will come from the live test.

## Notes / decisions
- Phase (c): uploading a session runs compaction automatically with the saved settings (FR2), so every session has a status. `?auto_run=false` skips it.
- Every run (and every restore) is a new version in `runs`; the uploaded `messages` rows are never modified. Undo/redo moves the session's `current_run_id` along the version history; starting a new run after an undo discards the redo branch (marked `superseded`).
- A dropped item that was later folded into the summary can't be put back in place (API returns 409); its full text is still available via `/api/runs/{id}/recall/{item_id}`.
- Fernet key source: `JEVCOMPACT_SECRET_KEY` env → OS keyring → (deviation) owner-only key file `.jevcompact/secret.key` when no keyring backend works, e.g. headless Linux. A warning is logged.
- Provider choice in the server: `JUDGE`/`SUMMARIZER` env vars win; otherwise a real provider is used when its keys are saved in Settings.
- Live tests (`pytest -m live`) have not run: no `.env` keys yet. Real measurements will be committed separately when keys are added.
- Python 3.11 venv created with uv (machine default is 3.10).
- Jev limits (32k tokens/request, 80 req/s, 100k tok/s, English only, $0.042/M input) are configurable defaults from our SRS (TypeSafe models page, Oct 2026); the quickstart does not state them.
- Both Jev questions are `noul` questions (`instructions` field, per the OpenAPI spec), phrased as the spec's yes/no questions; thresholds apply directly to the noul value.
- Jev via OpenRouter: same System One API at `https://openrouter.ai/api/v1` (set `JEV_BASE_URL`, `JEV_MODEL=~typesafe/jev-latest`).
- TypeSafe docs give 64k tokens per request / 32k per question by default; our 32k per request (SRS) is stricter, so no contradiction. Rate limits are per organisation (console); 80 req/s and 100k tok/s stay as SRS defaults. English-only is not stated in the docs; kept from the SRS.
- Each tool output is clipped to 300 tokens (head + tail) inside the Jev state (`jev_item_max_tokens`), which keeps a 180k-token session near $0.0016. Outputs under 300 tokens are sent whole, so TC-04 sends 50k real tokens.
- Requests are packed to 95% of 32k because our tokenizer (cl100k) may differ from Jev's.
- "Dropped" tool results are replaced by a one-line stub with a recall id, not deleted, so tool_call/tool_result pairs stay valid in both APIs.
- Fallback on low savings fires only when Jev saved < 10% **and** the session is still over budget.
