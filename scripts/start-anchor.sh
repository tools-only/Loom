#!/usr/bin/env bash
# Start Anchor (:3000) and Loom Brain (:3002) on headless Linux.
# Idempotent: safe to run repeatedly.
# Run scripts/setup-linux.sh once before first start.
# Usage: bash scripts/start-anchor.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/loom/.venv"

# ── Guard: setup required ─────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "[error] loom/.venv not found. Run setup first:"
  echo "        bash scripts/setup-linux.sh"
  exit 1
fi

# ── ① Anchor Service (:3000) ──────────────────────────────────────────────────
if curl -sf http://localhost:3000/health >/dev/null 2>&1; then
  echo "[anchor] Already running on http://localhost:3000"
else
  echo "[anchor] Starting Anchor service on http://localhost:3000 ..."
  mkdir -p logs
  ANCHOR_USE_AUTOEXEC=1 ANCHOR_DISABLE_ENRICHMENT=1 \
    nohup node mcp/server.cjs >> logs/anchor.log 2>&1 &
  echo "[anchor] PID $!"
fi

# ── ② Loom Brain (:3002) ──────────────────────────────────────────────────────
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
