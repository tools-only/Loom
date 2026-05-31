# Linux Headless Support Design

**Date:** 2026-05-31  
**Scope:** Adapt Loom's startup path for headless Linux servers (no desktop, no Electron)

---

## Context

The project currently ships two startup scripts:

| Script | Platform | Coverage |
|--------|----------|----------|
| `scripts/start-anchor.bat` | Windows | Anchor (:3000) + Brain (:3002) |
| `scripts/start-anchor.sh` | Linux/Mac | Anchor (:3000) + Brain (:3002) — **exists but incomplete** |

Gaps in the existing `.sh` script:
- No prerequisite check (node / python3 / curl)
- No `mcp/node_modules` install step
- No Python venv creation
- No pip dependency install
- Brain is launched with bare `python3` instead of a venv-isolated interpreter

No systemd auto-start is in scope (out of scope by user decision).

---

## Target User Path

**First run:**
```
bash scripts/start-anchor.sh
# → installs mcp deps, creates loom/.venv, pip-installs requirements
# → starts Anchor + Brain
# → prints: Done. Anchor :3000 | Loom Brain :3002
```

**Subsequent runs:**
```
bash scripts/start-anchor.sh
# → all dep checks skip (sentinel file / node_modules present)
# → "Already running" if services up, or restarts if down
# → <1s overhead
```

---

## Changes

### 1. `scripts/start-anchor.sh` — full rewrite

Seven sequential steps, each idempotent:

**① Prerequisite check**  
Verify `node`, `python3`, `curl` exist in PATH. Exit with a clear message if any is missing.

**② mcp/node_modules**  
If `mcp/node_modules` does not exist: run `(cd mcp && npm install)`.  
Skip silently if already present.

**③ loom/.venv creation**  
If `loom/.venv` does not exist: run `python3 -m venv loom/.venv`.

**④ pip dependency install**  
Use a sentinel file `loom/.venv/.installed` to track install state.  
Install (or re-install) when:
- `loom/.venv/.installed` does not exist, OR
- `loom/requirements.txt` is newer than the sentinel  

Command: `loom/.venv/bin/pip install -r loom/requirements.txt`  
After success: `touch loom/.venv/.installed`

**⑤ Anchor service (:3000)**  
Health-check via `curl -sf http://localhost:3000/health`.  
Already running → print skip message.  
Not running → `nohup node mcp/server.cjs >> logs/anchor.log 2>&1 &`  
Env vars: `ANCHOR_USE_AUTOEXEC=1 ANCHOR_DISABLE_ENRICHMENT=1`

**⑥ Loom Brain (:3002)**  
Health-check via `curl -sf http://localhost:3002/health`.  
Already running → print skip message.  
Not running → `nohup bash -c "cd '$ROOT/loom' && '$VENV/bin/python' main.py" >> logs/brain.log 2>&1 &`  
Uses venv python (not system python3).

**⑦ Summary**  
Print: `Done. Anchor :3000 | Loom Brain :3002`  
Print: `Logs: logs/anchor.log  logs/brain.log`

### 2. `loom/requirements.txt` — no changes needed

Scan of all Python files (loom/ + loom_core/) confirms all external deps are already listed:

| Package | Used in |
|---------|---------|
| `fastapi` | brain.py, all routes |
| `uvicorn[standard]` | main.py entry point |
| `pydantic` | brain.py models |
| `anthropic` | provider_client.py (Anthropic provider) |
| `httpx` | hands/, loom_core/ |
| `apscheduler` | harness/scheduler.py |
| `openai` | provider_client.py (OpenAI-compat providers) |

`loom_core` is a local package at repo root — no pip install needed.

---

## Error handling

| Condition | Behavior |
|-----------|----------|
| `node` not in PATH | `echo "[error] 'node' not found..."` + `exit 1` |
| `python3` not in PATH | same pattern |
| `npm install` fails | `set -e` propagates exit |
| `pip install` fails | `set -e` propagates exit |
| Service fails to start | nohup backgrounded; user checks `logs/anchor.log` |

---

## Out of scope

- systemd user service (user decision)
- Electron AppImage for desktop Linux
- `scripts/start-core.bat` Linux equivalent (Windows-only hardcoded path; not part of current headless path)
- Auto-open browser (headless server — no display)
