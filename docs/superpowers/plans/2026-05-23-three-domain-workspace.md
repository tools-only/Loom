# Three-Domain Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three domain entry cards (Market/Position/Target) to the home page, a push inbox panel, and the backend scheduler+broker infrastructure that lets CC push notifications on cron or on demand.

**Architecture:** New CommonJS modules `mcp/inbox.cjs`, `mcp/push-broker.cjs`, `mcp/scheduler.cjs` are loaded by `mcp/server.cjs`. The broker appends to a flat JSON inbox and broadcasts `inbox_updated` to all webview clients. Hero cards on the home page show live unread counts and navigate to per-domain workspace files. A new right-edge Inbox panel mirrors the existing Context/Timeline pattern.

**Tech Stack:** node-cron (installed in `bridge/node_modules` to match existing pattern), vanilla JS, CommonJS modules in `mcp/`, JSON persistence in `logs/workspace/`.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `mcp/inbox.cjs` | Inbox store: load/save/append/list/markRead/counts |
| Create | `mcp/push-broker.cjs` | Routes push events → inbox or CC spawn |
| Create | `mcp/scheduler.cjs` | Cron schedule manager |
| Modify | `mcp/server.cjs` | Init 3 modules, 8 new HTTP routes, `inbox_updated` broadcast |
| Modify | `mcp/shim.cjs` | 3 new MCP tools: `anchor_inbox_push`, `anchor_inbox_list`, `anchor_schedule` |
| Modify | `bridge/webview/index.html` | Hero card grid + Inbox panel HTML |
| Modify | `bridge/webview/anchor-client.js` | Hero card click, inbox panel, `inbox_updated` WS handler |
| Modify | `bridge/webview/styles.css` | Hero card + inbox panel styles |
| Runtime | `logs/workspace/inbox.json` | Created by inbox.cjs on first write |
| Runtime | `logs/workspace/schedules.json` | Created by scheduler.cjs on first write |

---

## Task 1: Install node-cron

**Files:**
- Modify: `bridge/package.json`
- Install: `bridge/node_modules/node-cron`

- [ ] **Step 1: Install**

```bash
cd "D:/ai-native chrome/bridge" && npm install node-cron
```

Expected output: `added N packages` with no errors.

- [ ] **Step 2: Verify it loads**

```bash
node -e "require('D:/ai-native chrome/bridge/node_modules/node-cron'); console.log('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd "D:/ai-native chrome"
git add bridge/package.json bridge/package-lock.json
git commit -m "deps: add node-cron to bridge/node_modules"
```

---

## Task 2: Create inbox store (`mcp/inbox.cjs`)

**Files:**
- Create: `mcp/inbox.cjs`

- [ ] **Step 1: Create the file**

```javascript
// mcp/inbox.cjs
// Flat-file inbox store. Items persisted to logs/workspace/inbox.json.
'use strict';

const fs   = require('fs');
const path = require('path');

const ROOT      = path.join(__dirname, '..');
const INBOX_FILE = path.join(ROOT, 'logs', 'workspace', 'inbox.json');

const DOMAINS = ['market', 'position', 'target'];

let _items = [];  // in-memory cache

function _save() {
  try { fs.writeFileSync(INBOX_FILE, JSON.stringify(_items, null, 2), 'utf8'); } catch {}
}

function load() {
  try {
    const raw = fs.readFileSync(INBOX_FILE, 'utf8');
    _items = JSON.parse(raw);
    if (!Array.isArray(_items)) _items = [];
  } catch { _items = []; }
}

function append(item) {
  // item: { domain, title, summary, payload?, source }
  const entry = {
    id: Date.now() + '-' + Math.random().toString(36).slice(2, 7),
    domain: item.domain,
    title: String(item.title || ''),
    summary: String(item.summary || ''),
    payload: item.payload || {},
    source: item.source || 'manual',
    read: false,
    timestamp: new Date().toISOString()
  };
  _items.unshift(entry);
  if (_items.length > 200) _items = _items.slice(0, 200);
  _save();
  return entry;
}

function markRead(id) {
  const item = _items.find(i => i.id === id);
  if (!item) return false;
  item.read = true;
  _save();
  return true;
}

function markAllRead(domain) {
  let changed = false;
  for (const item of _items) {
    if (!domain || item.domain === domain) { item.read = true; changed = true; }
  }
  if (changed) _save();
}

function list({ domain, unread } = {}) {
  let result = _items;
  if (domain) result = result.filter(i => i.domain === domain);
  if (unread)  result = result.filter(i => !i.read);
  return result;
}

function unreadCounts() {
  const counts = { market: 0, position: 0, target: 0, total: 0 };
  for (const item of _items) {
    if (!item.read && DOMAINS.includes(item.domain)) {
      counts[item.domain]++;
      counts.total++;
    }
  }
  return counts;
}

module.exports = { load, append, markRead, markAllRead, list, unreadCounts };
```

- [ ] **Step 2: Smoke-test the module**

```bash
node -e "
const inbox = require('./mcp/inbox.cjs');
inbox.load();
const item = inbox.append({ domain: 'market', title: 'Test', summary: 'smoke test', source: 'manual' });
console.log('appended:', item.id);
console.log('counts:', JSON.stringify(inbox.unreadCounts()));
inbox.markRead(item.id);
console.log('after read:', JSON.stringify(inbox.unreadCounts()));
console.log('ok');
" 2>&1
```

Expected output (ids will differ):
```
appended: 1748001234567-abc12
counts: {"market":1,"position":0,"target":0,"total":1}
after read: {"market":0,"position":0,"target":0,"total":0}
ok
```

- [ ] **Step 3: Commit**

