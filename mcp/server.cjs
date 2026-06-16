// Anchor Web-UI Service — persistent HTTP + WebSocket daemon.
//
// Responsibilities: serve the webview, capture user ops from the browser,
// relay ops to the CC shim via /ws/agent (push), and broadcast AI-generated
// HTML/patches back to the browser.
//
// CC Agent connects via MCP shim (mcp/shim.cjs), which opens a persistent
// WebSocket to /ws/agent. The service pushes ops immediately on arrival;
// the shim never polls.
//
// Start: scripts\start-anchor.bat

const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec, spawn } = require('child_process');

const ROOT         = path.join(__dirname, '..');
const BRIDGE_NM    = path.join(ROOT, 'bridge', 'node_modules');
const WEBVIEW_DIR  = path.join(ROOT, 'bridge', 'webview');
const OUTPUT_DIR   = path.join(ROOT, 'output');
const PROMPTS_DIR  = path.join(ROOT, 'prompts');
const LOGS_DIR     = path.join(ROOT, 'logs');
const RUNTIME_DIR  = path.join(LOGS_DIR, 'runtime');
const WORKSPACE_DIR = path.join(LOGS_DIR, 'workspace');
const SESSIONS_DIR = path.join(LOGS_DIR, 'sessions');
const SCHEMAS_DIR  = path.join(__dirname, 'schemas');
const CURRENT_HTML   = path.join(OUTPUT_DIR, 'current.html');
const CANVAS_HTML    = path.join(OUTPUT_DIR, 'canvas.html');
const PENDING_PROMPT = path.join(PROMPTS_DIR, 'pending.md');
const PENDING_OP_JSON = path.join(PROMPTS_DIR, 'pending-op.json');
const OPS_LOG      = path.join(LOGS_DIR, 'ops.jsonl');
const TIMELINE_LOG = path.join(LOGS_DIR, 'timeline.log');
const PROCESS_REGISTRY = path.join(RUNTIME_DIR, 'anchor-processes.json');
const SHUTDOWN_LOG = path.join(RUNTIME_DIR, 'shutdown.log');
const WORKSPACE_FILE = path.join(WORKSPACE_DIR, 'workspace.json');
const CUSTOM_CONTEXT_FILE = path.join(WORKSPACE_DIR, 'context-registry.json');
const CHANNEL_RESOURCES_FILE = path.join(WORKSPACE_DIR, 'channel-resources.json');
const INTENT_STREAM_FILE = path.join(ROOT, 'brain', 'context', 'intent-stream.jsonl');
const INTENT_WIKI_INTENTS_FILE = path.join(ROOT, 'brain', 'intent_wiki', 'intents.json');
const INTENT_WIKI_EVIDENCE_FILE = path.join(ROOT, 'brain', 'intent_wiki', 'evidence.jsonl');
const TARGET_PATH = process.env.ANCHOR_TARGET_PATH || path.join(ROOT, 'anchor-output');
const CONFIG_FILE = path.join(WORKSPACE_DIR, 'connectors.json');

const PORT = parseInt(process.env.ANCHOR_PORT || '3000');

const express = require(path.join(BRIDGE_NM, 'express'));
const wsLib   = require(path.join(BRIDGE_NM, 'ws'));
const { WebSocketServer } = wsLib;

// Trading domain extension — lazy init, gated behind file existence.
// Finance logic is being migrated to the Python Core daemon (port 3001).
// These imports will be removed once the migration is complete.
let tradingEvents = null, tradingRoutes = null, tradingPolicyGate = null, tradingCanvasRenderer = null;
try {
  tradingEvents = require('../trading/trading-events.cjs');
  tradingRoutes = require('../trading/trading-routes.cjs');
  tradingPolicyGate = require('../trading/policy-gate.cjs');
  tradingCanvasRenderer = require('../trading/trading-canvas-renderer.cjs');
} catch (e) {
  log('trading domain modules not available (migration to Python Core in progress): ' + e.message);
}

const inbox              = require('./inbox.cjs');
const { PushBroker }     = require('./push-broker.cjs');
const { buildAgentTimingPayload } = require('./lib/agent-timing.cjs');
const canvasState        = require('./lib/canvas-state.cjs');

const ANTHROPIC_SDK_PATH = path.join(BRIDGE_NM, '..', 'node_modules', '@anthropic-ai', 'sdk');
let inprocAgent = null;
const scheduler          = require('./scheduler.cjs');
const connectorRegistry  = require('./connectors/index.cjs');

[OUTPUT_DIR, PROMPTS_DIR, LOGS_DIR, RUNTIME_DIR, WORKSPACE_DIR, SESSIONS_DIR].forEach(d => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});
if (!fs.existsSync(TARGET_PATH)) fs.mkdirSync(TARGET_PATH, { recursive: true });

// ── State ─────────────────────────────────────────────────────────────
let currentHtml = '';
const surfaceHtml = { fin: '', general: '' };
const pendingOps = [];            // buffered while agent not connected
const webviewClients = new Set(); // browser WebSocket connections
let mainAgentWs = null;          // main CC agent shim (subagent_id = null)
// processorWs is replaced by processorPool: agentId → { ws, partition, ops }
const processorPool = new Map();  // agentId → { ws, ops: [...] } — one entry per spawned processor
let processorSeq = 0;            // increments per spawn; used to generate unique agentIds
let ccSpawnLock  = false;        // prevent concurrent spawnCCProcessor calls
const spawningPartitions = new Set(); // partitions currently being spawned (per-partition lock)
const agentRegistry = new Map();  // agentId → { ws, subagentId, label, connectedAt }
let loopEnabled = true;
let shuttingDown = false;
const SERVER_BOOT_MS = Date.now();
const LOOP_BOOT_GRACE_MS = 5000;
const processRegistry = new Map();
const managedChildren = new Map();

let pushBroker = null;

let currentSession = null;
let lastUserIntentId = null;
let envelopeSchema = null;
let manifestCache = { data: null, ts: 0 };
const MANIFEST_CACHE_MS = 5000;
let _tl = null;

if (!process.env.ANCHOR_FRESH_START && fs.existsSync(CURRENT_HTML)) {
  currentHtml = fs.readFileSync(CURRENT_HTML, 'utf8');
  surfaceHtml.fin = currentHtml;
}

function log(msg) { process.stderr.write(`[anchor] ${msg}\n`); }

function anchorLayoutContract() {
  return [
    'Anchor UI layout contract:',
    '- Use only existing classes: anc-section, anc-section--gc, anc-kpi-grid, anc-kpi, kpi-top, kpi-label-top, kpi-icon, kpi-bottom, kpi-value, kpi-unit, anc-pill-row, anc-pill.',
    '- KPI cards must be scannable: short label in kpi-label-top, one compact value in kpi-value, supporting text in kpi-unit. Never put long prose beside the value.',
    '- For ticker/watchlist cards, do not force six columns. Use anc-kpi-grid and let CSS wrap; keep each card meaningful at 240px width.',
    '- Long analysis belongs in p/li or nested anc-section blocks, not inside KPI cards.',
    '- For layered work, keep the visible card to high-level judgment only: conclusion, one or two signals, and minimal visual summary.',
    '- Put deeper data, evidence, source notes, payload fields, caveats, and detailed analysis in a hidden `<aside class="anc-detail" hidden>` inside the same card. Do not duplicate the visible card as the detail content.',
    '- Detail asides may contain `<section class="anc-detail-section" data-detail-section="..." data-detail-label="...">`; standard section classes are `anc-detail-section--content`, `anc-detail-section--sources`, `anc-detail-section--hand-eval`, and `anc-detail-section--brain-eval`.',
    '- Add `data-has-detail="true"` to any card with an `anc-detail` aside so Loom can open it as a generic expandable card across market, coding, design, and other domains.',
    '- Avoid inline widths, fixed heights, negative letter spacing, and tiny font sizes. Text must wrap naturally and never become vertical.',
    '- Preserve every data-anc, data-handles, data-deps attribute and existing class unless the user explicitly asks otherwise.'
  ].join('\n');
}

function escapeHtmlAttr(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderDynamicVisualPage(visualId) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Loom Visual</title>
<link rel="stylesheet" href="/resource/colors_and_type.css">
<link rel="stylesheet" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css">
<link rel="stylesheet" href="/styles.css">
<link rel="stylesheet" href="/loom-detail-overlay.css">
</head>
<body data-loom-entry="dynamic-visual" data-loom-visual-id="${escapeHtmlAttr(visualId)}">
<div class="refraction-bg">
  <div class="blob blob1"></div>
  <div class="blob blob2"></div>
  <div class="blob blob3"></div>
  <div class="light light1"></div>
  <div class="light light2"></div>
  <div class="grain"></div>
</div>
<header id="anchor-toolbar">
  <img class="toolbar-logo" src="/assets/logo-mark.svg" alt="Loom" width="32" height="32">
  <span class="toolbar-brand">Loom Visual</span>
  <span class="toolbar-status" id="status">connecting...</span>
  <span class="toolbar-processing" id="processing" style="display:none">
    <span class="processing-dot"></span>
    <span class="processing-label">Processing</span>
    <span class="processing-target"></span>
  </span>
  <span class="toolbar-info" id="info"></span>
  <button class="toolbar-shutdown" id="anchor-shutdown" title="Shutdown Anchor services" type="button">
    <i class="ph-bold ph-power"></i>
  </button>
</header>
<section id="anchor-home" class="anchor-home anchor-home--general" style="display:none"></section>
<main id="anchor-shell">
  <section id="anchor-content"></section>
</main>
<script src="/timing-waterfall.js"></script>
<script src="/loom-detail-overlay.js"></script>
<script src="/anchor-client.js"></script>
<script>document.addEventListener('DOMContentLoaded',()=>{if(window.AnchorClient)AnchorClient._allowIncomingHtml=true;});</script>
<script src="/prompt-panel.js"></script>
<script src="/hand-feedback-widget.js"></script>
<div id="anchor-execute-all" class="hidden">
  <button class="btn btn--brand execute-all-btn">
    <span class="execute-icon"><i class="ph-bold ph-play"></i></span>
    <span class="execute-label">Execute All</span>
  </button>
  <span class="execute-badge">0</span>
</div>
</body>
</html>`;
}

function browserSurfaceFromUrl(url) {
  try {
    const parsed = new URL(url || '/', `http://localhost:${PORT}`);
    const visualPrefix = '/ws/visual/';
    if (parsed.pathname.startsWith(visualPrefix)) {
      return surfaceFromVisualId(decodeURIComponent(parsed.pathname.slice(visualPrefix.length)));
    }
    if (parsed.pathname === '/ws/general') return 'general';
  } catch {}
  return 'fin';
}

