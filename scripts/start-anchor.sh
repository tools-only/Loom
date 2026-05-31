#!/usr/bin/env bash
# Start Anchor (:3000) and Loom Brain (:3002) on headless Linux.
# Idempotent: safe to run repeatedly. Installs deps on first run.
# Usage: bash scripts/start-anchor.sh

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
  echo "[deps]   Installing mcp Node dependencies..."
  (cd mcp && npm install)
fi

# ── ③ Python venv ────────────────────────────────────────────────────────────
VENV="$ROOT/loom/.venv"
if [ ! -d "$VENV" ]; then
  echo "[deps]   Creating Python venv at loom/.venv ..."
  python3 -m venv "$VENV"
fi

# ── ④ pip dependencies ───────────────────────────────────────────────────────
REQ="$ROOT/loom/requirements.txt"
SENTINEL="$VENV/.installed"
if [ ! -f "$SENTINEL" ] || [ "$REQ" -nt "$SENTINEL" ]; then
  echo "[deps]   Installing Python dependencies from loom/requirements.txt ..."
  "$VENV/bin/pip" install --upgrade pip --quiet
  "$VENV/bin/pip" install -r "$REQ"
  touch "$SENTINEL"
fi

# ── ⑤ Anchor Service (:3000) ─────────────────────────────────────────────────
if curl -sf http://localhost:3000/health >/dev/null 2>&1; then
  echo "[anchor] Already running on http://localhost:3000"
else
  echo "[anchor] Starting Anchor service on http://localhost:3000 ..."
  mkdir -p logs
  ANCHOR_USE_AUTOEXEC=1 ANCHOR_DISABLE_ENRICHMENT=1 \
    nohup node mcp/server.cjs >> logs/anchor.log 2>&1 &
  echo "[anchor] PID $!"
fi

# ── ⑥ Loom Brain (:3002) ─────────────────────────────────────────────────────
if curl -sf http://localhost:3002/health >/dev/null 2>&1; then
  echo "[brain]  Already running on http://localhost:3002"
else
  echo "[brain]  Starting Loom Brain on http://localhost:3002 ..."
  mkdir -p logs
  nohup bash -c "cd '$ROOT/loom' && '$VENV/bin/python' main.py" \
    >> "$ROOT/logs/brain.log" 2>&1 &
  echo "[brain]  PID $!"
fi

echo ""
echo "Done. Anchor :3000 | Loom Brain :3002"
echo "Logs: logs/anchor.log  logs/brain.log"
