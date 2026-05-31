# Hands — File Convention & Adapter Guide

Each hand (`market`, `sentiment`, `target`, `position`) has its own directory here.
The files inside carry user preferences and fresh context into analysis, regardless
of which adapter path runs the hand agent.

---

## Directory layout

```
hands/<hand_id>/
├── personal/
│   ├── profile.md          User's research style, time horizon, risk preference
│   ├── themes.md           Themes the user is actively tracking
│   ├── watchlist.md        Tickers and why they matter
│   ├── sources.md          KOLs, media, custom RSS the user trusts
│   └── learned-notes.md    Accumulated prose feedback (append-only, newest at bottom)
├── context/
│   └── regime-snapshot.md  Written by connectors; read only if < 24h old
├── wiki/                   Structured hand memory (existing)
│   └── *.md
│
│   ── Future stages (not yet present) ──
├── scouts/<scout_id>/      Sub-agent inbox + digest (Stage 3)
├── outbox/                 UI push queue (Stage 3)
└── team.yaml               Scout list + cadence config (Stage 3)
```

---

## Adapter architecture

Brain dispatches a `/run` request to one of four adapter paths.
All four receive the same `personal/` content — the delivery mechanism differs.

```
POST /run { hand_id, task, context, runtime? }
          │
          ├─ runtime == "sdk"              → BaseHand._assemble_prompt()
          │                                  inlines SKILL.md + personal/ + context/
          │
          ├─ runtime == "cc" / "codex"     → process × loom
          │  runtime == "herms"               claude -p / codex / herms
          │  runtime == "opencode"            stdin: envelope JSON (includes "personal" key)
          │                                   cwd: hands/<id>/   ← can Read files directly
          │
          ├─ runtime == "<id>-mounted"     → http × openai
          │                                  system_prompt includes personal block
          │                                  (set at mount time; remount to refresh)
          │
          └─ cloud Loom agent              → http × loom
                                             snapshot body includes context.__personal__
```

### How personal context reaches each path

| Path | Transport × Protocol | How personal/ arrives |
|------|---------------------|----------------------|
| SDK | in-process Python | `_assemble_prompt` reads files, inlines into system prompt each call |
| cc / codex / herms / opencode | process × loom | `envelope["personal"]` in stdin JSON; CWD = `hands/<id>/` (Read tool works) |
| Mounted remote agent | http × openai | `_build_hand_system_prompt` inlines at **mount time** |
| Cloud Loom agent | http × loom | `context.__personal__` forwarded by `_build_snapshot` |

---

## Adapter setup steps

### SDK (default — no setup needed)

The `hand_registry.py` default is `"runtime": "sdk"` for all hands.
Call `/run` without a `runtime` field and the SDK path runs automatically.

```bash
curl -X POST http://127.0.0.1:3002/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id":"market","task":"今日大盘研判"}'
```

Personal files are read fresh on every call. Changes take effect immediately.

---

### Local CLI agent (cc / codex / herms / opencode)

These agents are pre-registered by `loom_core/agent_adapters/providers/`.
Pass `runtime` in the request, or change `hand_registry.py` to make it the default.

```bash
# One-off: specify runtime per request
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判","runtime":"cc"}'

# Permanent: edit loom/hand_registry.py
#   "market": { ..., "runtime": "cc" }
```