function readJsonFile(file, fallback) {
  try {
    if (!fs.existsSync(file)) return fallback;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJsonFile(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8');
}

function appendJsonl(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, JSON.stringify(data, null, 2).replace(/\n\s*/g, '') + '\n', 'utf8');
}

function slugify(input, fallback) {
  const s = String(input || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return s || fallback || 'item';
}

function compactText(input, max = 300) {
  return String(input || '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function keywordsFromText(input, limit = 12) {
  const stop = new Set(['the', 'and', 'for', 'with', 'this', 'that', 'user', 'intent', 'source']);
  const words = String(input || '').toLowerCase().match(/[a-z0-9\u4e00-\u9fff]{2,}/g) || [];
  const out = [];
  for (const word of words) {
    if (stop.has(word) || out.includes(word)) continue;
    out.push(word);
    if (out.length >= limit) break;
  }
  return out;
}

function normalizeChannel(value, url = '') {
  const raw = String(value || '').trim().toLowerCase();
  if (raw) return slugify(raw, 'external');
  const u = String(url || '').toLowerCase();
  if (u.includes('x.com') || u.includes('twitter.com')) return 'x';
  if (u.includes('reddit.com')) return 'reddit';
  if (u.includes('youtube.com') || u.includes('youtu.be')) return 'youtube';
  if (u.includes('github.com')) return 'github';
  if (u.includes('rss') || u.endsWith('.xml')) return 'rss';
  return 'external';
}

function channelTrustTier(value) {
  const v = String(value || '').trim().toUpperCase();
  return /^[A-G]$/.test(v) ? v : 'F';
}

function loadChannelResources() {
  const data = readJsonFile(CHANNEL_RESOURCES_FILE, { version: 1, resources: [] });
  return { version: 1, resources: Array.isArray(data.resources) ? data.resources : [] };
}

function saveChannelResources(data) {
  writeJsonFile(CHANNEL_RESOURCES_FILE, {
    version: 1,
    resources: Array.isArray(data.resources) ? data.resources : [],
  });
}

function normalizeChannelResource(input) {
  const now = new Date().toISOString();
  const url = compactText(input.url || '', 1000);
  const text = compactText(input.text || input.source || input.title || url, 2000);
  const channel = normalizeChannel(input.channel, url);
  const source = compactText(input.source || url || channel, 200);
  const title = compactText(input.title || source || url || 'External resource', 160);
  const tags = Array.isArray(input.tags)
    ? input.tags.map(tag => slugify(tag, '')).filter(Boolean).slice(0, 12)
    : [];
  const baseId = 'channel_' + channel + '_' + slugify(url || source || title, 'resource');
  return {
    resource_id: compactText(input.resource_id || baseId, 120),
    channel,
    source,
    url,
    title,
    description: compactText(input.description || '', 500),
    text,
    tags,
    trust_tier: channelTrustTier(input.trust_tier),
    resource_kind: slugify(input.resource_kind || (url ? 'link' : 'note'), 'note'),
    intent_hint: compactText(input.intent_hint || '', 500),
    value_signal: compactText(input.value_signal || input.intent_hint || title, 300),
    created_at: input.created_at || now,
    updated_at: now,
    added_by: input.added_by || 'host_agent',
  };
}

function registerChannelResource(input) {
  const resource = normalizeChannelResource(input || {});
  const store = loadChannelResources();
  const existingIndex = store.resources.findIndex(item =>
    item.resource_id === resource.resource_id ||
    (resource.url && item.url === resource.url) ||
    (!resource.url && item.channel === resource.channel && item.source === resource.source && item.title === resource.title)
  );
  if (existingIndex >= 0) {
    resource.resource_id = store.resources[existingIndex].resource_id;
    resource.created_at = store.resources[existingIndex].created_at || resource.created_at;
    store.resources[existingIndex] = { ...store.resources[existingIndex], ...resource };
  } else {
    store.resources.unshift(resource);
  }
  saveChannelResources(store);
  cultivateIntentWikiFromChannelResource(resource);
  return resource;
}

function cultivateIntentWikiFromChannelResource(resource) {
  const now = new Date().toISOString();
  const rawInput = compactText([resource.title, resource.url, resource.text].filter(Boolean).join(' | '), 300);
  const value = compactText(resource.value_signal || resource.intent_hint || resource.title, 120);
  const intentId = 'source_preferences.' + slugify(value, 'external_resource');
  const event = {
    ts: now,
    input_type: 'resource_share',
    channel_resource_entry: true,
    raw_input: rawInput,
    intent: {
      goal: `Use external resource: ${resource.title}`,
      motivation: resource.intent_hint || 'User registered an external channel/resource for future Loom context.',
      decision_frame: '',
      belief_signal: '',
      behavior_intent: 'register external resource channel',
      analytical_direction: resource.intent_hint || resource.description || '',
      content_signal: value,
    },
    anchor_context: null,
    resource_intent: {
      engagement_type: 'channel_connect',
      what_user_values: value,
      author_signal: resource.source || resource.channel,
    },
    session_id: 'channel:' + resource.resource_id,
  };
  appendJsonl(INTENT_STREAM_FILE, event);
  appendJsonl(INTENT_WIKI_EVIDENCE_FILE, {
    ts: now,
    intent_id: intentId,
    event_ts: event.ts,
    input_type: 'resource_share',
    channel_resource_entry: true,
    raw_input: rawInput,
    anchor_context: null,
    intent: event.intent,
    reason: 'external channel resource registered',
    resource_id: resource.resource_id,
    channel: resource.channel,
  });

  const graph = readJsonFile(INTENT_WIKI_INTENTS_FILE, {
    version: 1,
    zones: { source_preferences: 'What evidence, resources, or authors the user tends to value.' },
    intents: [],
  });
  if (!Array.isArray(graph.intents)) graph.intents = [];
  const idx = graph.intents.findIndex(node => node.intent_id === intentId);
  const activationHints = {
    keywords: keywordsFromText([resource.title, resource.source, resource.tags.join(' '), resource.intent_hint, resource.value_signal].join(' ')),
    resource_ids: [resource.resource_id],
    channels: [resource.channel],
    requires_fresh_context: ['x', 'twitter', 'reddit', 'rss', 'youtube', 'social'].includes(resource.channel),
  };
  if (idx >= 0) {
    const node = graph.intents[idx];
    const oldHints = node.activation_hints || {};
    node.label = value || node.label;
    node.principle = 'Prefer evidence and resources matching this registered external channel when relevant.';
    node.evidence_count = (node.evidence_count || 0) + 1;
    node.confidence = Math.min(0.95, Number(((node.confidence || 0.35) + 0.08).toFixed(2)));
    node.updated_at = now;
    node.last_evidence_ts = event.ts;
    node.activation_hints = {
      ...oldHints,
      keywords: Array.from(new Set([...(oldHints.keywords || []), ...activationHints.keywords])).slice(0, 16),
      resource_ids: Array.from(new Set([...(oldHints.resource_ids || []), resource.resource_id])),
      channels: Array.from(new Set([...(oldHints.channels || []), resource.channel])),
      requires_fresh_context: Boolean(oldHints.requires_fresh_context || activationHints.requires_fresh_context),
    };
  } else {
    graph.intents.push({
      intent_id: intentId,
      zone: 'source_preferences',
      label: value || 'Registered external resource channel',
      principle: 'Prefer evidence and resources matching this registered external channel when relevant.',
      status: 'active',
      confidence: 0.43,
      evidence_count: 1,
      activation_hints: activationHints,
      created_at: now,
      updated_at: now,
      last_evidence_ts: event.ts,
    });
  }
  writeJsonFile(INTENT_WIKI_INTENTS_FILE, graph);
}

function normalizeVisualId(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

function surfaceFromVisualId(visualId) {
  const id = normalizeVisualId(visualId);
  return id ? `visual:${id}` : 'general';
}

function normalizeSurface(value) {
  const raw = String(value || '').trim();
  if (raw === 'general') return 'general';
  if (raw.startsWith('visual:')) return surfaceFromVisualId(raw.slice('visual:'.length));
  return 'fin';
}

function opSurface(op) {
  return normalizeSurface(op?.context_bundle?.route_context?.surface);
}

function agentSurface(agentId) {
  if (!agentId) return 'fin';
  const entry = processorPool.get(agentId) || agentRegistry.get(agentId);
  if (entry?.surface) return normalizeSurface(entry.surface);
  return opSurface(entry?.ops?.[0]);
}

function setSurfaceHtml(surface, html) {
  const target = normalizeSurface(surface);
  surfaceHtml[target] = html || '';
  currentHtml = surfaceHtml[target];
  if (target === 'fin') {
    try { fs.writeFileSync(CURRENT_HTML, currentHtml, 'utf8'); } catch (e) { log('render write failed: ' + e.message); }
  }
}

function nowIso() {
  return new Date().toISOString();
}

function createId(prefix, seed) {
  return `${prefix}_${slugify(seed, prefix)}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

function defaultWorkspace() {
  const ts = nowIso();
  const fileId = 'file_welcome';
  return {
    version: 1,
    current_file_id: fileId,
    nodes: [
      { id: 'folder_root', type: 'folder', parent_id: null, name: 'Workspace', created_at: ts, updated_at: ts },
      { id: fileId, type: 'file', parent_id: 'folder_root', name: 'Welcome', created_at: ts, updated_at: ts }
    ],
    files: {
      [fileId]: {
        id: fileId,
        title: 'Welcome',
        prompt: '',
        html: '',
        history: [],
        context: { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [], subagent_id: null, context_mode: null },
        created_at: ts,
        updated_at: ts
      }
    }
  };
}

function ensureWorkspace() {
  const ws = readJsonFile(WORKSPACE_FILE, null) || defaultWorkspace();
  if (!Array.isArray(ws.nodes)) ws.nodes = [];
  if (!ws.files || typeof ws.files !== 'object') ws.files = {};
  if (!ws.current_file_id || !ws.files[ws.current_file_id]) {
    const first = Object.keys(ws.files)[0];
    ws.current_file_id = first || null;
  }
  writeJsonFile(WORKSPACE_FILE, ws);
  return ws;
}

function saveWorkspace(ws) {
  writeJsonFile(WORKSPACE_FILE, ws);
  return ws;
}

function ensureContextRegistry() {
  const reg = readJsonFile(CUSTOM_CONTEXT_FILE, null) || {};
  if (!Array.isArray(reg.skills)) reg.skills = [];
  if (!Array.isArray(reg.resources)) reg.resources = [];
  writeJsonFile(CUSTOM_CONTEXT_FILE, reg);
  return reg;
}

function saveContextRegistry(reg) {
  writeJsonFile(CUSTOM_CONTEXT_FILE, reg);
  manifestCache.ts = 0;
  broadcast(JSON.stringify({ type: 'manifest_updated' }));
  return reg;
}

function normalizeHistoryEntry(entry) {
  const ts = nowIso();
  return {
    id: entry.id || createId('hist', entry.summary || 'entry'),
    timestamp: entry.timestamp || ts,
    anchorCount: Number(entry.anchorCount || entry.anchor_count || 0),
    html: String(entry.html || ''),
    summary: String(entry.summary || 'Saved version')
  };
}

function ensureSubagentDefinition(subagentId) {
  if (!subagentId || !/^[a-zA-Z0-9_-]+$/.test(subagentId)) {
    return { ok: false, error: 'Invalid subagent_id' };
  }
  const existing = path.join(PROJECT_AGENTS, subagentId + '.md');
  if (fs.existsSync(existing)) return { ok: true, path: existing, created: false };

  const known = loadSubagentsManifest().find(a => a.id === subagentId);
  if (!known) return { ok: false, error: `Unknown subagent_id: ${subagentId}` };

  try { fs.mkdirSync(PROJECT_AGENTS, { recursive: true }); } catch (e) {
    return { ok: false, error: 'Cannot create agents directory: ' + e.message };
  }
  if (!isPathSafe(existing)) return { ok: false, error: 'Path not allowed.' };
  const content = [
    '---',
    `name: ${subagentId}`,
    `description: ${(known.description || 'Anchor generated subagent').replace(/\n/g, ' ')}`,
    'tools: "*"',
    '---',
    '',
    `You are ${known.name || subagentId}, an Anchor subagent.`,
    'Handle the selected Anchor operation and return changes through the Anchor MCP tools.',
    'Preserve data-anc, data-handles, data-deps, and existing CSS classes unless the user explicitly asks otherwise.',
    ''
  ].join('\n');
  try {
    fs.writeFileSync(existing, content, 'utf8');
    manifestCache.ts = 0;
    broadcast(JSON.stringify({ type: 'manifest_updated' }));
    log(`[agents] materialized subagent definition: ${subagentId}`);
    return { ok: true, path: existing, created: true };
  } catch (e) {
    return { ok: false, error: 'Write failed: ' + e.message };
  }
}

function appendShutdownLog(msg, extra) {
  const entry = { ts: new Date().toISOString(), msg, ...(extra || {}) };
  try { fs.appendFileSync(SHUTDOWN_LOG, JSON.stringify(entry) + '\n', 'utf8'); } catch {}
}

function writeProcessRegistry() {
  const data = {
    root: ROOT,
    port: PORT,
    updated_at: new Date().toISOString(),
    shutting_down: shuttingDown,
    processes: Array.from(processRegistry.values())
  };
  try { fs.writeFileSync(PROCESS_REGISTRY, JSON.stringify(data, null, 2), 'utf8'); } catch (e) {
    log('process registry write failed: ' + e.message);
  }
}

function registerProcess(record, child) {
  if (!record || !record.pid) return null;
  const id = record.id || `${record.role || 'process'}:${record.pid}`;
  const full = {
    id,
    role: record.role || 'process',
    pid: record.pid,
    status: record.status || 'running',
    started_at: record.started_at || new Date().toISOString(),
    cwd: record.cwd || ROOT,
    command: record.command || '',
    metadata: record.metadata || {}
  };
  processRegistry.set(id, full);
  if (child) managedChildren.set(id, child);
  writeProcessRegistry();
  return id;
}

function updateRegisteredProcess(id, patch) {
  const existing = processRegistry.get(id);
  if (!existing) return;
  processRegistry.set(id, { ...existing, ...(patch || {}) });
  writeProcessRegistry();
}

function unregisterProcess(id, patch) {
  const existing = processRegistry.get(id);
  if (!existing) return;
  const next = {
    ...existing,
    ...(patch || {}),
    status: (patch && patch.status) || 'exited',
    exited_at: (patch && patch.exited_at) || new Date().toISOString()
  };
  processRegistry.set(id, next);
  managedChildren.delete(id);
  setTimeout(() => {
    const latest = processRegistry.get(id);
    if (latest && latest.status !== 'running') {
      processRegistry.delete(id);
      writeProcessRegistry();
    }
  }, 1000);
  writeProcessRegistry();
}

function processSnapshot() {
  return Array.from(processRegistry.values()).map(p => ({
    ...p,
    alive: isPidAlive(p.pid)
  }));
}

function isPidAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function forceKillPid(pid) {
  return new Promise(resolve => {
    if (!pid || pid === process.pid) return resolve(false);
    const bin = process.platform === 'win32' ? 'taskkill.exe' : 'kill';
    const args = process.platform === 'win32'
      ? ['/PID', String(pid), '/T', '/F']
      : ['-9', String(pid)];
    const child = spawn(bin, args, { windowsHide: true, stdio: 'ignore' });
    child.on('exit', () => resolve(true));
    child.on('error', () => resolve(false));
  });
}

function closeWs(ws) {
  if (!ws || ws.readyState !== 1) return;
  try { ws.close(1001, 'Anchor shutdown'); } catch {}
}

async function runShutdown(reason) {
  appendShutdownLog('shutdown begin', { reason });
  loopEnabled = false;
  broadcastAgentEvent({ type: 'shutdown_started', summary: 'Anchor service is shutting down' });

  for (const ws of webviewClients) {
    try { ws.send(JSON.stringify({ type: 'shutdown', message: 'Anchor service shutting down' })); } catch {}
    closeWs(ws);
  }
  for (const entry of processorPool.values()) closeWs(entry.ws);
  closeWs(mainAgentWs);
  for (const entry of agentRegistry.values()) closeWs(entry.ws);

  const stopIds = Array.from(processRegistry.keys()).filter(id => {
    const rec = processRegistry.get(id);
    return rec && rec.pid && rec.pid !== process.pid;
  });
  for (const id of stopIds) {
    const child = managedChildren.get(id);
    const rec = processRegistry.get(id);
    updateRegisteredProcess(id, { status: 'stopping', stopping_at: new Date().toISOString() });
    try {
      if (child) child.kill('SIGTERM');
      else process.kill(rec.pid, 'SIGTERM');
    } catch {}
    appendShutdownLog('sent graceful stop', { id, pid: rec?.pid });
  }

  await delay(4000);

  for (const id of stopIds) {
    const rec = processRegistry.get(id);
    if (rec && isPidAlive(rec.pid)) {
      updateRegisteredProcess(id, { status: 'force_killing' });
      await forceKillPid(rec.pid);
      appendShutdownLog('sent force kill', { id, pid: rec.pid });
    }
    unregisterProcess(id, { status: 'stopped' });
  }

  updateRegisteredProcess('anchor-service:' + process.pid, { status: 'stopping' });
  appendShutdownLog('closing http server', { pid: process.pid });
  try { fs.unlinkSync(PROCESS_REGISTRY); } catch {}

  const exitSoon = () => setTimeout(() => process.exit(0), 50);
  try {
    httpServer.close(exitSoon);
    setTimeout(() => process.exit(0), 1500);
  } catch {
    process.exit(0);
  }
}

// ── WebSocket trace logger ─────────────────────────────────────────────
const TRACE_LOG = path.join(LOGS_DIR, 'ws_trace.log');
const TRACE_MSGS = [];
const TRACE_MAX = 500;

function wsTrace(direction, channel, msgType, meta) {
  const entry = { ts: new Date().toISOString(), direction, channel, msgType, ...meta };
  const line = JSON.stringify(entry) + '\n';
  process.stdout.write(`[ws-trace] ${direction} ${channel} ${msgType} ${JSON.stringify(meta)}\n`);
  try { fs.appendFileSync(TRACE_LOG, line, 'utf8'); } catch {}
  TRACE_MSGS.push(entry);
  if (TRACE_MSGS.length > TRACE_MAX) TRACE_MSGS.splice(0, TRACE_MSGS.length - TRACE_MAX);
}

function timelineMark(event) {
  const now = new Date();
  const hhmm = now.toTimeString().slice(0, 5);
  if (!_tl) _tl = { startMs: now.getTime(), events: {} };
  _tl.events[event] = { hhmm, ms: now.getTime() };
  const line = `[Timeline ${hhmm}] ${event}\n`;
  process.stdout.write(line);
  try { fs.appendFileSync(TIMELINE_LOG, line, 'utf8'); } catch {}
}

function startInteractionTimeline() {
  _tl = null;
  _curTiming = { haStart: 0, haEnd: 0, haMs: null, renderTime: 0, loomMs: null, context: null, _emitted: false };
  timelineMark('user_click_received');
}

let _curTiming = { haStart: 0, haEnd: 0, haMs: null, renderTime: 0, loomMs: null, context: null, _emitted: false };

function _tryEmitTiming() {
  if (_curTiming._emitted) return;
  // Always show split timing: if no hand agent was invoked, set haMs = 0
  if (_curTiming.haMs == null) _curTiming.haMs = 0;
  // Calculate loomMs if render completed
  if (_curTiming.loomMs == null && _curTiming.renderTime > 0) {
    const base = _curTiming.haEnd > 0 ? _curTiming.haEnd : _curTiming.haStart;
    _curTiming.loomMs = base > 0 ? _curTiming.renderTime - base : _curTiming.renderTime - _curTiming.haStart;
  }
  if (_curTiming.loomMs == null) return;
  const payload = {
    ms_hand_agent: _curTiming.haMs,
    ms_loom_agent: _curTiming.loomMs,
    agent_context: _curTiming.context,
    timing_source: 'render',
  };
  broadcastAgentEvent({ type: 'timing', ...payload });
  _curTiming._emitted = true;
  log(`[timing] hand_agent=${_curTiming.haMs ?? '-'}ms · loom_agent=${_curTiming.loomMs ?? '-'}ms`);
}

// ── HTTP + WebSocket setup ────────────────────────────────────────────
//
// Two separate WS servers routed by path:
//   /ws/agent   — MCP shim persistent connection (push channel)
//   everything else — browser clients
const app = express();
const httpServer = http.createServer(app);
httpServer.timeout = 0;

const wssBrowser = new WebSocketServer({ noServer: true });
const wssAgent   = new WebSocketServer({ noServer: true });

httpServer.on('upgrade', (req, socket, head) => {
  const url = req.url || '';
  if (url.startsWith('/ws/agent')) {
    // Extract agentId from query string: /ws/agent?agentId=xxx
    const parsed = new URL(url, `http://localhost:${PORT}`);
    const agentId = parsed.searchParams.get('agentId') || null;
    wssAgent.handleUpgrade(req, socket, head, ws => wssAgent.emit('connection', ws, req, agentId));
  } else {
    wssBrowser.handleUpgrade(req, socket, head, ws => wssBrowser.emit('connection', ws, req));
  }
});

app.use(express.json({ limit: '10mb' }));
app.use(express.static(WEBVIEW_DIR));

app.use((req, res, next) => {
  if (!shuttingDown) return next();
  if (req.path === '/shutdown' || req.path === '/debug/status' || req.path === '/debug/processes') return next();
  res.status(503).json({ ok: false, error: 'Anchor service is shutting down' });
});

// ── HTTP routes ───────────────────────────────────────────────────────

// Allow external tools (e.g. bridge/server.js) to push full HTML
app.post('/html', (req, res) => {
  const html = req.body.html || '';
  if (!html.trim()) return res.status(400).json({ error: 'empty html' });
  const surface = req.body.visual_id ? surfaceFromVisualId(req.body.visual_id) : normalizeSurface(req.body.surface || 'fin');
  setSurfaceHtml(surface, html);
  broadcast(html, surface);
  fs.writeFileSync(CURRENT_HTML, html, 'utf8');
  log(`HTML via POST (${html.length} bytes, surface=${surface}), ${webviewClients.size} client(s)`);
  res.json({ ok: true });
});

// Legacy /op route (HTTP fallback parity)
app.post('/op', (req, res) => {
  const op = req.body || {};
  logOp(op);
  if (!fs.existsSync(PENDING_PROMPT)) {
    fs.writeFileSync(PENDING_PROMPT, formatOpAsPrompt(op), 'utf8');
  }
  if (!deliverOp(op)) pendingOps.push(op);
  notifyPendingChanged();
  res.json({ ok: true });
});

// Agent event broadcast (kept for external tooling)
app.post('/event', (req, res) => {
  const event = req.body && (req.body.event || req.body);
  if (!event || !event.kind) return res.status(400).json({ error: 'missing event.kind' });
  const msg = JSON.stringify({ type: 'agent_event', event });
  let sent = 0;
  for (const ws of webviewClients) {
    if (ws.readyState === 1) try { ws.send(msg); sent++; } catch {}
  }
  if (currentSession) {
    try { recordEvent(event.kind, event.payload || {}, { parent_event_id: lastUserIntentId, event_id: event.event_id }); } catch {}
  }
  res.json({ ok: true });
});

// ── Loom proxies ──────────────────────────────────────────────────────
// CORE_PORT: Loom Core HTTP daemon (loom_core/__main__.py) — adapter registry, domains
// BRAIN_PORT: Loom Brain FastAPI (loom/main.py) — /config, /run, /hand/*, /feedback
const CORE_PORT  = parseInt(process.env.LOOM_CORE_PORT  || '3001');
const BRAIN_PORT = parseInt(process.env.LOOM_BRAIN_PORT || '3002');

function _makeProxy(port) {
  return async function _proxy(req, res, targetPath) {
    const method = req.method;
    const rawBody = ['GET', 'HEAD', 'DELETE'].includes(method) ? null : JSON.stringify(req.body || {});
    const opts = {
      hostname: '127.0.0.1', port,
      path: targetPath + (Object.keys(req.query || {}).length ? '?' + new URLSearchParams(req.query).toString() : ''),
      method,
      headers: { 'Content-Type': 'application/json' },
      timeout: 30000,
    };
    if (rawBody) opts.headers['Content-Length'] = Buffer.byteLength(rawBody);
    try {
      const upstream = await new Promise((resolve, reject) => {
        const r = http.request(opts, resolve);
        r.on('error', reject);
        r.on('timeout', () => { r.destroy(); reject(new Error('timeout')); });
        if (rawBody) r.write(rawBody);
        r.end();
      });
      let data = '';
      upstream.on('data', c => data += c);
      upstream.on('end', () => {
        try { res.status(upstream.statusCode).json(JSON.parse(data)); }
        catch { res.status(upstream.statusCode).send(data); }
      });
    } catch (e) {
      res.status(502).json({ error: `Proxy :${port} unreachable: ${e.message}` });
    }
  };
}

const _proxyToBrain = _makeProxy(BRAIN_PORT);
const _proxyToCore  = _makeProxy(CORE_PORT);

// /config, /run, /feedback, /hand/* → Brain FastAPI at port 3002 (direct paths)
app.all('/config',           (req, res) => _proxyToBrain(req, res, '/config'));
app.all('/run',              (req, res) => _proxyToBrain(req, res, '/run'));
app.all('/feedback',         (req, res) => _proxyToBrain(req, res, '/feedback'));
app.all(/^\/hand(\/.*)?$/,   (req, res) => _proxyToBrain(req, res, '/hand' + (req.params[0] || '')));

// /loom/* → Brain FastAPI at port 3002 (strips /loom prefix)
app.all(/^\/loom(\/.*)?$/, (req, res) => {
  const brainPath = (req.params[0] || '/') || '/';
  return _proxyToBrain(req, res, brainPath);
});

// /core/* → Loom Core HTTP daemon at port 3001
app.all(/^\/core(?:\/(.*))?$/, async (req, res) => {
  const corePath = req.params[0] ? '/' + req.params[0] : '/';
  return _proxyToCore(req, res, corePath);
});

// ── Loom hand-agent invocation (generic, adapter-agnostic) ────────────
// Calls Brain /run before delivering op to CC so CC gets pre-fetched artifact.
function _callBrainRun(handId, task, context) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ hand_id: handId, task: task || '', context: context || {} });
    const opts = {
      hostname: '127.0.0.1', port: BRAIN_PORT,
      path: '/run', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 90000,
    };
    const req = http.request(opts, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch { reject(new Error('Brain /run: invalid JSON')); } });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Brain /run: timeout')); });
    req.write(body);
    req.end();
  });
}

