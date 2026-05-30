#!/usr/bin/env node
// ops-pusher.cjs — sidecar: polls Anchor REST endpoints every 1s,
// pushes aggregated state to dashboard clients via WebSocket on port 3002.
// Zero token cost, zero existing-file changes, Node-driven refresh.
//
// Usage: node scripts/ops-pusher.cjs
// Dashboard: http://localhost:3000/ops-dashboard.html
// The dashboard connects to ws://localhost:3002 for state pushes.

'use strict';

const path = require('path');
const http = require('http');
const BRIDGE_NM = path.join(__dirname, '..', 'bridge', 'node_modules');
const { WebSocketServer } = require(path.join(BRIDGE_NM, 'ws'));

const ANCHOR_PORT = parseInt(process.env.ANCHOR_PORT || '3000');
const PUSHER_PORT = parseInt(process.env.OPS_PUSHER_PORT || '3002');
const INTERVAL = parseInt(process.env.OPS_INTERVAL || '1000');
const HOST = '127.0.0.1';
const BASE = `http://${HOST}:${ANCHOR_PORT}`;

const clients = new Set();
let frame = 0;

// ── HTTP fetch ─────────────────────────────────────────────────────
function fetchJSON(path) {
  return new Promise((resolve) => {
    http.get(BASE + path, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch (_) { resolve(null); } });
    }).on('error', () => resolve(null)).on('timeout', function() { this.destroy(); resolve(null); });
  });
}

// ── Aggregate state ────────────────────────────────────────────────
async function collectState() {
  const [health, agents, status, spawnLog, processes] = await Promise.all([
    fetchJSON('/health'), fetchJSON('/agents'), fetchJSON('/debug/status'),
    fetchJSON('/debug/spawn-log'), fetchJSON('/debug/processes'),
  ]);
  frame++;
  return {
    type: 'ops_state',
    ts: new Date().toISOString(),
    frame,
    server_up: !!(health && health.ok),
    data: { health, agents, status, spawnLog, processes },
  };
}

// ── Broadcast ──────────────────────────────────────────────────────
async function broadcast() {
  const msg = JSON.stringify(await collectState());
  for (const ws of clients) {
    if (ws.readyState === 1) { try { ws.send(msg); } catch (_) { clients.delete(ws); } }
  }
}

// ── Main ───────────────────────────────────────────────────────────
const wss = new WebSocketServer({ port: PUSHER_PORT, host: HOST });
console.log(`[ops-pusher] WebSocket on ws://${HOST}:${PUSHER_PORT}  interval=${INTERVAL}ms  anchor=${HOST}:${ANCHOR_PORT}`);

wss.on('connection', (ws) => {
  clients.add(ws);
  // Send immediate state on connect
  collectState().then(s => { if (ws.readyState === 1) ws.send(JSON.stringify(s)); });
  ws.on('close', () => clients.delete(ws));
  ws.on('error', () => clients.delete(ws));
});

setInterval(broadcast, INTERVAL);
