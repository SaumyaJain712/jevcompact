# JevCompact — Session Compaction using Jev

(Full README is written in phase (g).)

## Setup (Python 3.11 required)

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

If the uv install script (`curl … | sh`) is blocked on your machine, install uv from PyPI instead: `pip install --user uv`.

## Provider limits

Jev limits used as defaults — 32k tokens per request, 80 requests/s, 100k tokens/s, English only, $0.042 per million input tokens — come from our SRS (TypeSafe's models page, Oct 2026), not from the quickstart. All are configurable in `CompactionConfig`.

Cloudflare: the default summarizer model is `@cf/zai-org/glm-4.7-flash` (set `CF_MODEL` to change it). This differs from the spec's `@cf/meta/llama-3.1-8b-instruct` because both Llama 3.1 8B variants are deprecated (base on 2026-05-30, `-fp8` on 2026-11-20); GLM-4.7-flash is Cloudflare's recommended replacement.

GLM-4.7-flash costs 5,500 neurons per million input tokens and 36,400 per million output tokens. A typical summary (20k tokens in, ~1.5k out including reasoning) uses about 165 neurons, so the free 10,000 neurons/day covers roughly 60 summaries; a small one (5k in) about 155; a full-context one (120k in) about 13. Summaries are cached by content hash, so re-running the same session costs nothing.