function parseLoomSlashCommand(text) {
  const match = String(text || '').trim().match(/^\/(loom|loom-visual)(?:\s+([\s\S]*))?$/i);
  if (!match) return null;
  const command = match[1].toLowerCase();
  const rest = String(match[2] || '').trim();
  return {
    command,
    route: 'general',
    text: rest,
    visualize: command === 'loom-visual',
  };
}

async function _enrichAndDeliverEnvelope(envelope) {
  const handId = envelope.context_bundle?.loom_hand;
  if (handId) {
    const task = envelope.intent?.instruction || '';
    _curTiming.haStart = Date.now();
    log(`[loom] invoking hand=${handId} task=${JSON.stringify(task.slice(0, 60))}`);
    broadcastAgentEvent({ type: 'thinking', summary: `Running hand agent: ${handId}...` });
    try {
      const result = await _callBrainRun(handId, task);
      if (result.ok && result.artifact) {
        envelope.context_bundle.loom_artifact = result.artifact;
        _curTiming.haEnd = Date.now();
        _curTiming.haMs = _curTiming.haEnd - _curTiming.haStart;
        _tryEmitTiming();
      } else if (!result.ok) {
        log(`[loom] Brain /run error for ${handId}: ${result.error}`);
      }
    } catch (e) {
      log(`[loom] hand invoke failed (${handId}): ${e.message} — proceeding without artifact`);
    }
  }
  try {
    if (!fs.existsSync(PENDING_PROMPT)) {
      fs.writeFileSync(PENDING_PROMPT, formatEnvelopeAsPrompt(envelope), 'utf8');
      fs.writeFileSync(PENDING_OP_JSON, JSON.stringify(envelope), 'utf8');
    }
  } catch {}
  const delivered = deliverOp(envelope);
  if (!delivered) pendingOps.push(envelope);
  notifyPendingChanged();
}

// Patch broadcast (kept for external tooling)
app.post('/patch', (req, res) => {
  const { patches } = (req.body || {});
  if (!patches || !Array.isArray(patches) || patches.length === 0) {
    return res.status(400).json({ error: 'patches array required' });
  }
  broadcastPatches(patches);
  emitPatchCompleteEvents(patches, 'updated via HTTP');
  const missed = detectMissedCascades(patches, currentHtml);
  res.json({ ok: true, cascade_warnings: missed.length });
});

// ── Connector data query (used by bridge.py get_connector_data) ──────
// Returns inbox items for a specific connector source, newest-first.
// Supports ?ticker=NVDA for per-ticker filtering (e.g. finnhub).
app.get('/data/:connectorId', (req, res) => {
  const { connectorId } = req.params;
  const { ticker, limit: limitStr } = req.query;
  const limit = Math.min(parseInt(limitStr, 10) || 50, 200);
  let items = inbox.list({}).filter(item => {
    const src = item.source || '';
    return src === connectorId ||
           src === 'feed:' + connectorId ||
           src === 'webhook:' + connectorId ||
           src.startsWith(connectorId + ':');
  });
  if (ticker) {
    const t = ticker.toUpperCase();
    items = items.filter(item => {
      const p = item.payload || {};
      return (p.ticker || '').toUpperCase() === t || (item.title || '').toUpperCase().includes(t);
    });
  }
  items = items.slice(0, limit);
  res.json({ ok: true, connector_id: connectorId, count: items.length, items });
});

// ── Inbox routes ─────────────────────────────────────────────────────

app.get('/inbox', (req, res) => {
  const { domain, unread } = req.query;
  res.json({ ok: true, items: inbox.list({ domain, unread: unread === 'true' }) });
});

app.get('/inbox/counts', (req, res) => {
  res.json({ ok: true, counts: inbox.unreadCounts() });
});

app.get('/api/inbox/:domain', (req, res) => {
  const domain = req.params.domain;
  if (!inbox.DOMAINS.includes(domain)) {
    return res.status(400).json({ error: 'unknown domain', domains: inbox.DOMAINS });
  }
  const items = inbox.list({ domain });
  res.json({ ok: true, domain, items, meta: inbox.unreadCounts() });
});

app.post('/inbox/read-all', (req, res) => {
  inbox.markAllRead(req.body?.domain || null);
  broadcastBrowserMessage({ type: 'inbox_updated', counts: inbox.unreadCounts() });
  res.json({ ok: true });
});

app.post('/inbox/:id/read', (req, res) => {
  const ok = inbox.markRead(req.params.id);
  if (ok) broadcastBrowserMessage({ type: 'inbox_updated', counts: inbox.unreadCounts() });
  res.json({ ok });
});

// ── Annotations store ─────────────────────────────────────────────
const ANNOTATIONS_FILE = path.join(WORKSPACE_DIR, 'annotations.json');

function _loadAnnotations() {
  try { return JSON.parse(fs.readFileSync(ANNOTATIONS_FILE, 'utf8')); } catch { return []; }
}
function _saveAnnotations(items) {
  try { fs.writeFileSync(ANNOTATIONS_FILE, JSON.stringify(items, null, 2), 'utf8'); } catch {}
}

app.get('/annotations', (req, res) => {
  const { anchor_id } = req.query;
  let items = _loadAnnotations();
  if (anchor_id) items = items.filter(a => a.anchor_id === anchor_id);
  res.json({ items });
});

app.post('/annotations', (req, res) => {
  const { anchor_id, text } = req.body || {};
  if (!anchor_id || !text) return res.status(400).json({ error: 'anchor_id and text required' });
  const items = _loadAnnotations();
  const ann = {
    id: 'ann_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6),
    anchor_id, text,
    ts: new Date().toISOString(),
  };
  items.push(ann);
  _saveAnnotations(items);
  res.json(ann);
});

