// Anchor MCP Server — JSON-RPC over stdio, zero SDK deps
// Reuses bridge/node_modules (express, ws) for webview

const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec, spawn } = require('child_process');

const ROOT = path.join(__dirname, '..');
const BRIDGE_NM = path.join(ROOT, 'bridge', 'node_modules');
const WEBVIEW_DIR = path.join(ROOT, 'bridge', 'webview');
const OUTPUT_DIR = path.join(ROOT, 'output');
const PROMPTS_DIR = path.join(ROOT, 'prompts');
const LOGS_DIR = path.join(ROOT, 'logs');
const SESSIONS_DIR = path.join(LOGS_DIR, 'sessions');
const SCHEMAS_DIR = path.join(__dirname, 'schemas');
const CURRENT_HTML = path.join(OUTPUT_DIR, 'current.html');
const PENDING_PROMPT = path.join(PROMPTS_DIR, 'pending.md');
const PENDING_OP_JSON = path.join(PROMPTS_DIR, 'pending-op.json');
const OPS_LOG = path.join(LOGS_DIR, 'ops.jsonl');
const PORT = 3000;
const AUTO_EXEC_ENABLED = process.env.ANCHOR_AUTO_EXECUTE !== '0';
const AUTO_EXEC_TIMEOUT_MS = parseInt(process.env.ANCHOR_AUTO_EXECUTE_TIMEOUT_MS) || 5 * 60 * 1000;

// Resolve from bridge's node_modules
const express = require(path.join(BRIDGE_NM, 'express'));
const wsModule = require(path.join(BRIDGE_NM, 'ws'));
const { WebSocketServer } = wsModule;

[OUTPUT_DIR, PROMPTS_DIR, LOGS_DIR, SESSIONS_DIR].forEach(d => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});

// ── State ───────────────────────────────────────────────────────────
let currentHtml = '';
const pendingOps = [];
let pendingSubscribers = new Set();  // subscription IDs for pending-op resource
const webviewClients = new Set();

// Session state (Phase 5)
let currentSession = null;       // { id, dir, manifestPath, eventsPath, startedAt, eventCount }
let lastUserIntentId = null;     // parent_event_id for subsequent agent events
let envelopeSchema = null;       // loaded JSON schema (Phase 2)

// Auto-execute (Phase 6) — leader spawns `claude -p` subprocess; follower routes calls back
let isFollower = false;
const autoExecQueue = [];
let autoExecChildRunning = false;

if (fs.existsSync(CURRENT_HTML)) {
  currentHtml = fs.readFileSync(CURRENT_HTML, 'utf8');
}

// ── HTTP + WebSocket ────────────────────────────────────────────────
const app = express();
const httpServer = http.createServer(app);
const wss = new WebSocketServer({ server: httpServer });

app.use(express.json({ limit: '10mb' }));
app.use(express.static(WEBVIEW_DIR));

app.post('/html', (req, res) => {
  const html = req.body.html || '';
  if (!html.trim()) return res.status(400).json({ error: 'empty html' });
  currentHtml = html;
  fs.writeFileSync(CURRENT_HTML, html, 'utf8');
  broadcast(html);
  log(`HTML via POST (${html.length} bytes), ${webviewClients.size} client(s)`);
  res.json({ ok: true });
});

// Legacy /op route (HTTP fallback parity with old bridge/server.js)
app.post('/op', (req, res) => {
  const op = req.body || {};
  // TODO: validate op shape
  pendingOps.push(op);
  logOp(op);
  fs.writeFileSync(PENDING_PROMPT, formatOpAsPrompt(op), 'utf8');
  notifyPendingChanged();
  maybeAutoExecute(op);
  res.json({ ok: true });
});

// Auto-execute: probe used by spawned follower MCP servers
app.get('/health', (req, res) => res.json({ ok: true, role: 'leader', port: PORT }));

// Auto-execute: receive agent_event from follower (spawned claude -p)
app.post('/event', (req, res) => {
  const event = req.body && (req.body.event || req.body);
  if (!event || !event.kind) return res.status(400).json({ error: 'missing event.kind' });
  const msg = JSON.stringify({ type: 'agent_event', event });
  for (const ws of webviewClients) {
    if (ws.readyState === 1) ws.send(msg);
  }
  if (currentSession) {
    try { recordEvent(event.kind, event.payload || {}, { parent_event_id: lastUserIntentId, event_id: event.event_id }); } catch (e) { /* non-fatal */ }
  }
  res.json({ ok: true });
});

// Context manifest endpoint (Phase 1)
let manifestCache = { data: null, ts: 0 };
const MANIFEST_CACHE_MS = 5000;

app.get('/context-manifest', (req, res) => {
  const now = Date.now();
  if (manifestCache.data && (now - manifestCache.ts) < MANIFEST_CACHE_MS) {
    return res.json(manifestCache.data);
  }
  const data = {
    memory: loadMemoryManifest(),
    skills: loadSkillsManifest(),
    subagents: loadSubagentsManifest(),
    resources: loadResourcesManifest()
  };
  manifestCache = { data, ts: now };
  res.json(data);
});

// Session listing (Phase 5)
app.get('/sessions', (req, res) => {
  try {
    const dirs = fs.readdirSync(SESSIONS_DIR);
    const sessions = [];
    dirs.forEach(d => {
      const mf = path.join(SESSIONS_DIR, d, 'manifest.json');
      if (!fs.existsSync(mf)) return;
      try {
        const m = JSON.parse(fs.readFileSync(mf, 'utf8'));
        sessions.push({ id: m.id, started_at: m.started_at, ended_at: m.ended_at, event_count: m.event_count });
      } catch (e) { /* skip corrupt */ }
    });
    sessions.sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
    res.json({ sessions });
  } catch (e) {
    res.status(500).json({ error: 'Failed to list sessions' });
  }
});

app.get('/session/:id', (req, res) => {
  try {
    const dir = findSessionDir(req.params.id);
    if (!dir) return res.status(404).json({ error: 'Session not found' });
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
    const eventsRaw = fs.readFileSync(path.join(dir, 'events.jsonl'), 'utf8');
    const events = eventsRaw.trim() ? eventsRaw.trim().split('\n').map(JSON.parse) : [];
    const limit = parseInt(req.query.limit) || 1000;
    const truncated = events.length > limit;
    res.json({ id: req.params.id, manifest, events: events.slice(0, limit), truncated });
  } catch (e) {
    res.status(500).json({ error: 'Failed to read session: ' + e.message });
  }
});

