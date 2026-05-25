#!/usr/bin/env node
// Anchor MCP Shim — thin stdio JSON-RPC bridge to the Anchor Service.
//
// Claude Code starts this process (via .claude/mcp.json). The Anchor Service
// (mcp/server.cjs) runs separately: scripts\start-anchor.bat
//
// Architecture:
//   CC Agent ←─── stdio JSON-RPC ───→ Shim ←─── WebSocket ───→ Service
//
// The shim holds a persistent WebSocket connection to /ws/agent.
// When a browser user triggers an op, the service PUSHES it to the shim;
// anchor_await_op() resolves immediately. No HTTP polling.
//
// HTTP is used only for loop-gate endpoints (/loop/active, /loop/disable).

const http = require('http');
const path = require('path');

const PORT     = parseInt(process.env.ANCHOR_PORT || '3000');
const AGENT_ID = process.env.ANCHOR_AGENT_ID || null;  // multi-agent routing id
const BRIDGE_NM = path.join(__dirname, '..', 'bridge', 'node_modules');

// Reuse ws from bridge/node_modules — no separate install needed
const wsLib    = require(path.join(BRIDGE_NM, 'ws'));
const WebSocket = wsLib.WebSocket || wsLib; // ws >= 8 exports {WebSocket,...}; older exports class directly

// ── stdio JSON-RPC ────────────────────────────────────────────────────
let _buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  _buf += chunk;
  let nl;
  while ((nl = _buf.indexOf('\n')) !== -1) {
    const line = _buf.slice(0, nl).trim();
    _buf = _buf.slice(nl + 1);
    if (line) { try { dispatch(JSON.parse(line)); } catch { /* skip malformed */ } }
  }
});
process.stdin.resume();

function send(obj)            { process.stdout.write(JSON.stringify(obj) + '\n'); }
function rpcResult(id, text)  { send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }] } }); }
function rpcErr(id, code, msg){ send({ jsonrpc: '2.0', id, error: { code, message: msg } }); }
function log(msg)             { process.stderr.write(`[anchor-shim] ${msg}\n`); }

const TRACE_LOG = path.join(__dirname, '..', 'logs', 'shim_trace.log');
function wsTrace(direction, msgType, meta) {
  const entry = { ts: new Date().toISOString(), direction, msgType, ...meta };
  process.stdout.write(`[shim-trace] ${direction} ${msgType} ${JSON.stringify(meta)}\n`);
  try { require('fs').appendFileSync(TRACE_LOG, JSON.stringify(entry) + '\n', 'utf8'); } catch {}
}

// ── WebSocket connection to service ──────────────────────────────────
//
// Single persistent connection.  Reconnects automatically on close.
// Op push path: service → WS message {type:'op'} → opQueue / opResolver
// Command path: shim → WS message {type:'render'|'patch'|...} → ack response

let serviceWs  = null;   // current WebSocket instance
let wsReady    = false;  // true when connection is open
let reconnecting = false;

// anchor_await_op state
let opQueue    = [];     // ops received before await_op was called
let opResolver = null;   // { id, timer } — parked await_op call

// Per-request ack tracking  (req_id → resolve fn)
let pendingReqs = new Map();
let reqSeq      = 0;
const genReqId  = () => 'r' + (++reqSeq);

function connectToService() {
  if (reconnecting) return;
  reconnecting = true;

  let wsUrl = `ws://localhost:${PORT}/ws/agent`;
  if (AGENT_ID) wsUrl += `?agentId=${encodeURIComponent(AGENT_ID)}`;
  log(`connecting to ${wsUrl}`);

  let ws;
  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    reconnecting = false;
    setTimeout(connectToService, 2000);
    return;
  }

  ws.on('open', () => {
    serviceWs  = ws;
    wsReady    = true;
    reconnecting = false;
    log(`connected to Anchor service (ws://localhost:${PORT}/ws/agent${AGENT_ID ? '?agentId=' + AGENT_ID : ''})`);
  });

  ws.on('message', (data) => {
    let msg;
    try { msg = JSON.parse(data.toString()); } catch { return; }

    if (msg.type === 'op') {
      // Service pushed ops — resolve parked await_op or buffer for next call
      const ops = msg.ops || [];
      wsTrace('recv', 'op_push', { count: ops.length, ops: ops.map(o => o?.intent?.op + ':' + (o?.intent?.target_ref || o?.target_ref)) });
      if (ops.length === 0) return;
      if (opResolver) {
        const { id, timer } = opResolver;
        if (timer) clearTimeout(timer);
        opResolver = null;
        wsTrace('send', 'await_op_resolve', { count: ops.length, via: 'parked_resolver' });
        rpcResult(id, JSON.stringify({ pending: true, ops, count: ops.length }));
      } else {
        opQueue.push(...ops);
        wsTrace('buffer', 'op_queue', { queued: ops.length, total: opQueue.length });
      }

    } else if (msg.type === 'ack' || msg.type === 'html_state') {
      // Response to a render/patch/event/get_html command
      wsTrace('recv', 'cmd_ack', { req_id: msg.req_id, ok: msg.ok, type: msg.type });
      const cb = pendingReqs.get(msg.req_id);
      if (cb) { pendingReqs.delete(msg.req_id); cb(msg); }
    }
  });

  ws.on('close', () => {
    serviceWs = null;
    wsReady   = false;
    reconnecting = false;
    const suffix = AGENT_ID ? ` (subagent=${AGENT_ID})` : ' (main)';
    log('disconnected from Anchor service, reconnecting in 1s...' + suffix);
    // If anchor_await_op is parked, leave it — it will time out naturally or
    // resolve when the service reconnects and re-drains pending ops.
    setTimeout(connectToService, 1000);
  });

  ws.on('error', () => {
    // 'error' always precedes 'close'; let close handler reconnect.
  });
}