app.delete('/annotations/:id', (req, res) => {
  let items = _loadAnnotations();
  items = items.filter(a => a.id !== req.params.id);
  _saveAnnotations(items);
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

// ── Webhook receiver ─────────────────────────────────────────────────
const crypto = require('crypto');

app.post('/webhook/:connectorId', (req, res) => {
  const { connectorId } = req.params;
  const cfg = (() => {
    try {
      const raw = fs.readFileSync(CONFIG_FILE, 'utf8');
      const js  = JSON.parse(raw);
      return js[connectorId] || {};
    } catch { return {}; }
  })();

  // HMAC signature verification if secret configured
  const secret = cfg.webhookSecret;
  if (secret) {
    const sig   = req.headers['x-signature'] || req.headers['x-webhook-signature'] || '';
    const hmac  = crypto.createHmac('sha256', secret);
    const raw   = JSON.stringify(req.body);
    const digest = 'sha256=' + hmac.update(raw).digest('hex');
    if (sig !== digest) {
      return res.status(401).json({ error: 'invalid signature' });
    }
  }

  const item = pushBroker.push({
    domain:   cfg.webhookDomain   || 'market',
    title:    cfg.webhookTitle    || `[Webhook] ${connectorId}`,
    summary:  cfg.webhookSummary  || JSON.stringify(req.body).slice(0, 200),
    source:   `webhook:${connectorId}`,
    payload:  { external_id: `webhook:${connectorId}:${Date.now()}`, kind: 'webhook', data: req.body }
  });
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
  market:    { icon: '📊', label: '市场情报', color: 'aurora' },
  position:  { icon: '💼', label: '仓位管理', color: 'cool'   },
  target:    { icon: '🎯', label: '标的跟踪', color: 'warm'   },
  sentiment: { icon: '🌡️', label: '市场情绪', color: 'flame'  }
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
  <p>共 <strong>${items.length}</strong> 条推送 · 点击任意条目进行 AI 精炼</p>
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
  const ws   = ensureWorkspace();
  const meta = DOMAIN_META[domain];

  let file = Object.values(ws.files).find(f => f.domain === domain);
  const html = buildDomainStubHtml(domain);

  if (!file) {
    const id = 'domain-' + domain + '-' + Date.now();
    const ts = new Date().toISOString();
    const node = { id, name: meta.label, type: 'file', domain, created_at: ts, updated_at: ts };
    file = { id, title: meta.label, domain, html, history: [], context: {}, prompt: '', created_at: ts, updated_at: ts };
    ws.nodes.unshift(node);
    ws.files[id] = file;
  } else {
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

// ─────────────────────────────────────────────────────────────────────

app.get('/loom-visual/:visualId', (req, res) => {
  const visualId = normalizeVisualId(req.params.visualId);
  if (!visualId) return res.status(404).send('visual session not found');
  res.type('html').send(renderDynamicVisualPage(visualId));
});

app.get('/loom-visual', (req, res) => {
  res.status(400).send('Create a Loom visual session from /loom-visual in the host agent first.');
});

app.post('/runtime/open-url', (req, res) => {
  const url = normalizeLocalVisualUrl(req.body?.url);
  if (!url) return res.status(400).json({ ok: false, error: 'only local /loom-visual URLs are allowed' });
  broadcastBrowserMessage({ type: 'navigate', url });
  if (webviewClients.size === 0) openBrowserUrl(url);
  res.json({ ok: true, url });
});

app.get('/loom-fin', (req, res) => {
  res.sendFile(path.join(WEBVIEW_DIR, 'index.html'));
});

app.get('/health', (req, res) => res.json({
  ok: true, port: PORT,
  capabilities: {
    service_version: 'dynamic-visual-v2',
    dynamic_visual_webview: true,
  },
  shutting_down: shuttingDown,
  pending_ops: pendingOps.length,
  main_agent_connected: !!mainAgentWs,
  subagents_connected: Array.from(agentRegistry.keys()),
  webview_clients: webviewClients.size
}));

app.get('/agents', (req, res) => res.json({
  main: !!mainAgentWs,
  subagents: Array.from(agentRegistry.entries()).map(([id, e]) => ({
    id, label: e.label, connectedAt: e.connectedAt
  }))
}));

app.get('/debug/spawn-log', (req, res) => res.json({
  entries: spawnLog.slice().reverse(),  // newest first
  pool_size: processorPool.size,
  cc_spawn_lock: ccSpawnLock
}));

app.get('/debug/status', (req, res) => res.json({
  ok: true,
  loop_enabled: loopEnabled,
  shutting_down: shuttingDown,
  webview_clients: webviewClients.size,
  has_current_html: !!(currentHtml && currentHtml.trim()),
  pending_ops: pendingOps.length,
  pending_prompt_file: fs.existsSync(PENDING_PROMPT),
  pending_op_file: fs.existsSync(PENDING_OP_JSON),
  agent_connected: !!mainAgentWs,
  pool_size: processorPool.size,
  pool_idle: Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length,
  cc_spawn_lock: ccSpawnLock
}));

app.get('/debug/processes', (req, res) => res.json({
  ok: true,
  registry_file: PROCESS_REGISTRY,
  processes: processSnapshot()
}));

app.post('/debug/register-process', (req, res) => {
  const body = req.body || {};
  const pid = parseInt(body.pid, 10);
  if (!pid || pid === process.pid) return res.status(400).json({ ok: false, error: 'valid external pid required' });
  const role = body.role || 'external';
  if (!/^[-_a-zA-Z0-9]+$/.test(role)) return res.status(400).json({ ok: false, error: 'invalid role' });
  const id = registerProcess({
    id: body.id || `${role}:${pid}`,
    role,
    pid,
    command: body.command || '',
    metadata: body.metadata || {}
  });
  res.json({ ok: true, id });
});

app.post('/shutdown', (req, res) => {
  if (shuttingDown) {
    return res.json({ ok: true, already_shutting_down: true, processes: processSnapshot() });
  }
  shuttingDown = true;
  const reason = req.body?.reason || 'user_request';
  writeProcessRegistry();
  const processes = processSnapshot();
  res.json({ ok: true, message: 'shutdown_started', processes });
  setTimeout(() => {
    runShutdown(reason).catch(e => {
      appendShutdownLog('shutdown failed', { error: e.message });
      process.exit(1);
    });
  }, 50);
});

// Loop gate — consulted by the Stop hook
app.get('/loop/active', (req, res) => {
  const inBootGrace = (Date.now() - SERVER_BOOT_MS) < LOOP_BOOT_GRACE_MS;
  const active = loopEnabled && !inBootGrace;
  res.json({
    active,
    loop_enabled: loopEnabled,
    webview_clients: webviewClients.size,
    has_current_html: !!(currentHtml && currentHtml.trim()),
    boot_grace: inBootGrace,
    pending_ops: pendingOps.length
  });
});

app.post('/loop/disable', (req, res) => {
  loopEnabled = false;
  log('loop: disabled via /loop/disable');
  res.json({ ok: true, loop_enabled: loopEnabled });
});

app.post('/loop/enable', (req, res) => {
  loopEnabled = true;
  log('loop: enabled via /loop/enable');
  res.json({ ok: true, loop_enabled: loopEnabled });
});

app.get('/current-html', (req, res) => {
  res.type('text/plain').send(currentHtml || '');
});

app.get('/canvas', (req, res) => {
  res.sendFile(path.join(WEBVIEW_DIR, 'canvas.html'));
});

app.get('/current-canvas', (req, res) => {
  try {
    if (fs.existsSync(CANVAS_HTML)) {
      res.type('text/html').send(fs.readFileSync(CANVAS_HTML, 'utf8'));
    } else {
      res.type('text/html').send('');
    }
  } catch { res.type('text/html').send(''); }
});

app.post('/canvas-state', (req, res) => {
  const html = req.body && req.body.html ? req.body.html : '';
  if (!html) return res.json({ ok: false, error: 'html required' });
  try {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    fs.writeFileSync(CANVAS_HTML, html, 'utf8');
    canvasState.update({
      html,
      viewport:  req.body.viewport  || undefined,
      selection: req.body.selection || undefined,
    });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.get('/workspace', (req, res) => {
  res.json({ ok: true, workspace: ensureWorkspace() });
});

app.post('/workspace/folder', (req, res) => {
  const ws = ensureWorkspace();
  const name = String(req.body?.name || 'New folder').trim() || 'New folder';
  const parentId = req.body?.parent_id || 'folder_root';
  const ts = nowIso();
  const node = { id: createId('folder', name), type: 'folder', parent_id: parentId, name, created_at: ts, updated_at: ts };
  ws.nodes.push(node);
  saveWorkspace(ws);
  const folderPath = path.join(TARGET_PATH, name);
  try { fs.mkdirSync(folderPath, { recursive: true }); } catch (e) { log('target path write failed: ' + e.message); }
  res.json({ ok: true, node, workspace: ws, target_path: folderPath });
});

app.post('/workspace/link-folder', (req, res) => {
  const localPath = req.body?.path;
  if (!localPath) return res.status(400).json({ error: 'path required' });
  const resolved = path.resolve(localPath);
  let stats;
  try { stats = fs.statSync(resolved); } catch {
    return res.status(400).json({ error: 'Path does not exist or is not accessible' });
  }
  if (!stats.isDirectory()) return res.status(400).json({ error: 'Path is not a directory' });
  const ws = ensureWorkspace();
  const ts = nowIso();
  const folderName = path.basename(resolved) || localPath;
  const node = {
    id: createId('linked-folder', folderName),
    type: 'linked-folder',
    parent_id: req.body?.parent_id || 'folder_root',
    name: folderName,
    local_path: resolved,
    created_at: ts,
    updated_at: ts
  };
  ws.nodes.push(node);
  saveWorkspace(ws);
  res.json({ ok: true, node, workspace: ws });
});

app.get('/workspace/linked-folder/:id/contents', (req, res) => {
  const ws = ensureWorkspace();
  const node = ws.nodes.find(n => n.id === req.params.id && n.type === 'linked-folder');
  if (!node) return res.status(404).json({ error: 'Linked folder not found' });
  const localPath = node.local_path;
  if (!localPath || !fs.existsSync(localPath)) return res.status(404).json({ error: 'Linked folder path no longer exists' });
  try {
    const entries = fs.readdirSync(localPath, { withFileTypes: true });
    const children = entries.map(entry => ({
      name: entry.name,
      type: entry.isDirectory() ? 'folder' : 'file',
      path: path.join(localPath, entry.name)
    })).sort((a, b) => {
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    res.json({ ok: true, node_id: node.id, children });
  } catch (e) { res.status(500).json({ error: 'Failed to read directory: ' + e.message }); }
});

app.get('/workspace/linked-folder/file', (req, res) => {
  const filePath = req.query.path;
  if (!filePath) return res.status(400).json({ error: 'path query parameter required' });
  const resolved = path.resolve(filePath);
  if (!isPathSafe(resolved)) return res.status(403).json({ error: 'Path is not allowed' });
  try {
    if (!fs.existsSync(resolved)) return res.status(404).json({ error: 'File not found' });
    const content = fs.readFileSync(resolved, 'utf8');
    res.json({ ok: true, path: resolved, content });
  } catch (e) { res.status(500).json({ error: 'Failed to read file: ' + e.message }); }
});

app.post('/workspace/linked-file', (req, res) => {
  const ws = ensureWorkspace();
  const filePath = req.body?.path;
  const fileName = req.body?.name || (filePath ? path.basename(filePath) : 'linked-file');
  if (!filePath) return res.status(400).json({ error: 'path required' });
  const resolved = path.resolve(filePath);
  if (!isPathSafe(resolved)) return res.status(403).json({ error: 'Path is not allowed' });
  try {
    if (!fs.existsSync(resolved)) return res.status(404).json({ error: 'File not found' });
    const content = fs.readFileSync(resolved, 'utf8');
    const ts = nowIso();
    const fileId = createId('linked-file', fileName);
    const node = {
      id: fileId, type: 'file', parent_id: req.body?.parent_id || 'folder_root',
      name: fileName, linked_path: resolved, created_at: ts, updated_at: ts
    };
    const file = {
      id: fileId, title: fileName, html: content, linked_path: resolved,
      history: [], context: { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [], subagent_id: null, context_mode: null },
      created_at: ts, updated_at: ts
    };
    ws.nodes.push(node);
    ws.files[fileId] = file;
    ws.current_file_id = fileId;
    saveWorkspace(ws);
    res.json({ ok: true, node, file, workspace: ws });
  } catch (e) { res.status(500).json({ error: 'Failed to register linked file: ' + e.message }); }
});

app.post('/workspace/file', (req, res) => {
  const ws = ensureWorkspace();
  const title = String(req.body?.name || req.body?.title || 'Untitled').trim() || 'Untitled';
  const parentId = req.body?.parent_id || 'folder_root';
  const ts = nowIso();
  const id = createId('file', title);
  const html = String(req.body?.html || '');
  const node = { id, type: 'file', parent_id: parentId, name: title, created_at: ts, updated_at: ts };
  var context = req.body?.context || { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [], subagent_id: null, context_mode: null };
  var isTrading = req.body?.domain === 'trading.private';
  var effectiveHtml = html;
  if (isTrading && tradingEvents) {
    context.domain = 'trading.private';
    context.trading_session_id = tradingEvents.initTradingSession(id, currentSession?.id);
    if (!effectiveHtml && tradingCanvasRenderer) {
      effectiveHtml = tradingCanvasRenderer.generateTradingCanvasHTML({
        trading_session_id: context.trading_session_id,
        title: title
      });
    }
  }
  const file = {
    id,
    title,
    prompt: String(req.body?.prompt || ''),
    html: effectiveHtml,
    history: [],
    context: context,
    created_at: ts,
    updated_at: ts
  };
  ws.nodes.push(node);
  ws.files[id] = file;
  ws.current_file_id = id;
  if (effectiveHtml) {
    currentHtml = effectiveHtml;
    try { fs.writeFileSync(CURRENT_HTML, effectiveHtml, 'utf8'); } catch {}
  }
  saveWorkspace(ws);
  const filePath = path.join(TARGET_PATH, title + '.html');
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, html || '', 'utf8');
  } catch (e) { log('target path write failed: ' + e.message); }
  res.json({ ok: true, node, file, workspace: ws, target_path: filePath });
});

app.patch('/workspace/file/:id', (req, res) => {
  const ws = ensureWorkspace();
  const file = ws.files[req.params.id];
  if (!file) return res.status(404).json({ ok: false, error: 'file not found' });
  const ts = nowIso();
  if (typeof req.body?.title === 'string' || typeof req.body?.name === 'string') {
    const title = String(req.body.title || req.body.name).trim() || file.title;
    file.title = title;
    const node = ws.nodes.find(n => n.id === file.id);
    if (node) { node.name = title; node.updated_at = ts; }
  }
  if (typeof req.body?.html === 'string') file.html = req.body.html;
  if (typeof req.body?.prompt === 'string') file.prompt = req.body.prompt;
  if (req.body?.context && typeof req.body.context === 'object') file.context = req.body.context;
  if (req.body?.set_current) {
    ws.current_file_id = file.id;
    currentHtml = file.html || '';
    try { fs.writeFileSync(CURRENT_HTML, currentHtml, 'utf8'); } catch {}
    broadcastBrowserMessage({ type: 'workspace_current', file });
  }
  file.updated_at = ts;
  saveWorkspace(ws);
  const filePath = path.join(TARGET_PATH, file.title + '.html');
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, file.html || '', 'utf8');
  } catch (e) { log('target path write failed: ' + e.message); }
  res.json({ ok: true, file, workspace: ws });
});

app.post('/workspace/target-path', (req, res) => {
  const newPath = req.body?.path;
  if (!newPath) return res.status(400).json({ error: 'path required' });
  const resolved = path.resolve(newPath);
  try { fs.mkdirSync(resolved, { recursive: true }); } catch (e) {}
  res.json({ ok: true, target_path: resolved });
});

app.get('/workspace/file/:id/history', (req, res) => {
  const ws = ensureWorkspace();
  const file = ws.files[req.params.id];
  if (!file) return res.status(404).json({ ok: false, error: 'file not found' });
  res.json({ ok: true, file_id: file.id, history: file.history || [] });
});

app.post('/workspace/file/:id/history', (req, res) => {
  const ws = ensureWorkspace();
  const file = ws.files[req.params.id];
  if (!file) return res.status(404).json({ ok: false, error: 'file not found' });
  file.history = Array.isArray(file.history) ? file.history : [];
  file.history.unshift(normalizeHistoryEntry(req.body || {}));
  file.history = file.history.slice(0, 50);
  file.updated_at = nowIso();
  saveWorkspace(ws);
  res.json({ ok: true, history: file.history });
});

app.post('/skills/register', (req, res) => {
  const name = String(req.body?.name || '').trim();
  const url = String(req.body?.url || '').trim();
  if (!name) return res.status(400).json({ ok: false, error: 'name required' });
  const reg = ensureContextRegistry();
  const id = req.body?.id && /^[a-zA-Z0-9_-]+$/.test(req.body.id) ? req.body.id : createId('skill', name);
  const item = {
    id,
    name,
    description: String(req.body?.description || url || 'Pending custom skill').trim(),
    url,
    source: 'custom',
    status: 'pending',
    file_id: req.body?.file_id || null,
    created_at: nowIso()
  };
  reg.skills = reg.skills.filter(s => s.id !== id);
  reg.skills.push(item);
  saveContextRegistry(reg);
  res.json({ ok: true, skill: item });
});

app.post('/resources/register', (req, res) => {
  const name = String(req.body?.name || '').trim();
  const url = String(req.body?.url || '').trim();
  if (!name) return res.status(400).json({ ok: false, error: 'name required' });
  const reg = ensureContextRegistry();
  const id = req.body?.id && /^[a-zA-Z0-9_:/.-]+$/.test(req.body.id) ? req.body.id : createId('resource', name);
  const item = {
    id,
    name,
    description: String(req.body?.description || url || 'User resource').trim(),
    url,
    mimeType: req.body?.mimeType || 'text/uri-list',
    scope: 'workspace',
    source: 'custom',
    status: 'pending',
    file_id: req.body?.file_id || null,
    created_at: nowIso()
  };
  reg.resources = reg.resources.filter(r => r.id !== id);
  reg.resources.push(item);
  saveContextRegistry(reg);
  res.json({ ok: true, resource: item });
});

app.post('/channels/capture', (req, res) => {
  const body = req.body || {};
  const url = compactText(body.url || '', 1000);
  const title = compactText(body.title || body.source || url || '', 160);
  const note = compactText(body.note || body.description || '', 500);
  const text = compactText(body.text || note || url || title, 2000);
  if (!title && !url && !text) {
    return res.status(400).json({ ok: false, error: 'resource content required' });
  }

  const rawTags = Array.isArray(body.tags)
    ? body.tags
    : String(body.tags || '').split(',');
  const tags = rawTags.map(tag => String(tag || '').trim()).filter(Boolean);
  const resource = registerChannelResource({
    channel: body.channel || '',
    source: body.source || title || url,
    url,
    title: title || 'Captured resource',
    description: note,
    text,
    tags,
    trust_tier: body.trust_tier || '',
    resource_kind: body.resource_kind || (url ? 'link' : 'note'),
    intent_hint: body.intent_hint || note,
    value_signal: body.value_signal || body.intent_hint || title || url || text,
    added_by: 'desktop_capture',
  });

  res.json({
    ok: true,
    resource,
    paths: {
      channel_resources: 'logs/workspace/channel-resources.json',
      intent_stream: 'brain/context/intent-stream.jsonl',
      intent_wiki_evidence: 'brain/intent_wiki/evidence.jsonl',
      intent_wiki_intents: 'brain/intent_wiki/intents.json',
    },
  });
});

app.get('/pending-op', (req, res) => {
  if (pendingOps.length === 0) return res.json({ pending: false });
  const op = pendingOps.shift();
  notifyPendingChanged();
  clearPendingFallback();
  const subtree = op?.render_state?.relevant_subtree || null;
  const opKind = op?.intent?.op || '';
  const HEAVY = ['restructure', 'branch', 'expand'];
  const needsFull = HEAVY.includes(opKind) || !subtree;
  res.json({
    pending: true, op,
    relevant_subtree: subtree || undefined,
    current_html: needsFull ? currentHtml : undefined
  });
});

// Context manifest
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

// Save custom subagent definition
app.post('/agents/save', express.json(), (req, res) => {
  const { name, description, system_prompt, tools } = req.body || {};
  if (!name || !/^[a-zA-Z0-9_-]+$/.test(name)) {
    return res.status(400).json({ error: 'Invalid name — use only letters, numbers, hyphens, underscores.' });
  }
  if (!fs.existsSync(PROJECT_AGENTS)) {
    try { fs.mkdirSync(PROJECT_AGENTS, { recursive: true }); } catch (e) {
      return res.status(500).json({ error: 'Cannot create agents directory: ' + e.message });
    }
  }
  const targetPath = path.join(PROJECT_AGENTS, name + '.md');
  if (!isPathSafe(targetPath)) return res.status(400).json({ error: 'Path not allowed.' });
  let resolvedTools = tools || '*';
  if (resolvedTools !== '*' && Array.isArray(resolvedTools) && resolvedTools.length > 0) {
    const required = ['mcp__anchor__anchor_patch', 'mcp__anchor__anchor_emit_event', 'Read', 'Grep'];
    const toolSet = new Set(resolvedTools);
    required.forEach(t => toolSet.add(t));
    resolvedTools = Array.from(toolSet).join(', ');
  } else {
    resolvedTools = '*';
  }
  const toolsLine = resolvedTools === '*' ? 'tools: "*"' : `tools: [${resolvedTools}]`;
  const content = `---\nname: ${name}\ndescription: ${(description || '').replace(/\n/g, ' ')}\n${toolsLine}\n---\n\n${system_prompt || ''}\n`;
  try {
    fs.writeFileSync(targetPath, content, 'utf8');
    manifestCache.ts = 0;
    broadcast(JSON.stringify({ type: 'manifest_updated' }));
    log(`[agents] saved custom subagent: ${name}`);
    res.json({ ok: true, id: name });
  } catch (e) {
    res.status(500).json({ error: 'Write failed: ' + e.message });
  }
});

// Session endpoints
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
      } catch {}
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

app.get('/session/:id/events', (req, res) => {
  try {
    const dir = findSessionDir(req.params.id);
    if (!dir) return res.json({ events: [], error: 'Session not found' });
    const raw = fs.readFileSync(path.join(dir, 'events.jsonl'), 'utf8');
    let events = raw.trim() ? raw.trim().split('\n').map(JSON.parse) : [];
    if (req.query.up_to) {
      const idx = events.findIndex(e => e.event_id === req.query.up_to);
      if (idx >= 0) events = events.slice(0, idx + 1);
    }
    const truncated = events.length > 1000;
    if (truncated) events = events.slice(0, 1000);
    res.json({ events, truncated });
  } catch (e) {
    res.json({ events: [], error: e.message });
  }
});

// ── Browser WebSocket handler ─────────────────────────────────────────

wssBrowser.on('connection', (ws, req) => {
  ws.loomSurface = normalizeSurface(browserSurfaceFromUrl(req?.url || ''));
  webviewClients.add(ws);
  log(`browser connected (${webviewClients.size} total, surface=${ws.loomSurface})`);

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (shuttingDown && msg.type !== 'ping') {
        ws.send(JSON.stringify({ type: 'error', message: 'Anchor service is shutting down' }));
        return;
      }

      if (msg.type === 'op') {
        logOp(msg.op);
        wsTrace('recv', 'browser', 'op', { op: msg.op?.intent?.op, target: msg.op?.intent?.target_ref || msg.op?.target_ref });
        const delivered = deliverOp(msg.op);
        if (!delivered) {
          pendingOps.push(msg.op);
          if (!fs.existsSync(PENDING_PROMPT)) {
            fs.writeFileSync(PENDING_PROMPT, formatOpAsPrompt(msg.op), 'utf8');
          }
        }
        notifyPendingChanged();
        ws.send(JSON.stringify({ type: 'ack', message: 'Op received', queue_length: pendingOps.length }));

      } else if (msg.type === 'envelope') {
        startInteractionTimeline();
        const result = validateEnvelope(msg.envelope);
        if (!result.ok) {
          ws.send(JSON.stringify({ type: 'error', code: result.code, message: result.message }));
          return;
        }
        const eid = recordEvent('user.intent', msg.envelope);
        lastUserIntentId = eid;

        // Trading domain extension — record trading-specific events
        if (msg.envelope.domain && msg.envelope.domain.namespace === 'trading.private' && tradingEvents) {
          try {
            const tKind = 'trading.' + String(msg.envelope.domain.action || 'unknown').toLowerCase();
            tradingEvents.recordTradingEvent(tKind, {
              trading_session_id: msg.envelope.domain.trading_session_id,
              workspace_file_id: msg.envelope.context_bundle?.file_id || null,
              actor: 'human',
              visibility: 'private',
              envelope: msg.envelope,
              domain_action: msg.envelope.domain.action,
              claim_id: msg.envelope.domain.claim_id || null,
              finding_id: msg.envelope.domain.finding_id || null
            });
          } catch (e) {
            log('trading event recording failed: ' + e.message);
          }
        }
        wsTrace('recv', 'browser', 'envelope', {
          op: msg.envelope?.intent?.op,
          target: msg.envelope?.intent?.target_ref,
          subagent: msg.envelope?.context_bundle?.subagent_id
        });
        // Ack immediately; enrichment (optional Brain /run) and delivery happen async.
        ws.send(JSON.stringify({ type: 'ack', message: 'Envelope received', queue_length: pendingOps.length }));
        _enrichAndDeliverEnvelope(msg.envelope).catch(e =>
          log('[loom] envelope enrichment error: ' + e.message)
        );

      } else if (msg.type === 'prompt') {
        startInteractionTimeline();
        const rawText = (msg.text || '').trim();
        const slash = parseLoomSlashCommand(rawText);
        const text = slash ? slash.text : rawText;
        if (!text) { ws.send(JSON.stringify({ type: 'error', message: 'prompt text required' })); return; }

        // Parse \hand prefix — if present, route through Brain enrichment
        const promptText = text;
        const handMatch = promptText.match(/^\\(market|position|target|sentiment)\s+(.*)/s);
        const requestedVisualize = slash && typeof slash.visualize === 'boolean'
          ? slash.visualize
          : msg.visualize;
        const routeContext = {
          ...(msg.context || {}),
          source: msg.context?.source || 'ui',
          visualize: requestedVisualize !== false,
          presentation: requestedVisualize === false ? 'none' : (msg.context?.presentation || 'card'),
          surface: msg.context?.visual_id
            ? surfaceFromVisualId(msg.context.visual_id)
            : normalizeSurface(msg.context?.surface || (slash?.command === 'loom-visual' ? 'general' : 'fin')),
          visual_id: msg.context?.visual_id || null,
        };
        const effectiveRoute = String(msg.route || slash?.route || (handMatch ? handMatch[1] : '') || 'general').trim();
        if (requestedVisualize === false) {
          const cleanPrompt = handMatch ? handMatch[2] : promptText;
          // General non-visual prompts must be handled by the mounted host-agent Brain.
          // The server does not call Python /analyze or any standalone LLM path here.
          ws.send(JSON.stringify({ type: 'ack', message: 'Prompt requires host-agent Brain' }));
          ws.send(JSON.stringify({
            type: 'prompt_result',
            route: effectiveRoute,
            result: {
              ok: false,
              code: 'HOST_AGENT_BRAIN_REQUIRED',
              prompt: cleanPrompt,
              route: effectiveRoute,
              message: 'Run this task from the current Claude Code or Codex main agent. Do not bypass through server /analyze.'
            }
          }));
          return;
        }
        if (handMatch) {
          const hand = handMatch[1];
          const cleanPrompt = handMatch[2];
          const envelope = {
            schema_version: '1.0',
            intent: { op: 'initial_render', target_kind: 'global', target_ref: null, instruction: cleanPrompt },
            context_bundle: { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
                             loom_hand: hand, file_id: effectiveRoute || null, route_context: routeContext },
            render_state: { anchor_tree: [], anchor_index: {} },
            provenance: { session_id: null, event_id: 'prompt-' + Date.now(), parent_event_id: null,
                          timestamp: new Date().toISOString(), client_version: '0.1.0' }
          };
          ws.send(JSON.stringify({ type: 'ack', message: 'Prompt received with hand=' + hand }));
          _enrichAndDeliverEnvelope(envelope).catch(e =>
            log('[loom] envelope enrichment error: ' + e.message)
          );
        } else {
          // Always use envelope path so all rendering goes through spawned processor, never mainAgentWs
          const envelope = {
            schema_version: '1.0',
            intent: { op: 'initial_render', target_kind: 'global', target_ref: null, instruction: text },
            context_bundle: { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
                             file_id: effectiveRoute || null, route_context: routeContext },
            render_state: { anchor_tree: [], anchor_index: {} },
            provenance: { session_id: null, event_id: 'prompt-' + Date.now(), parent_event_id: null,
                          timestamp: new Date().toISOString(), client_version: '0.1.0' }
          };
          ws.send(JSON.stringify({ type: 'ack', message: 'Prompt received' }));
          _enrichAndDeliverEnvelope(envelope).catch(e =>
            log('[loom] envelope enrichment error: ' + e.message)
          );
        }

      } else if (msg.type === 'context_changed') {
        recordEvent('user.context_changed', msg.bundle || {});

      } else if (msg.type === 'html_synced') {
        const syncedHtml = msg.html || '';
        if (syncedHtml) {
          currentHtml = syncedHtml;
          try { fs.writeFileSync(CURRENT_HTML, currentHtml, 'utf8'); } catch {}
          recordEvent('agent.html_synced', { html_size: currentHtml.length, sig: msg.sig || '' });
        }

      } else if (msg.type === 'suggestion_accept') {
        const sug = canvasState.acceptSuggestion(msg.suggestion_id);
        if (sug) {
          broadcastBrowserMessage({ type: 'suggestion_accepted', suggestion_id: msg.suggestion_id, moves: sug.moves });
        }
        ws.send(JSON.stringify({ type: 'ack' }));

      } else if (msg.type === 'suggestion_reject') {
        canvasState.rejectSuggestion(msg.suggestion_id);
        broadcastBrowserMessage({ type: 'suggestion_rejected', suggestion_id: msg.suggestion_id });
        ws.send(JSON.stringify({ type: 'ack' }));

      } else if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
      }
    } catch (e) { log('invalid browser WS msg: ' + e.message); }
  });

  // Send current HTML to new browser clients so the page is populated immediately.
  const initialHtml = surfaceHtml[ws.loomSurface] || (ws.loomSurface === 'fin' ? currentHtml : '');
  if (initialHtml && initialHtml.trim()) {
    try { ws.send(JSON.stringify({ type: 'html', content: initialHtml })); } catch {}
  }

  ws.on('close', () => {
    webviewClients.delete(ws);
    log(`browser disconnected (${webviewClients.size} left)`);
  });
});

// ── Agent WebSocket handler ───────────────────────────────────────────
//
// The MCP shim opens one persistent connection here on startup.
// When an op arrives from a browser, deliverOp() pushes it directly
// over this channel. The shim calls anchor_await_op(), which resolves
// the moment the op arrives — no polling required.
//
// Commands from shim → server: render, patch, event, get_html
// Commands from server → shim: op (push)

wssAgent.on('connection', (ws, req, agentId) => {
  // ── Spawned processor connection (Option C: per-partition pool) ────────
  // agentId format: '__proc__<seq>' — unique per spawned processor.
  // Multiple processors can connect simultaneously; each handles its own op partition.
  if (agentId && agentId.startsWith('__proc__')) {
    const procId = agentId;
    const partition = processorPool.get(procId);

    // Update pool entry with ws reference (processor is now connected and ready)
    if (partition) {
      partition.ws = ws;
    } else {
      log(`[agent] ${procId} connected but no pool entry found (already cleaned up?)`);
    }

    // Deliver only the FIRST op to the processor; subsequent ops are fetched
    // one at a time via 'op_req' messages from anchor_get_pending_op.
    // This prevents CC from receiving all ops at once and only processing the first one.
    if (partition && partition.ops.length > 0) {
      const [firstOp, ...remaining] = partition.ops;
      partition.ops = remaining;
      ws.send(JSON.stringify({ type: 'op', ops: [firstOp], count: 1 }));
      log(`[agent] ${procId} connected, delivered first op (${remaining.length} remaining in partition queue)`);
    } else {
      log(`[agent] ${procId} connected (no ops in partition queue)`);
    }

    ws.on('message', (data) => {
      try { handleAgentMessage(ws, JSON.parse(data.toString()), null); }
      catch (e) { log('[agent] invalid msg from processor: ' + e.message); }
    });

    ws.on('close', () => {
      // Mark pool entry as disconnected (don't delete — partition info may still be useful)
      const entry = processorPool.get(procId);
      if (entry) entry.ws = null;
      log(`[agent] ${procId} disconnected (pool size: ${processorPool.size})`);
      // Check if we need to respawn: remaining ops but no idle processors
      if (pendingOps.length > 0) {
        const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;
        if (idleCount === 0) setTimeout(spawnCCProcessor, 300);
      }
    });

    return;
  }

  // If agentId is provided (non-proc), this is a subagent; otherwise it's the main agent
  if (agentId) {
    // Subagent connection
    const label = 'subagent:' + agentId;
    // Remove any existing connection for this agentId
    if (agentRegistry.has(agentId)) {
      const old = agentRegistry.get(agentId);
      if (old.ws && old.ws.readyState === 1) {
        log(`[agent] replacing existing subagent connection: ${label}`);
        old.ws.close();
      }
    }
    agentRegistry.set(agentId, {
      ws, subagentId: agentId, label,
      connectedAt: new Date().toISOString()
    });
    log(`[agent] subagent connected: ${label} (total agents: ${agentRegistry.size + (mainAgentWs ? 1 : 0)})`);

    // Drain any ops specifically queued for this subagent
    const myOps = pendingOps.filter(op => op.context_bundle?.subagent_id === agentId);
    if (myOps.length > 0) {
      // Remove only these ops from pendingOps
      for (const op of myOps) {
        const idx = pendingOps.indexOf(op);
        if (idx >= 0) pendingOps.splice(idx, 1);
      }
      ws.send(JSON.stringify({ type: 'op', ops: myOps, count: myOps.length }));
      log(`[agent] drained ${myOps.length} op(s) to ${label}`);
    }

    ws.on('message', (data) => {
      try { handleAgentMessage(ws, JSON.parse(data.toString()), agentId); }
      catch (e) { log(`[agent] invalid msg from ${label}: ` + e.message); }
    });

    ws.on('close', () => {
      if (agentRegistry.get(agentId)?.ws === ws) {
        agentRegistry.delete(agentId);
        log(`[agent] subagent disconnected: ${label} (remaining: ${agentRegistry.size + (mainAgentWs ? 1 : 0)})`);
      }
    });

  } else {
    // Main agent connection
    if (mainAgentWs && mainAgentWs.readyState === 1) {
      log('[agent] replacing existing main agent connection');
      mainAgentWs.close();
    }
    mainAgentWs = ws;
    log('[agent] main agent connected');

    // In Option C, ops are handled by the spawned processor (__proc__), not the main session.
    // The main session is for user-directed commands (anchor_render, etc.) only.
    // If ops are pending and no processor is connected, trigger a spawn.
    if (pendingOps.length > 0) {
      log('[agent] main agent connected with pending ops — delegating to processor spawn');
      setTimeout(spawnCCProcessor, 150);
    }

    ws.on('message', (data) => {
      try { handleAgentMessage(ws, JSON.parse(data.toString()), null); }
      catch (e) { log('[agent] invalid msg from main: ' + e.message); }
    });

    ws.on('close', () => {
      if (mainAgentWs === ws) mainAgentWs = null;
      log('[agent] main agent disconnected');
    });
  }
});

// Push one op to the connected shim, or buffer it if no matching agent.
// Routes to subagent WS if subagent_id is set, otherwise to the processor pool.
// For concurrent multi-card processing, each subagent_id gets its own CC process.
function deliverOp(op) {
  const subagentId = op?.context_bundle?.subagent_id || null;
  const surface = opSurface(op);
  let targetWs = null;
  let targetLabel = '';

  if (subagentId) {
    // First try the live subagent WS (user-started subagent session)
    const entry = agentRegistry.get(subagentId);
    if (entry && entry.ws && entry.ws.readyState === 1) {
      targetWs = entry.ws;
      targetLabel = 'subagent:' + subagentId;
    } else {
      // Route to the dedicated processor pool entry for this subagent_id
      const poolEntry = processorPool.get(subagentId);
      if (poolEntry && poolEntry.ws && poolEntry.ws.readyState === 1) {
        targetWs = poolEntry.ws;
        targetLabel = 'processor:' + subagentId;
      }
      // If neither is connected, op stays in pendingOps; spawnCCProcessor will pick it up.
    }
  } else {
    // Regular op: route to any idle processor in the pool (round-robin among idle entries).
    // If no idle processor, the op stays in pendingOps for spawnCCProcessor to handle.
    for (const [key, entry] of processorPool) {
      if (entry.ws && entry.ws.readyState === 1 && !entry.done && normalizeSurface(entry.surface) === surface) {
        targetWs = entry.ws;
        targetLabel = 'pool:' + key;
        break;
      }
    }
    // No mainAgentWs fallback — keeps op in pendingOps so spawnCCProcessor fires.
  }

  if (!targetWs) {
    wsTrace('drop', subagentId ? subagentId : 'main', 'op', { reason: 'no_agent_ws', op: op?.intent?.op, target: op?.intent?.target_ref });
    return false;
  }

  const targetRef = (op.intent?.target_ref) || op.target_ref || op.target || '';
  if (targetRef && targetRef !== '__root__') {
    broadcastAgentEvent({ type: 'thinking', target_anchor: targetRef, summary: 'processing' }, surface);
  }
  wsTrace('send', targetLabel, 'op', { op: op?.intent?.op, target: targetRef, queue: pendingOps.length });
  targetWs.send(JSON.stringify({ type: 'op', ops: [op], count: 1 }));
  clearPendingFallback();
  notifyPendingChanged();
  return true;
}

// Handle render/patch/event/get_html commands sent from the shim.
function handleAgentMessage(ws, msg, agentId) {
  const { type, req_id } = msg;
  const label = agentId ? 'subagent:' + agentId : 'main';
  const surface = msg.visual_id ? surfaceFromVisualId(msg.visual_id) : normalizeSurface(msg.surface || agentSurface(agentId));
  const ack = (ok, extra) => {
    try { ws.send(JSON.stringify({ type: 'ack', req_id, ok, ...(extra || {}) })); } catch {}
  };

  if (type === 'render') {
    const html = msg.html || '';
    wsTrace('recv', label, 'render', { html_len: html.length, surface });
    if (!html.trim()) { ack(false, { error: 'empty html' }); return; }
    setSurfaceHtml(surface, html);
    broadcast(html, surface);
    if (currentSession) recordEvent('agent.render', { html_size: html.length });
    log(`[${label}] render ${html.length} bytes → ${webviewClients.size} browser(s)`);
    const clientCount = Array.from(webviewClients).filter(client => normalizeSurface(client.loomSurface) === surface).length;
    wsTrace('send', 'browser', 'html', { html_len: html.length, clients: clientCount, surface });
    // Track render completion for loom agent timing calculation
    _curTiming.renderTime = Date.now();
    _tryEmitTiming();
    ack(true);

  } else if (type === 'patch') {
    const { patches } = msg;
    if (!Array.isArray(patches) || patches.length === 0) {
      wsTrace('recv', label, 'patch', { count: 0, invalid_patches_type: typeof patches });
      ack(false, { error: 'patches array required' }); return;
    }
    wsTrace('recv', label, 'patch', { count: patches.length, patches: patches.map(p => p.anchor_id) });
    timelineMark('agent_content_generated');
    broadcastPatches(patches, surface);
    timelineMark('webview_patch_broadcast');
    broadcastAgentTiming(label);
    wsTrace('send', 'browser', 'patch', { count: patches.length, anchors: patches.map(p => p.anchor_id) });
    emitPatchCompleteEvents(patches, 'updated', surface);
    const missed = detectMissedCascades(patches, currentHtml);
    if (missed.length > 0) {
      const warnEvent = {
        event_id: generateEventId(),
        session_id: currentSession?.id || null,
        timestamp: new Date().toISOString(),
        kind: 'agent.decision',
        parent_event_id: lastUserIntentId,
        payload: { warning_type: 'missed_cascade', missing_deps: missed,
                   message: 'patches may have missed reverse-dependency nodes' }
      };
      sendBrowserMessageToSurface({ type: 'agent_event', event: warnEvent }, surface);
    }
    log(`[${label}] patch ${patches.length} node(s)${missed.length ? ` (${missed.length} cascade warning(s))` : ''}`);
    ack(true, { cascade_warnings: missed.length });

  } else if (type === 'event') {
    const kind = msg.kind || 'agent.event';
    const payload = msg.payload || {};
    wsTrace('recv', label, 'event', { kind });
    const event = {
      event_id: generateEventId(),
      session_id: currentSession?.id || null,
      timestamp: new Date().toISOString(),
      kind,
      parent_event_id: lastUserIntentId,
      payload
    };
    const sent = sendBrowserMessageToSurface({ type: 'agent_event', event }, surface);
    if (currentSession) {
      try { recordEvent(kind, payload, { event_id: event.event_id, parent_event_id: lastUserIntentId }); } catch {}
    }
    log(`[${label}] event ${kind} → ${sent} browser(s)`);
    wsTrace('send', 'browser', 'agent_event', { kind, sent });
    ack(true, { event_id: event.event_id });

  } else if (type === 'get_html') {
    wsTrace('recv', label, 'get_html', { surface });
    try { ws.send(JSON.stringify({ type: 'html_state', html: surfaceHtml[surface] || currentHtml, req_id })); } catch {}

  } else if (type === 'op_req') {
    // Processor requests the next op from its partition queue (via anchor_get_pending_op).
    // Find which processor this ws belongs to and dequeue one op from its partition.
    let procId = null;
    for (const [key, entry] of processorPool) {
      if (entry.ws === ws) { procId = key; break; }
    }
    const partition = procId ? processorPool.get(procId) : null;
    const nextOp = partition && partition.ops.length > 0 ? partition.ops.shift() : null;
    if (nextOp) {
      wsTrace('recv', 'proc:' + procId, 'op_req', { remaining: partition ? partition.ops.length : 0 });
      ws.send(JSON.stringify({ type: 'op', ops: [nextOp], count: 1 }));
    } else {
      // Partition empty — mark done so deliverOp won't route new ops to this exiting processor
      if (partition) partition.done = true;
      wsTrace('recv', 'proc:' + procId, 'op_req', { remaining: 0, done: true });
      ws.send(JSON.stringify({ type: 'op', ops: [], count: 0 }));
    }
  }
}

// ── Broadcast helpers ─────────────────────────────────────────────────

function broadcast(html, surface = 'fin') {
  const target = normalizeSurface(surface);
  const payload = JSON.stringify({ type: 'html', content: html });
  for (const ws of webviewClients) {
    if (ws.readyState === 1 && normalizeSurface(ws.loomSurface) === target) try { ws.send(payload); } catch {}
  }
}

function broadcastBrowserMessage(message) {
  const payload = JSON.stringify(message);
  for (const ws of webviewClients) {
    if (ws.readyState === 1) try { ws.send(payload); } catch {}
  }
}

function sendBrowserMessageToSurface(message, surface = 'fin') {
  const target = normalizeSurface(surface);
  const payload = JSON.stringify(message);
  let sent = 0;
  for (const ws of webviewClients) {
    if (ws.readyState === 1 && normalizeSurface(ws.loomSurface) === target) {
      try { ws.send(payload); sent++; } catch {}
    }
  }
  return sent;
}

function broadcastPatches(patches, surface = 'fin') {
  const target = normalizeSurface(surface);
  currentHtml = surfaceHtml[target] || currentHtml;
  const beforeHtml = currentHtml;
  let appliedCount = 0;
  for (const patch of patches) {
    if (!patch || !patch.anchor_id || !patch.html_fragment) continue;
    const nextHtml = replaceAnchorNode(currentHtml, patch.anchor_id, patch.html_fragment);
    if (nextHtml !== currentHtml) { currentHtml = nextHtml; appliedCount++; }
  }
  if (appliedCount > 0) {
    surfaceHtml[target] = currentHtml;
    if (target === 'fin') try { fs.writeFileSync(CURRENT_HTML, currentHtml, 'utf8'); } catch (e) {
      log('patch sync write failed: ' + e.message);
    }
  } else if (beforeHtml) {
    log('patch sync skipped: no matching anchors in currentHtml');
  }
  const payload = JSON.stringify({ type: 'patch', patches });
  for (const ws of webviewClients) {
    if (ws.readyState === 1 && normalizeSurface(ws.loomSurface) === target) try { ws.send(payload); } catch {}
  }
}

function broadcastAgentEvent(payload, surface = null) {
  const event = {
    event_id: 'srv-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
    session_id: currentSession?.id || null,
    timestamp: new Date().toISOString(),
    kind: 'agent.' + (payload.type || 'event'),
    parent_event_id: lastUserIntentId,
    payload
  };
  if (surface) {
    sendBrowserMessageToSurface({ type: 'agent_event', event }, surface);
    return;
  }
  const msg = JSON.stringify({ type: 'agent_event', event });
  for (const ws of webviewClients) {
    if (ws.readyState === 1) try { ws.send(msg); } catch {}
  }
}

function emitPatchCompleteEvents(patches, summary, surface = null) {
  for (const patch of patches || []) {
    if (!patch || !patch.anchor_id) continue;
    broadcastAgentEvent({ type: 'complete', target_anchor: patch.anchor_id, summary: summary || 'updated' }, surface);
  }
}

// ── DOM utilities ─────────────────────────────────────────────────────

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function findTagEnd(html, start) {
  let quote = null;
  for (let i = start; i < html.length; i++) {
    const ch = html[i];
    if (quote) { if (ch === quote) quote = null; }
    else if (ch === '"' || ch === "'") { quote = ch; }
    else if (ch === '>') { return i; }
  }
  return -1;
}

function replaceAnchorNode(html, anchorId, fragment) {
  if (!html || !anchorId || !fragment) return html;
  const ancRe = new RegExp('data-anc\\s*=\\s*([\\\'"])' + escapeRegex(anchorId) + '\\1', 'i');
  const match = ancRe.exec(html);
  if (!match) return html;
  const tagStart = html.lastIndexOf('<', match.index);
  if (tagStart < 0 || html[tagStart + 1] === '/') return html;
  const openEnd = findTagEnd(html, tagStart);
  if (openEnd < 0) return html;
  const openTag = html.slice(tagStart, openEnd + 1);
  const tagNameMatch = /^<([a-zA-Z][\w:-]*)\b/.exec(openTag);
  if (!tagNameMatch) return html;
  const tagName = tagNameMatch[1];
  if (/\/\s*>$/.test(openTag)) {
    return html.slice(0, tagStart) + fragment + html.slice(openEnd + 1);
  }
  const tagRe = new RegExp('</?' + escapeRegex(tagName) + '\\b[^>]*>', 'gi');
  tagRe.lastIndex = tagStart;
  let depth = 0, tokenMatch;
  while ((tokenMatch = tagRe.exec(html)) !== null) {
    const token = tokenMatch[0];
    const isClose = /^<\//.test(token);
    const isSelfClosing = /\/\s*>$/.test(token);
    if (isClose) {
      depth--;
      if (depth === 0) return html.slice(0, tagStart) + fragment + html.slice(tagRe.lastIndex);
    } else if (!isSelfClosing) { depth++; }
  }
  return html;
}

function detectMissedCascades(patches, htmlSnapshot) {
  const patched = new Set(patches.map(p => p.anchor_id));
  const missed = [];
  patched.forEach(id => {
    const re = new RegExp(
      'data-anc="([^"]+)"[^>]*data-deps="[^"]*\\b' + escapeRegex(id) + '\\b[^"]*"', 'g'
    );
    let m;
    while ((m = re.exec(htmlSnapshot)) !== null) {
      if (!patched.has(m[1])) missed.push({ source: id, dependent: m[1] });
    }
  });
  const seen = new Set();
  return missed.filter(e => {
    const key = e.source + '→' + e.dependent;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

function clearPendingFallback() {
  try { if (fs.existsSync(PENDING_PROMPT)) fs.unlinkSync(PENDING_PROMPT); } catch {}
  try { if (fs.existsSync(PENDING_OP_JSON)) fs.unlinkSync(PENDING_OP_JSON); } catch {}
}

function initInprocAgent() {
  if (inprocAgent) return inprocAgent;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return null;
  let Anthropic;
  try {
    const sdk = require(ANTHROPIC_SDK_PATH);
    Anthropic = sdk.default || sdk;
  } catch (e) {
    log('[inproc] SDK load failed: ' + e.message);
    return null;
  }
  const inprocMod = require('./inproc-agent.cjs');
  const model = process.env.ANCHOR_INPROC_MODEL || 'claude-haiku-4-5-20251001';
  const toolRegistry = {
    anchor_get_pending_op: async (input, ctx) => {
      if (ctx.opConsumed) return JSON.stringify({ pending: false });
      ctx.opConsumed = true;
      const op = ctx.opPayload;
      const subtree = op?.render_state?.relevant_subtree || null;
      const opKind = op?.intent?.op || '';
      const needsFull = ['restructure', 'branch', 'expand'].includes(opKind) || !subtree;
      return JSON.stringify({
        pending: true, op,
        relevant_subtree: subtree || undefined,
        current_html: needsFull ? currentHtml : undefined,
      });
    },
    anchor_get_html: async () => currentHtml,
    anchor_emit_event: async (input, ctx) => {
      const { type, payload } = input;
      if (type === 'layout_suggest' && payload) {
        const sug = { id: payload.suggestion_id || ('sug-' + Date.now()), moves: payload.moves || [] };
        canvasState.addSuggestion(sug);
        broadcastBrowserMessage({ type: 'layout_suggest', suggestion_id: sug.id, moves: sug.moves });
        return 'layout_suggest queued: ' + sug.id;
      }
      broadcastAgentEvent({ type, target_anchor: ctx.target, ...(payload || {}) });
      if (type === 'complete') ctx.completed = true;
      return 'ok';
    },
    anchor_patch: async (input, ctx) => {
      const { patches } = input;
      if (!Array.isArray(patches) || patches.length === 0) return 'no patches';
      timelineMark('agent_content_generated');
      broadcastPatches(patches);
      timelineMark('webview_patch_broadcast');
      broadcastAgentTiming('inproc');
      ctx.completed = true;
      return 'patched ' + patches.length + ' node(s)';
    },
  };
  try {
    inprocAgent = inprocMod.create({
      Anthropic, apiKey, model, toolRegistry,
      log: (msg) => log('[inproc] ' + msg),
      autoExecLog: (evt) => addSpawnEvent({
        status: evt.event === 'inproc_complete' ? 'done' : 'start',
        msg: `inproc op=${evt.opKind||''} target=${evt.target||''}`,
      }),
      concurrency: parseInt(process.env.ANCHOR_INPROC_CONCURRENCY || '3'),
    });
    log('[inproc] agent initialized model=' + model);
    return inprocAgent;
  } catch (e) {
    log('[inproc] init failed: ' + e.message);
    return null;
  }
}

function notifyPendingChanged() {
  if (pendingOps.length === 0) return;
  const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;
  if (idleCount > 0) return;
  const agent = initInprocAgent();
  if (agent) {
    while (pendingOps.length > 0) agent.enqueue(pendingOps.shift());
  } else {
    setTimeout(spawnCCProcessor, 150);
  }
}

// ── Option C: auto-spawn CC processor ────────────────────────────────
// When a browser op arrives with no processor connected, the server spawns
// `claude -p <prompt>` as a subprocess. The subprocess starts its own shim
// (via mcp.json), connects to /ws/agent?agentId=__proc__, drains all pending
// ops via anchor_get_pending_op, and exits. No loop, no Stop hook needed.

// Build a per-op prompt for `claude -p`. The output is raw HTML written to
// stdout — no tools needed. Server reads stdout and applies the patch directly.
function buildOpPrompt(op) {
  const kind      = op.intent?.op || '';
  const target    = op.intent?.target_ref || '';
  const instr     = op.intent?.instruction || '';
  const targetHtml = op.render_state?.relevant_subtree?.target_html || currentHtml;

  if (kind === 'initial_render') {
    return (
      `Generate a complete Anchor HTML page.\n` +
      `Request: ${instr}\n\n` +
      `${anchorLayoutContract()}\n\n` +
      `Follow the Anchor HTML protocol and Bloom CSS classes from CLAUDE.md.\n` +
      `Output ONLY the raw <!DOCTYPE html> document. No markdown fences, no explanation.`
    );
  }

  return (
    `Op: ${kind} | Target: data-anc="${target}" | Instruction: "${instr}"\n\n` +
    `Current HTML:\n${targetHtml}\n\n` +
    `Reply with ONLY the replacement outerHTML for data-anc="${target}". ` +
    `Keep data-anc/data-handles/data-deps. Use Bloom CSS. ` +
    `${anchorLayoutContract()} ` +
    `NO preamble, NO explanation, NO markdown fences. ` +
    `First character of your response must be '<'.`
  );
}

function stripCodeFence(text) {
  // Extract HTML from a code fence anywhere in the output (CC often adds preamble)
  const m = text.match(/```(?:html)?\s*\n([\s\S]*?)```/);
  if (m) return m[1].trim();
  // No fence — find first '<' and return from there
  const trimmed = text.trim();
  const lt = trimmed.indexOf('<');
  return lt >= 0 ? trimmed.slice(lt) : trimmed;
}

// In-memory spawn event log — exposed via GET /debug/spawn-log
const spawnLog = [];
const SPAWN_LOG_MAX = 50;

function addSpawnEvent(evt) {
  spawnLog.push({ ts: new Date().toISOString(), ...evt });
  if (spawnLog.length > SPAWN_LOG_MAX) spawnLog.shift();
}

function buildProcessorPrompt(ops) {
  const summary = ops.map((op, i) => {
    const intent = op.intent || {};
    const target = intent.target_ref || op.target_ref || op.target || '?';
    const instruction = intent.instruction || op.args?.instruction || op.args?.value || '';
    return `${i + 1}. ${intent.op || op.op || '?'} -> ${target}${instruction ? ` | ${instruction}` : ''}`;
  }).join('\n');

  const hasSubagent = ops.some(op => op.context_bundle?.subagent_id);
  const skillSummary = ops.flatMap(op => op.context_bundle?.skill_ids || []);
  const resourceSummary = ops.flatMap(op => op.context_bundle?.resource_ids || []);
  const processorPrompt = [
    '[ANCHOR SINGLE-PASS OP PROCESSOR]',
    '',
    'You are a short-lived processor spawned by the Anchor service.',
    'Do not answer the user directly and do not print HTML to stdout.',
    '',
    'Process pending Anchor ops through the MCP tools:',
    '1. Call anchor_get_pending_op() once to get the op(s).',
    '2. If {pending:false}, exit with one-line summary.',
    '3. For initial_render, call anchor_render(html).',
    '4. For op with subagent_id set in context_bundle: call Agent(subagent_type="<subagent_id>", prompt=...) to generate the patch, then call anchor_patch({patches:[...]}).',
    '5. For regular op: generate the modified outerHTML, then call anchor_patch({patches:[...]}).',
    '6. If context_bundle.skill_ids contains pending custom skills or context_bundle.resource_ids contains URLs, inspect those resources as task context before editing.',
    '7. For initial_render: after the first anchor_render(), call anchor_get_html() to inspect the rendered page, then use anchor_patch() for a UI refinement pass — fix card grid distribution, spacing, alignment, and visual hierarchy.',
    '',
    'Never call anchor_await_op from this spawned processor.',
    'Preserve data-anc, data-handles, data-deps, and existing CSS classes in patched fragments.',
    '',
    anchorLayoutContract(),
    '',
    hasSubagent
      ? 'NOTE: Some ops are routed to subagents. When the op has context_bundle.subagent_id, generate a prompt describing the target HTML and instruction, then use Agent(subagent_type=<id>, prompt=...) to get the result, and call anchor_patch with the returned fragment.'
      : 'Ops are processed directly by this processor.',
    skillSummary.length ? `Selected skills: ${Array.from(new Set(skillSummary)).join(', ')}` : '',
    resourceSummary.length ? `Selected resources: ${Array.from(new Set(resourceSummary)).join(', ')}` : '',
    '',
    'Ops expected in this batch:',
    summary || '(none)',
    '',
    ...ops.flatMap(op => {
      const artifact = op.context_bundle?.loom_artifact;
      const handId   = op.context_bundle?.loom_hand;
      if (!artifact) return [];
      const claims = artifact.metadata?.key_claims || [];
      return [
        `--- HAND AGENT ANALYSIS (hand=${handId}) ---`,
        ...claims.map((c, i) => `${i + 1}. ${c}`),
        'Based on the above findings, render an Anchor HTML page with gradient KPI cards for key metrics and detailed analysis sections beneath.',
        '---',
      ];
    }),
    // 容灾: hand agent unavailable, fall back to skill invocation
    // This runs when loom_hand is set but loom_artifact is missing (timeout/error)
    ...ops.flatMap(op => {
      const handId   = op.context_bundle?.loom_hand;
      const artifact = op.context_bundle?.loom_artifact;
      if (!handId || artifact) return [];
      const SKILL_PATHS = {
        market:    'D:\\nano\\nanobot\\nanobot\\skills\\hand-market\\SKILL.md',
        sentiment: 'D:\\nano\\nanobot\\nanobot\\skills\\hand-sentiment\\SKILL.md',
        target:    'D:\\nano\\nanobot\\nanobot\\skills\\hand-target\\SKILL.md',
        position:  'D:\\nano\\nanobot\\nanobot\\skills\\hand-position\\SKILL.md',
      };
      const skillPath = SKILL_PATHS[handId];
      if (!skillPath) return [];
      return [
        `--- HAND AGENT UNAVAILABLE (hand=${handId}) — FALLBACK TO SKILL ---`,
        `The remote hand agent for "${handId}" failed. You MUST:`,
        `1. Read the hand skill file using Read tool: Read(file_path="${skillPath}")`,
        `2. Follow the skill instructions to generate the analysis (use web_fetch/search for current data as needed).`,
        `3. Render an Anchor HTML page with gradient KPI cards for key metrics and detailed analysis sections beneath.`,
        '---',
      ];
    }),
    '',
    '--- UI REFINEMENT PASS ---',
    'After the initial render, do a second pass to polish the UI:',
    '1. Call anchor_get_html() to fetch the rendered page.',
    '2. Use anchor_patch() to fix layout issues:',
    '   - KPI grid: ensure cards are evenly distributed (3 per row for 6 cards, NOT 4+2).',
    '   - Text alignment: headings, values, and supporting text should be consistently aligned within each card.',
    '   - Spacing: adequate gap between cards (use CSS gap or margin, not fixed widths).',
    '   - Visual hierarchy: section titles should clearly separate topic areas; use anc-section--gc with appropriate color themes.',
    '   - Responsive: cards should reflow naturally. Do NOT set inline widths or fixed column counts.',
    '3. Call anchor_patch() with the refined fragments. Only patch what needs changing.',
    '---',
  ].join('\n');
  return processorPrompt;
}

function psQuote(s) {
  return "'" + String(s).replace(/'/g, "''") + "'";
}

function spawnCCProcessor() {
  if (ccSpawnLock) return;
  const allOps = pendingOps.slice();
  if (allOps.length === 0) return;

  // Separate ops by subagent_id — each subagent_id gets its own processor partition
  const subagentOps = allOps.filter(op => op.context_bundle?.subagent_id);
  const regularOps  = allOps.filter(op => !op.context_bundle?.subagent_id);

  // Validate subagent definitions
  const subagentIds = Array.from(new Set(subagentOps.map(op => op.context_bundle?.subagent_id).filter(Boolean)));
  for (const subagentId of subagentIds) {
    const ensured = ensureSubagentDefinition(subagentId);
    if (!ensured.ok) {
      addSpawnEvent({ status: 'error', msg: ensured.error, subagent: subagentId });
      broadcastBrowserMessage({ type: 'error', message: ensured.error });
      for (let i = pendingOps.length - 1; i >= 0; i--) {
        if (pendingOps[i]?.context_bundle?.subagent_id === subagentId) pendingOps.splice(i, 1);
      }
    }
  }

  // Count idle pool entries
  const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;

  // Remove these ops from pendingOps so they aren't picked up again on respawn
  const opSet = new Set(allOps);
  const remaining = pendingOps.filter(o => !opSet.has(o));
  pendingOps.splice(0, pendingOps.length, ...remaining);

  // Build partition list: one entry per subagent_id + one for all regular ops
  const partitions = [];

  if (idleCount === 0) {
    // No idle processor — need to spawn. Create one partition per subagent_id + one for regular ops.
    if (regularOps.length > 0) partitions.push({ id: 'regular', ops: regularOps });
    for (const subagentId of subagentIds) {
      const ops = allOps.filter(op => op.context_bundle?.subagent_id === subagentId);
      if (ops.length > 0) partitions.push({ id: subagentId, ops });
    }
  } else {
    // At least one idle processor exists — new ops will be picked up via deliverOp routing
    log(`[spawn] pool has ${idleCount} idle processor(s), queueing ${allOps.length} op(s) for existing pool`);
    return;
  }

  if (partitions.length === 0) return;

  // Spawn one processor per partition in parallel (no global lock during spawn)
  for (const { id: partitionId, ops } of partitions) {
    const partitionKey = opSurface(ops[0]) + ':' + partitionId;
    if (spawningPartitions.has(partitionKey)) continue;  // already spawning this partition
    spawningPartitions.add(partitionKey);
    spawnProcessorPartition(partitionId, ops, () => spawningPartitions.delete(partitionKey));
  }
}

function spawnProcessorPartition(partitionId, ops, onDone) {
  const op = ops[0];
  const kind   = op.intent?.op || '?';
  const target = op.intent?.target_ref || '?';
  const hasHandAgent = op.context_bundle?.loom_hand || op.context_bundle?.loom_artifact;
  processorSeq++;
  const procId = '__proc__' + processorSeq;  // unique agentId for this spawned processor

  const msg = hasHandAgent
    ? `Loom agent rendering hand agent data`
    : `Generating page (${kind})`;
  log(`[spawn] ${msg} partition=${partitionId} (${ops.length} op(s))`);
  addSpawnEvent({ status: 'start', msg, op_count: ops.length, partition: partitionId });

  const prompt = buildProcessorPrompt(ops);
  const claudeBin = process.env.ANCHOR_CLAUDE_BIN || 'claude';

  // Use bash on all platforms (including Windows with Git Bash / MSYS2).
  // Write prompt to a temp file to avoid shell quoting issues with large prompts.
  let spawnBin, spawnArgs, promptFile;
  promptFile = path.join(ROOT, 'output', `proc-${Date.now()}.txt`);
  try { fs.writeFileSync(promptFile, prompt, 'utf8'); } catch {}
  spawnBin  = 'bash';
  // $0 = promptFile, $1 = claudeBin — avoids all shell quoting issues with spaces/special chars
  spawnArgs = ['-c', 'p=$(cat "$0"); "$1" -p "$p" --dangerously-skip-permissions < /dev/null', promptFile, claudeBin];

  let child;
  try {
    child = spawn(spawnBin, spawnArgs, {
      cwd: ROOT,
      env: { ...process.env, ANCHOR_AGENT_ID: procId, ANCHOR_PORT: String(PORT), ANCHOR_PROCESSOR: '1' },
      shell: false,
      stdio: 'pipe',
      windowsHide: true
    });
    // Register this processor in the pool — ws will be set when it connects
    processorPool.set(procId, { ws: null, partition: partitionId, ops, surface: opSurface(op) });
  } catch (e) {
    log('[spawn] failed to start CC: ' + e.message);
    addSpawnEvent({ status: 'error', msg: 'spawn failed: ' + e.message });
    if (onDone) onDone();
    return;
  }

  const pid = child.pid;
  const procRegistryId = registerProcess({
    role: 'processor',
    pid,
    command: `${spawnBin} ${spawnArgs.join(' ')}`,
    metadata: { partition: partitionId, op: kind, target }
  }, child);
  addSpawnEvent({ status: 'running', msg: hasHandAgent ? 'Loom agent processing' : 'Generating content', pid });

  let stdoutBuf = '';
  let stderrBuf = '';
  if (child.stdout) child.stdout.on('data', d => { stdoutBuf += d.toString(); });
  if (child.stderr) child.stderr.on('data', d => {
    const s = d.toString().trim().slice(0, 300);
    stderrBuf += s + '\n';
    log(`[proc:${pid}] err: ${s}`);
  });

  child.on('exit', (code) => {
    if (promptFile) try { fs.unlinkSync(promptFile); } catch {}
    unregisterProcess(procRegistryId, { exit_code: code });
    const output = stdoutBuf.trim();
    const hadPoolEntry = processorPool.has(procId);
    const remainingAll = pendingOps.slice();
    log(`[spawn] pid=${pid} procId=${procId} partition=${partitionId} exited code=${code}, stdout=${output.length} chars`);

    processorPool.delete(procId);

    if (code === 0 && hadPoolEntry) {
      addSpawnEvent({ status: 'done', msg: hasHandAgent ? 'Loom agent complete' : 'Generation complete', pid });
    } else if (code === 0) {
      addSpawnEvent({ status: 'error', msg: `pid=${pid} exited without WS connection (${output.slice(0, 120)})`, pid });
    } else {
      const errSnip = stderrBuf.trim().slice(0, 200);
      addSpawnEvent({ status: 'error', msg: `pid=${pid} exited code=${code} (${output.slice(0, 120)})`, pid, stderr: errSnip });
    }

    if (remainingAll.length > 0) {
      const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;
      if (idleCount === 0) setTimeout(spawnCCProcessor, 300);
    }
    if (onDone) onDone();
  });

  child.on('error', (e) => {
    log('[spawn] error: ' + e.message);
    addSpawnEvent({ status: 'error', msg: e.message, pid });
    unregisterProcess(procRegistryId, { status: 'error', error: e.message });
    processorPool.delete(procId);
    if (pendingOps.length > 0) setTimeout(spawnCCProcessor, 300);
  });
}


function recoverPendingFallback() {
  if (!fs.existsSync(PENDING_OP_JSON)) return;
  try {
    const op = JSON.parse(fs.readFileSync(PENDING_OP_JSON, 'utf8'));
    const opId = op?.provenance?.event_id || op?.id || op?.op_id || null;
    const alreadyQueued = pendingOps.some(existing => {
      const existingId = existing?.provenance?.event_id || existing?.id || existing?.op_id || null;
      return opId && existingId === opId;
    });
    if (alreadyQueued) return;
    pendingOps.push(op);
    log('recovered pending fallback op: ' +
        ((op.intent && op.intent.op) || op.op || '?') + ' -> ' +
        ((op.intent && op.intent.target_ref) || op.target || '?'));
  } catch (e) {
    log('recover pending fallback failed: ' + e.message);
  }
}

function formatOpAsPrompt(op) {
  const instruction = op.args?.instruction || op.args?.value || '(no instruction)';
  const sel = op.selection ? `\n**Selection**: "${op.selection.text}"` : '';
  return `## Anchor User Action\n\n**Operation**: \`${op.op}\`\n**Target**: \`${op.target}\`${sel}\n**Instruction**: ${instruction}\n\n### Current HTML\n\`\`\`html\n${currentHtml}\n\`\`\`\n\n### Instructions\n\n1. Generate the modified HTML fragment for \`${op.target}\`.\n2. Call \`anchor_patch({patches:[{anchor_id:"${op.target}",html_fragment:"<new complete outerHTML>"}]})\`.\n3. Call \`anchor_await_op()\` to wait for the next user action.\n`;
}

// ── Push infrastructure init ──────────────────────────────────────────
inbox.load();
pushBroker = new PushBroker({ inbox, pendingOps, notifyPendingChanged, broadcastBrowserMessage });
scheduler.init(pushBroker);
connectorRegistry.loadAll(pushBroker, scheduler);

// ── File watcher ──────────────────────────────────────────────────────

function watchHtmlFile() {
  let lastMtime = 0;
  try { lastMtime = fs.statSync(CURRENT_HTML).mtimeMs; } catch {}
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
  }, 500);
}

function normalizeLocalVisualUrl(value) {
  try {
    const parsed = new URL(String(value || ''), `http://localhost:${PORT}`);
    const hostOk = ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname);
    const portOk = parsed.port === String(PORT) || (!parsed.port && PORT === 80);
    if (!hostOk || !portOk || !parsed.pathname.startsWith('/loom-visual/')) return '';
    parsed.hash = '';
    return parsed.toString();
  } catch {
    return '';
  }
}

function openBrowserUrl(url) {
  const cmd = process.platform === 'win32' ? `start "" "${url}"`
            : process.platform === 'darwin' ? `open "${url}"`
            : `xdg-open "${url}"`;
  exec(cmd, (err) => {
    if (err) log(`auto-open failed (non-fatal): ${err.message}`);
    else log(`opened browser at ${url}`);
  });
}

function maybeAutoOpenBrowser() {
  if (process.env.ANCHOR_NO_AUTO_BROWSER === '1') return;
  setTimeout(() => {
    if (webviewClients.size > 0) return;
    const url = process.env.ANCHOR_OPEN_URL || `http://localhost:${PORT}`;
    if (process.env.ANCHOR_OPEN_URL && !normalizeLocalVisualUrl(url)) {
      log(`ignored invalid ANCHOR_OPEN_URL: ${url}`);
      openBrowserUrl(`http://localhost:${PORT}`);
      return;
    }
    openBrowserUrl(url);
  }, 800);
}

// ── Session management ────────────────────────────────────────────────

const MANIFEST_FLUSH_INTERVAL = 10;

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
    anchor_version: '1.0.0', event_count: 0
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
  fs.writeFileSync(eventsPath, '', 'utf8');
  currentSession = { id, dir, manifestPath, eventsPath, manifest, _flushCounter: 0 };
  lastUserIntentId = null;
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
  if (kind === 'user.intent') {
    const envPath = path.join(currentSession.dir, 'envelopes', eventId + '.json');
    try { fs.writeFileSync(envPath, JSON.stringify(payload, null, 2), 'utf8'); } catch {}
  }
  try { fs.appendFileSync(currentSession.eventsPath, JSON.stringify(event) + '\n', 'utf8'); } catch {}
  currentSession._flushCounter = (currentSession._flushCounter || 0) + 1;
  currentSession.manifest.event_count = (currentSession.manifest.event_count || 0) + 1;
  if (currentSession._flushCounter >= MANIFEST_FLUSH_INTERVAL) {
    currentSession._flushCounter = 0;
    try { fs.writeFileSync(currentSession.manifestPath, JSON.stringify(currentSession.manifest, null, 2), 'utf8'); } catch {}
  }
  return eventId;
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
        const evtPath = path.join(dir, 'events.jsonl');
        const evt = {
          event_id: generateEventId(), session_id: manifest.id,
          timestamp: new Date().toISOString(), kind: 'system.session_end',
          parent_event_id: null,
          payload: { recovered: true, reason: 'previous session did not shut down cleanly' }
        };
        fs.appendFileSync(evtPath, JSON.stringify(evt) + '\n', 'utf8');
        manifest.ended_at = new Date().toISOString();
        manifest.event_count += 1;
        fs.writeFileSync(mf, JSON.stringify(manifest, null, 2), 'utf8');
        log('recovered residual session: ' + manifest.id);
      }
    } catch {}
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
    } catch {}
  }
  return null;
}

