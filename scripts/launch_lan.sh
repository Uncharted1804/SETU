#!/usr/bin/env bash
# LAN mode launcher.  OWNER: P4.
#
# SETU_TRUSTED_SUBNET must be set from the subnet you ACTUALLY observe at the
# venue - a phone hotspot hands out a different range every session, so it is
# never hardcoded in a committed file.
#
#   ./scripts/launch_lan.sh 192.168.50.0/24
#
# An invalid subnet is a HARD startup failure, never a silent fallback to
# single-laptop mode.
set -euo pipefail

SUBNET="${1:-}"
if [ -z "$SUBNET" ]; then
  echo "usage: $0 <CIDR>    e.g. $0 192.168.50.0/24" >&2
  echo "" >&2
  echo "Observe the subnet first:" >&2
  echo "  ip -4 addr | grep inet        # Linux/WSL" >&2
  echo "  ipconfig                      # Windows" >&2
  exit 2
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

export SETU_TRUSTED_SUBNET="$SUBNET"
export SETU_MOCK_MODE="${SETU_MOCK_MODE:-0}"
export OLLAMA_HOST="127.0.0.1:11434"
# Rule from the blueprint: DEV_MODE and TRUSTED_SUBNET are never both set.
unset SETU_DEV_MODE SETU_DEV_ORIGINS || true

echo "LAN mode: binding 0.0.0.0:8000, trusting $SUBNET only."
echo "Reminder: Ollama stays on loopback. Colleagues talk to SETU, not to the model server."
echo "Firewall (run once, as admin, on Windows):"
echo "  New-NetFirewallRule -DisplayName 'SETU API' -Direction Inbound -Protocol TCP \\"
echo "    -LocalPort 8000 -RemoteAddress $SUBNET -Action Allow"

PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$REPO/.venv/Scripts/python.exe"
exec "$PYTHON" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