```bash
cd "D:/ai-native chrome"
git add mcp/inbox.cjs
git commit -m "feat: add inbox store module"
```

---

## Task 3: Create push broker (`mcp/push-broker.cjs`)

**Files:**
- Create: `mcp/push-broker.cjs`

The broker receives push events from the scheduler and external HTTP calls. It writes to the inbox and optionally spawns CC for AI-generated content.

- [ ] **Step 1: Create the file**

```javascript
// mcp/push-broker.cjs
// Routes push events to the inbox and optionally spawns CC to enrich them.
'use strict';

class PushBroker {
  // opts: { inbox, pendingOps, notifyPendingChanged, broadcastBrowserMessage }
  constructor(opts) {
    this._inbox = opts.inbox;
    this._pendingOps = opts.pendingOps;
    this._notifyPendingChanged = opts.notifyPendingChanged;
    this._broadcast = opts.broadcastBrowserMessage;
  }

  // Push a notification. event shape:
  // { domain, title, summary, payload?, source, ccPrompt? }
  // If ccPrompt is provided, adds a push_analyze op that CC will process
  // and call anchor_inbox_push with the enriched result.
  push(event) {
    if (!event || !event.domain || !event.title) {
      console.error('[push-broker] invalid event:', event);
      return null;
    }
    const item = this._inbox.append({
      domain: event.domain,
      title: event.title,
      summary: event.summary || '',
      payload: event.payload || {},
      source: event.source || 'broker'
    });
    const counts = this._inbox.unreadCounts();
    this._broadcast({ type: 'inbox_updated', counts });

    if (event.ccPrompt) {
      this._pendingOps.push({
        intent: {
          op: 'push_analyze',
          target_ref: 'inbox.' + event.domain,
          instruction: event.ccPrompt,
          inbox_item_id: item.id
        },
        context_bundle: {}
      });
      this._notifyPendingChanged();
    }
    return item;
  }
}

module.exports = { PushBroker };
```

- [ ] **Step 2: Smoke-test the broker**

```bash
node -e "
const inbox = require('./mcp/inbox.cjs');
inbox.load();
const { PushBroker } = require('./mcp/push-broker.cjs');
const ops = [];
const broker = new PushBroker({
  inbox,
  pendingOps: ops,
  notifyPendingChanged: () => {},
  broadcastBrowserMessage: (m) => console.log('broadcast:', m.type, JSON.stringify(m.counts))
});
broker.push({ domain: 'market', title: '早报测试', summary: '测试', source: 'test' });
console.log('ops:', ops.length, '(should be 0, no ccPrompt)');
broker.push({ domain: 'target', title: 'Alert', summary: 'test', source: 'test', ccPrompt: 'analyze this' });
console.log('ops with ccPrompt:', ops.length, '(should be 1)');
"
```

Expected:
```
broadcast: inbox_updated {"market":1,"position":0,"target":0,"total":1}
ops: 0 (should be 0, no ccPrompt)
broadcast: inbox_updated {"market":1,"position":0,"target":1,"total":2}
ops with ccPrompt: 1 (should be 1)
```

- [ ] **Step 3: Commit**

```bash
git add mcp/push-broker.cjs
git commit -m "feat: add push broker module"
```

---

## Task 4: Create scheduler (`mcp/scheduler.cjs`)

**Files:**
- Create: `mcp/scheduler.cjs`

Loads schedule definitions from `logs/workspace/schedules.json`. Each schedule fires into the push broker.

- [ ] **Step 1: Create the file**

```javascript
// mcp/scheduler.cjs
// Cron-based push scheduler. Schedules persisted to logs/workspace/schedules.json.
'use strict';

const fs   = require('fs');
const path = require('path');

const ROOT           = path.join(__dirname, '..');
const BRIDGE_NM      = path.join(ROOT, 'bridge', 'node_modules');
const SCHEDULES_FILE = path.join(ROOT, 'logs', 'workspace', 'schedules.json');

const nodeCron = require(path.join(BRIDGE_NM, 'node-cron'));

let _broker  = null;
let _jobs    = new Map();  // id → cron task
let _specs   = [];         // schedule spec objects

function _save() {
  try { fs.writeFileSync(SCHEDULES_FILE, JSON.stringify(_specs, null, 2), 'utf8'); } catch {}
}

function _load() {
  try {
    const raw = fs.readFileSync(SCHEDULES_FILE, 'utf8');
    _specs = JSON.parse(raw);
    if (!Array.isArray(_specs)) _specs = [];
  } catch { _specs = []; }
}

function _register(spec) {
  if (!spec.enabled) return;
  if (!nodeCron.validate(spec.cron)) {
    console.warn('[scheduler] invalid cron expression for', spec.id, ':', spec.cron);
    return;
  }
  const task = nodeCron.schedule(spec.cron, () => {
    console.log('[scheduler] firing:', spec.id);
    _broker.push({
      domain:   spec.domain,
      title:    spec.title,
      summary:  spec.summary || '',
      source:   'cron',
      ccPrompt: spec.ccPrompt || undefined
    });
  }, { timezone: spec.timezone || 'Asia/Shanghai' });
  _jobs.set(spec.id, task);
}

function init(broker) {
  _broker = broker;
  _load();
  for (const spec of _specs) _register(spec);
  console.log('[scheduler] loaded', _specs.length, 'schedule(s)');
}

function add(spec) {
  // spec: { id, name, cron, domain, title, summary?, ccPrompt?, timezone?, enabled }
  if (!spec.id || !spec.cron || !spec.domain || !spec.title) {
    throw new Error('schedule requires id, cron, domain, title');
  }
  remove(spec.id);  // idempotent replace
  const entry = { ...spec, enabled: spec.enabled !== false };
  _specs.push(entry);
  _save();
  _register(entry);
  return entry;
}

function remove(id) {
  const task = _jobs.get(id);
  if (task) { task.stop(); _jobs.delete(id); }
  _specs = _specs.filter(s => s.id !== id);
  _save();
}

function list() { return _specs.slice(); }

module.exports = { init, add, remove, list };
```

