// Loom Bridge + MCP Server — single process, MCP-native
// MCP JSON-RPC over stdio for Claude Code, HTTP/WS on :3000 for webview

const express = require('express');
const http = require('http');
const { WebSocketServer } = require('ws');
const fs = require('fs');
const path = require('path');

const PORT = 3000;
const OUTPUT_DIR = path.join(__dirname, '..', 'output');
const PROMPTS_DIR = path.join(__dirname, '..', 'prompts');
const LOGS_DIR = path.join(__dirname, '..', 'logs');
const CURRENT_HTML = path.join(OUTPUT_DIR, 'current.html');
const PENDING_PROMPT = path.join(PROMPTS_DIR, 'pending.md');
const OPS_LOG = path.join(LOGS_DIR, 'ops.jsonl');

[OUTPUT_DIR, PROMPTS_DIR, LOGS_DIR].forEach(d => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'webview')));

let webviewClients = new Set();
let currentHtml = '';

// ── MCP state ────────────────────────────────────────────────────────
let pendingOp = null;
let pendingSubscribers = new Set();
let mcpInputBuffer = '';
let mcpInitialized = false;

// Load existing HTML if present
if (fs.existsSync(CURRENT_HTML)) {
  currentHtml = fs.readFileSync(CURRENT_HTML, 'utf8');
}

// ── HTTP: receive HTML ───────────────────────────────────────────────
app.post('/html', (req, res) => {
  const html = req.body.html || '';
  if (!html.trim()) return res.status(400).json({ error: 'empty html' });

  currentHtml = html;
  fs.writeFileSync(CURRENT_HTML, html, 'utf8');
  broadcast({ type: 'html', content: html });
  console.log(`[bridge] HTML received (${html.length} bytes), broadcasting to ${webviewClients.size} clients`);
  res.json({ ok: true, size: html.length });
});

// ── HTTP: receive op from webview ────────────────────────────────────
app.post('/op', (req, res) => {
  const op = req.body;
  if (!op || !op.op) return res.status(400).json({ error: 'invalid op: missing "op" field' });

  pendingOp = op;
  console.log(`[bridge] op via HTTP: ${op.op} -> ${op.target}`);

  const promptText = formatOpAsPrompt(op);
  fs.writeFileSync(PENDING_PROMPT, promptText, 'utf8');
  logOp(op);
  notifyPendingOpChanged();

  res.json({ ok: true, prompt_written: true });
});

// ── HTTP: get current HTML ───────────────────────────────────────────
app.get('/current-html', (req, res) => {
  res.set('Content-Type', 'text/html; charset=utf-8');
  res.send(currentHtml);
});

// ── WebSocket ────────────────────────────────────────────────────────
wss.on('connection', (ws) => {
  webviewClients.add(ws);
  console.log(`[bridge] webview connected (${webviewClients.size} total)`);

  if (currentHtml) {
    ws.send(JSON.stringify({ type: 'html', content: currentHtml }));
  }

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'op') {
        console.log(`[bridge] op via WS: ${msg.op.op} -> ${msg.op.target}`);
        pendingOp = msg.op;

        const promptText = formatOpAsPrompt(msg.op);
        fs.writeFileSync(PENDING_PROMPT, promptText, 'utf8');
        logOp(msg.op);
        notifyPendingOpChanged();

        ws.send(JSON.stringify({ type: 'ack', message: 'Op received' }));
      } else if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
      }
    } catch (e) {
      console.error('[bridge] invalid message:', e.message);
    }
  });

  ws.on('close', () => {
    webviewClients.delete(ws);
    console.log(`[bridge] webview disconnected (${webviewClients.size} remaining)`);
  });
});

function broadcast(msg) {
  const payload = JSON.stringify(msg);
  for (const ws of webviewClients) {
    if (ws.readyState === 1) ws.send(payload);
  }
}

