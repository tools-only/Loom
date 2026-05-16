// Anchor MCP Server — renders HTML to webview, collects user ops
// Protocol: MCP over stdio (tools + resources) + HTTP/WS on port 3000

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import express from 'express';
import { WebSocketServer } from 'ws';
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { z } from 'zod';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const OUTPUT_DIR = path.join(ROOT, 'output');
const PROMPTS_DIR = path.join(ROOT, 'prompts');
const CURRENT_HTML = path.join(OUTPUT_DIR, 'current.html');
const PENDING_PROMPT = path.join(PROMPTS_DIR, 'pending.md');
const WEBVIEW_DIR = path.join(ROOT, 'bridge', 'webview');
const PORT = 3000;

// Ensure directories exist
[OUTPUT_DIR, PROMPTS_DIR].forEach(d => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});

// ── State ───────────────────────────────────────────────────────────
let currentHtml = '';
let pendingOp = null;
const webviewClients = new Set();
let transportRef = null;  // for sending resource-update notifications

// Load existing HTML
if (fs.existsSync(CURRENT_HTML)) {
  currentHtml = fs.readFileSync(CURRENT_HTML, 'utf8');
}

// ── HTTP + WebSocket (webview) ──────────────────────────────────────
const app = express();
const httpServer = http.createServer(app);
const wss = new WebSocketServer({ server: httpServer });

app.use(express.json({ limit: '10mb' }));
app.use(express.static(WEBVIEW_DIR));

// Legacy: POST /html (compatible with existing PostToolUse hook)
app.post('/html', (req, res) => {
  const html = req.body.html || '';
  if (!html.trim()) return res.status(400).json({ error: 'empty html' });
  currentHtml = html;
  fs.writeFileSync(CURRENT_HTML, html, 'utf8');
  broadcast(html);
  console.error(`[anchor-mcp] HTML received via POST (${html.length} bytes), ${webviewClients.size} clients`);
  res.json({ ok: true });
});

wss.on('connection', (ws) => {
  webviewClients.add(ws);
  console.error(`[anchor-mcp] webview connected (${webviewClients.size} total)`);

  if (currentHtml) {
    ws.send(JSON.stringify({ type: 'html', content: currentHtml }));
  }

  ws.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === 'op') {
        pendingOp = msg.op;
        console.error(`[anchor-mcp] op received: ${msg.op.op} -> ${msg.op.target}`);

        // Write to pending.md for Stop-hook fallback
        const promptText = formatOpAsPrompt(msg.op);
        fs.writeFileSync(PENDING_PROMPT, promptText, 'utf8');

        // Notify MCP resource subscribers
        if (transportRef) {
          try {
            transportRef.sendNotification({
              method: 'notifications/resources/updated',
              params: { uri: 'anchor://pending-op' }
            });
          } catch (e) { /* ignore */ }
        }

        ws.send(JSON.stringify({ type: 'ack', message: 'Op received — return to Claude Code to process' }));
      }
    } catch (e) {
      console.error('[anchor-mcp] invalid WS message:', e.message);
    }
  });

  ws.on('close', () => {
    webviewClients.delete(ws);
    console.error(`[anchor-mcp] webview disconnected (${webviewClients.size} remaining)`);
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
  const selection = op.selection
    ? `\n**Selection**: "${op.selection.text}" (range: ${op.selection.range.join('-')})`
    : '';

  return `## Anchor User Action

**Operation**: \`${op.op}\`
**Target**: \`${op.target}\`${selection}
**Instruction**: ${instruction}

### Context
The user performed this action on the rendered HTML. Please update the HTML to reflect this change.
- Only modify the target element (data-anc="${op.target}") and any elements listed in its data-deps.
- Preserve all data-anc, data-handles, and data-deps attributes.
- Call \`anchor_render\` with the COMPLETE updated HTML.

### Current HTML
\`\`\`html
${currentHtml}
\`\`\`

Call \`anchor_render\` with the COMPLETE updated HTML now.
`;
}

httpServer.listen(PORT, () => {
  console.error(`[anchor-mcp] Webview available at http://localhost:${PORT}`);
});

// ── MCP Server ──────────────────────────────────────────────────────
const mcp = new McpServer({
  name: 'anchor',
  version: '1.0.0'
});

// Tool: render HTML to webview
mcp.tool(
  'anchor_render',
  'Render HTML to the Anchor webview. The HTML must have data-anc, data-handles, data-deps attributes per Anchor protocol.',
  { html: z.string().describe('Complete HTML document with anchor annotations') },
  async ({ html }) => {
    currentHtml = html;
    fs.writeFileSync(CURRENT_HTML, html, 'utf8');
    broadcast(html);
    console.error(`[anchor-mcp] anchor_render: ${html.length} bytes -> ${webviewClients.size} client(s)`);
    return {
      content: [{
        type: 'text',
        text: `Rendered ${html.length} bytes to ${webviewClients.size} webview client(s). Open http://localhost:${PORT} to interact.`
      }]
    };
  }
);

// Tool: get pending user op
mcp.tool(
  'anchor_get_pending_op',
  'Get and clear the pending user interaction from the webview. Returns the op with target, operation, instruction, and current HTML context. Returns {pending: false} if no pending op.',
  {},
  async () => {
    if (!pendingOp) {
      return { content: [{ type: 'text', text: JSON.stringify({ pending: false }) }] };
    }
    const op = pendingOp;
    pendingOp = null;

    // Notify resource subscribers that pending-op changed
    if (transportRef) {
      try {
        transportRef.sendNotification({
          method: 'notifications/resources/updated',
          params: { uri: 'anchor://pending-op' }
        });
      } catch (e) { /* ignore */ }
    }

    return {
      content: [{
        type: 'text',
        text: JSON.stringify({
          pending: true,
          op,
          current_html: currentHtml.substring(0, 15000)
        })
      }]
    };
  }
);

// Tool: get current HTML state
mcp.tool(
  'anchor_get_html',
  'Get the currently rendered HTML from the webview.',
  {},
  async () => {
    return {
      content: [{
        type: 'text',
        text: currentHtml || '(empty)'
      }]
    };
  }
);

// Resource: current HTML
mcp.resource(
  'current-html',
  'anchor://current-html',
  { mimeType: 'text/html' },
  async () => ({
    contents: [{
      uri: 'anchor://current-html',
      mimeType: 'text/html',
      text: currentHtml || '<!-- no HTML rendered yet -->'
    }]
  })
);

// Resource: pending op
mcp.resource(
  'pending-op',
  'anchor://pending-op',
  { mimeType: 'application/json' },
  async () => ({
    contents: [{
      uri: 'anchor://pending-op',
      mimeType: 'application/json',
      text: pendingOp
        ? JSON.stringify({ pending: true, op: pendingOp })
        : JSON.stringify({ pending: false })
    }]
  })
);

// ── Boot ────────────────────────────────────────────────────────────
const transport = new StdioServerTransport();
transportRef = transport;  // store for sending resource-update notifications
await mcp.connect(transport);
console.error('[anchor-mcp] MCP server connected via stdio');