The agent receives:
- `envelope["personal"]` — dict of `{label: file_content}` (skill index + personal/*.md + context/)
- `envelope["hand_dir"]` — absolute path to `hands/<id>/` as CWD
- From CWD the agent can also `Read("personal/themes.md")` directly

The process×loom protocol: Brain pipes the envelope as JSON to the agent's stdin.
The agent streams NDJSON events to stdout; Brain consumes `run.artifact` events.

**Prerequisites:**
- `cc`: `claude` CLI installed and authenticated
- `codex`: `codex` CLI installed (`npm i -g @openai/codex`)
- `herms`: `herms` binary on PATH
- `opencode`: `opencode` CLI installed

---

### Remote HTTP agent (http × openai)

Any OpenAI-compatible chat completion endpoint can be mounted as a hand agent.
The system prompt is built once at mount time and includes the current personal/ content.

**Step 1 — Mount the agent:**

```bash
curl -X POST http://127.0.0.1:3002/hand/mount \
  -H "Content-Type: application/json" \
  -d '{
    "hand_id":    "market",
    "endpoint":   "https://api.openai.com/v1/chat/completions",
    "auth_token": "sk-...",
    "description": "GPT-4o market analyst",
    "timeout_s":  90
  }'
```

The mount is persisted to `loom/mounts.json` and survives Brain restarts.

**Step 2 — Run:**

```bash
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判"}'
# Automatically uses the mounted agent (market-mounted takes priority over sdk)
```

**Refreshing personal context after file edits:**

The system prompt is baked at mount time. After editing `personal/*.md`, remount:

```bash
# Unmount
curl -X DELETE http://127.0.0.1:3002/hand/market/mount

# Remount (Brain re-reads personal/ and rebuilds the system prompt)
curl -X POST http://127.0.0.1:3002/hand/mount -d '{ ... same params ... }'
```

**What the remote agent receives:**

The request body follows the OpenAI ChatCompletion format:
```json
{
  "messages": [
    {
      "role": "user",
      "content": "<system_prompt_with_personal_block>\n\n{\"task\":\"...\",\"hand_id\":\"market\",\"context\":{}}"
    }
  ],
  "stream": false
}
```

The agent must respond with content containing exactly one NDJSON line:
```json
{"type":"run.artifact","artifact":{"metadata":{"resources_used":[...],"key_claims":[...],"gaps":[...]},"narrative":"..."}}
```

Optionally, prepend `{"type":"wiki.write","path":"file.md","content":"..."}` lines to
write back to `hands/<id>/wiki/`.

---

### Cloud Loom agent (http × loom)

A cloud agent that speaks the Loom NDJSON event protocol. Registered via
`loom_core/agent_adapters/cloud_bootstrap.py` (reads `hands/<id>/cloud.json`).

**`hands/<id>/cloud.json` format:**

```json
{
  "endpoint": "https://your-cloud-agent/run",
  "auth_token": "...",
  "timeout_s": 120,
  "include_wiki_snapshot": true,
  "prefetch_resources": ["fred", "reuters-rss"]
}
```

The agent receives a full snapshot POST:
```json
{
  "task": "...",
  "hand_id": "market",
  "context": {
    "__personal__": {
      "skill_index": "...",
      "personal/themes.md": "...",
      "personal/watchlist.md": "...",
      "personal/sources.md": "...",
      "personal/profile.md": "...",
      "personal/learned-notes.md": "...(tail)",
      "context/regime-snapshot.md": "..."
    }
  },
  "wiki_snapshot": { "analysis.md": "..." },
  "config": {},
  "feedback_recent": [],
  "resources": { "fred": {...} }
}
```

The agent streams NDJSON events back. It may emit `wiki.write` events; Brain
applies them to `hands/<id>/wiki/` automatically.

**Run:**
```bash
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判","runtime":"<cloud-adapter-id>"}'
```

---

## Personalising a hand

Edit any file under `personal/` directly. Changes take effect on the next run
(SDK and process paths read fresh each call; http×openai mounts require a remount).

| File | What to put in it |
|------|-------------------|
| `profile.md` | Research style, time horizon, risk tolerance |
| `themes.md` | Current macro / sector themes you are actively tracking |
| `watchlist.md` | Tickers + one-line reason each matters |
| `sources.md` | KOLs, media outlets, custom RSS you trust or distrust |
| `learned-notes.md` | Append-only prose feedback; see `references/loop.md` for what is worth recording |

Quick examples:

```bash
# Add a theme
cat >> hands/market/personal/themes.md << 'EOF'

### 进行中
- AI capex 持续性
- 美债期限溢价
EOF

# Add a watchlist entry
echo "| NVDA | AI 算力核心 |" >> hands/market/personal/watchlist.md

# Write a manual context snapshot (< 24h is treated as fresh)
echo "# Regime snapshot ($(date -u +%FT%TZ))" \
  > hands/market/context/regime-snapshot.md
echo "Risk-off. VIX 22, HYG breaking down, credit spreads +25bp." \
  >> hands/market/context/regime-snapshot.md
```

---

## Skill references

The investment research framework skill lives at:

```
skills/investment-research-framework/
├── SKILL.md                   Trigger conditions + reference index (~40 lines)
└── references/
    ├── regime.md              基本盘 + 大资金流向
    ├── sector-and-chains.md   板块热度 + 上下游产业链
    ├── policy.md              政策层 6 维度
    ├── loop.md                When to write a learned-note
    ├── evidence-and-sources.md  Source weighting + conflict resolution
    ├── industry-chain-map.md  Sector → chain segment map
    └── evolution-loop.md      Feedback classification framework
```

The `SKILL.md` index is inlined into every agent's context automatically.
Deeper references are opened by the agent on demand via its Read tool (process path)
or are accessible to SDK agents via `fetch_resource`.

---

## Seeding

To create all template files at once (idempotent):

```bash
python scripts/seed-hand-personal.py
```

---

## Future stages

| Stage | What gets added |
|-------|----------------|
| Stage 2 | `references/team.md`, `synthesis.md`, `push-decision.md`; SKILL.md team-aware |
| Stage 3 | `scouts/<id>/`, `outbox/`, `team.yaml` per hand |
| Stage 4 | SDK reads `scouts/*/digest.md` tail (SDK becomes a "main agent") |
| Stage 5 | Harness: scheduler drives scouts, outbox drainer → UI, `/feedback` writes notes, connector writes snapshots |
| Stage 6 | Config cleanup, `_buildCcPrompt` neutralisation |
