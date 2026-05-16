// Anchor Standalone Server — zero dependencies, Node.js built-ins only
// SSE for push, HTTP POST for ops. No express, no ws.

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = __dirname;
const WEBVIEW_DIR = path.join(ROOT, 'bridge', 'webview');
const OUTPUT_DIR = path.join(ROOT, 'output');
const CURRENT_HTML = path.join(OUTPUT_DIR, 'current.html');
const PORT = 3000;

// SSE clients
const sseClients = new Set();

// MIME types
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

// Current HTML
let currentHtml = '';
if (fs.existsSync(CURRENT_HTML)) {
  currentHtml = fs.readFileSync(CURRENT_HTML, 'utf8');
}

function log(msg) {
  process.stderr.write(`[anchor] ${msg}\n`);
}

function broadcast(type, data) {
  const payload = JSON.stringify({ type, ...data });
  for (const c of sseClients) {
    c.write(`data: ${payload}\n\n`);
  }
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const method = req.method;

  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  // SSE endpoint
  if (url.pathname === '/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.write(':ok\n\n');
    sseClients.add(res);
    req.on('close', () => sseClients.delete(res));
    // Send current HTML immediately
    if (currentHtml) {
      res.write(`data: ${JSON.stringify({ type: 'html', content: currentHtml })}\n\n`);
    }
    return;
  }

  // POST /html — push new HTML
  if (method === 'POST' && url.pathname === '/html') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        const html = JSON.parse(body).html || '';
        if (!html.trim()) {
          res.writeHead(400);
          return res.end(JSON.stringify({ error: 'empty html' }));
        }
        currentHtml = html;
        fs.writeFileSync(CURRENT_HTML, html, 'utf8');
        broadcast('html', { content: html });
        log(`HTML pushed: ${html.length} bytes, ${sseClients.size} SSE clients`);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
      } catch (e) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // POST /op — receive user operation
  if (method === 'POST' && url.pathname === '/op') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        const op = JSON.parse(body);
        log(`op: ${op.op} -> ${op.target}`);
        // Write pending prompt
        const promptsDir = path.join(ROOT, 'prompts');
        if (!fs.existsSync(promptsDir)) fs.mkdirSync(promptsDir, { recursive: true });
        const instruction = op.args?.instruction || op.args?.value || '(no instruction)';
        const sel = op.selection ? `\n**Selection**: "${op.selection.text}"` : '';
        const prompt = `## Anchor User Action

**Operation**: \`${op.op}\`
**Target**: \`${op.target}\`${sel}
**Instruction**: ${instruction}

### Context
The user performed this action on the rendered HTML. Update the HTML accordingly.
- Only modify target (data-anc="${op.target}") and its data-deps.
- Preserve all data-anc, data-handles, data-deps attributes.

### Current HTML
\`\`\`html
${currentHtml}
\`\`\`
`;
        fs.writeFileSync(path.join(promptsDir, 'pending.md'), prompt, 'utf8');
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, message: 'Op received' }));
      } catch (e) {
        res.writeHead(400);
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // GET /api/html — get current HTML
  if (method === 'GET' && url.pathname === '/api/html') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ html: currentHtml }));
    return;
  }

  // Static file serving
  let filePath;
  if (url.pathname === '/' || url.pathname === '/index.html') {
    filePath = path.join(WEBVIEW_DIR, 'index.html');
  } else {
    // Security: prevent directory traversal
    const safe = path.normalize(url.pathname).replace(/^(\.\.(\/|\\|$))+/, '');
    filePath = path.join(WEBVIEW_DIR, safe);
  }

  const ext = path.extname(filePath);
  const mime = MIME[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end('Not Found');
      return;
    }
    res.writeHead(200, { 'Content-Type': mime });
    res.end(data);
  });
});

server.listen(PORT, () => {
  log(`Server running at http://localhost:${PORT}`);
  log(`Open http://localhost:${PORT} in your browser`);
});