app.get('/session/:id/render/:event_id', (req, res) => {
  try {
    const dir = findSessionDir(req.params.id);
    if (!dir) return res.status(404).json({ error: 'Session not found' });
    const htmlPath = path.join(dir, 'renders', req.params.event_id + '.html');
    if (!fs.existsSync(htmlPath)) return res.status(404).json({ error: 'Render not found' });
    res.type('text/html').sendFile(htmlPath);
  } catch (e) {
    res.status(500).json({ error: 'Failed to serve render: ' + e.message });
  }
});

app.get('/session/:id/envelope/:event_id', (req, res) => {
  try {
    const dir = findSessionDir(req.params.id);
    if (!dir) return res.status(404).json({ error: 'Session not found' });
    const envPath = path.join(dir, 'envelopes', req.params.event_id + '.json');
    if (!fs.existsSync(envPath)) return res.status(404).json({ error: 'Envelope not found' });
    res.json(JSON.parse(fs.readFileSync(envPath, 'utf8')));
  } catch (e) {
    res.status(500).json({ error: 'Failed to serve envelope: ' + e.message });
  }
});

// ── Phase 1: Manifest loaders ─────────────────────────────────────────

const USER_CLAUDE = 'C:\\Users\\qi\\.claude';
const USER_MEMORY = path.join(USER_CLAUDE, 'memory');
const USER_SKILLS = path.join(USER_CLAUDE, 'skills');
const PROJECT_SKILLS = path.join(ROOT, '.claude', 'skills');
const PROJECT_AGENTS = path.join(ROOT, '.claude', 'agents');
const PINNED_RESOURCES = path.join(PROMPTS_DIR, 'pinned-resources.json');

const BUILTIN_SUBAGENTS = [
  { id: 'Explore', name: 'Explore', description: 'Fast agent for exploring codebases' },
  { id: 'general-purpose', name: 'General Purpose', description: 'General-purpose agent for complex multi-step tasks' },
  { id: 'Plan', name: 'Plan', description: 'Software architect agent for designing implementation plans' },
  { id: 'claude-code-guide', name: 'Claude Code Guide', description: 'Answers questions about Claude Code CLI, SDK, and API' },
  { id: 'statusline-setup', name: 'Statusline Setup', description: 'Configures the Claude Code status line' }
];

function parseFrontmatter(content) {
  const m = content.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!m) return {};
  const fm = {};
  m[1].split('\n').forEach(line => {
    const colon = line.indexOf(':');
    if (colon < 0) return;
    const k = line.slice(0, colon).trim();
    let v = line.slice(colon + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    fm[k] = v;
  });
  return fm;
}

function isPathSafe(absPath) {
  const allowRoots = [USER_CLAUDE, ROOT];
  return allowRoots.some(r => absPath.replace(/\\/g, '/').startsWith(r.replace(/\\/g, '/')));
}

function loadMemoryManifest() {
  const items = [];
  const dirs = [USER_MEMORY];
  // Also try project-specific memory path
  const projMem = path.join(USER_CLAUDE, 'projects', 'D--ai-native chrome', 'memory');
  if (fs.existsSync(projMem)) dirs.push(projMem);

  dirs.forEach(dir => {
    if (!fs.existsSync(dir)) return;
    let files;
    try { files = fs.readdirSync(dir).filter(f => f.endsWith('.md')); } catch { return; }
    files.forEach(f => {
      const fp = path.join(dir, f);
      if (!isPathSafe(fp)) return;
      try {
        const raw = fs.readFileSync(fp, 'utf8');
        const fm = parseFrontmatter(raw);
        const stat = fs.statSync(fp);
        const id = f.replace(/\.md$/, '');
        items.push({
          id, name: fm.name || id, description: fm.description || '',
          type: fm.type || 'unknown', source_path: fp, size_bytes: stat.size
        });
      } catch (e) { /* skip unreadable */ }
    });
  });
  return items;
}

function loadSkillsManifest() {
  const items = [];
  const sources = [
    { dir: USER_SKILLS, source: 'user' },
    { dir: PROJECT_SKILLS, source: 'project' }
  ];
  sources.forEach(({ dir, source }) => {
    if (!fs.existsSync(dir)) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    entries.filter(e => e.isDirectory()).forEach(e => {
      const skillMd = path.join(dir, e.name, 'SKILL.md');
      if (!fs.existsSync(skillMd)) return;
      try {
        const raw = fs.readFileSync(skillMd, 'utf8');
        const fm = parseFrontmatter(raw);
        items.push({
          id: e.name, name: fm.name || e.name, description: fm.description || '',
          source, source_path: skillMd
        });
      } catch (ex) { /* skip */ }
    });
  });
  return items;
}

function loadSubagentsManifest() {
  const items = [...BUILTIN_SUBAGENTS];
  if (fs.existsSync(PROJECT_AGENTS)) {
    let files;
    try { files = fs.readdirSync(PROJECT_AGENTS).filter(f => f.endsWith('.md')); } catch { files = []; }
    files.forEach(f => {
      const fp = path.join(PROJECT_AGENTS, f);
      try {
        const raw = fs.readFileSync(fp, 'utf8');
        const fm = parseFrontmatter(raw);
        const id = f.replace(/\.md$/, '');
        items.push({ id, name: fm.name || id, description: fm.description || '', custom: true });
      } catch (e) { /* skip */ }
    });
  }
  return items;
}

function loadResourcesManifest() {
  const items = [
    { id: 'anchor://current-html', name: 'Current rendered HTML', mimeType: 'text/html', scope: 'session' },
    { id: 'anchor://pending-op', name: 'Pending user operation', mimeType: 'application/json', scope: 'session' }
  ];
  if (fs.existsSync(PINNED_RESOURCES)) {
    try {
      const pinned = JSON.parse(fs.readFileSync(PINNED_RESOURCES, 'utf8'));
      if (Array.isArray(pinned)) items.push(...pinned);
    } catch (e) { /* skip */ }
  }
  return items;
}

