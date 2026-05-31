#!/usr/bin/env bash
# One-time environment setup for headless Linux.
# Run once before first start. Safe to re-run — all steps are idempotent.
# Usage: bash scripts/setup-linux.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── ① Prerequisites ──────────────────────────────────────────────────────────
for cmd in node python3 curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[error] '$cmd' not found in PATH. Please install it first."
    exit 1
  fi
done

# ── ② mcp/node_modules ───────────────────────────────────────────────────────
if [ ! -d "mcp/node_modules" ]; then
  echo "[setup]  Installing mcp Node dependencies..."
  (cd mcp && npm install)
else
  echo "[setup]  mcp/node_modules already present, skipping."
fi

# ── ③ Python venv ────────────────────────────────────────────────────────────
VENV="$ROOT/loom/.venv"
if [ ! -d "$VENV" ]; then
  echo "[setup]  Creating Python venv at loom/.venv ..."
  python3 -m venv "$VENV"
else
  echo "[setup]  loom/.venv already present, skipping."
fi

# ── ④ pip dependencies ───────────────────────────────────────────────────────
REQ="$ROOT/loom/requirements.txt"
SENTINEL="$VENV/.installed"
if [ ! -f "$SENTINEL" ] || [ "$REQ" -nt "$SENTINEL" ]; then
  echo "[setup]  Installing Python dependencies from loom/requirements.txt ..."
  "$VENV/bin/pip" install --upgrade pip --quiet
  "$VENV/bin/pip" install -r "$REQ"
  touch "$SENTINEL"
else
  echo "[setup]  Python dependencies up to date, skipping."
fi

echo ""
echo "Setup complete. Run: bash scripts/start-anchor.sh"