connectToService();

// Send a message to the service and wait for its ack/response.
function sendCmd(msg, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (!wsReady) {
      wsTrace('send', 'cmd_dropped', { type: msg.type, reason: 'not_connected' });
      reject(new Error(`Anchor service not running on port ${PORT}. Start it: scripts\\start-anchor.bat`));
      return;
    }
    const reqId = genReqId();
    msg.req_id  = reqId;
    wsTrace('send', 'cmd', { type: msg.type, req_id: reqId });
    const timer = setTimeout(() => {
      pendingReqs.delete(reqId);
      wsTrace('timeout', 'cmd', { req_id: reqId, type: msg.type });
      reject(new Error('Request timed out'));
    }, timeoutMs || 10000);
    pendingReqs.set(reqId, (response) => {
      clearTimeout(timer);
      resolve(response);
    });
    serviceWs.send(JSON.stringify(msg));
  });
}

// ── HTTP helpers (loop-gate only) ─────────────────────────────────────
function httpReq(method, urlPath, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const opts = {
      hostname: 'localhost', port: PORT, path: urlPath, method,
      headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
      timeout: (timeoutMs || 5000) + 2000
    };
    const req = http.request(opts, res => {
      let b = ''; res.on('data', c => b += c);
      res.on('end', () => resolve({ status: res.statusCode, body: b }));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('request timed out')); });
    if (data) req.write(data);
    req.end();
  });
}
const get  = (p, ms)    => httpReq('GET',  p, null, ms);
const post = (p, b, ms) => httpReq('POST', p, b,    ms);

// ── Tool definitions ──────────────────────────────────────────────────
const TOOLS = [
  {
    name: 'anchor_render',
    description: 'Render HTML to the Anchor webview. The HTML must have data-anc, data-handles, data-deps attributes per Anchor protocol. After calling, open http://localhost:3000 to see the interactive page.',
    inputSchema: { type: 'object', properties: { html: { type: 'string', description: 'Complete HTML document with anchor annotations' } }, required: ['html'] }
  },
  {
    name: 'anchor_await_op',
    description: 'Wait for the next user execute action from the webview. Returns immediately if ops are already queued; otherwise holds the call open until the user clicks execute (or timeout). Returns {pending:true, ops:[...], count:N} with all queued ops, or {pending:false, timeout:true}. Use this after anchor_render to keep the agent loop alive without polling or spawning.',
    inputSchema: { type: 'object', properties: { timeout_ms: { type: 'integer', description: 'Max wait time in ms (default 300000 = 5 min)' } } }
  },
  {
    name: 'anchor_listen',
    description: 'Register as a listener for user ops. Returns immediately; when an op arrives the service pushes it over the agent WebSocket channel. Then call anchor_get_pending_op to drain the queue.',
    inputSchema: { type: 'object', properties: { timeout_ms: { type: 'integer', description: 'Listener timeout in ms (0 = infinite, default 0)' } } }
  },
  {
    name: 'anchor_get_pending_op',
    description: 'Get and clear one pending user interaction from the webview. Returns {pending:false} if no pending op, or {pending:true, op, current_html}. Prefer anchor_await_op for the main event loop.',
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
        type: { type: 'string', enum: ['thinking', 'tool_call', 'partial_render', 'decision', 'complete', 'error', 'debate'] },
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
      properties: { session_id: { type: 'string' }, up_to_event_id: { type: 'string' } },
      required: ['session_id']
    }
  },
  {
    name: 'anchor_inbox_push',
    description: 'Push a notification to the user inbox and update hero card badges. Use this to proactively surface findings, alerts, or insights without waiting for the user to ask.',
    inputSchema: {
      type: 'object',
      properties: {
        domain:  { type: 'string', enum: ['market', 'position', 'target'] },
        title:   { type: 'string', description: 'Short notification title (max ~60 chars)' },
        summary: { type: 'string', description: 'One-sentence summary shown in the inbox list' },
        payload: { type: 'object', description: 'Optional structured data attached to the notification' }
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
    description: 'Register a recurring cron-based push schedule. Fires into the push broker at the given cron expression. Set enabled:false to pause without deleting.',
    inputSchema: {
      type: 'object',
      properties: {
        id:       { type: 'string', description: 'Stable identifier, e.g. "market-morning-brief"' },
        name:     { type: 'string', description: 'Human-readable schedule name' },
        cron:     { type: 'string', description: 'Cron expression, e.g. "0 9 * * 1-5"' },
        domain:   { type: 'string', enum: ['market', 'position', 'target'] },
        title:    { type: 'string', description: 'Notification title when schedule fires' },
        summary:  { type: 'string', description: 'Notification summary when schedule fires' },
        ccPrompt: { type: 'string', description: 'If set, spawns CC with this prompt to enrich the notification' },
        timezone: { type: 'string', description: 'Timezone string, default Asia/Shanghai' },
        enabled:  { type: 'boolean', description: 'Whether the schedule is active (default true)' }
      },
      required: ['id', 'cron', 'domain', 'title']
    }
  },
  {
    name: 'anchor_patch',
    description: 'Patch specific anchor nodes with HTML fragments (DOM-level replacement, no full-page render). Each patch replaces one data-anc node. Prefer this over anchor_render for targeted edits.',
    inputSchema: {
      type: 'object',
      properties: {
        patches: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              anchor_id:     { type: 'string', description: 'data-anc value of the target node' },
              html_fragment: { type: 'string', description: 'Complete outerHTML for the replacement (must include data-anc)' }
            },
            required: ['anchor_id', 'html_fragment']
          }
        }
      },
      required: ['patches']
    }
  }
];