wss.on('connection', (ws) => {
  webviewClients.add(ws);
  log(`webview connected (${webviewClients.size} total)`);
  if (currentHtml) ws.send(JSON.stringify({ type: 'html', content: currentHtml }));

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'op') {
        pendingOps.push(msg.op);
        log(`op: ${msg.op.op} -> ${msg.op.target} (queue: ${pendingOps.length})`);
        logOp(msg.op);

        const promptText = formatOpAsPrompt(msg.op);
        fs.writeFileSync(PENDING_PROMPT, promptText, 'utf8');

        notifyPendingChanged();
        ws.send(JSON.stringify({ type: 'ack', message: 'Op received', queue_length: pendingOps.length }));
        maybeAutoExecute(msg.op);
      } else if (msg.type === 'envelope') {
        // Phase 2 path — typed IntentEnvelope
        const result = validateEnvelope(msg.envelope);
        if (!result.ok) {
          ws.send(JSON.stringify({ type: 'error', code: result.code, message: result.message }));
          return;
        }
        pendingOps.push(msg.envelope);
        log(`envelope: ${msg.envelope.intent?.op} -> ${msg.envelope.intent?.target_ref} (queue: ${pendingOps.length})`);
        const eid = recordEvent('user.intent', msg.envelope);
        lastUserIntentId = eid;
        fs.writeFileSync(PENDING_PROMPT, formatEnvelopeAsPrompt(msg.envelope), 'utf8');
        notifyPendingChanged();
        ws.send(JSON.stringify({ type: 'ack', message: 'Envelope received', queue_length: pendingOps.length }));
        maybeAutoExecute(msg.envelope);
      } else if (msg.type === 'context_changed') {
        // Phase 1 — log only; default context bundle changed in webview
        log(`context_changed: ${JSON.stringify(msg.bundle || {}).length} bytes`);
        recordEvent('user.context_changed', msg.bundle || {});
      } else if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
      }
    } catch (e) { log('invalid WS msg: ' + e.message); }
  });

  ws.on('close', () => {
    webviewClients.delete(ws);
    log(`webview disconnected (${webviewClients.size} left)`);
  });
});

function broadcast(html) {
  const payload = JSON.stringify({ type: 'html', content: html });
  for (const ws of webviewClients) {
    if (ws.readyState === 1) ws.send(payload);
  }
}

function formatOpAsPrompt(op) {
  const instruction = op.args?.instruction || op.args?.value || '(no instruction)';
  const sel = op.selection ? `\n**Selection**: "${op.selection.text}"` : '';
  return `## Anchor User Action

**Operation**: \`${op.op}\`
**Target**: \`${op.target}\`${sel}
**Instruction**: ${instruction}

### Context
The user performed this action on the rendered HTML. Update the HTML accordingly.
- Only modify target (data-anc="${op.target}") and its data-deps.
- Preserve all data-anc, data-handles, data-deps attributes.
- Call \`anchor_render\` with the COMPLETE updated HTML.

### Current HTML
\`\`\`html
${currentHtml}
\`\`\`

Call \`anchor_render\` with the complete updated HTML now.
`;
}

function notifyPendingChanged() {
  for (const subId of pendingSubscribers) {
    sendMCP({ jsonrpc: '2.0', method: 'notifications/resources/updated', params: { uri: 'anchor://pending-op' } });
  }
}

bootstrap();

// ── Phase 6: Bootstrap with leader/follower detection ────────────────

async function bootstrap() {
  const leaderReachable = await probeLeader();
  if (leaderReachable) {
    isFollower = true;
    log('FOLLOWER MODE: existing leader detected on port ' + PORT);
    loadEnvelopeSchema();
    return;
  }

  httpServer.on('error', (err) => {
    if (err && err.code === 'EADDRINUSE') {
      isFollower = true;
      log('FOLLOWER MODE: port ' + PORT + ' in use after probe');
    } else if (err) {
      log('server error: ' + err.message);
    }
  });

  httpServer.listen(PORT, () => {
    log(`LEADER MODE: webview at http://localhost:${PORT} (auto-exec=${AUTO_EXEC_ENABLED ? 'on' : 'off'})`);
    initSession();
    loadEnvelopeSchema();
    maybeAutoOpenBrowser();
    watchHtmlFile();
  });
}

