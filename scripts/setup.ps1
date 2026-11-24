# JevCompact setup for Windows (PowerShell, no GPU needed). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found; installing it from PyPI"
    py -3 -m pip install --user uv
}
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location dashboard; npm ci; npm run build; Pop-Location
} else {
    Write-Host "npm not found: the dashboard is not built (the library, CLI and API still work)."
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example; add your Cloudflare keys to it." }
Write-Host "Done. Start the dashboard with:  .venv\Scripts\jevcompact.exe serve   (http://127.0.0.1:8000)"