function generateEventId() {
  return 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
}

// ── Envelope validation ───────────────────────────────────────────────

function loadEnvelopeSchema() {
  const schemaPath = path.join(SCHEMAS_DIR, 'intent-envelope.json');
  if (!fs.existsSync(schemaPath)) { log('envelope schema not found, validation disabled'); return; }
  try {
    envelopeSchema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
    log('envelope schema loaded');
  } catch (e) { log('failed to load envelope schema: ' + e.message); }
}

function validateEnvelope(instance) {
  function check(schema, inst, p) {
    if (schema.required) {
      for (const r of schema.required) {
        if (!(r in (inst || {})))
          return { ok: false, code: 'MISSING_REQUIRED', message: r + ' is required', details: { path: p + '.' + r } };
      }
    }
    if (inst === null || inst === undefined) {
      if (schema.type) {
        const types = Array.isArray(schema.type) ? schema.type : [schema.type];
        if (!types.includes('null') && !types.includes('object'))
          return { ok: false, code: 'WRONG_TYPE', message: p + ' is null', details: { path: p, expected: types } };
      }
      return { ok: true };
    }
    if (schema.enum && !schema.enum.includes(inst))
      return { ok: false, code: 'INVALID_ENUM', message: p + ' must be one of: ' + schema.enum.join(', '), details: { path: p, allowed: schema.enum, got: inst } };
    if (schema.const !== undefined && inst !== schema.const)
      return { ok: false, code: 'INVALID_CONST', message: p + ' must be ' + schema.const, details: { path: p, expected: schema.const, got: inst } };
    if (schema.maxLength !== undefined && typeof inst === 'string' && inst.length > schema.maxLength)
      return { ok: false, code: 'TOO_LONG', message: p + ' exceeds max length ' + schema.maxLength, details: { path: p, max: schema.maxLength, got: inst.length } };
    if (schema.type) {
      const types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.some(t => matchType(t, inst)))
        return { ok: false, code: 'WRONG_TYPE', message: p + ' must be ' + types.join('|'), details: { path: p, expected: types, got: typeof inst } };
    }
    if (schema.properties && inst && typeof inst === 'object') {
      for (const [key, propSchema] of Object.entries(schema.properties)) {
        if (key in inst) {
          const r = check(propSchema, inst[key], p + '.' + key);
          if (!r.ok) return r;
        }
      }
    }
    return { ok: true };
  }
  return check(envelopeSchema || SCHEMA_STUB, instance, '');
}