- [ ] **Step 2: Verify cron validation**

```bash
node -e "
const path = require('path');
const nodeCron = require(path.join('D:/ai-native chrome/bridge/node_modules', 'node-cron'));
console.log('valid weekday 9am:', nodeCron.validate('0 9 * * 1-5'));
console.log('invalid:', nodeCron.validate('invalid'));
"
```

Expected:
```
valid weekday 9am: true
invalid: false
```

- [ ] **Step 3: Commit**

```bash
git add mcp/scheduler.cjs
git commit -m "feat: add cron scheduler module"
```

---

## Task 5: Wire modules into `mcp/server.cjs`

**Files:**
- Modify: `mcp/server.cjs`

Add requires, init calls, 8 HTTP routes, and domain page generation.

- [ ] **Step 1: Add requires at the top of server.cjs (after line 48 — the tradingCanvasRenderer require)**

Find this block in `mcp/server.cjs`:
```javascript
const tradingCanvasRenderer = require('../trading/trading-canvas-renderer.cjs');
```

Add immediately after it:
```javascript
const inbox      = require('./inbox.cjs');
const { PushBroker } = require('./push-broker.cjs');
const scheduler  = require('./scheduler.cjs');
```

- [ ] **Step 2: Declare `pushBroker` in the state variable section (around line 74)**

Find the state variable block (around line 56–79):
```javascript
let currentSession = null;
let lastUserIntentId = null;
```

Add `let pushBroker = null;` in this block (anywhere among the other `let` declarations):
```javascript
let pushBroker = null;
```

This allows the HTTP route closures (defined later in the file) to reference `pushBroker` before it is assigned at boot. The routes only execute when requests arrive — after the boot section has assigned the value.

- [ ] **Step 3: Init modules at startup (find the bootstrap/init section)**

Search for this existing comment block near the bottom of the file (around line 1830+):
```javascript
function watchHtmlFile() {
```

Just before `watchHtmlFile()`, add:
```javascript
// ── Push infrastructure init ──────────────────────────────────────────
inbox.load();
pushBroker = new PushBroker({           // assigns the let declared in the state section
  inbox,
  pendingOps,
  notifyPendingChanged,
  broadcastBrowserMessage
});
scheduler.init(pushBroker);
```

- [ ] **Step 4: Add inbox and push HTTP routes**

Find the block with `app.get('/health', ...)` (around line 490). Add these routes **before** `app.get('/health', ...)`:

```javascript
// ── Inbox routes ──────────────────────────────────────────────────────

app.get('/inbox', (req, res) => {
  const { domain, unread } = req.query;
  res.json({ ok: true, items: inbox.list({ domain, unread: unread === 'true' }) });
});

app.get('/inbox/counts', (req, res) => {
  res.json({ ok: true, counts: inbox.unreadCounts() });
});

app.post('/inbox/:id/read', (req, res) => {
  const ok = inbox.markRead(req.params.id);
  if (ok) broadcastBrowserMessage({ type: 'inbox_updated', counts: inbox.unreadCounts() });
  res.json({ ok });
});

app.post('/inbox/read-all', (req, res) => {
  inbox.markAllRead(req.body?.domain || null);
  broadcastBrowserMessage({ type: 'inbox_updated', counts: inbox.unreadCounts() });
  res.json({ ok: true });
});

app.post('/push/manual', (req, res) => {
  const event = req.body;
  if (!event || !event.domain || !event.title) {
    return res.status(400).json({ error: 'domain and title required' });
  }
  const item = pushBroker.push({ ...event, source: event.source || 'manual' });
  res.json({ ok: true, item });
});

// ── Schedule routes ───────────────────────────────────────────────────

app.get('/schedules', (req, res) => {
  res.json({ ok: true, schedules: scheduler.list() });
});

app.post('/schedules', (req, res) => {
  try {
    const spec = scheduler.add(req.body || {});
    res.json({ ok: true, spec });
  } catch (e) {
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.delete('/schedules/:id', (req, res) => {
  scheduler.remove(req.params.id);
  res.json({ ok: true });
});

// ── Domain workspace page ─────────────────────────────────────────────

const DOMAIN_META = {
  market:   { icon: '📊', label: '市场情报',   color: 'aurora'  },
  position: { icon: '💼', label: '仓位管理',   color: 'cool'    },
  target:   { icon: '🎯', label: '标的跟踪',   color: 'warm'    }
};

function buildDomainStubHtml(domain) {
  const meta  = DOMAIN_META[domain] || { icon: '📄', label: domain, color: 'arctic' };
  const items = inbox.list({ domain });
  const itemsHtml = items.length === 0
    ? `<p style="color:var(--fg-3);text-align:center;padding:40px 0;">暂无推送内容 · 等待 Agent 推送或手动触发</p>`
    : items.map(item => `
      <div class="anc-section anc-section--gc" data-anc="inbox-item.${item.id}" data-handles="refine,annotate" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div>
            <strong>${item.title}</strong>
            <p style="margin:6px 0 0;color:var(--fg-2);font-size:14px;">${item.summary}</p>
          </div>
          <span style="font-size:12px;color:var(--fg-3);white-space:nowrap;">${new Date(item.timestamp).toLocaleString('zh-CN')}</span>
        </div>
      </div>`).join('\n');

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>${meta.label}</title></head>
<body>
<section class="anc-section anc-section--gc anc-section--${meta.color}" data-anc="${domain}.header" data-handles="refine,restructure">
  <h2>${meta.icon} ${meta.label}</h2>
  <p>来自 <strong>${items.length}</strong> 条推送 · 点击任意条目进行 AI 精炼</p>
</section>
<section class="anc-section anc-section--gc" data-anc="${domain}.feed" data-handles="refine,restructure">
  <h3>推送流</h3>
  ${itemsHtml}
</section>
</body>
</html>`;
}

