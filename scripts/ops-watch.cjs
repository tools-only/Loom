#!/usr/bin/env node
// ops-watch.cjs — real-time terminal dashboard for Anchor/Loom
// Usage: node scripts/ops-watch.cjs [interval_ms]
//        Default interval 1000ms. Like `watch -n 1 nvidia-smi` for Anchor.
//
// Connects to ws://localhost:3000 for sub-100ms event push,
// polls REST for full-state sync at the given interval.

'use strict';

const http = require('http');
const WS_PORT = parseInt(process.env.ANCHOR_PORT || '3000');
const INTERVAL = parseInt(process.argv[2]) || 1000;
const HOST = '127.0.0.1';
const BASE = `http://${HOST}:${WS_PORT}`;

// ── ANSI helpers ────────────────────────────────────────────────────
const CSI = '\x1b[';
const HOME = CSI + 'H';
const CLEAR = CSI + '2J';
const HIDE_CURSOR = CSI + '?25l';
const SHOW_CURSOR = CSI + '?25h';
const RESET = CSI + '0m';
const BOLD = CSI + '1m';
const DIM = CSI + '2m';

function color(c, s) { return CSI + c + 'm' + s + RESET; }
const green = s => color('32', s);
const yellow = s => color('33', s);
const red = s => color('31', s);
const blue = s => color('36', s);
const purple = s => color('35', s);
const gray = s => color('90', s);
const white = s => color('37;1', s);

function bar(val, max, w) {
  w = w || 10;
  const pct = max > 0 ? val / max : 0;
  const filled = Math.round(pct * w);
  const rest = w - filled;
  const c = pct > 0.8 ? '31' : pct > 0.5 ? '33' : '32';
  return color(c, '█'.repeat(filled)) + gray('░'.repeat(rest));
}

function pad(s, n) { s = String(s); return s.length >= n ? s : s + ' '.repeat(n - s.length); }
function rpad(s, n) { s = String(s); return s.length >= n ? s : ' '.repeat(n - s.length) + s; }

// ── State ──────────────────────────────────────────────────────────
const S = {
  health: null, agents: null, status: null, spawnLog: null, processes: null,
  wsLive: false, wsEvents: [], fetchErrors: {}, lastFetch: null, frames: 0,
  startedAt: Date.now(),
};

// ── HTTP fetch ─────────────────────────────────────────────────────
function fetchJSON(path) {
  return new Promise((resolve) => {
    http.get(BASE + path, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (_) { resolve(null); }
      });
    }).on('error', () => resolve(null)).on('timeout', function() { this.destroy(); resolve(null); });
  });
}

async function fetchAll() {
  const [health, agents, status, spawnLog, processes] = await Promise.all([
    fetchJSON('/health'), fetchJSON('/agents'), fetchJSON('/debug/status'),
    fetchJSON('/debug/spawn-log'), fetchJSON('/debug/processes'),
  ]);
  S.health = health; S.agents = agents; S.status = status;
  S.spawnLog = spawnLog; S.processes = processes;
  S.lastFetch = Date.now();
}

// ── Rendering ───────────────────────────────────────────────────────
function render() {
  S.frames++;
  const now = Date.now();
  const uptime = Math.floor((now - S.startedAt) / 1000);
  const uh = Math.floor(uptime / 3600), um = Math.floor((uptime % 3600) / 60), us = uptime % 60;

  let out = '';
  out += HOME;

  // ═══ Header ═══
  out += white('Loom Ops Watch') + gray('  │  ');
  out += 'port ' + blue(':' + WS_PORT) + '  ';
  out += 'refresh ' + INTERVAL + 'ms  ';
  out += 'uptime ' + uh + 'h ' + um + 'm ' + us + 's  ';
  out += 'frames ' + S.frames + '  ';
  out += 'WS ' + (S.wsLive ? green('● LIVE') : yellow('◉ RECONNECTING')) + '\n';
  out += gray('─'.repeat(process.stdout.columns > 0 ? process.stdout.columns - 1 : 80)) + '\n\n';

  // ═══ Alerts ═══
  if (!S.health || !S.health.ok) {
    out += red('  ╳  SERVER UNREACHABLE') + ' — ' + gray(new Date().toLocaleTimeString()) + '\n\n';
  } else if (S.health.shutting_down) {
    out += yellow('  ⚠  Server shutting down') + '\n\n';
  }

  // ═══ Row 1: Server + Inproc + Pool ═══
  const w = Math.floor((process.stdout.columns || 120) / 3) - 2;
  out += box('SERVER', renderServer(), w) + '  ' + box('INPROC AGENT', renderAgent(), w) + '  ' + box('PROCESSOR POOL', renderPool(), w) + '\n\n';

  // ═══ Row 2: Processes ═══
  out += box('OS PROCESSES', renderProcesses(), (process.stdout.columns || 120) - 2) + '\n\n';

  // ═══ Row 3: Spawn Log + WS Events ═══
  const halfW = Math.floor((process.stdout.columns || 120) / 2) - 2;
  out += box('SPAWN LOG (last 8)', renderSpawnLog(), halfW) + '  ' + box('WS EVENTS (last 12)', renderWSEvents(), halfW) + '\n';

  // ═══ Footer ═══
  out += '\n' + gray('─'.repeat(process.stdout.columns > 0 ? process.stdout.columns - 1 : 80)) + '\n';
  out += gray('last fetch: ') + (S.lastFetch ? ago(now - S.lastFetch) : 'never') + gray(' ago');
  out += gray('  │  q: quit  r: force refresh');
  out += '\n';

  process.stdout.write(out);
}

