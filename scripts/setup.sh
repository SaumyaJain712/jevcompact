#!/usr/bin/env sh
# JevCompact setup for macOS and Linux (no GPU needed). Run from the repository root:  sh scripts/setup.sh
set -e
command -v uv >/dev/null 2>&1 || { echo "uv not found; installing it from PyPI"; python3 -m pip install --user uv; }
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
if command -v npm >/dev/null 2>&1; then
  (cd dashboard && npm ci && npm run build)
else
  echo "npm not found: the dashboard is not built (the library, CLI and API still work)."
fi
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example; add your Cloudflare keys to it."; }
echo "Done. Start the dashboard with:  .venv/bin/jevcompact serve   (http://127.0.0.1:8000)"