function probeLeader() {
  return new Promise(resolve => {
    const req = http.request({
      hostname: 'localhost', port: PORT, path: '/health',
      method: 'GET', timeout: 400
    }, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => {
        if (res.statusCode !== 200) return resolve(false);
        try {
          const j = JSON.parse(body);
          resolve(j && j.role === 'leader');
        } catch { resolve(false); }
      });
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

function postToLeader(endpoint, data) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const req = http.request({
      hostname: 'localhost', port: PORT, path: endpoint, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 3000
    }, (res) => {
      let buf = '';
      res.on('data', c => buf += c);
      res.on('end', () => resolve(buf));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.write(body);
    req.end();
  });
}

// ── Phase 6: Spawn `claude -p` to actually run inference ─────────────

function maybeAutoExecute(op) {
  if (!AUTO_EXEC_ENABLED) {
    log('auto-execute disabled (ANCHOR_AUTO_EXECUTE=0)');
    return;
  }
  if (isFollower) return;

  // Batch ops: split into individual ops so each gets its own claude -p invocation.
  if (op._batch_ops && Array.isArray(op._batch_ops) && op._batch_ops.length > 1) {
    log('auto-execute: splitting batch of ' + op._batch_ops.length + ' ops');
    op._batch_ops.forEach(batchOp => {
      const singleOp = {
        intent: {
          op: batchOp.op,
          target_kind: op.intent?.target_kind || 'anchor',
          target_ref: batchOp.target_ref,
          instruction: batchOp.instruction || ''
        },
        context_bundle: op.context_bundle,
        provenance: { ...op.provenance, parent_event_id: op.provenance?.event_id }
      };
      autoExecQueue.push(singleOp);
    });
  } else {
    autoExecQueue.push(op);
  }

  // Sub-claude now owns this op. Pull it out of leader's manual queues so the
  // main CC session (and its Stop hook) won't try to consume the same op.
  try { if (fs.existsSync(PENDING_PROMPT)) fs.unlinkSync(PENDING_PROMPT); } catch {}
  const idx = pendingOps.indexOf(op);
  if (idx >= 0) pendingOps.splice(idx, 1);
  notifyPendingChanged();
  pumpAutoExecQueue();
}

function pumpAutoExecQueue() {
  if (autoExecChildRunning) return;
  const op = autoExecQueue.shift();
  if (!op) return;
  autoExecChildRunning = true;

  // Write this op's payload to disk for the sub-claude's follower MCP to read.
  // Only one in-flight at a time, so a single file is safe.
  try {
    fs.writeFileSync(PENDING_OP_JSON, JSON.stringify(op), 'utf8');
  } catch (e) {
    log('auto-execute: pending-op.json write failed: ' + e.message);
    autoExecChildRunning = false;
    return pumpAutoExecQueue();
  }

  // Short, sanitized prompt for argv. The real op (with instruction text) is in
  // pending-op.json — sub-claude reads it via anchor_get_pending_op below.
  // Keep this prompt free of user-supplied content to avoid shell-quoting issues.
  const prompt = 'Anchor Auto-Execute: one-shot session for a SINGLE op. '
    + 'Step 1: call anchor_emit_event type=thinking with a 1-line plan for this op. '
    + 'Step 2: call anchor_get_pending_op to receive the user intent (with target_ref, op name, instruction) and full current HTML. '
    + 'Step 3: apply the op ONLY to the target anchor and its data-deps. Do NOT modify other sections. Preserve all data-anc, data-handles, data-deps attributes and CSS classes. '
    + 'Step 4: call anchor_render with the COMPLETE updated HTML document (not a fragment). '
    + 'Step 5: call anchor_emit_event type=complete with a 1-line summary of what changed. '
    + 'Do not ask the user follow-up questions; make best-judgment decisions and exit.';

  const targetLabel = op?.intent?.target_ref || op?.target || '(unknown)';
  log(`auto-execute: spawning claude -p for target=${targetLabel} (queue ${autoExecQueue.length})`);

  // Extra claude CLI args (e.g. "--dangerously-skip-permissions") via env var
  const extraArgs = (process.env.ANCHOR_AUTO_EXECUTE_ARGS || '').split(/\s+/).filter(Boolean);
  // Headless mode: pass prompt as -p's argument. Use shell:false so Node handles
  // argv escaping for us — avoids quote/dollar/backtick hell with shell:true.
  // On Windows, the claude CLI is installed as claude.cmd, which needs shell.
  // Workaround: invoke `cmd /c claude ...` explicitly on Windows.
  const isWin = process.platform === 'win32';
  const cmd = isWin ? 'cmd' : 'claude';
  const claudeArgs = isWin
    ? ['/c', 'claude', '-p', ...extraArgs, prompt]
    : ['-p', ...extraArgs, prompt];
  log(`auto-execute: ${cmd} ${claudeArgs.slice(0, isWin ? 3 : 1).join(' ')} <prompt ${prompt.length} bytes>`);

  let child;
  try {
    child = spawn(cmd, claudeArgs, {
      cwd: ROOT,
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env }
    });
  } catch (e) {
    autoExecChildRunning = false;
    log('auto-execute: spawn threw: ' + e.message);
    // Restore op to leader's manual queues so the main session can still pick it up
    pendingOps.push(op);
    try { fs.writeFileSync(PENDING_PROMPT, formatEnvelopeAsPrompt(op), 'utf8'); } catch {}
    notifyPendingChanged();
    broadcast({ type: 'agent_event', event: { kind: 'error', summary: 'Auto-execute spawn failed: ' + e.message, timestamp: Date.now() } });
    pumpAutoExecQueue();
    return;
  }

  let stderrTail = '';
  child.stdout.on('data', () => { /* discard — claude -p prints final answer; the actual side effect is via MCP tools */ });
  child.stderr.on('data', d => {
    stderrTail += d.toString();
    if (stderrTail.length > 4096) stderrTail = stderrTail.slice(-4096);
  });

  const killTimer = setTimeout(() => {
    if (child.exitCode === null) {
      log('auto-execute: timeout (' + AUTO_EXEC_TIMEOUT_MS + 'ms), killing child');
      try { child.kill('SIGTERM'); } catch {}
      setTimeout(() => { try { child.kill('SIGKILL'); } catch {} }, 2000);
    }
  }, AUTO_EXEC_TIMEOUT_MS);

  child.on('exit', (code, signal) => {
    clearTimeout(killTimer);
    autoExecChildRunning = false;
    log(`auto-execute: child exit code=${code} signal=${signal || '-'}`);
    if (code !== 0 && stderrTail.trim()) {
      log('auto-execute stderr (tail): ' + stderrTail.slice(-500).replace(/\n/g, ' | '));
    }
    pumpAutoExecQueue();
  });

  child.on('error', (err) => {
    clearTimeout(killTimer);
    autoExecChildRunning = false;
    log('auto-execute: child error: ' + err.message);
    // Restore op on process error so the main session can still pick it up
    pendingOps.push(op);
    try { fs.writeFileSync(PENDING_PROMPT, formatEnvelopeAsPrompt(op), 'utf8'); } catch {}
    notifyPendingChanged();
    broadcast({ type: 'agent_event', event: { kind: 'error', summary: 'Auto-execute process error: ' + err.message, timestamp: Date.now() } });
    pumpAutoExecQueue();
  });
}

// ── File watcher: detect external writes to output/current.html ──────

function watchHtmlFile() {
  // fs.watch is unreliable on Windows; use stat-polling instead
  let lastMtime = 0;
  try { lastMtime = fs.statSync(CURRENT_HTML).mtimeMs; } catch {}

  const POLL_MS = 500;
  setInterval(() => {
    let mtime;
    try { mtime = fs.statSync(CURRENT_HTML).mtimeMs; } catch { return; }
    if (mtime === lastMtime) return;
    lastMtime = mtime;

    let html;
    try { html = fs.readFileSync(CURRENT_HTML, 'utf8'); } catch { return; }
    if (html === currentHtml) return;

    currentHtml = html;
    log(`file-watcher: reloaded ${html.length} bytes from output/current.html`);
    broadcast(html);
  }, POLL_MS);
}

// ── Phase 0: Browser auto-launch ────────────────────────────────────

function maybeAutoOpenBrowser() {
  if (process.env.ANCHOR_NO_AUTO_BROWSER === '1') {
    log('auto-browser disabled via ANCHOR_NO_AUTO_BROWSER');
    return;
  }
  // Skip if a webview client connects within 5s (avoid duplicate tabs on restart)
  setTimeout(() => {
    if (webviewClients.size > 0) {
      log('webview already connected, skipping auto-open');
      return;
    }
    const url = `http://localhost:${PORT}`;
    const cmd = process.platform === 'win32' ? `start "" "${url}"`
              : process.platform === 'darwin' ? `open "${url}"`
              : `xdg-open "${url}"`;
    exec(cmd, (err) => {
      if (err) log(`auto-open failed (non-fatal): ${err.message}`);
      else log(`opened browser at ${url}`);
    });
  }, 800);
}

// ── Phase 5: Session lifecycle ──────────────────────────────────────

const MANIFEST_FLUSH_INTERVAL = 10;  // flush manifest.json every N events

function initSession() {
  const id = 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  const iso = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const dir = path.join(SESSIONS_DIR, iso + '_' + id);
  const subdirs = ['envelopes', 'renders', 'context_snapshots'];
  fs.mkdirSync(dir, { recursive: true });
  subdirs.forEach(d => fs.mkdirSync(path.join(dir, d), { recursive: true }));

  const manifestPath = path.join(dir, 'manifest.json');
  const eventsPath = path.join(dir, 'events.jsonl');
  const manifest = {
    id, started_at: new Date().toISOString(), ended_at: null,
    client_info: { platform: process.platform, node: process.version },
    anchor_version: '1.0.0', event_count: 0, oversized: false
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
  // Empty events file (touched)
  fs.writeFileSync(eventsPath, '', 'utf8');

  currentSession = { id, dir, manifestPath, eventsPath, manifest, _flushCounter: 0 };
  lastUserIntentId = null;

  // Check for residual sessions from previous run
  recoverResidualSessions();

  recordEvent('system.session_start', { reason: 'server_start' });
  log('session started: ' + id);
}

function recordEvent(kind, payload, opts) {
  if (!currentSession) return null;
  const opts_ = opts || {};
  const eventId = opts_.event_id || generateEventId();
  const event = {
    event_id: eventId,
    session_id: currentSession.id,
    timestamp: new Date().toISOString(),
    kind,
    parent_event_id: opts_.parent_event_id || null,
    payload: payload || {}
  };
  if (kind === 'user.intent') event.envelope_ref = 'envelopes/' + eventId + '.json';
  if (kind === 'agent.render') event.render_ref = 'renders/' + eventId + '.html';
  if (opts_.envelope_ref) event.envelope_ref = opts_.envelope_ref;  // allow override
  if (opts_.render_ref) event.render_ref = opts_.render_ref;

  try {
    fs.appendFileSync(currentSession.eventsPath, JSON.stringify(event) + '\n', 'utf8');
  } catch (e) {
    log('recordEvent append failed: ' + e.message);
    return eventId;
  }

  // Sidecar files
  if (kind === 'user.intent') {
    try {
      const envDir = path.join(currentSession.dir, 'envelopes');
      fs.writeFileSync(path.join(envDir, eventId + '.json'), JSON.stringify(payload, null, 2), 'utf8');
    } catch (e) { log('envelope write failed: ' + e.message); }
  }
  if (kind === 'agent.render') {
    try {
      const renDir = path.join(currentSession.dir, 'renders');
      fs.writeFileSync(path.join(renDir, eventId + '.html'), currentHtml, 'utf8');
    } catch (e) { log('render write failed: ' + e.message); }
  }

  // Flush manifest periodically
  currentSession._flushCounter = (currentSession._flushCounter || 0) + 1;
  currentSession.manifest.event_count = (currentSession.manifest.event_count || 0) + 1;
  if (currentSession._flushCounter >= MANIFEST_FLUSH_INTERVAL) {
    currentSession._flushCounter = 0;
    try {
      fs.writeFileSync(currentSession.manifestPath, JSON.stringify(currentSession.manifest, null, 2), 'utf8');
    } catch (e) { /* non-critical */ }
  }

  return eventId;
}

function flushManifest() {
  if (!currentSession) return;
  try {
    fs.writeFileSync(currentSession.manifestPath, JSON.stringify(currentSession.manifest, null, 2), 'utf8');
  } catch (e) { /* non-critical */ }
}

function recoverResidualSessions() {
  let dirs;
  try { dirs = fs.readdirSync(SESSIONS_DIR); } catch { return; }
  dirs.forEach(d => {
    const dir = path.join(SESSIONS_DIR, d);
    const mf = path.join(dir, 'manifest.json');
    if (!fs.existsSync(mf)) return;
    try {
      const manifest = JSON.parse(fs.readFileSync(mf, 'utf8'));
      if (manifest.event_count > 0 && !manifest.ended_at) {
        // Append a recovered end marker
        const evtPath = path.join(dir, 'events.jsonl');
        const evt = { event_id: generateEventId(), session_id: manifest.id,
          timestamp: new Date().toISOString(), kind: 'system.session_end',
          parent_event_id: null, payload: { recovered: true, reason: 'previous session did not shut down cleanly' } };
        fs.appendFileSync(evtPath, JSON.stringify(evt) + '\n', 'utf8');
        manifest.ended_at = new Date().toISOString();
        manifest.event_count += 1;
        fs.writeFileSync(mf, JSON.stringify(manifest, null, 2), 'utf8');
        log('recovered residual session: ' + manifest.id);
      }
    } catch (e) { /* skip corrupt */ }
  });
}

function findSessionDir(sessionId) {
  let dirs;
  try { dirs = fs.readdirSync(SESSIONS_DIR); } catch { return null; }
  for (const d of dirs) {
    const mf = path.join(SESSIONS_DIR, d, 'manifest.json');
    if (!fs.existsSync(mf)) continue;
    try {
      const m = JSON.parse(fs.readFileSync(mf, 'utf8'));
      if (m.id === sessionId) return path.join(SESSIONS_DIR, d);
    } catch (e) { /* skip */ }
  }
  return null;
}

function generateEventId() {
  return 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
}

// ── Phase 2: Envelope schema + validation (skeleton) ────────────────

function loadEnvelopeSchema() {
  const schemaPath = path.join(SCHEMAS_DIR, 'intent-envelope.json');
  if (!fs.existsSync(schemaPath)) {
    log('envelope schema not found, validation disabled');
    return;
  }
  try {
    envelopeSchema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
    log('envelope schema loaded');
  } catch (e) {
    log('failed to load envelope schema: ' + e.message);
  }
}

function validateEnvelope(instance) {
  // Minimal draft-07 subset: required, enum, const, type (incl. compound), maxLength
  function check(schema, inst, path) {
    if (schema.required) {
      for (const r of schema.required) {
        if (!(r in (inst || {}))) {
          return { ok: false, code: 'MISSING_REQUIRED', message: r + ' is required', details: { path: path + '.' + r } };
        }
      }
    }
    if (inst === null || inst === undefined) {
      // If schema allows null, OK; else error (unless required already caught it)
      if (schema.type) {
        const types = Array.isArray(schema.type) ? schema.type : [schema.type];
        if (!types.includes('null') && !types.includes('object')) {
          return { ok: false, code: 'WRONG_TYPE', message: path + ' is null', details: { path, expected: types } };
        }
        return { ok: true }; // null with type allowing null
      }
      return { ok: true }; // no type constraint
    }

    if (schema.enum) {
      if (!schema.enum.includes(inst)) {
        return { ok: false, code: 'INVALID_ENUM', message: path + ' must be one of: ' + schema.enum.join(', '), details: { path, allowed: schema.enum, got: inst } };
      }
    }
    if (schema.const !== undefined) {
      if (inst !== schema.const) {
        return { ok: false, code: 'INVALID_CONST', message: path + ' must be ' + schema.const, details: { path, expected: schema.const, got: inst } };
      }
    }
    if (schema.maxLength !== undefined && typeof inst === 'string' && inst.length > schema.maxLength) {
      return { ok: false, code: 'TOO_LONG', message: path + ' exceeds max length ' + schema.maxLength, details: { path, max: schema.maxLength, got: inst.length } };
    }

    if (schema.type) {
      const types = Array.isArray(schema.type) ? schema.type : [schema.type];
      const matches = types.some(t => matchType(t, inst));
      if (!matches) {
        return { ok: false, code: 'WRONG_TYPE', message: path + ' must be ' + types.join('|'), details: { path, expected: types, got: typeof inst } };
      }
    }

    if (schema.properties && inst && typeof inst === 'object') {
      for (const [key, propSchema] of Object.entries(schema.properties)) {
        if (key in inst) {
          const r = check(propSchema, inst[key], path + '.' + key);
          if (!r.ok) return r;
        }
      }
    }
    return { ok: true };
  }
  return check(envelopeSchema || SCHEMA_STUB, instance, '');
}

function matchType(t, val) {
  if (t === 'string') return typeof val === 'string';
  if (t === 'integer') return typeof val === 'number' && Number.isInteger(val);
  if (t === 'number') return typeof val === 'number';
  if (t === 'boolean') return typeof val === 'boolean';
  if (t === 'array') return Array.isArray(val);
  if (t === 'object') return val !== null && typeof val === 'object' && !Array.isArray(val);
  if (t === 'null') return val === null;
  return false;
}

// Fallback if schema file missing
const SCHEMA_STUB = {
  type: 'object',
  required: ['intent', 'provenance', 'schema_version'],
  properties: {
    schema_version: { const: '1.0' },
    intent: {
      type: 'object',
      required: ['op', 'target_kind'],
      properties: {
        op: { enum: ['refine','expand','shorten','longer','edit','lock','annotate','branch','restructure','ask','custom'] },
        instruction: { type: 'string', maxLength: 4000 },
        target_kind: { enum: ['anchor','selection','global'] },
        target_ref: { type: 'string' }
      }
    },
    selection: {
      type: ['object', 'null'],
      properties: {
        text: { type: 'string' },
        start_offset: { type: 'integer' },
        end_offset: { type: 'integer' },
        ancestor_anchor: { type: ['string', 'null'] },
        dom_path: { type: 'string' }
      }
    },
    context_bundle: {
      type: 'object',
      properties: {
        memory_ids: { type: 'array' },
        skill_ids: { type: 'array' },
        subagent_ids: { type: 'array' },
        resource_ids: { type: 'array' },
        scope_hint: { enum: ['minimal','standard','wide'] },
        transient_override: { type: 'boolean' }
      }
    },
    render_state: {
      type: 'object',
      properties: {
        anchor_tree: { type: 'array' },
        dom_signature: { type: 'string' }
      }
    },
    provenance: {
      type: 'object',
      required: ['session_id', 'event_id', 'timestamp'],
      properties: {
        session_id: { type: 'string' },
        event_id: { type: 'string' },
        parent_event_id: { type: ['string', 'null'] },
        timestamp: { type: 'string' },
        client_version: { type: 'string' }
      }
    }
  }
};

function formatEnvelopeAsPrompt(envelope) {
  const intent = envelope.intent || {};
  const sel = envelope.selection;
  const bundle = envelope.context_bundle || {};
  const rs = envelope.render_state || {};
  const MAX_HTML = 15000;

  let out = '## Anchor User Action (IntentEnvelope v1.0)\n\n';

  // ── 1. Intent ──
  out += '### Intent\n';
  out += `- **Op**: \`${intent.op || '(unknown)'}\`\n`;
  out += `- **Target kind**: \`${intent.target_kind || '(unknown)'}\`\n`;
  out += `- **Target ref**: \`${intent.target_ref || '(none)'}\`\n`;
  if (intent.instruction) out += `- **Instruction**: ${intent.instruction}\n`;
  out += '\n';

  // ── 2. Selection (if present) ──
  if (sel && sel.text) {
    out += '### Selection\n';
    out += `- **Text**: "${sel.text.substring(0, 200)}"${sel.text.length > 200 ? '…' : ''}\n`;
    if (sel.ancestor_anchor) out += `- **Ancestor anchor**: \`${sel.ancestor_anchor}\`\n`;
    if (sel.dom_path) out += `- **DOM path**: \`${sel.dom_path}\`\n`;
    out += '- **Offsets**: ' + (sel.start_offset ?? '?') + ' → ' + (sel.end_offset ?? '?') + '\n';
    out += '\n';
  }

  // ── 3. Context Bundle ──
  const mem = bundle.memory_ids || [];
  const skl = bundle.skill_ids || [];
  const sub = bundle.subagent_ids || [];
  const res = bundle.resource_ids || [];
  if (mem.length || skl.length || sub.length || res.length) {
    out += '### Context Bundle\n';
    if (mem.length) out += '- **Memory**: ' + mem.map(id => '`' + id + '`').join(', ') + ' (read from `C:\\Users\\qi\\.claude\\memory\\`) \n';
    if (skl.length) out += '- **Skills**: ' + skl.map(id => '`' + id + '`').join(', ') + ' (invoke with Skill tool)\n';
    if (sub.length) out += '- **Subagents**: ' + sub.map(id => '`' + id + '`').join(', ') + ' (launch with Agent tool)\n';
    if (res.length) out += '- **Resources**: ' + res.map(id => '`' + id + '`').join(', ') + '\n';
    if (bundle.transient_override) out += '- ⚠ This is a **per-op override** — do not persist for future rounds.\n';
    out += '\n';
  }

  // ── 4. Render State ──
  const anchors = rs.anchor_tree || [];
  out += '### Render State\n';
  out += '- **Anchor count**: ' + anchors.length + '\n';
  if (anchors.length > 0) {
    out += '- **Anchor IDs**: ' + (anchors.length <= 30 ? anchors.map(a => '`' + a + '`').join(', ') : anchors.slice(0, 30).map(a => '`' + a + '`').join(', ') + '… (truncated)') + '\n';
  }
  out += '\n';

  // ── 5. Current HTML ──
  out += '### Current HTML\n';
  if (currentHtml.length > MAX_HTML) {
    out += '_HTML truncated to ' + MAX_HTML + ' chars_\n';
  }
  out += '```html\n';
  out += currentHtml.substring(0, MAX_HTML);
  if (currentHtml.length > MAX_HTML) out += '\n… (truncated)';
  out += '\n```\n\n';

  // ── Call to action ──
  out += '### Instructions\n';
  out += '- Apply the op ONLY to the target element(s). Preserve all `data-anc`, `data-handles`, `data-deps` attributes.\n';
  out += '- During processing, call `anchor_emit_event` at these milestones: starting → `thinking`, each tool call → `tool_call`, key choices → `decision`, finished → `complete`.\n';
  out += '- When done, call `anchor_render` with the COMPLETE updated HTML.\n';

  return out;
}

// ── logging ────────────────────────────────────────────────────────

function logOp(op) {
  try {
    const line = JSON.stringify({ t: new Date().toISOString(), ...op }) + '\n';
    fs.appendFileSync(OPS_LOG, line, 'utf8');
  } catch (e) {
    log('logOp failed: ' + e.message);
  }
}

// ── MCP JSON-RPC over stdio ─────────────────────────────────────────

let inputBuffer = '';
let mcpInitialized = false;

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { inputBuffer += chunk; drain(); });
process.stdin.on('end', () => { if (inputBuffer.trim()) drain(true); });

function drain(final) {
  const lines = inputBuffer.split('\n');
  inputBuffer = final ? '' : lines.pop() || '';
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      handleMCP(JSON.parse(trimmed));
    } catch (e) { log('MCP parse error: ' + e.message); }
  }
}