function matchType(t, val) {
  if (t === 'string')  return typeof val === 'string';
  if (t === 'integer') return typeof val === 'number' && Number.isInteger(val);
  if (t === 'number')  return typeof val === 'number';
  if (t === 'boolean') return typeof val === 'boolean';
  if (t === 'array')   return Array.isArray(val);
  if (t === 'object')  return val !== null && typeof val === 'object' && !Array.isArray(val);
  if (t === 'null')    return val === null;
  return false;
}

const SCHEMA_STUB = {
  type: 'object',
  required: ['intent', 'provenance', 'schema_version'],
  properties: {
    schema_version: { const: '1.0' },
    domain: { type: ['object', 'null'] },
    intent: {
      type: 'object',
      required: ['op', 'target_kind'],
      properties: {
        op: { enum: ['refine','expand','shorten','longer','edit','lock','annotate','branch','restructure','ask','custom','initial_render','debate','debate_abort'] },
        instruction: { type: 'string', maxLength: 4000 },
        target_kind: { enum: ['anchor','selection','global','group'] },
        target_ref: { type: 'string' }
      }
    },
    selection: {
      type: ['object', 'null'],
      properties: {
        text: { type: 'string' }, start_offset: { type: 'integer' },
        end_offset: { type: 'integer' }, ancestor_anchor: { type: ['string', 'null'] },
        dom_path: { type: 'string' }
      }
    },
    context_bundle: {
      type: 'object',
      properties: {
        memory_ids: { type: 'array' }, skill_ids: { type: 'array' },
        subagent_ids: { type: 'array' }, resource_ids: { type: 'array' },
        scope_hint: { enum: ['minimal','standard','wide'] },
        transient_override: { type: 'boolean' },
        subagent_id: { type: ['string', 'null'] },
        context_mode: { type: ['string', 'null'] },
        file_id: { type: ['string', 'null'] },
        card_anchor_ids: { type: 'array' }
      }
    },
    render_state: {
      type: 'object',
      properties: {
        anchor_tree: { type: 'array' },
        dom_signature: { type: 'string' },
        anchor_index: { type: 'object' },
        selected_subtrees: { type: 'object' }
      }
    },
    provenance: {
      type: 'object',
      required: ['session_id', 'event_id', 'timestamp'],
      properties: {
        session_id: { type: 'string' }, event_id: { type: 'string' },
        parent_event_id: { type: ['string', 'null'] }, timestamp: { type: 'string' },
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

  // ── Canvas co-design mode ──────────────────────────────────────
  if (bundle.context_mode === 'canvas') {
    const snap = canvasState.getSnapshot();
    const stateCtx = snap.cards.length > 0
      ? '\n### Canvas State (' + snap.cards.length + ' cards)\n' +
        '```json\n' + JSON.stringify(snap.cards.map(c => ({
          id: c.anchor_id, x: c.x, y: c.y, w: c.w,
          ...(c.h > 0 ? {h: c.h} : {}),
          ...(c.rot !== 0 ? {rot: c.rot} : {}),
          ...(c.scale !== 1 ? {scale: c.scale} : {}),
        })), null, 2).substring(0, 3000) + '\n```\n'
      : '';
    const cardContext = (() => {
      const subtree = rs.relevant_subtree;
      if (!subtree || !subtree.target_html || subtree.target_html.length < 50) return '';
      return '\n### Current Canvas HTML\n```html\n' + subtree.target_html.substring(0, 6000) + '\n```\n';
    })();
    const isGroup = intent.target_kind === 'group';
    const targetRefs = intent.target_refs || [];
    const selectedCtx = (() => {
      const subs = rs.selected_subtrees || {};
      const ids = Object.keys(subs);
      if (ids.length === 0) return '';
      return '\n### Selected Cards\n' + ids.map(id =>
        '**`' + id + '`**:\n```html\n' + ((subs[id].target_html || '').substring(0, 2000)) + '\n```'
      ).join('\n') + '\n';
    })();
    const groupInstruction = isGroup && targetRefs.length > 0
      ? '\n**Mode: GROUP** — patch these ' + targetRefs.length + ' card(s): `' + targetRefs.join('`, `') + '`\n' +
        'Call `anchor_patch({patches:[...]})` with one entry per selected card. Preserve their `data-anc-x/y/rot/scale` unless the instruction explicitly requests movement.\n'
      : '';
    return [
      '## Canvas Co-design Request',
      '',
      '**Op**: ' + (intent.op || 'initial_render'),
      '**Instruction**: ' + (intent.instruction || '(none)'),
      groupInstruction,
      stateCtx,
      cardContext,
      selectedCtx,
      '## Canvas HTML Format',
      '',
      'All cards must be children of `<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:3000px;height:2000px;">`.',
      '',
      'Each card:',
      '```html',
      '<div class="anc-card anc-section anc-section--gc"',
      '     data-anc="card-[unique-slug]"',
      '     data-handles="refine,expand,shorten"',
      '     data-anc-x="80"',
      '     data-anc-y="80"',
      '     data-anc-w="320"',
      '     data-anc-rot="0"',
      '     data-anc-scale="1"',
      '     data-anc-z="1"',
      '     style="position:absolute;left:80px;top:80px;width:320px;transform:rotate(0deg) scale(1);">',
      '  <!-- Bloom CSS card content (h2, p, anc-kpi-grid, etc.) -->',
      '</div>',
      '```',
      '',
      '**Placement**: 4-column grid, step (360px, 280px) starting at (80,80). No overlap.',
      '**For initial_render / global ops**: Generate all cards, wrap in a full HTML document, and call `anchor_render(html)`.',
      '**For refine/patch ops on existing cards**: Call `anchor_patch({patches:[...]})` — preserve user-set data-anc-x/y/rot/scale unless instruction explicitly asks to move.',
      '**To create a new card**: call `anchor_patch` with a new unique anchor_id not already in Canvas State.',
      '**To propose a layout rearrangement**: call `anchor_emit_event("layout_suggest", {suggestion_id, moves:[{anchor_id,x,y},...]})`; do NOT directly patch positions.',
      '',
      anchorLayoutContract(),
    ].join('\n');
  }

  if (intent.op === 'initial_render') {
    let prompt = `## Anchor Initial Render Request\n\n**Instruction**: ${intent.instruction || '(none)'}\n\n`;

    // Include selected card anchors if present
    const cardIds = bundle.card_anchor_ids || [];
    const cardSubtrees = rs.selected_subtrees || {};
    if (cardIds.length > 0) {
      prompt += '### Selected Card Anchors (User Context)\n';
      cardIds.forEach(id => { prompt += '- **`' + id + '`**\n'; });
      prompt += '\n';
      Object.entries(cardSubtrees).forEach(([id, subtree]) => {
        if (subtree && subtree.target_html) {
          const limit = 3000;
          const html = subtree.target_html.length > limit
            ? subtree.target_html.substring(0, limit) + '\n... (truncated)'
            : subtree.target_html;
          prompt += '**`' + id + '`**:\n```html\n' + html + '\n```\n\n';
        }
      });
      prompt += 'The user has selected these ' + cardIds.length +
        ' card(s) as reference context. Consider their content when generating your response.\n\n';
    }

    prompt += anchorLayoutContract() + '\n\nGenerate a complete Anchor HTML page and call `anchor_render(html)`.\n';
    return prompt;
  }

  const subagentId = bundle.subagent_id || null;
  if (subagentId) {
    const subtree = rs.relevant_subtree || null;
    const targetNodeHtml = subtree && subtree.target_html ? subtree.target_html : null;
    let htmlCtx = targetNodeHtml
      ? `### Target Node HTML\n\`\`\`html\n${targetNodeHtml}\n\`\`\`\n\n`
      : `### Current HTML\n\`\`\`html\n${currentHtml.substring(0, 8000)}\n\`\`\`\n\n`;
    if (subtree?.forward_deps && Object.keys(subtree.forward_deps).length > 0) {
      htmlCtx += '### Forward Dependencies\n';
      Object.entries(subtree.forward_deps).forEach(([depId, depHtml]) => {
        htmlCtx += `**\`${depId}\`**:\n\`\`\`html\n${depHtml}\n\`\`\`\n\n`;
      });
    }
    const targetRef = intent.target_ref || '(target)';
    return [
      `## Anchor Subagent Op: ${intent.op} on \`${targetRef}\``,
      ``,
      `**Subagent**: ${subagentId}`,
      `**Instruction**: ${intent.instruction || '(no instruction)'}`,
      ``,
      htmlCtx,
      `## Your Task`,
      `1. Generate the modified HTML fragment for \`${targetRef}\`.`,
      `   Preserve every \`data-anc\`, \`data-handles\`, \`data-deps\` attribute and CSS class.`,
      ``,
      anchorLayoutContract(),
      ``,
      `2. Call \`anchor_emit_event\` with type=\`thinking\`, then call \`anchor_patch\`.`,
      `3. Call \`anchor_emit_event\` with type=\`complete\`.`,
      `4. Reply with one line: "Patched \`${targetRef}\`."`,
      ``,
      `**NEVER call \`anchor_render\`.**`,
    ].join('\n');
  }

  let out = '## Anchor User Action\n\n';
  out += `**Op**: \`${intent.op || '(unknown)'}\` on \`${intent.target_ref || '(none)'}\`\n`;
  if (intent.instruction) out += `**Instruction**: ${intent.instruction}\n`;
  out += '\n';
  if (sel && sel.text) out += `**Selection**: "${sel.text.substring(0, 200)}"${sel.text.length > 200 ? '…' : ''}\n\n`;
  const mem = bundle.memory_ids || [];
  const skl = bundle.skill_ids || [];
  const res = bundle.resource_ids || [];
  if (bundle.file_id) out += '**Workspace file**: `' + bundle.file_id + '`\n';
  if (mem.length) out += '**Memory**: ' + mem.map(id => '`' + id + '`').join(', ') + '\n';
  if (skl.length) out += '**Skills**: ' + skl.map(id => '`' + id + '`').join(', ') + '\n';
  if (res.length) out += '**Resources**: ' + res.map(id => '`' + id + '`').join(', ') + '\n';
  if (bundle.file_id || mem.length || skl.length || res.length) out += '\n';

  // Card anchor context (user-selected page content)
  const cardAnchorIds = bundle.card_anchor_ids || [];
  const selectedSubtrees = rs.selected_subtrees || {};
  if (cardAnchorIds.length > 0) {
    out += '### Selected Card Anchors (User Context)\n';
    cardAnchorIds.forEach(id => { out += '- **`' + id + '`**\n'; });
    out += '\n';
    Object.entries(selectedSubtrees).forEach(([id, subtree]) => {
      if (subtree && subtree.target_html) {
        const limit = 3000;
        const html = subtree.target_html.length > limit
          ? subtree.target_html.substring(0, limit) + '\n... (truncated)'
          : subtree.target_html;
        out += '**`' + id + '`**:\n```html\n' + html + '\n```\n\n';
      }
    });
    out += 'The user has selected these ' + cardAnchorIds.length +
      ' card(s) as reference context. Consider their content when generating your response.\n\n';
  }

  const subtree = rs.relevant_subtree || null;
  const targetNodeHtml = subtree && subtree.target_html ? subtree.target_html : null;
  if (targetNodeHtml) {
    out += '### Target Node HTML\n```html\n' + targetNodeHtml + '\n```\n\n';
    if (subtree.forward_deps && Object.keys(subtree.forward_deps).length > 0) {
      out += '### Forward Dependencies\n';
      Object.entries(subtree.forward_deps).forEach(([depId, depHtml]) => {
        out += '**`' + depId + '`**:\n```html\n' + depHtml + '\n```\n\n';
      });
    }
  } else {
    out += '### Current HTML\n```html\n' + currentHtml.substring(0, MAX_HTML);
    if (currentHtml.length > MAX_HTML) out += '\n… (truncated)';
    out += '\n```\n\n';
  }

  const targetRef = intent.target_ref || '(target)';
  out += '### Instructions\n\n';
  out += `1. Generate the modified HTML fragment for \`${targetRef}\`. Preserve all \`data-anc\`, \`data-handles\`, \`data-deps\` attrs and CSS classes.\n`;
  out += anchorLayoutContract() + '\n';
  out += `2. Call \`anchor_patch({patches:[{anchor_id:"${targetRef}",html_fragment:"<new complete outerHTML>"}]})\`. Add reverse-dep patches in same call if needed.\n`;
  out += '3. Call `anchor_await_op()` to wait for the next user action.\n\n';
  out += '**NEVER call `anchor_render`. Dispatch Agent subagents only when `context_bundle.subagent_id` is set.**\n';
  return out;
}

// ── Manifest loaders ──────────────────────────────────────────────────

const USER_CLAUDE    = 'C:\\Users\\qi\\.claude';
const USER_MEMORY    = path.join(USER_CLAUDE, 'memory');
const USER_SKILLS    = path.join(USER_CLAUDE, 'skills');
const PROJECT_SKILLS = path.join(ROOT, '.claude', 'skills');
const PROJECT_AGENTS = path.join(ROOT, '.claude', 'agents');
const PINNED_RESOURCES = path.join(PROMPTS_DIR, 'pinned-resources.json');

const BUILTIN_SUBAGENTS = [
  { id: 'anchor-writer',     name: 'Anchor Writer',     description: 'AI subagent for generating HTML patches in Anchor webview',           can_patch: true  },
  { id: 'Explore',          name: 'Explore',          description: 'Fast agent for exploring codebases',                                can_patch: false },
  { id: 'general-purpose',  name: 'General Purpose',  description: 'General-purpose agent for complex multi-step tasks',              can_patch: true  },
  { id: 'Plan',             name: 'Plan',             description: 'Software architect agent for designing implementation plans', can_patch: false },
  { id: 'claude-code-guide',name: 'Claude Code Guide',description: 'Answers questions about Claude Code CLI, SDK, and API',      can_patch: false },
  { id: 'statusline-setup', name: 'Statusline Setup', description: 'Configures the Claude Code status line',                    can_patch: false }
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
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
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
        items.push({ id, name: fm.name || id, description: fm.description || '',
                     type: fm.type || 'unknown', source_path: fp, size_bytes: stat.size });
      } catch {}
    });
  });
  return items;
}