app.get('/workspace/domain/:domain', (req, res) => {
  const domain = req.params.domain;
  if (!DOMAIN_META[domain]) return res.status(400).json({ error: 'unknown domain' });
  const ws = ensureWorkspace();
  const meta = DOMAIN_META[domain];

  // Find existing domain-pinned file
  let file = Object.values(ws.files).find(f => f.domain === domain);
  const html = buildDomainStubHtml(domain);

  if (!file) {
    // Create it
    const id = 'domain-' + domain + '-' + Date.now();
    const ts = new Date().toISOString();
    const node = { id, name: meta.label, type: 'file', domain, created_at: ts, updated_at: ts };
    file = { id, title: meta.label, domain, html, history: [], context: {}, prompt: '', created_at: ts, updated_at: ts };
    ws.nodes.unshift(node);
    ws.files[id] = file;
  } else {
    // Refresh the stub HTML with current inbox items
    file.html = html;
    file.updated_at = new Date().toISOString();
  }

  ws.current_file_id = file.id;
  currentHtml = html;
  try { fs.writeFileSync(CURRENT_HTML, html, 'utf8'); } catch {}
  saveWorkspace(ws);
  broadcastBrowserMessage({ type: 'workspace_current', file });
  broadcast(html);
  res.json({ ok: true, fileId: file.id });
});
```

- [ ] **Step 5: Restart the server and run smoke tests**

```bash
# Stop any running server first (Ctrl+C or via task manager), then:
scripts\start-anchor.bat
```

Wait 3 seconds, then:

```bash
# Test inbox endpoint
curl -s http://localhost:3000/inbox | node -e "const d=require('fs').readFileSync(0,'utf8');console.log(JSON.parse(d).ok)"
# Expected: true

# Test manual push
curl -s -X POST http://localhost:3000/push/manual \
  -H "Content-Type: application/json" \
  -d "{\"domain\":\"market\",\"title\":\"Test Push\",\"summary\":\"Server wired correctly\",\"source\":\"smoke\"}" | \
  node -e "const d=require('fs').readFileSync(0,'utf8');const r=JSON.parse(d);console.log(r.ok, r.item?.id)"
# Expected: true <some-id>

# Test inbox counts
curl -s http://localhost:3000/inbox/counts
# Expected: {"ok":true,"counts":{"market":1,"position":0,"target":0,"total":1}}

# Test schedules
curl -s http://localhost:3000/schedules | node -e "const d=require('fs').readFileSync(0,'utf8');console.log(JSON.parse(d).ok)"
# Expected: true

