# SETU development launcher (Windows PowerShell).  OWNER: P1.
#
#   .\scripts\dev.ps1              # mock mode, backend only, loopback
#   .\scripts\dev.ps1 -Real        # real mode (needs Ollama + Docker + models)
#   .\scripts\dev.ps1 -Ui          # backend + Vite dev server with gated CORS
#
# Nothing here downloads a model, a wheel or an npm package.

param(
    [switch]$Real,
    [switch]$Ui,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:SETU_MOCK_MODE = if ($Real) { "0" } else { "1" }
$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:SETU_WORKSPACE = Join-Path $repo "data\workspace"
$env:SETU_AUDIT_PATH = Join-Path $repo "logs\audit.jsonl"

if ($Ui) {
    # The ONLY supported use of CORS. Both variables are required; the backend
    # fails closed if SETU_DEV_ORIGINS is missing, and never installs a wildcard.
    $env:SETU_DEV_MODE = "1"
    $env:SETU_DEV_ORIGINS = "http://localhost:5173"
    Write-Host "DEV CORS ENABLED for http://localhost:5173 - never run this on the demo box." -ForegroundColor Yellow
    Start-Process -FilePath "npm" -ArgumentList "run","dev" -WorkingDirectory (Join-Path $repo "frontend")
} else {
    Remove-Item Env:SETU_DEV_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:SETU_DEV_ORIGINS -ErrorAction SilentlyContinue
}

Write-Host "SETU starting on http://127.0.0.1:$Port  (mock_mode=$($env:SETU_MOCK_MODE))"
& (Join-Path $repo ".venv\Scripts\python.exe") -m uvicorn app.main:app --app-dir backend --port $Port