// ── Dispatcher ────────────────────────────────────────────────────────
async function dispatch(msg) {
  const { id, method, params } = msg;

  if (method === 'initialize') {
    send({ jsonrpc: '2.0', id, result: {
      protocolVersion: '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: 'anchor-shim', version: '2.0.0' }
    }});
    return;
  }

  if (method === 'notifications/initialized') return;

  if (method && !msg.id) {
    log('Server notification: ' + method);
    return;
  }

  if (method === 'tools/list') {
    send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
    return;
  }

  if (method === 'resources/list') {
    send({ jsonrpc: '2.0', id, result: { resources: [] } });
    return;
  }

  if (method === 'prompts/list') {
    send({ jsonrpc: '2.0', id, result: { prompts: [] } });
    return;
  }

  if (method === 'tools/call') {
    const { name, arguments: args = {} } = params || {};
    await callTool(id, name, args);
    return;
  }

  if (id != null) rpcErr(id, -32601, `Unknown method: ${method}`);
}

// ── Tool handlers ─────────────────────────────────────────────────────
async function callTool(id, name, args) {
  try {
    switch (name) {

      // ── anchor_render ────────────────────────────────────────────────
      case 'anchor_render': {
        const html = args.html || '';
        const r = await sendCmd({ type: 'render', html });
        rpcResult(id, r.ok
          ? `Rendered ${html.length} bytes to webview.`
          : `Error: ${r.error}`);
        break;
      }

      // ── anchor_await_op ──────────────────────────────────────────────
      // Push-based: the service sends {type:'op'} when a user acts.
      // If ops are already buffered (from before this call), resolve immediately.
      // Otherwise park and wait; the WS message handler will resolve us.
      case 'anchor_await_op': {
        const ms = args.timeout_ms != null ? args.timeout_ms : 300000;

        // Drain any ops already buffered from the WS channel
        if (opQueue.length > 0) {
          const ops = opQueue.splice(0);
          wsTrace('send', 'await_op_resolve', { count: ops.length, via: 'queue_drain' });
          rpcResult(id, JSON.stringify({ pending: true, ops, count: ops.length }));
          break;
        }

        // If not yet connected, fall back to a short wait then timeout
        if (!wsReady) {
          rpcResult(id, JSON.stringify({ pending: false, timeout: true,
            note: 'Anchor service not connected — start it with scripts\\start-anchor.bat' }));
          break;
        }

        // Park the call; WS push from service will resolve it.
        // timeout_ms=0 means infinite (no timer) — use for permanent listening loop.
        const effectiveMs = (ms == null) ? 300000 : ms;  // default 5min; 0 = infinite
        const timer = effectiveMs > 0
          ? setTimeout(() => {
              if (opResolver && opResolver.id === id) {
                opResolver = null;
                rpcResult(id, JSON.stringify({ pending: false, timeout: true }));
              }
            }, effectiveMs)
          : null;
        opResolver = { id, timer };
        // Note: do NOT call rpcResult here — response is deferred until service push
        break;
      }

      // ── anchor_listen ────────────────────────────────────────────────
      // Alias for anchor_await_op; returns immediately with {listening:true}
      // then the WS push resolves anchor_get_pending_op.
      case 'anchor_listen': {
        const ms = args.timeout_ms != null ? args.timeout_ms : 270000;
        if (opQueue.length > 0) {
          rpcResult(id, JSON.stringify({ pending: true, ops: opQueue.splice(0) }));
          break;
        }
        const timer = ms > 0
          ? setTimeout(() => {
              if (opResolver && opResolver.id === id) {
                opResolver = null;
                rpcResult(id, JSON.stringify({ pending: false, timeout: true }));
              }
            }, ms)
          : null;
        opResolver = { id, timer };
        break;
      }

      // ── anchor_get_pending_op ────────────────────────────────────────
      // Returns one op at a time from the local queue. When the queue is empty,
      // sends {type:'op_req'} via WS to fetch the next op from the processor's
      // partition on the server. This replaces the old HTTP /pending-op fallback
      // which caused issues with multi-op batches (server had already drained all
      // ops at connection time, so HTTP would return pending:false prematurely).
      case 'anchor_get_pending_op': {
        if (opQueue.length > 0) {
          const op = opQueue.shift();
          const subtree = op?.render_state?.relevant_subtree || null;
          const opKind  = op?.intent?.op || '';
          const HEAVY   = ['restructure', 'branch', 'expand'];
          const needsFull = HEAVY.includes(opKind) || !subtree;
          rpcResult(id, JSON.stringify({
            pending: true, op,
            relevant_subtree: subtree || undefined,
            current_html: needsFull ? undefined : undefined
          }));
          break;
        }
        // Queue empty — request next op from the server via WS (not HTTP).
        // The server holds remaining ops in the processor's partition queue and
        // sends them one at a time via {type:'op'} push.
        if (wsReady && serviceWs && serviceWs.readyState === 1) {
          // Park this request; when the server pushes {type:'op'} via WS,
          // it will be received by the ws.onmessage handler and resolved.
          const timer = setTimeout(() => {
            if (opResolver && opResolver.id === id) {
              opResolver = null;
              rpcResult(id, JSON.stringify({ pending: false, timeout: true }));
            }
          }, 30000);
          opResolver = { id, timer };
          serviceWs.send(JSON.stringify({ type: 'op_req', req_id: id }));
          wsTrace('send', 'cmd', { type: 'op_req', req_id: id });
        } else {
          rpcResult(id, JSON.stringify({ pending: false, reason: 'not_connected' }));
        }
        break;
      }

      // ── anchor_get_html ──────────────────────────────────────────────
      case 'anchor_get_html': {
        const r = await sendCmd({ type: 'get_html' });
        rpcResult(id, r.html || '(empty)');
        break;
      }

      // ── anchor_inbox_push ─────────────────────────────────────────────
      case 'anchor_inbox_push': {
        const r = await post('/push/manual', {
          domain: args.domain, title: args.title, summary: args.summary,
          payload: args.payload || {}, source: 'agent'
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

      // ── anchor_patch ─────────────────────────────────────────────────
      case 'anchor_patch': {
        const r = await sendCmd({ type: 'patch', patches: args.patches || [] });
        rpcResult(id, r.ok
          ? `Patched ${(args.patches || []).length} node(s)${r.cascade_warnings ? ` (${r.cascade_warnings} cascade warning(s))` : ''}.`
          : `Error: ${r.error}`);
        break;
      }

      // ── anchor_emit_event ────────────────────────────────────────────
      case 'anchor_emit_event': {
        const r = await sendCmd({ type: 'event', kind: 'agent.' + args.type, payload: args.payload || {} });
        rpcResult(id, 'emitted ' + (r.event_id || ''));
        break;
      }

      // ── anchor_replay_session ─────────────────────────────────────────
      case 'anchor_replay_session': {
        const qs = args.up_to_event_id
          ? `?up_to=${encodeURIComponent(args.up_to_event_id)}` : '';
        const r = await get(`/session/${encodeURIComponent(args.session_id)}/events${qs}`, 10000);
        rpcResult(id, r.body);
        break;
      }

      default:
        rpcErr(id, -32601, `Unknown tool: ${name}`);
    }
  } catch (e) {
    const msg = e.message || String(e);
    if (msg.includes('not running') || msg.includes('not connected') || msg.includes('ECONNREFUSED')) {
      rpcErr(id, -32603, `Anchor service not running on port ${PORT}. Start it: scripts\\start-anchor.bat`);
    } else {
      rpcErr(id, -32603, msg);
    }
  }
}