function handleMCP(msg) {
  const { id, method, params } = msg;

  if (method === 'initialize') {
    sendMCP({
      jsonrpc: '2.0', id,
      result: {
        protocolVersion: '2024-11-05',
        serverInfo: { name: 'anchor', version: '1.0.0' },
        capabilities: { tools: {}, resources: { subscribe: true } }
      }
    });
    return;
  }

  if (method === 'notifications/initialized') {
    mcpInitialized = true;
    log('MCP initialized');
    return;  // no response
  }

  if (!mcpInitialized) return;

  if (method === 'tools/list') {
    sendMCP({
      jsonrpc: '2.0', id, result: { tools: [
        {
          name: 'anchor_render',
          description: 'Render HTML to the Anchor webview. The HTML must have data-anc, data-handles, data-deps attributes per Anchor protocol. After calling, open http://localhost:3000 to see the interactive page.',
          inputSchema: {
            type: 'object',
            properties: { html: { type: 'string', description: 'Complete HTML document with anchor annotations' } },
            required: ['html']
          }
        },
        {
          name: 'anchor_get_pending_op',
          description: 'Get and clear the pending user interaction from the webview. Returns {pending:false} if no pending op, or {pending:true, op, current_html} with the full context needed to process the op.',
          inputSchema: { type: 'object', properties: {} }
        },
        {
          name: 'anchor_get_html',
          description: 'Get the currently rendered HTML from the webview.',
          inputSchema: { type: 'object', properties: {} }
        },
        {
          name: 'anchor_emit_event',
          description: 'Emit an intermediate agent event (thinking/tool_call/partial_render/decision/complete/error) to the webview timeline panel. Use during op processing to surface progress.',
          inputSchema: {
            type: 'object',
            properties: {
              type: { type: 'string', enum: ['thinking','tool_call','partial_render','decision','complete','error'] },
              payload: { type: 'object' }
            },
            required: ['type']
          }
        },
        {
          name: 'anchor_replay_session',
          description: 'Read events from a recorded session (read-only). Optionally truncate to a specific event_id.',
          inputSchema: {
            type: 'object',
            properties: {
              session_id:      { type: 'string' },
              up_to_event_id:  { type: 'string' }
            },
            required: ['session_id']
          }
        }
      ]}
    });
    return;
  }

  if (method === 'tools/call') {
    handleToolCall(id, params);
    return;
  }

  if (method === 'resources/list') {
    sendMCP({
      jsonrpc: '2.0', id, result: { resources: [
        { uri: 'anchor://current-html', name: 'Current rendered HTML', mimeType: 'text/html' },
        { uri: 'anchor://pending-op', name: 'Pending user operation', mimeType: 'application/json' }
      ]}
    });
    return;
  }

  if (method === 'resources/read') {
    handleResourceRead(id, params);
    return;
  }

  if (method === 'resources/subscribe') {
    const uri = params?.uri;
    if (uri === 'anchor://pending-op') {
      pendingSubscribers.add(id);
    }
    sendMCP({ jsonrpc: '2.0', id, result: {} });
    return;
  }

  if (method === 'resources/unsubscribe') {
    pendingSubscribers.delete(params?.uri);
    sendMCP({ jsonrpc: '2.0', id, result: {} });
    return;
  }

  // Unknown method
  sendMCP({ jsonrpc: '2.0', id, error: { code: -32601, message: `Unknown method: ${method}` } });
}