function box(title, content, width) {
  const top = '┌─ ' + white(title) + ' ' + '─'.repeat(Math.max(0, width - title.length - 3)) + '┐\n';
  const lines = content.split('\n').map(l => '│ ' + pad(l, width - 1) + '│\n');
  const bot = '└' + '─'.repeat(width) + '┘\n';
  return top + lines.join('') + bot;
}

function ago(ms) { return ms < 1000 ? Math.floor(ms) + 'ms' : ms < 60000 ? (ms / 1000).toFixed(1) + 's' : Math.floor(ms / 60000) + 'm'; }

function renderServer() {
  const h = S.health;
  if (!h) return red('  UNREACHABLE\n');
  return [
    pad('Port:', 14) + blue(':' + h.port) + '\n',
    pad('Pending ops:', 14) + (h.pending_ops > 0 ? yellow(String(h.pending_ops)) : green('0')) + '\n',
    pad('Main agent:', 14) + (h.main_agent_connected ? green('Connected') : red('Disconnected')) + '\n',
    pad('Subagents:', 14) + blue(String(h.subagents_connected?.length || 0)) + '\n',
    pad('WS clients:', 14) + String(h.webview_clients || 0) + '\n',
  ].join('');
}

function renderAgent() {
  const a = S.agents;
  let out = '';
  if (!a) return gray('  No data\n');
  out += pad('CC main:', 14) + (a.main ? green('● Connected') : gray('○ Idle')) + '\n';
  if (a.subagents && a.subagents.length > 0) {
    a.subagents.forEach(s => {
      out += pad(s.label || s.id, 14) + green('● Active') + '\n';
    });
  } else {
    out += pad('Subagents:', 14) + gray('none') + '\n';
  }
  return out;
}

function renderPool() {
  const s = S.status;
  if (!s) return gray('  No data\n');
  return [
    pad('Pool size:', 14) + blue(String(s.pool_size)) + '  idle: ' + (s.pool_idle > 0 ? green(String(s.pool_idle)) : yellow(String(s.pool_idle))) + '\n',
    pad('Spawn lock:', 14) + (s.cc_spawn_lock ? yellow('LOCKED') : green('free')) + '\n',
    pad('Loop:', 14) + (s.loop_enabled ? green('enabled') : red('disabled')) + '\n',
    pad('Pending ops:', 14) + (s.pending_ops > 0 ? yellow(String(s.pending_ops)) : green('0')) + '\n',
    pad('Has HTML:', 14) + (s.has_current_html ? green('yes') : gray('no')) + '\n',
  ].join('');
}

function renderProcesses() {
  const p = S.processes;
  if (!p || !p.processes || p.processes.length === 0) return gray('  None\n');
  let out = pad('PID', 8) + pad('ROLE', 16) + pad('STATUS', 12) + pad('ALIVE', 7) + pad('STARTED', 12) + '\n';
  out += gray('  ' + '─'.repeat(55)) + '\n';
  p.processes.slice(0, 8).forEach(pr => {
    const alive = pr.alive !== false;
    out +=
      pad(String(pr.pid || '-'), 8) +
      pad(pr.role || '-', 16) +
      pad(pr.status || '-', 12) +
      (alive ? green(pad('● yes', 7)) : red(pad('○ no', 7))) +
      pad(pr.started_at ? ago(Date.now() - new Date(pr.started_at).getTime()) : '-', 12) + '\n';
  });
  return out;
}