# Test domain page
curl -s http://localhost:3000/workspace/domain/market | node -e "const d=require('fs').readFileSync(0,'utf8');const r=JSON.parse(d);console.log(r.ok, r.fileId)"
# Expected: true domain-market-<timestamp>
```

- [ ] **Step 6: Commit**

```bash
git add mcp/server.cjs
git commit -m "feat: wire inbox, push broker, scheduler into server; add HTTP routes"
```

---

## Task 6: Add MCP tools to `mcp/shim.cjs`

**Files:**
- Modify: `mcp/shim.cjs`

Three new tools: `anchor_inbox_push` (CC pushes to inbox), `anchor_inbox_list` (CC reads inbox), `anchor_schedule` (CC registers a cron schedule).

- [ ] **Step 1: Add tool definitions to the TOOLS array**

Find in `mcp/shim.cjs`:
```javascript
  {
    name: 'anchor_patch',
```

Add these three definitions **before** `anchor_patch`:

```javascript
  {
    name: 'anchor_inbox_push',
    description: 'Push a notification to the user inbox and update hero card badges. Use this when you want to proactively surface a finding, alert, or insight to the user without waiting for them to ask.',
    inputSchema: {
      type: 'object',
      properties: {
        domain:  { type: 'string', enum: ['market', 'position', 'target'], description: 'Which domain inbox to add to' },
        title:   { type: 'string', description: 'Short notification title (max ~60 chars)' },
        summary: { type: 'string', description: 'One-sentence summary shown in the inbox list' },
        payload: { type: 'object',  description: 'Optional structured data attached to the notification' }
      },
      required: ['domain', 'title', 'summary']
    }
  },
  {
    name: 'anchor_inbox_list',
    description: 'Read items from the user inbox, optionally filtered by domain or unread status.',
    inputSchema: {
      type: 'object',
      properties: {
        domain: { type: 'string', enum: ['market', 'position', 'target'] },
        unread: { type: 'boolean', description: 'If true, return only unread items' }
      }
    }
  },
  {
    name: 'anchor_schedule',
    description: 'Register a recurring cron-based push schedule. The schedule fires into the push broker at the given cron expression and creates an inbox notification. Set enabled:false to pause a schedule without deleting it.',
    inputSchema: {
      type: 'object',
      properties: {
        id:       { type: 'string', description: 'Stable identifier, e.g. "market-morning-brief"' },
        name:     { type: 'string', description: 'Human-readable schedule name' },
        cron:     { type: 'string', description: 'Cron expression, e.g. "0 9 * * 1-5" for weekdays at 9am' },
        domain:   { type: 'string', enum: ['market', 'position', 'target'] },
        title:    { type: 'string', description: 'Notification title when the schedule fires' },
        summary:  { type: 'string', description: 'Notification summary when the schedule fires' },
        ccPrompt: { type: 'string', description: 'Optional: if set, spawns CC with this prompt to enrich the notification' },
        timezone: { type: 'string', description: 'Timezone string, default Asia/Shanghai' },
        enabled:  { type: 'boolean', description: 'Whether the schedule is active (default true)' }
      },
      required: ['id', 'cron', 'domain', 'title']
    }
  },
```

- [ ] **Step 2: Add tool handlers in the `callTool` switch block**

Find in `mcp/shim.cjs`:
```javascript
      // ── anchor_patch ─────────────────────────────────────────────────
      case 'anchor_patch': {
```

Add these three cases **before** `anchor_patch`:

```javascript
      // ── anchor_inbox_push ─────────────────────────────────────────────
      case 'anchor_inbox_push': {
        const r = await post('/push/manual', {
          domain:  args.domain,
          title:   args.title,
          summary: args.summary,
          payload: args.payload || {},
          source:  'agent'
        }, 8000);
        const parsed = typeof r.body === 'string' ? JSON.parse(r.body) : r.body;
        rpcResult(id, parsed.ok
          ? `Pushed to ${args.domain} inbox: "${args.title}" (id: ${parsed.item?.id})`
          : `Error: ${parsed.error}`);
        break;
      }

      // ── anchor_inbox_list ─────────────────────────────────────────────
      case 'anchor_inbox_list': {
        const qs = new URLSearchParams();
        if (args.domain) qs.set('domain', args.domain);
        if (args.unread) qs.set('unread', 'true');
        const r = await get(`/inbox?${qs}`, 5000);
        rpcResult(id, r.body);
        break;
      }

      // ── anchor_schedule ───────────────────────────────────────────────
      case 'anchor_schedule': {
        const r = await post('/schedules', args, 5000);
        const parsed = typeof r.body === 'string' ? JSON.parse(r.body) : r.body;
        rpcResult(id, parsed.ok
          ? `Schedule "${args.id}" registered (${args.cron})`
          : `Error: ${parsed.error}`);
        break;
      }

```

- [ ] **Step 3: Verify tools/list includes new tools**

Restart the Anchor server, then test via CLI:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | node mcp/shim.cjs 2>/dev/null | node -e "const d=require('fs').readFileSync(0,'utf8');const r=JSON.parse(d);console.log(r.result.tools.map(t=>t.name).join(', '))"
```

Expected output (all 11 tools):
```
anchor_render, anchor_await_op, anchor_listen, anchor_get_pending_op, anchor_get_html, anchor_emit_event, anchor_replay_session, anchor_inbox_push, anchor_inbox_list, anchor_schedule, anchor_patch
```

- [ ] **Step 4: Commit**

```bash
git add mcp/shim.cjs
git commit -m "feat: add anchor_inbox_push, anchor_inbox_list, anchor_schedule MCP tools"
```

---

## Task 7: Add hero cards to `bridge/webview/index.html`

**Files:**
- Modify: `bridge/webview/index.html`

Replace `.home-suggestions` buttons with a 3-card hero grid. Add the Inbox trigger + panel alongside Context/Timeline.

- [ ] **Step 1: Replace suggestion buttons with hero card grid**

In `bridge/webview/index.html`, find and replace the entire `.home-suggestions` div:

Old:
```html
    <div class="home-suggestions" aria-label="Prompt examples">
      <button type="button" data-prompt="Create a concise market brief canvas with thesis, risks, catalysts, and watchlist sections.">Market brief</button>
      <button type="button" data-prompt="Create a private trading analysis canvas for one ticker with intent, raw reasoning, claims, bull and bear tracking threads, reactions, position outcome, and postmortem sections.">Trading canvas</button>
      <button type="button" data-prompt="Create a research dashboard with summary, key metrics, evidence cards, open questions, and next actions.">Research dashboard</button>
    </div>
```

New:
```html
    <div class="home-domain-grid" aria-label="Domain entries">
      <button class="home-domain-card" type="button" data-domain="market">
        <span class="domain-card-icon">📊</span>
        <span class="domain-card-badge" id="badge-market" hidden>0</span>
        <span class="domain-card-title">市场情报</span>
        <span class="domain-card-meta" id="meta-market">Market Intelligence</span>
      </button>
      <button class="home-domain-card" type="button" data-domain="position">
        <span class="domain-card-icon">💼</span>
        <span class="domain-card-badge" id="badge-position" hidden>0</span>
        <span class="domain-card-title">仓位管理</span>
        <span class="domain-card-meta" id="meta-position">Position Management</span>
      </button>
      <button class="home-domain-card" type="button" data-domain="target">
        <span class="domain-card-icon">🎯</span>
        <span class="domain-card-badge" id="badge-target" hidden>0</span>
        <span class="domain-card-title">标的跟踪</span>
        <span class="domain-card-meta" id="meta-target">Target Tracking</span>
      </button>
    </div>
```

- [ ] **Step 2: Add Inbox trigger button (after `#trigger-timeline`)**

Find:
```html
<div class="anc-panel-trigger" id="trigger-timeline" title="Timeline">
  <i class="ph-bold ph-pulse"></i><span>Timeline</span>
</div>
```

Add immediately after:
```html
<div class="anc-panel-trigger" id="trigger-inbox" title="Inbox">
  <i class="ph-bold ph-tray"></i><span>Inbox</span>
  <span class="inbox-trigger-badge" id="inbox-trigger-badge" hidden>0</span>
</div>
```

- [ ] **Step 3: Add Inbox panel (after `#anchor-timeline-panel`)**

Find:
```html
<!-- Agent process timeline (floating overlay, right side) -->
<aside id="anchor-timeline-panel" class="anc-side-panel collapsed">
```

Add this entire block immediately before it (so inbox panel is between timeline and context — ordering doesn't matter for stacking, just placement):

Actually add it **after** the closing `</aside>` of `anchor-timeline-panel`. Find:
```html
</aside>

<div id="anchor-shell">
```

Insert between the `</aside>` and `<div id="anchor-shell">`:

```html
<!-- Inbox panel (floating overlay, right side) -->
<aside id="anchor-inbox-panel" class="anc-side-panel collapsed">
  <div class="side-panel-header">
    <span class="side-panel-title">Inbox</span>
    <button class="inbox-read-all btn btn--sm btn--ghost" type="button">全部已读</button>
    <button class="side-panel-toggle" data-target="anchor-inbox-panel">×</button>
  </div>
  <div class="side-panel-body">
    <div id="inbox-domain-tabs" class="inbox-tabs">
      <button class="inbox-tab active" data-domain="">全部</button>
      <button class="inbox-tab" data-domain="market">市场 <span class="inbox-tab-badge" id="itab-market"></span></button>
      <button class="inbox-tab" data-domain="position">仓位 <span class="inbox-tab-badge" id="itab-position"></span></button>
      <button class="inbox-tab" data-domain="target">标的 <span class="inbox-tab-badge" id="itab-target"></span></button>
    </div>
    <div id="inbox-list" class="inbox-list"></div>
  </div>
</aside>
```

- [ ] **Step 4: Verify HTML is valid**

Open `http://localhost:3000` in a browser. The home page should show three cards instead of the text suggestion buttons. The right edge should now have three panel triggers: Context / Timeline / Inbox (top to bottom).

- [ ] **Step 5: Commit**

```bash
git add bridge/webview/index.html
git commit -m "feat: add domain hero cards and inbox panel HTML"
```

---

## Task 8: Add styles to `bridge/webview/styles.css`

**Files:**
- Modify: `bridge/webview/styles.css`

Add hero card grid styles and inbox panel styles. Add at the end of the file (before the closing media queries section or at the very end).

- [ ] **Step 1: Add hero card styles**

Find the very end of `bridge/webview/styles.css` (after all existing rules). Append:

```css

/* ── Domain hero cards ───────────────────────────────────────────────── */
.home-domain-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 24px;
  width: 100%;
}

.home-domain-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 22px 16px 18px;
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(20,21,43,0.09);
  border-radius: 20px;
  cursor: pointer;
  text-align: center;
  transition: transform 0.18s var(--ease-out), box-shadow 0.18s var(--ease-out), background 0.18s;
  box-shadow: 0 2px 12px -8px rgba(20,21,43,0.18);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.home-domain-card:hover {
  transform: translateY(-3px);
  background: rgba(255,255,255,0.88);
  box-shadow: 0 14px 36px -16px rgba(20,21,43,0.28);
}

.home-domain-card:active {
  transform: scale(0.97);
}

.domain-card-icon {
  font-size: 28px;
  line-height: 1;
}

.domain-card-badge {
  position: absolute;
  top: 10px;
  right: 12px;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  background: #f43f5e;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.domain-card-title {
  font-family: var(--font-display-cjk);
  font-weight: 700;
  font-size: 15px;
  color: var(--ink);
}

.domain-card-meta {
  font-size: 12px;
  color: var(--fg-3);
  line-height: 1.3;
}

@media (max-width: 600px) {
  .home-domain-grid { grid-template-columns: 1fr; gap: 10px; }
  .home-domain-card { flex-direction: row; text-align: left; padding: 14px 16px; }
  .domain-card-icon { font-size: 22px; }
}

/* ── Inbox panel trigger ─────────────────────────────────────────────── */
#trigger-inbox {
  top: 310px;
  padding: 14px 10px;
  background:
    linear-gradient(180deg, rgba(244,63,94,0.12), rgba(249,168,37,0.07)),
    rgba(255,255,255,0.74);
  border: 1px solid rgba(220,38,38,0.12);
}
#trigger-inbox:hover { background: rgba(255,255,255,0.88); }

.inbox-trigger-badge {
  position: absolute;
  top: 6px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background: #f43f5e;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Inbox panel body ────────────────────────────────────────────────── */
.inbox-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border-subtle, rgba(20,21,43,0.08));
  flex-shrink: 0;
}

.inbox-tab {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--fg-2);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.12s;
}

.inbox-tab.active {
  background: rgba(122,90,248,0.10);
  border-color: rgba(122,90,248,0.20);
  color: var(--accent-iris, #7A5AF8);
}

.inbox-tab-badge {
  font-size: 10px;
  font-weight: 700;
  color: #f43f5e;
}

.inbox-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.inbox-item {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(20,21,43,0.05);
  cursor: pointer;
  transition: background 0.12s;
}

.inbox-item:hover { background: rgba(122,90,248,0.04); }

.inbox-item.is-read { opacity: 0.55; }

.inbox-item-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
}

.inbox-item-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--ink);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inbox-item-time {
  font-size: 11px;
  color: var(--fg-3);
  white-space: nowrap;
  flex-shrink: 0;
}

.inbox-item-summary {
  font-size: 12px;
  color: var(--fg-2);
  margin-top: 3px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.inbox-item-domain {
  display: inline-block;
  margin-top: 4px;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.inbox-item-domain--market   { background: rgba(61,211,245,0.14); color: #1a7a9a; }
.inbox-item-domain--position { background: rgba(43,182,115,0.14); color: #1a6b3a; }
.inbox-item-domain--target   { background: rgba(255,91,164,0.14); color: #a0175a; }

.inbox-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--fg-3);
  font-size: 14px;
}

.inbox-read-all {
  margin-left: auto;
  font-size: 11px;
  padding: 3px 8px;
}
```

- [ ] **Step 2: Verify styles render correctly**

Open `http://localhost:3000`, check:
1. Three cards in a row on the home page with icons, titles, and subtitle text
2. Right edge has Inbox (🗂) trigger at ~310px from top
3. Cards have hover lift animation

- [ ] **Step 3: Commit**

```bash
git add bridge/webview/styles.css
git commit -m "feat: add hero card and inbox panel styles"
```

---

## Task 9: Wire hero cards and inbox panel in `anchor-client.js`

**Files:**
- Modify: `bridge/webview/anchor-client.js`

Add: `inbox_updated` WS handler, hero card click, inbox panel (load items, tab filter, mark read), initial badge fetch.

- [ ] **Step 1: Add `inbox_updated` to the WS message dispatcher**

Find in `anchor-client.js` (around the `switch` statement in the WS message handler):
```javascript
      case 'shutdown':
        this.shuttingDown = true;
        this.setStatus('', msg.message || 'Shutting down...');
        this.toast(msg.message || 'Anchor service shutting down');
        break;
      case 'pong':
        break;
    }
```

Add `inbox_updated` case **before** `case 'shutdown':`:
```javascript
      case 'inbox_updated':
        this._applyInboxCounts(msg.counts);
        if (window.InboxPanel && InboxPanel.isOpen()) InboxPanel.reload();
        break;
```

- [ ] **Step 2: Add `_applyInboxCounts` method**

Find in `anchor-client.js` the `_handleAgentEvent` method. Add a new method directly after it:

```javascript
  _applyInboxCounts(counts) {
    var domains = ['market', 'position', 'target'];
    var total = 0;
    for (var i = 0; i < domains.length; i++) {
      var d = domains[i];
      var n = (counts && counts[d]) || 0;
      total += n;
      var badge = document.getElementById('badge-' + d);
      if (badge) {
        badge.textContent = n;
        badge.hidden = n === 0;
      }
      var tbadge = document.getElementById('itab-' + d);
      if (tbadge) tbadge.textContent = n > 0 ? n : '';
    }
    var trigBadge = document.getElementById('inbox-trigger-badge');
    if (trigBadge) {
      trigBadge.textContent = total;
      trigBadge.hidden = total === 0;
    }
  },
```

- [ ] **Step 3: Add hero card click handler**

Find where existing suggestion buttons are wired. Look for `_initPromptBar` in `anchor-client.js` (around line 62). Add a new method `_initDomainCards` and call it from `init()`.

Find in the `init()` method:
```javascript
    this._initPromptBar();
```

Add after it:
```javascript
    this._initDomainCards();
    this._fetchInboxCounts();
```

Then add the new methods (add near `_initPromptBar`):

```javascript
  _initDomainCards() {
    var self = this;
    var cards = document.querySelectorAll('.home-domain-card[data-domain]');
    cards.forEach(function(card) {
      card.addEventListener('click', function() {
        self._openDomain(card.dataset.domain);
      });
    });
  },

  _openDomain(domain) {
    fetch('/workspace/domain/' + domain)
      .then(function(r) { return r.json(); })
      .catch(function() { return { ok: false }; })
      .then(function(data) {
        if (!data.ok) {
          console.warn('[domain] failed to open', domain);
        }
        // Server already broadcasts html + workspace_current; client will receive them via WS
      });
  },

  _fetchInboxCounts() {
    var self = this;
    fetch('/inbox/counts')
      .then(function(r) { return r.json(); })
      .then(function(data) { if (data.ok) self._applyInboxCounts(data.counts); })
      .catch(function() {});
  },
```

- [ ] **Step 4: Add the InboxPanel module**

At the very end of `anchor-client.js` (after `window.TimelinePanel = TimelinePanel;`), append:

```javascript
// ── Inbox Panel ─────────────────────────────────────────────────────────

var InboxPanel = {
  _open: false,
  _currentDomain: '',
  _el: null,
  _list: null,

  init() {
    this._el = document.getElementById('anchor-inbox-panel');
    this._list = document.getElementById('inbox-list');
    if (!this._el) return;

    var trigger = document.getElementById('trigger-inbox');
    if (trigger) {
      trigger.addEventListener('click', function() { InboxPanel.toggle(); });
    }

    var closeBtn = this._el.querySelector('.side-panel-toggle');
    if (closeBtn) closeBtn.addEventListener('click', function() { InboxPanel.close(); });

    var readAllBtn = this._el.querySelector('.inbox-read-all');
    if (readAllBtn) readAllBtn.addEventListener('click', function() {
      fetch('/inbox/read-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: InboxPanel._currentDomain || null })
      }).then(function() { InboxPanel.reload(); });
    });

    var tabs = this._el.querySelectorAll('.inbox-tab');
    tabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        tabs.forEach(function(t) { t.classList.remove('active'); });
        tab.classList.add('active');
        InboxPanel._currentDomain = tab.dataset.domain || '';
        InboxPanel.reload();
      });
    });
  },

  isOpen() { return this._open; },

  toggle() {
    if (this._open) this.close(); else this.open();
  },

  open() {
    if (!this._el) return;
    this._open = true;
    this._el.classList.remove('collapsed');
    this.reload();
  },

  close() {
    if (!this._el) return;
    this._open = false;
    this._el.classList.add('collapsed');
  },

  reload() {
    if (!this._list) return;
    var domain = this._currentDomain;
    var url = '/inbox' + (domain ? '?domain=' + domain : '');
    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(data) { InboxPanel._render(data.items || []); })
      .catch(function() { InboxPanel._list.innerHTML = '<div class="inbox-empty">加载失败</div>'; });
  },

  _render(items) {
    if (!this._list) return;
    if (items.length === 0) {
      this._list.innerHTML = '<div class="inbox-empty">暂无推送内容</div>';
      return;
    }
    var domainLabel = { market: '市场', position: '仓位', target: '标的' };
    this._list.innerHTML = items.map(function(item) {
      var dt = new Date(item.timestamp);
      var timeStr = dt.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      return '<div class="inbox-item' + (item.read ? ' is-read' : '') + '" data-id="' + item.id + '" data-domain="' + item.domain + '">' +
        '<div class="inbox-item-header">' +
          '<span class="inbox-item-title">' + _escHtml(item.title) + '</span>' +
          '<span class="inbox-item-time">' + timeStr + '</span>' +
        '</div>' +
        '<div class="inbox-item-summary">' + _escHtml(item.summary) + '</div>' +
        '<span class="inbox-item-domain inbox-item-domain--' + item.domain + '">' + (domainLabel[item.domain] || item.domain) + '</span>' +
      '</div>';
    }).join('');

    this._list.querySelectorAll('.inbox-item').forEach(function(el) {
      el.addEventListener('click', function() {
        var id = el.dataset.id;
        var domain = el.dataset.domain;
        fetch('/inbox/' + id + '/read', { method: 'POST' }).catch(function() {});
        el.classList.add('is-read');
        // Navigate to the domain page
        fetch('/workspace/domain/' + domain)
          .then(function(r) { return r.json(); })
          .catch(function() { return {}; });
        InboxPanel.close();
      });
    });
  }
};

function _escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.InboxPanel = InboxPanel;
document.addEventListener('DOMContentLoaded', function() { InboxPanel.init(); });
```

- [ ] **Step 5: Verify full flow**

1. Open `http://localhost:3000`
2. Home should show 3 domain cards. All badges hidden (no unread items yet).
3. Push a test notification via curl:
   ```bash
   curl -s -X POST http://localhost:3000/push/manual \
     -H "Content-Type: application/json" \
     -d "{\"domain\":\"market\",\"title\":\"测试推送\",\"summary\":\"Badge should appear\",\"source\":\"smoke\"}"
   ```
4. Without refreshing the page: the Market card should show a red "1" badge, and the Inbox trigger should show "1".
5. Click the Inbox trigger (🗂) — panel slides in showing the notification.
6. Click the notification — it marks as read, navigates to the market domain page, panel closes.
7. Click the Market card directly — domain page loads with the notification rendered.
8. Home card badge should now be 0.

- [ ] **Step 6: Commit**

```bash
git add bridge/webview/anchor-client.js
git commit -m "feat: wire hero cards, inbox panel, and inbox_updated WS handler"
```

---

## Task 10: Register a demo cron schedule via CC

This demonstrates the AI-native push capability end-to-end.

- [ ] **Step 1: Add a test schedule via curl**

```bash
curl -s -X POST http://localhost:3000/schedules \
  -H "Content-Type: application/json" \
  -d "{
    \"id\": \"market-test-every-minute\",
    \"name\": \"市场测试(每分钟)\",
    \"cron\": \"* * * * *\",
    \"domain\": \"market\",
    \"title\": \"定时推送测试\",
    \"summary\": \"Cron fired successfully\",
    \"timezone\": \"Asia/Shanghai\",
    \"enabled\": true
  }"
```

Expected: `{"ok":true,"spec":{...}}`

- [ ] **Step 2: Wait ~65 seconds, then check inbox**

```bash
curl -s http://localhost:3000/inbox/counts
# Expected: market count increases by 1 per minute
```

Also verify the badge appears in the browser without refresh.

- [ ] **Step 3: Remove the test schedule**

```bash
curl -s -X DELETE http://localhost:3000/schedules/market-test-every-minute
# Expected: {"ok":true}
```

- [ ] **Step 4: Test anchor_inbox_push MCP tool via CC**

In a Claude Code session connected to Anchor, call:
```
anchor_inbox_push(domain="target", title="AI 主动发现", summary="通过分析检测到异常，请注意")
```

Verify: badge appears on Target card and notification shows in Inbox panel.

- [ ] **Step 5: Final commit and status check**

```bash
cd "D:/ai-native chrome"
git status  # Should be clean
git log --oneline -8
```

---

## Verification Checklist

| Check | How |
|-------|-----|
| Hero cards show on home | Open `http://localhost:3000`, no canvas open |
| Badges update live | `POST /push/manual` → badge appears without refresh |
| Inbox panel opens/closes | Click 🗂 trigger |
| Tab filter works | Switch between 全部/市场/仓位/标的 in panel |
| Click notification → domain page | Inbox item click navigates |
| Click hero card → domain page | Direct card click works |
| Domain page shows inbox items | Fresh content on each open |
| Cron schedule fires | `/schedules` endpoint + wait |
| CC can push via MCP tool | `anchor_inbox_push` tool call |
| CC can register schedule | `anchor_schedule` tool call |
| No console errors | Browser dev tools console |

---

## What This Plan Does NOT Cover (follow-up)

- Full Mode A canvas (market briefings with real data sources — Alpha Vantage, 金十/财联社)
- Full Mode B canvas (position registry UI — requires `docs/trading-workspace-design.md` Mode B implementation)
- Full Mode C canvas (target tracking + divergence engine — requires Mode C implementation)
- External webhook/SSE connectors (add as `mcp/connectors/<source>.cjs` using the `push-broker.push()` interface)
- Push notification preferences / subscription management UI
