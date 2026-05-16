// Anchor CC Hook — closes the Anchor feedback loop
// PostToolUse: forwards HTML writes to Bridge
// Stop: checks for pending prompts, feeds them back to Claude

const http = require('http');
const fs = require('fs');
const path = require('path');

const BRIDGE_PORT = 3000;
const PENDING_PROMPT = path.join(__dirname, '..', 'prompts', 'pending.md');
const IS_WINDOWS = process.platform === 'win32';

// ── Platform-adaptive stdin reading ────────────────────────────────

function readStdin() {
  if (IS_WINDOWS) {
    readStdinAsync();
  } else {
    // Linux/macOS: synchronous /dev/stdin, zero race condition
    let raw;
    try { raw = fs.readFileSync('/dev/stdin', 'utf8'); }
    catch { raw = ''; }
    processInput(raw);
  }
}

function readStdinAsync() {
  // Windows: readable+read with timeout guard
  let data = '';
  let handled = false;

  process.stdin.setEncoding('utf8');

  process.stdin.on('readable', () => {
    let chunk;
    while ((chunk = process.stdin.read()) !== null) {
      data += chunk;
    }
  });

  process.stdin.on('end', () => {
    if (handled) return;
    handled = true;
    processInput(data);
  });

  // If 'end' never fires (pipe race), timeout guarantee
  setTimeout(() => {
    if (handled) return;
    handled = true;
    console.error('[anchor-hook] stdin timeout, processing available data');
    processInput(data);
  }, 3000);
}

// ── Route by hook event ─────────────────────────────────────────────

function processInput(raw) {
  let ctx = {};
  try {
    if (raw && raw.trim()) {
      ctx = JSON.parse(raw);
    }
  } catch (e) {
    console.error('[anchor-hook] JSON parse failed:', e.message);
  }

  const event = ctx.hook_event_name || '';

  if (event === 'PostToolUse') {
    handlePostToolUse(ctx);
  } else if (event === 'Stop') {
    handleStop(ctx);
  } else {
    // Unknown event or empty — approve silently
    safeExit({ decision: 'approve' });
  }
}

// ── PostToolUse: forward HTML writes to Bridge ──────────────────────

function handlePostToolUse(ctx) {
  if (ctx.tool_name !== 'Write') {
    safeExit({});
    return;
  }

  const filePath = ctx.tool_input?.file_path || '';
  if (!filePath.endsWith('.html') && !filePath.includes('output')) {
    safeExit({});
    return;
  }

  const absPath = path.isAbsolute(filePath)
    ? filePath
    : path.join(ctx.cwd || process.cwd(), filePath);

  try {
    if (!fs.existsSync(absPath)) { safeExit({}); return; }
    const html = fs.readFileSync(absPath, 'utf8');
    if (!html.includes('data-anc')) { safeExit({}); return; }
    postToBridge('/html', { html });
  } catch (e) {
    safeExit({});
  }
}

// ── Stop: check for pending webview prompts ─────────────────────────

function handleStop(ctx) {
  // Infinite loop guard
  if (ctx.stop_hook_active) {
    console.error('[anchor-hook] Stop hook already active, approving');
    safeExit({ decision: 'approve' });
    return;
  }

  try {
    if (!fs.existsSync(PENDING_PROMPT)) {
      safeExit({ decision: 'approve' });
      return;
    }

    const prompt = fs.readFileSync(PENDING_PROMPT, 'utf8').trim();
    if (!prompt) {
      safeExit({ decision: 'approve' });
      return;
    }

    // Consume the prompt to prevent loops
    fs.unlinkSync(PENDING_PROMPT);
    console.error(`[anchor-hook] Consumed pending prompt (${prompt.length} bytes), blocking`);

    safeExit({
      decision: 'block',
      reason: '[Anchor] User interacted with the webview. Process this op in the current thread:\n\n' + prompt
    });
  } catch (e) {
    console.error('[anchor-hook] Error in Stop:', e.message);
    safeExit({ decision: 'approve' });
  }
}

// ── Guaranteed stdout output ────────────────────────────────────────

function safeExit(payload) {
  // Always output valid JSON. Never silent-exit.
  const out = payload && Object.keys(payload).length > 0
    ? payload
    : { decision: 'approve' };
  try {
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    // Last resort — nothing we can do
  }
  process.exit(0);
}

// ── HTTP forwarding ─────────────────────────────────────────────────

function postToBridge(endpoint, data) {
  const body = JSON.stringify(data);

  const req = http.request({
    hostname: 'localhost',
    port: BRIDGE_PORT,
    path: endpoint,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body)
    },
    timeout: 3000
  }, (res) => {
    let respData = '';
    res.on('data', (chunk) => respData += chunk);
    res.on('end', () => {
      try {
        const result = JSON.parse(respData);
        if (result.ok) {
          console.error(`[anchor-hook] HTML forwarded (${data.html ? data.html.length : 0} bytes)`);
        }
      } catch (e) { /* ignore */ }
    });
    safeExit({});
  });

  req.on('error', (e) => {
    console.error('[anchor-hook] Bridge unreachable:', e.message);
    safeExit({});
  });

  req.write(body);
  req.end();
}

// ── Boot ────────────────────────────────────────────────────────────

readStdin();