function renderSpawnLog() {
  const log = S.spawnLog;
  if (!log || !log.entries || log.entries.length === 0) return gray('  Waiting for events...\n');
  let out = '';
  log.entries.slice(0, 8).forEach(e => {
    const ts = e.ts ? new Date(e.ts).toLocaleTimeString() : '--:--:--';
    const tag = colorTag(e.status);
    out += gray(ts) + ' ' + tag + ' ' + (e.msg || '').slice(0, 50) + '\n';
  });
  return out;
}

function renderWSEvents() {
  if (S.wsEvents.length === 0) return gray('  Waiting for events...\n');
  let out = '';
  S.wsEvents.slice(0, 12).forEach(ev => {
    const ts = new Date(ev.ts).toLocaleTimeString();
    let kind = ev.event?.type || ev.event?.kind || '?';
    let detail = '';
    if (ev.event?.type === 'thinking') detail = ev.event?.payload?.summary || '';
    else if (ev.event?.type === 'complete') detail = 'target=' + (ev.event?.payload?.target_anchor || ev.event?.target_anchor || '?') + ' ' + (ev.event?.payload?.summary || '');
    else if (ev.event?.type === 'error') detail = ev.event?.payload?.message || '';
    else if (ev.event?.kind === 'patch') detail = ev.event?.count + ' nodes';
    else detail = '';
    out += gray(ts) + ' ' + purple(kind.slice(0, 12)) + ' ' + detail.slice(0, 55) + '\n';
  });
  return out;
}

function colorTag(status) {
  switch (status) {
    case 'start': return blue('[start]');
    case 'running': return purple('[run  ]');
    case 'done': return green('[done ]');
    case 'error': return red('[error]');
    default: return gray('[' + (status || '?').slice(0, 5) + ']');
  }
}

// ── WebSocket ──────────────────────────────────────────────────────
let wsReconnectTimer = null;

function connectWS() {
  const ws = new (require('ws'))('ws://' + HOST + ':' + WS_PORT);
  ws.on('open', () => {
    S.wsLive = true;
    if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
  });
  ws.on('message', (data) => {
    let msg;
    try { msg = JSON.parse(data); } catch (_) { return; }
    if (msg.type === 'agent_event' && msg.event) {
      S.wsEvents.unshift({ ts: new Date().toISOString(), event: msg.event });
      if (S.wsEvents.length > 60) S.wsEvents.length = 60;
    }
    if (msg.type === 'patch') {
      S.wsEvents.unshift({ ts: new Date().toISOString(), event: { kind: 'patch', count: msg.patches?.length || 0 } });
      if (S.wsEvents.length > 60) S.wsEvents.length = 60;
    }
  });
  ws.on('close', () => {
    S.wsLive = false;
    wsReconnectTimer = setTimeout(connectWS, 2000);
  });
  ws.on('error', () => { ws.close(); });
}

// ── Main loop ───────────────────────────────────────────────────────
async function main() {
  process.stdout.write(HIDE_CURSOR + CLEAR);

  // Check if ws package available
  let wsOK = true;
  try { require.resolve('ws'); } catch (_) { wsOK = false; }

  // Initial fetch before first render
  await fetchAll();

  // Start WS for real-time events if ws package available
  if (wsOK) {
    try { connectWS(); } catch (_) { S.wsLive = false; }
  }

  // Render loop
  setInterval(async () => {
    await fetchAll();
    render();
  }, INTERVAL);

  // First render immediately
  render();

  // Keyboard: q to quit, r to force refresh
  const stdin = process.stdin;
  if (stdin.setRawMode) {
    stdin.setRawMode(true);
    stdin.resume();
    stdin.on('data', (buf) => {
      const key = buf.toString();
      if (key === 'q' || key === '\x03') {
        process.stdout.write(SHOW_CURSOR + CLEAR);
        process.exit(0);
      }
      if (key === 'r') { fetchAll().then(render); }
    });
  }

  // Cleanup on exit
  process.on('SIGINT', () => { process.stdout.write(SHOW_CURSOR + CLEAR); process.exit(0); });
  process.on('exit', () => { process.stdout.write(SHOW_CURSOR); });
}

main().catch(e => { console.error(e); process.exit(1); });
