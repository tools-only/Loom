# Loom — AI-Native Workspace
[[Demo]](https://tools-only.github.io/Loom/demo.html) **Think it. Live it.** 

Loom is an AI-native desktop workspace where HTML is the shared language between user and AI. Describe anything — dashboards, reports, prototypes — and watch it take shape. Click any element to refine, expand, or branch.

An AI-generated market research report rendered with the Bloom Design System. Hover over any section or KPI card to see available AI operations. No agent connection — pure interactive preview.

## Architecture

```
Browser ──op/envelope──► Anchor Service (daemon, port 3000)
                               │ push via /ws/agent WebSocket
                               ▼
                          MCP Shim ──stdio JSON-RPC──► Claude Code
                               ▲
                          anchor_patch / anchor_render
```

- **`mcp/server.cjs`** — persistent HTTP + WebSocket daemon
- **`mcp/shim.cjs`** — thin stdio bridge; MCP tools for Claude Code
- **`bridge/webview/`** — frontend (Bloom Design System, vanilla JS)
- **`electron/`** — desktop wrapper (Electron + system tray)

## Quick Start

### Windows

```bat
REM Start services (first run installs deps automatically)
scripts\start-anchor.bat
REM → opens http://localhost:3000 in your browser

REM Run as desktop app (Electron)
npm start

REM Build installer
npm run build
```

### Linux (headless server)

**Prerequisites:** Node.js, Python 3, curl — installed and in PATH.

```bash
# One-time setup: creates loom/.venv and installs all dependencies
bash scripts/setup-linux.sh

# Start services (run each time)
bash scripts/start-anchor.sh
# → open http://localhost:3000 in your browser

# Stop services
bash scripts/stop-anchor.sh
```

**`setup-linux.sh`** — run once, all steps idempotent:

| Step | Action | Skipped if |
|------|--------|-----------|
| ① Prereq check | Verify `node`, `python3`, `curl` in PATH | — |
| ② Node deps | `npm install` inside `mcp/` | `mcp/node_modules` exists |
| ③ Python venv | `python3 -m venv loom/.venv` | `loom/.venv` exists |
| ④ Python deps | `pip install -r loom/requirements.txt` | `requirements.txt` unchanged since last install |

**`start-anchor.sh`** — run each time:

| Step | Action | Skipped if |
|------|--------|-----------|
| ① Anchor | Start `mcp/server.cjs` on :3000 | Already running |
| ② Brain | Start `loom/main.py` (FastAPI) on :3002 | Already running |

Logs: `logs/anchor.log` · `logs/brain.log`

## Anchor HTML Protocol

Elements are annotated with `data-anc` and `data-handles` for AI interaction:

```html
<section class="anc-section anc-section--gc"
         data-anc="analysis.summary"
         data-handles="refine,expand,shorten,annotate">
  <h2>Summary</h2>
  <p data-anc="analysis.summary.text" data-handles="refine,edit">...</p>
</section>
```

Available ops: `refine` · `expand` · `shorten` · `edit` · `annotate` · `branch` · `restructure` · `lock`

## Bloom Design System

All UI uses CSS variables from `resource/colors_and_type.css`. Never hard-code colors — use `var(--accent-iris)`, `var(--pastel-*)`, `var(--shadow-*)`, etc.

| Component | Class |
|-----------|-------|
| Section card | `anc-section anc-section--gc` |
| KPI card | `anc-kpi anc-kpi--aurora` (7 gradient themes) |
| Status pill | `anc-pill anc-pill--active` |
| Button | `btn btn--brand` |

---

## Loom Fin — Hand Agents

> **使用手册：** [`docs/loom-fin.md`](docs/loom-fin.md)

Loom Fin connects **hand agents** — independent AI processes that handle specific trading analysis domains (market, sentiment, target, position). Each hand runs as its own agent process with a persistent wiki-style memory.

```
POST /run  →  Loom Brain (port 3001)  →  AgentAdapterRegistry
                                                  │
                              ┌───────────────────┼───────────────────┐
                              ▼                   ▼                   ▼
                        Local Subprocess    HTTP Cloud Agent    In-Process SDK
                        (claude -p, codex)  (openclaw, custom)  (legacy)
```

### Mounting a Local Hand Agent (claude / codex / openclaw)

Run hand agents as local subprocesses — the agent reads a task envelope from stdin, works in its own directory with a persistent wiki, and returns a JSON event stream.

**1. Set the runtime in `loom/hand_registry.py`:**

```python
REGISTRY = {
    "market": {
        "runtime": "cc",          # "cc" | "codex" | "openclaw" | "sdk"
        "wiki_dir": str(ROOT.parent / "hands" / "market" / "wiki"),
        ...
    }
}
```

**2. Prepare the hand workspace** (`hands/<id>/`):

```
hands/market/
  CLAUDE.md          ← agent instructions + wiki schema
  config.json        ← user settings (watched sectors, KOL feeds, etc.)
  wiki/
    index.md         ← persistent context across runs
    macro.md
```

**3. Trigger a run:**

```bash
curl -X POST http://127.0.0.1:3001/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id": "market", "task": "分析当前市场环境", "runtime": "cc"}'
```

The Brain spawns `claude -p <envelope>` in `hands/market/` as the working directory. The agent reads `wiki/`, calls `/resources` for live data, writes updated wiki pages, and outputs `{"type":"run.artifact","artifact":{...}}` on stdout. The artifact is patched into the webview at the `loom-market` anchor.

**Supported local runtimes:**

| `runtime` value | Command | Notes |
|---|---|---|
| `cc` | `claude -p` | Claude Code CLI |
| `codex` | `codex run` | OpenAI Codex CLI |
| `openclaw` | `openclaw run` | OpenClaw CLI |
| `sdk` | in-process Python | Legacy SDK path, no subprocess |

> **Full guide:** [`docs/loom-hand-agent-guide.md`](docs/loom-hand-agent-guide.md)

---

### Mounting a Cloud-Deployed Hand Agent

Run hand agents as remote HTTPS services — Loom Core sends a self-contained snapshot envelope (wiki, config, recent feedback, pre-fetched resources) and receives back a streaming NDJSON response. No tunnel or port exposure needed.

```
Brain  →  POST https://your-agent.example.com/run
               Authorization: Bearer <token>
               Body: { task, wiki_snapshot, config, feedback_recent, resources }

Agent  →  NDJSON stream:
               {"type":"wiki.write","path":"macro.md","content":"..."}  ← applied locally
               {"type":"run.artifact","artifact":{...}}                 ← patches webview
```

**1. Declare the endpoint** in `config/cloud-agents.json` (safe to commit — no secrets):

```json
{
  "openclaw-cloud": {
    "endpoint": "https://api.openclaw.ai/v1/run",
    "capabilities": ["market.analysis"],
    "timeout_s": 120,
    "token_env": "OPENCLAW_CLOUD_TOKEN",
    "require_auth": true
  }
}
```

**2. Set the token** in `.env` (gitignored):

```bash
OPENCLAW_CLOUD_TOKEN=your-token-here
```

**3. Point a hand at the cloud adapter:**

```python
# loom/hand_registry.py
"market": {
    "runtime": "openclaw-cloud",   # matches the key in cloud-agents.json
    ...
}
```

**4. (Optional) Declare resources to pre-fetch** in `hands/market/cloud.json`:

```json
{
  "include_wiki_snapshot": true,
  "prefetch_resources": ["fred", "reuters-rss"]
}
```

**5. Restart Brain and trigger a run** — the adapter is auto-registered:

```bash
curl -X POST http://127.0.0.1:3001/run \
  -d '{"hand_id":"market","task":"分析当前市场环境"}'
```

**Cloud agent NDJSON protocol** — your agent endpoint must accept the snapshot body and return a stream:

| Event type | Direction | Meaning |
|---|---|---|
| `run.artifact` | agent → Loom | **Required.** Final analysis result. |
| `wiki.write` | agent → Loom | Write a file to `hands/<id>/wiki/`. Applied locally; not forwarded to webview. |
| `feedback.signal` | agent → Loom | Append an event to the feedback log. |
| `run.error` | agent → Loom | Signal failure; Brain returns an error response. |
| `run.started` / `run.completed` | agent → Loom | Optional bookkeeping events. |

**Security notes:**
- Loom Core stays bound to `127.0.0.1` — it is never exposed to the public internet.
- Cloud agents cannot call back into `localhost`; all data is shipped in the envelope.
- Paths in `wiki.write` events containing `..` are silently rejected (path traversal guard).
- Tokens live only in `.env`; `cloud-agents.json` contains no secrets.

> **Full protocol reference:** [`docs/loom-hand-agent-guide.md`](docs/loom-hand-agent-guide.md) §10–13
