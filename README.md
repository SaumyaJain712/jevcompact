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

Cloudflare: the spec default `@cf/meta/llama-3.1-8b-instruct` was deprecated by Cloudflare on 2026-05-30, so the default is `@cf/meta/llama-3.1-8b-instruct-fp8` (set `CF_MODEL` to change it).
