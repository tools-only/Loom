#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ANCHOR_PORT:-3000}"
URL="http://localhost:${PORT}/shutdown"

echo "[anchor-stop] requesting graceful shutdown at ${URL}"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 3 -X POST "$URL" \
      -H 'Content-Type: application/json' \
      -d '{"reason":"stop_script"}' >/tmp/anchor-stop-response.json 2>/tmp/anchor-stop-error.log; then
    echo "[anchor-stop] shutdown accepted by Anchor service"
    cat /tmp/anchor-stop-response.json
    echo
    exit 0
  fi
fi

echo "[anchor-stop] service did not answer; using registry fallback"
node "$ROOT/scripts/stop-anchor-helper.cjs"