function handleToolCall(id, params) {
  const { name, arguments: args } = params || {};

  if (name === 'anchor_render') {
    const html = (args && args.html) || '';
    if (isFollower) {
      try {
        fs.writeFileSync(CURRENT_HTML, html, 'utf8');
      } catch (e) {
        sendMCP({ jsonrpc: '2.0', id, error: { code: -32603, message: 'follower write failed: ' + e.message } });
        return;
      }
      log(`anchor_render (follower): wrote ${html.length} bytes; leader file-watcher will broadcast`);
      sendMCP({
        jsonrpc: '2.0', id,
        result: { content: [{ type: 'text', text: `Rendered ${html.length} bytes (follower — leader broadcasts via file-watcher).` }] }
      });
      return;
    }
    currentHtml = html;
    fs.writeFileSync(CURRENT_HTML, html, 'utf8');
    broadcast(html);
    const renderEid = recordEvent('agent.render', { html_size: html.length, signature: 'md5-todo' }, { parent_event_id: lastUserIntentId });
    log(`anchor_render: ${html.length} bytes -> ${webviewClients.size} client(s) [${renderEid}]`);
    sendMCP({
      jsonrpc: '2.0', id,
      result: { content: [{ type: 'text', text: `Rendered ${html.length} bytes to ${webviewClients.size} client(s). Open http://localhost:${PORT} to interact.` }] }
    });
    return;
  }

  if (name === 'anchor_get_pending_op') {
    if (isFollower) {
      try {
        if (fs.existsSync(PENDING_OP_JSON)) {
          const op = JSON.parse(fs.readFileSync(PENDING_OP_JSON, 'utf8'));
          try { fs.unlinkSync(PENDING_OP_JSON); } catch {}
          let html = '';
          try { html = fs.readFileSync(CURRENT_HTML, 'utf8'); } catch {}
          // Follower returns FULL current HTML (no leader-style 15K truncation)
          // — sub-claude only sees what we pass here.
          const MAX = 500 * 1024;
          const truncated = html.length > MAX;
          sendMCP({
            jsonrpc: '2.0', id,
            result: { content: [{ type: 'text', text: JSON.stringify({
              pending: true, op,
              current_html: truncated ? html.substring(0, MAX) : html,
              html_truncated: truncated,
              html_total_bytes: html.length,
              queue_length: 0
            }) }] }
          });
        } else {
          sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ pending: false }) }] } });
        }
      } catch (e) {
        sendMCP({ jsonrpc: '2.0', id, error: { code: -32603, message: 'follower read failed: ' + e.message } });
      }
      return;
    }
    if (pendingOps.length === 0) {
      sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ pending: false }) }] } });
    } else {
      const op = pendingOps.shift();
      notifyPendingChanged();
      sendMCP({
        jsonrpc: '2.0', id,
        result: { content: [{ type: 'text', text: JSON.stringify({
          pending: true, op,
          current_html: currentHtml.substring(0, 15000),
          queue_length: pendingOps.length
        }) }] }
      });
    }
    return;
  }

  if (name === 'anchor_get_html') {
    if (isFollower) {
      let html = '';
      try { html = fs.readFileSync(CURRENT_HTML, 'utf8'); } catch {}
      sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: html || '(empty)' }] } });
      return;
    }
    sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: currentHtml || '(empty)' }] } });
    return;
  }

  if (name === 'anchor_emit_event') {
    const { type, payload } = args || {};
    if (!type) {
      sendMCP({ jsonrpc: '2.0', id, error: { code: -32602, message: 'type required' } });
      return;
    }
    if (isFollower) {
      const eid = 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      const event = {
        event_id: eid,
        timestamp: new Date().toISOString(),
        kind: 'agent.' + type,
        payload: payload || {}
      };
      postToLeader('/event', { event })
        .then(() => sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: 'emitted ' + eid + ' (follower→leader)' }] } }))
        .catch(e => sendMCP({ jsonrpc: '2.0', id, error: { code: -32603, message: 'forward to leader failed: ' + e.message } }));
      return;
    }
    // Record first to get a proper event_id
    const eid = recordEvent('agent.' + type, payload || {}, { parent_event_id: lastUserIntentId });
    const event = {
      event_id: eid,
      session_id: currentSession?.id || null,
      timestamp: new Date().toISOString(),
      kind: 'agent.' + type,
      parent_event_id: lastUserIntentId,
      payload: payload || {}
    };
    // Broadcast to webview
    const msg = JSON.stringify({ type: 'agent_event', event });
    for (const ws of webviewClients) {
      if (ws.readyState === 1) ws.send(msg);
    }
    sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: 'emitted ' + eid }] } });
    return;
  }

  if (name === 'anchor_replay_session') {
    const { session_id, up_to_event_id } = args || {};
    if (!session_id) {
      sendMCP({ jsonrpc: '2.0', id, error: { code: -32602, message: 'session_id required' } });
      return;
    }
    try {
      const dir = findSessionDir(session_id);
      if (!dir) {
        sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ events: [], error: 'Session not found' }) }] } });
        return;
      }
      const eventsRaw = fs.readFileSync(path.join(dir, 'events.jsonl'), 'utf8');
      let events = eventsRaw.trim() ? eventsRaw.trim().split('\n').map(JSON.parse) : [];
      if (up_to_event_id) {
        const idx = events.findIndex(e => e.event_id === up_to_event_id);
        if (idx >= 0) events = events.slice(0, idx + 1);
      }
      const truncated = events.length > 1000;
      if (truncated) events = events.slice(0, 1000);
      sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ events, truncated }) }] } });
    } catch (e) {
      sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ events: [], error: e.message }) }] } });
    }
    return;
  }

  sendMCP({ jsonrpc: '2.0', id, error: { code: -32601, message: `Unknown tool: ${name}` } });
}

