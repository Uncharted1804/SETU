#!/usr/bin/env bash
# SETU development launcher (Linux / WSL / macOS).  OWNER: P1.
#
#   ./scripts/dev.sh            # mock mode, backend only, loopback
#   ./scripts/dev.sh --real     # real mode (needs Ollama + Docker + models)
#   ./scripts/dev.sh --ui       # backend + Vite dev server with gated CORS
#
# Nothing here downloads a model, a wheel or an npm package.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PORT="${PORT:-8000}"
export SETU_MOCK_MODE=1
export OLLAMA_HOST="127.0.0.1:11434"
export SETU_WORKSPACE="$REPO/data/workspace"
export SETU_AUDIT_PATH="$REPO/logs/audit.jsonl"
unset SETU_DEV_MODE SETU_DEV_ORIGINS || true

for arg in "$@"; do
  case "$arg" in
    --real) export SETU_MOCK_MODE=0 ;;
    --ui)
      # The ONLY supported use of CORS. Both variables are required; the
      # backend fails closed without SETU_DEV_ORIGINS and never uses a wildcard.
      export SETU_DEV_MODE=1
      export SETU_DEV_ORIGINS="http://localhost:5173"
      echo "DEV CORS ENABLED for http://localhost:5173 - never on the demo box."
      (cd frontend && npm run dev &)
      ;;
  esac
done

PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$REPO/.venv/Scripts/python.exe"
[ -x "$PYTHON" ] || PYTHON="python3"

echo "SETU starting on http://127.0.0.1:$PORT (mock_mode=$SETU_MOCK_MODE)"
exec "$PYTHON" -m uvicorn app.main:app --app-dir backend --port "$PORT"