// ── Op helpers ───────────────────────────────────────────────────────
function formatOpAsPrompt(op) {
  const instruction = op.args?.instruction || op.args?.value || '(no instruction)';
  const selection = op.selection ? `\n**Selection**: "${op.selection.text}" (range: ${op.selection.range.join('-')})` : '';

  return `## Loom User Action

**Operation**: \`${op.op}\`
**Target**: \`${op.target}\`${selection}
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

function logOp(op) {
  const record = {
    timestamp: new Date().toISOString(),
    html_snapshot: currentHtml.substring(0, 5000),
    op: op
  };
  fs.appendFileSync(OPS_LOG, JSON.stringify(record) + '\n', 'utf8');
}

function notifyPendingOpChanged() {
  for (const subId of pendingSubscribers) {
    sendMCP({ jsonrpc: '2.0', method: 'notifications/resources/updated', params: { uri: 'anchor://pending-op' } });
  }
}

// ── File watcher: detect when HTML is written directly ───────────────
try {
  fs.watch(OUTPUT_DIR, (eventType, filename) => {
    if (filename === 'current.html' && eventType === 'change') {
      setTimeout(() => {
        try {
          const html = fs.readFileSync(CURRENT_HTML, 'utf8');
          if (html !== currentHtml) {
            currentHtml = html;
            broadcast({ type: 'html', content: html });
            console.log(`[bridge] file change detected, broadcasting (${html.length} bytes)`);
          }
        } catch (e) { /* file may be mid-write */ }
      }, 100);
    }
  });
  console.log('[bridge] watching output/ for HTML changes');
} catch (e) {
  console.log('[bridge] file watcher not available:', e.message);
}

// ── Start HTTP server ────────────────────────────────────────────────
server.listen(PORT, () => {
  console.log(`[bridge] Loom Bridge running on http://localhost:${PORT}`);
  console.log(`[bridge] Open http://localhost:${PORT} in your browser`);
});

// ═══════════════════════════════════════════════════════════════════════
// MCP JSON-RPC over stdio
// ═══════════════════════════════════════════════════════════════════════

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { mcpInputBuffer += chunk; drain(); });
process.stdin.on('end', () => { if (mcpInputBuffer.trim()) drain(true); });

function drain(final) {
  const lines = mcpInputBuffer.split('\n');
  mcpInputBuffer = final ? '' : lines.pop() || '';
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try { handleMCP(JSON.parse(trimmed)); }
    catch (e) { console.error('[bridge] MCP parse error: ' + e.message); }
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
    console.log('[bridge] MCP initialized');
    return;
  }

  if (!mcpInitialized) return;

  if (method === 'tools/list') {
    sendMCP({
      jsonrpc: '2.0', id, result: { tools: [
        {
          name: 'anchor_render',
          description: 'Render HTML to the Loom webview. The HTML must have data-anc, data-handles, data-deps attributes per Anchor protocol. After calling, open http://localhost:3000 to see the interactive page.',
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

  sendMCP({ jsonrpc: '2.0', id, error: { code: -32601, message: `Unknown method: ${method}` } });
}

function handleToolCall(id, params) {
  const { name, arguments: args } = params || {};

  if (name === 'anchor_render') {
    const html = (args && args.html) || '';
    currentHtml = html;
    fs.writeFileSync(CURRENT_HTML, html, 'utf8');
    broadcast({ type: 'html', content: html });
    console.log(`[bridge] anchor_render: ${html.length} bytes -> ${webviewClients.size} client(s)`);
    sendMCP({
      jsonrpc: '2.0', id,
      result: { content: [{ type: 'text', text: `Rendered ${html.length} bytes to ${webviewClients.size} client(s). Open http://localhost:${PORT} to interact.` }] }
    });
    return;
  }

  if (name === 'anchor_get_pending_op') {
    if (!pendingOp) {
      sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify({ pending: false }) }] } });
    } else {
      const op = pendingOp;
      pendingOp = null;
      notifyPendingOpChanged();
      sendMCP({
        jsonrpc: '2.0', id,
        result: { content: [{ type: 'text', text: JSON.stringify({ pending: true, op, current_html: currentHtml.substring(0, 15000) }) }] }
      });
    }
    return;
  }

  if (name === 'anchor_get_html') {
    sendMCP({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: currentHtml || '(empty)' }] } });
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
    const text = pendingOp
      ? JSON.stringify({ pending: true, op: pendingOp })
      : JSON.stringify({ pending: false });
    sendMCP({
      jsonrpc: '2.0', id,
      result: { contents: [{ uri, mimeType: 'application/json', text }] }
    });
    return;
  }
  sendMCP({ jsonrpc: '2.0', id, error: { code: -32602, message: `Unknown resource: ${uri}` } });
}

function sendMCP(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

console.log('[bridge] MCP server started, waiting for initialize...');