function handleResourceRead(id, params) {
  const uri = params?.uri;
  if (uri === 'anchor://current-html') {
    sendMCP({
      jsonrpc: '2.0', id,
      result: { contents: [{ uri, mimeType: 'text/html', text: currentHtml || '<!-- empty -->' }] }
    });
    return;
  }
  if (uri === 'anchor://pending-op') {
    const text = pendingOps.length > 0
      ? JSON.stringify({ pending: true, op: pendingOps[0], queue_length: pendingOps.length })
      : JSON.stringify({ pending: false });
    sendMCP({
      jsonrpc: '2.0', id,
      result: { contents: [{ uri, mimeType: 'application/json', text }] }
    });
    return;
  }
  sendMCP({ jsonrpc: '2.0', id, error: { code: -32602, message: `Unknown resource: ${uri}` } });
}

// ── Helpers ─────────────────────────────────────────────────────────

function sendMCP(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

function log(msg) {
  process.stderr.write(`[anchor-mcp] ${msg}\n`);
}

// ── B.5.11 Graceful shutdown ──────────────────────────────────────────

function shutdown(signal) {
  log('received ' + signal + ', flushing...');
  if (currentSession) {
    recordEvent('system.session_end', { reason: signal });
    flushManifest();
    currentSession.manifest.ended_at = new Date().toISOString();
    try {
      fs.writeFileSync(currentSession.manifestPath, JSON.stringify(currentSession.manifest, null, 2), 'utf8');
    } catch (e) { /* last-ditch */ }
  }
  process.exit(0);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

log('MCP server started, waiting for initialize...');