function loadSkillsManifest() {
  const items = [];
  [{ dir: USER_SKILLS, source: 'user' }, { dir: PROJECT_SKILLS, source: 'project' }].forEach(({ dir, source }) => {
    if (!fs.existsSync(dir)) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    entries.filter(e => e.isDirectory()).forEach(e => {
      const skillMd = path.join(dir, e.name, 'SKILL.md');
      if (!fs.existsSync(skillMd)) return;
      try {
        const raw = fs.readFileSync(skillMd, 'utf8');
        const fm = parseFrontmatter(raw);
        items.push({ id: e.name, name: fm.name || e.name, description: fm.description || '', source, source_path: skillMd });
      } catch {}
    });
  });
  const reg = ensureContextRegistry();
  for (const skill of reg.skills) {
    if (!skill || !skill.id) continue;
    items.push({
      id: skill.id,
      name: skill.name || skill.id,
      description: skill.description || skill.url || '',
      source: 'custom',
      source_path: skill.url || '',
      status: skill.status || 'pending',
      url: skill.url || ''
    });
  }
  return items;
}

function loadSubagentsManifest() {
  const byId = new Map(BUILTIN_SUBAGENTS.map(a => [a.id, { ...a, source: 'builtin' }]));
  if (fs.existsSync(PROJECT_AGENTS)) {
    let files;
    try { files = fs.readdirSync(PROJECT_AGENTS).filter(f => f.endsWith('.md')); } catch { files = []; }
    files.forEach(f => {
      const fp = path.join(PROJECT_AGENTS, f);
      try {
        const raw = fs.readFileSync(fp, 'utf8');
        const fm = parseFrontmatter(raw);
        const id = f.replace(/\.md$/, '');
        const toolsField = fm.tools || '*';
        const can_patch = toolsField === '*' || toolsField === '"*"' || toolsField.includes('mcp__anchor__anchor_patch');
        byId.set(id, { id, name: fm.name || id, description: fm.description || '', custom: true, source: 'project', source_path: fp, can_patch });
      } catch {}
    });
  }
  return Array.from(byId.values());
}

