# Linux Headless Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `scripts/start-anchor.sh` to be a fully self-contained, idempotent startup script for headless Linux servers — checking prereqs, installing Node and Python deps on first run, then starting Anchor (:3000) and Loom Brain (:3002).

**Architecture:** Single enhanced shell script replaces the existing partial one. Uses a sentinel file (`loom/.venv/.installed`) for pip change detection to keep subsequent runs fast. Brain is launched via venv python rather than system python3.

**Tech Stack:** bash, node, npm, python3 venv, pip, curl

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `scripts/start-anchor.sh` | **Modify** | Full rewrite — adds prereq check, npm install, venv, pip, uses venv python for Brain |
| `loom/requirements.txt` | No change | Already complete — confirmed by import scan |

---

### Task 1: Rewrite `scripts/start-anchor.sh`

**Files:**
- Modify: `scripts/start-anchor.sh`

- [ ] **Step 1: Read the current file**

Open `scripts/start-anchor.sh` and note the existing structure (Anchor block + Brain block). The rewrite keeps those two blocks and prepends five new steps.

- [ ] **Step 2: Write the new script**

Replace the entire contents of `scripts/start-anchor.sh` with:

```bash
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
```

- [ ] **Step 3: Verify line endings are Unix (LF)**

```bash
file scripts/start-anchor.sh
# Expected: scripts/start-anchor.sh: ASCII text
# If it shows CRLF, run: sed -i 's/\r//' scripts/start-anchor.sh
```

- [ ] **Step 4: Make executable**

```bash
chmod +x scripts/start-anchor.sh
```

- [ ] **Step 5: Smoke-test prereq check (no services needed)**

```bash
# Verify the script rejects missing commands gracefully
bash -c '
  PATH_BAK=$PATH
  export PATH=/usr/bin   # strip node from path temporarily to test
  bash scripts/start-anchor.sh 2>&1 | head -3 || true
  export PATH=$PATH_BAK
'
# Expected output contains: [error] 'node' not found in PATH
```

- [ ] **Step 6: Dry-run on a machine with node + python3 (no live services)**

```bash
# First run — should install deps then attempt to start services
bash scripts/start-anchor.sh
# Expected lines (in order):
# [deps]   Installing mcp Node dependencies...   ← only if mcp/node_modules missing
# [deps]   Creating Python venv at loom/.venv ... ← only if venv missing
# [deps]   Installing Python dependencies ...     ← only on first run
# [anchor] Starting Anchor service ...
# [brain]  Starting Loom Brain ...
# Done. Anchor :3000 | Loom Brain :3002
```

- [ ] **Step 7: Verify second run is fast (all skips)**

```bash
bash scripts/start-anchor.sh
# Expected (all skips, no pip/npm output):
# [anchor] Already running on http://localhost:3000
# [brain]  Already running on http://localhost:3002
# Done. Anchor :3000 | Loom Brain :3002
```

- [ ] **Step 8: Verify sentinel re-triggers on requirements.txt change**

```bash
# Simulate a requirements.txt update
touch loom/requirements.txt
bash scripts/start-anchor.sh
# Expected: "[deps]   Installing Python dependencies..." appears again
```

- [ ] **Step 9: Commit**

```bash
git add scripts/start-anchor.sh
git commit -m "feat: enhance start-anchor.sh for Linux headless — venv, deps, prereq checks"
```
