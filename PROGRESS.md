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
- [x] FR10 Dashboard: sessions, scores, tokens before/after — API (c); screens (d); Playwright `dashboard/e2e/tc10-scores.spec.ts`, `sessions.spec.ts`, `review.spec.ts`, `compare.spec.ts` (e)
- [x] FR11 Change thresholds, re-run, restore — library (a); API incl. folded items and version 0 `tests/test_api.py` (c); UI: re-run with preset, slider validation, R/U keys, Restore one, folded restore, Redo `dashboard/e2e/review.spec.ts` (e)
- [x] FR12 Export JSON + savings report JSON/CSV — library + CLI (a); API `/export.json`, `/report.json`, `/report.csv` `tests/test_api.py::test_exports` (c)

## Non-functional requirements
- [x] Performance (mock): TC-P1 scoring-step P95 < 1 s with MockJudge at 70–500 ms — `tests/test_nfr.py`, `docs/measurements/tc_p1_latency.json` (also records prune + check P95).
- [ ] Performance (real): real-Jev scoring P95, prune + check P95, and time with the real summarizer — `tests/test_live.py`, needs keys.
- [x] Cost (mock) ≤ $0.002 per compaction (tiktoken counts, 175k-token session) — `docs/measurements/cost.json`.
- [ ] Cost (real) from Jev-billed `usage.input_tokens` — `tests/test_live.py`, needs keys. Cloudflare cost reported as neurons.
- [x] Reliability: automatic fallback + property test (200 generated sessions, 0 user messages lost) — `tests/test_nfr.py`
- [ ] Accuracy ≥ 95% needed items kept (f)
- [x] Security: Fernet-encrypted at rest, masked in API responses and UI, redacted from logs, server binds 127.0.0.1 — `tests/test_api.py::test_keys_encrypted_masked_never_returned` (c), `dashboard/e2e/settings.spec.ts` (e)
- [x] Maintainability: Judge / Summarizer protocols, mocks swappable — `tests/test_nfr.py`
- [ ] Portability: Windows / macOS / Linux, no GPU (g: README + scripts; only Linux tested so far)

## Test cases
- [x] TC-03 user message never dropped
- [x] TC-04 50k tokens of candidates → 2 Jev requests
- [x] TC-05 score 0.05 dropped and cached
- [x] TC-08 Jev timeout → plain summary
- [x] TC-10 score shown for every item — `dashboard/e2e/tc10-scores.spec.ts`
- [x] TC-11 restored item returns verbatim
- [x] TC-P1 P95 under 1 s
- [x] Settings validation — library `tests/test_config.py` (a); API `tests/test_api.py::test_settings_validation` (c); UI `dashboard/e2e/settings.spec.ts` (e)
- [x] GUI style guide: exact colours, Inter 24/14, JetBrains Mono 13, all text ≥ 4.5:1, status words, one primary button top right, sidebar on every screen — `dashboard/e2e/layout.spec.ts`
- [x] Error banners: Jev timeout (real 5 s timeout via slow mock server), upload error, items dropped — `review.spec.ts`, `sessions.spec.ts`

## Phases
- [x] (a) Library core with mocks + tests
- [x] (b) Cloudflare + Jev clients (mocked-HTTP tests pass; live tests skipped: no keys yet)
- [x] (c) Database + FastAPI (live provider tests still pending keys)
- [x] (d) React dashboard (typecheck + build pass; UI tests come in e)
- [x] (e) Playwright tests + screenshots (21 UI tests; `docs/screenshots/01–08`, preview data until phase f)
- [ ] (f) Sample data + evaluation
- [ ] (g) Docs and diagrams

## Design deviations
- **Jev input clipped to 300 tokens per tool output** (`jev_item_max_tokens`, head + tail). Reason: cost. Sending full outputs of a 180k-token session costs ~$0.006 per compaction, over the $0.002 NFR; clipped it costs ~$0.0016. Phase (f) evaluates 300 / 1000 / unclipped for accuracy vs cost.
- **Cloudflare default model changed** from the spec's `@cf/meta/llama-3.1-8b-instruct` to `@cf/zai-org/glm-4.7-flash` (decided 2026-11-20). Reason: both Llama 3.1 8B variants are deprecated — the base model on 2026-05-30 (Cloudflare changelog 2026-05-08) and `-fp8` on 2026-11-20 (its model page). GLM-4.7-flash is Cloudflare's recommended replacement, has a 131,072-token context, and is not marked for deprecation. Still configurable via `CF_MODEL`.
  - GLM-4.7-flash is a reasoning model: we send `max_completion_tokens=2048` (its `max_tokens` is deprecated), strip `<think>` blocks, and treat an empty reply as a summarizer error (the pruned session is kept).
  - Cost (pricing page): 5,500 neurons per M input tokens, 36,400 per M output tokens. Per summary: ~65 neurons for 5k input + 1k output (~155 summaries/day on the free 10,000 neurons), ~165 neurons for 20k + 1.5k (~60/day), ~735 neurons for a full 120k + 2k (~13/day). Real numbers will come from the live test.

## Notes / decisions
- Phase (e): `npm run test:e2e` starts three local API servers (main; slow, where MockJudge takes 6 s so the 5 s Jev timeout and fallback really happen; clean one for screenshots) with fresh data in `.e2e-data/`. `npm run screenshots` writes `docs/screenshots/*.png` at 1440×900. Both use `data/samples/` once it exists, otherwise the generated preview sessions (`scripts/preview_sessions.py`), which is what the current screenshots show. `MOCK_JUDGE_LATENCY_MS` (e.g. `70,500`) sets MockJudge latency.
- Bugs found by the UI tests and fixed: (1) threshold edits made while the review page was still loading were overwritten, so Re-run could send the old thresholds; (2) item rows were `role=button` containing the Restore button (nested interactive controls) — the title is now the expand button; (3) "No items." showed while a large session was still loading — now "Loading items…".
- Dashboard (d): font sizes from the style guide (24 / 14 / 13 pt) are applied as CSS px, the usual meaning of "pt" in screen designs. Fonts are bundled with @fontsource, so the UI makes no external requests.
- Review screen: the top-right primary button is **Compare** (Undo/Redo secondary); **Re-run** sits in the right panel as a secondary button, so each screen has one primary button.
- Banners: the timeout banner uses the exact spec text; other fallback reasons (Jev error, low savings) show the reason followed by "We used the plain summary instead, so nothing was lost." The drop banner names the highest-scoring dropped item; The drop banner always shows Undo and Restore one. "View log" opens the decision log (time, item, score, action, reason) below the list.
- Restore buttons appear on dropped, cut and folded ("In summary") items.
- Phase (d) preview screenshots (mock judge, synthetic preview sessions) are kept in `docs/screenshots/preview/`.
- Phase (c): uploading a session runs compaction automatically with the saved settings (FR2), so every session has a status. `?auto_run=false` skips it.
- Every run (and every restore) is a new version in `runs`; the uploaded `messages` rows are never modified. The original upload is **version 0**: Undo is available after any compaction and can go back to it (status "Original", tokens after = tokens before). Undo/redo moves along [original, run 1, run 2, …]; starting a new run after an undo discards the redo branch (marked `superseded`) — `tests/test_api.py::test_undo_to_original_version_0`.
- Restore works for every removed item ("anything removed can be put back in one click"): dropped/cut items get their full text back in place; items folded into the summary get their whole original turn (assistant tool call + tool results, a matching pair) re-inserted verbatim right after the summary message, in original order among restored turns. Each restore is a new version — `tests/test_api.py::test_restore_folded_item_reinserts_turn_after_summary` (OpenAI + Anthropic).
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