function loadResourcesManifest() {
  const items = [
    { id: 'anchor://current-html', name: 'Current rendered HTML', mimeType: 'text/html',        scope: 'session' },
    { id: 'anchor://pending-op',   name: 'Pending user operation', mimeType: 'application/json', scope: 'session' }
  ];
  if (fs.existsSync(PINNED_RESOURCES)) {
    try {
      const pinned = JSON.parse(fs.readFileSync(PINNED_RESOURCES, 'utf8'));
      if (Array.isArray(pinned)) items.push(...pinned);
    } catch {}
  }
  const reg = ensureContextRegistry();
  for (const resource of reg.resources) {
    if (!resource || !resource.id) continue;
    items.push({
      id: resource.id,
      name: resource.name || resource.id,
      description: resource.description || resource.url || '',
      mimeType: resource.mimeType || 'text/uri-list',
      scope: resource.scope || 'workspace',
      source: 'custom',
      status: resource.status || 'pending',
      url: resource.url || ''
    });
  }
  return items;
}

// ── Logging ───────────────────────────────────────────────────────────

function logOp(op) {
  try {
    const line = JSON.stringify({ t: new Date().toISOString(), ...op }) + '\n';
    fs.appendFileSync(OPS_LOG, line, 'utf8');
  } catch (e) { log('logOp failed: ' + e.message); }
}

// ── Bootstrap ─────────────────────────────────────────────────────────

process.on('SIGINT', () => {
  if (shuttingDown) return;
  shuttingDown = true;
  runShutdown('SIGINT').catch(() => process.exit(1));
});

process.on('SIGTERM', () => {
  if (shuttingDown) return;
  shuttingDown = true;
  runShutdown('SIGTERM').catch(() => process.exit(1));
});

httpServer.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    log(`ERROR: port ${PORT} already in use. Stop any other Anchor process first.`);
    process.exit(1);
  } else if (err) {
    log('server error: ' + err.message);
  }
});

httpServer.listen(PORT, () => {
  registerProcess({
    id: 'anchor-service:' + process.pid,
    role: 'anchor-service',
    pid: process.pid,
    command: `node mcp/server.cjs`,
    metadata: { port: PORT }
  });
  log(`Anchor service running at http://localhost:${PORT}`);
  log(`  Browser WS : ws://localhost:${PORT}/`);
  log(`  Agent WS   : ws://localhost:${PORT}/ws/agent`);
  initSession();
  loadEnvelopeSchema();

  // Trading domain extension — initialize if available (migration to Python Core)
  if (tradingEvents) {
    try {
      tradingEvents.initialize({
        recordEvent: recordEvent,
        generateEventId: generateEventId,
        createId: createId,
        nowIso: nowIso,
        get currentSession() { return currentSession; }
      });
    } catch (e) { log('tradingEvents init failed: ' + e.message); }
  }
  if (tradingRoutes) {
    try {
      tradingRoutes.mountTradingRoutes(app, {
        tradingEvents: tradingEvents,
        policyGate: tradingPolicyGate,
        recordEvent: recordEvent,
        get currentSession() { return currentSession; }
      });
    } catch (e) { log('tradingRoutes mount failed: ' + e.message); }
  }

  recoverPendingFallback();
  maybeAutoOpenBrowser();
  watchHtmlFile();
});
