// Anchor CC Hook — closes the Anchor feedback loop
//
// Platform strategy:
//   Linux/macOS — /dev/stdin sync read (reliable, no race)
//   Windows     — CC pipe behaves differently from shell pipe;
//                 try sync drain first, fall back to 'data' event + timeout
//
// ALL output uses fs.writeSync(fd, ...) — NOT process.stdout.write
// or console.error — to guarantee unbuffered pipe writes on Windows.
// CC requires at least one stderr line; every exit path emits one.

const http = require('http');
const fs = require('fs');
const path = require('path');

const BRIDGE_PORT = 3000;
const PENDING_PROMPT = path.join(__dirname, '..', 'prompts', 'pending.md');
const IS_WINDOWS = process.platform === 'win32';
const DEBUG_FILE = path.join(__dirname, '..', '.claude', 'debug', 'hook-trace.txt');
const LOOP_COOKIE = path.join(__dirname, '..', '.claude', 'debug', 'in_await_loop');

// Ensure debug directory exists (trace writes will fail otherwise)
try { fs.mkdirSync(path.dirname(DEBUG_FILE), { recursive: true }); } catch {}

// ── Quick early-exit for PostToolUse only ──────────────────────────
// PostToolUse fires for every Write — skip if no pending UI interaction.
// Stop events MUST always proceed so we can check the loop gate.
// Moved into processInput() so we know the event type before deciding.

// ── Prove execution → write a trace file immediately ────────────────

let trace = '';
function traceLog(msg) {
  trace += new Date().toISOString() + ' ' + msg + '\n';
}
function flushTrace() {
  try { fs.appendFileSync(DEBUG_FILE, trace, 'utf8'); } catch {}
  trace = '';
}

// Safety: write trace on uncaught errors
process.on('uncaughtException', (err) => {
  traceLog('UNCAUGHT: ' + err.message);
  flushTrace();
  try { fs.writeSync(2, '[anchor-hook] UNCAUGHT: ' + err.message + '\n'); } catch {}
  try { fs.writeSync(1, '{"decision":"approve"}\n'); } catch {}
  process.exit(0);
});

traceLog('start platform=' + process.platform + ' pid=' + process.pid);

// ── stdout / stderr helpers (direct fd, no buffering) ───────────────

function writeStdout(json) {
  try { fs.writeSync(1, json + '\n'); }
  catch { /* pipe gone — nothing we can do */ }
}

function writeStderr(msg) {
  var line = '[anchor-hook] ' + msg + '\n';
  // _rawDebug writes directly to the OS stderr handle (WriteFile on Win32,
  // write(2) on Unix), bypassing Node streams, C stdio, and shell pipe layers.
  // If a shell middleman drops stderr, _rawDebug is our last resort.
  try { process._rawDebug(line); } catch {}
  // Also try fs.writeSync as fallback for platforms where _rawDebug doesn't exist
  try { fs.writeSync(2, line); } catch {}
}

// ── Platform-adaptive stdin ──────────────────────────────────────────

function readStdin() {
  if (IS_WINDOWS) {
    readStdinWindows();
  } else {
    readStdinUnix();
  }
}

function readStdinUnix() {
  let raw;
  try { raw = fs.readFileSync('/dev/stdin', 'utf8'); }
  catch { raw = ''; }
  traceLog('unix stdin=' + raw.length + ' bytes');
  flushTrace();
  processInput(raw);
}

function readStdinWindows() {
  // Strategy:
  //   1) Sync drain — data may already be buffered in Node's pipe reader
  //   2) If nothing, switch stdin to flowing mode, listen for 'data'/'end'
  //   3) Hard timeout at 3s to guarantee processInput is always called

  let data = '';
  let resolved = false;

  function resolve() {
    if (resolved) return;
    resolved = true;
    traceLog('windows stdin resolved: ' + data.length + ' bytes');
    flushTrace();
    processInput(data);
  }

  // Phase 1: immediate sync drain
  try {
    process.stdin.setEncoding('utf8');
    let chunk;
    while ((chunk = process.stdin.read()) !== null) {
      data += chunk;
    }
  } catch (e) {
    traceLog('sync drain error: ' + e.message);
  }

  if (data) {
    resolve();
    return;
  }

  // Phase 2: flowing-mode 'data' events
  process.stdin.on('data', function (chunk) {
    data += chunk;
  });

  process.stdin.on('end', function () {
    resolve();
  });

  process.stdin.resume();

  // Phase 3: hard timeout
  setTimeout(function () {
    traceLog('timeout reached, data=' + data.length + ' bytes');
    resolve();
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
    traceLog('JSON parse error: ' + e.message);
    writeStderr('JSON parse failed: ' + e.message);
  }

  const event = ctx.hook_event_name || '';
  traceLog('event=' + (event || '(empty)'));

  if (event === 'PreToolUse') {
    handlePreToolUse(ctx);
  } else if (event === 'PostToolUse') {
    // Quick exit for PostToolUse: skip if no pending UI interaction
    if (!fs.existsSync(PENDING_PROMPT)) {
      traceLog('PostToolUse: no pending.md, quick approve');
      safeExit({ decision: 'approve' });
      return;
    }
    handlePostToolUse(ctx);
  } else if (event === 'Stop') {
    handleStop(ctx);
  } else {
    traceLog('unknown event → approve');
    writeStderr('unknown/empty hook event, approving');
    safeExit({ decision: 'approve' });
  }
}

// ── PreToolUse ───────────────────────────────────────────────────────

function handlePreToolUse(ctx) {
  const tool = ctx.tool_name || '';
  traceLog('PreToolUse tool=' + tool);

  if (process.env.ANCHOR_AGENT_ID === '__proc__' || process.env.ANCHOR_PROCESSOR === '1') {
    traceLog('PreToolUse: spawned processor, approving ' + tool);
    safeExit({ decision: 'approve' });
    return;
  }

  // If CC is calling anchor_await_op itself, record that it's in the loop
  if (tool === 'mcp__anchor__anchor_await_op') {
    try { fs.writeFileSync(LOOP_COOKIE, Date.now().toString(), 'utf8'); } catch {}
    traceLog('PreToolUse: CC called await_op, marking in-loop');
    safeExit({ decision: 'approve' });
    return;
  }

  // Check cookie: is CC already in its own await_op loop?
  let inLoop = false;
  try {
    const ts = parseInt(fs.readFileSync(LOOP_COOKIE, 'utf8').trim());
    inLoop = !isNaN(ts) && (Date.now() - ts) < 3600000; // within 1 hour
  } catch {}

  if (inLoop) {
    traceLog('PreToolUse: in loop, approving ' + tool);
    safeExit({ decision: 'approve' });
    return;
  }

  // First tool call: force CC to enter the await_op loop first
  traceLog('PreToolUse: first call (' + tool + '), forcing await_op loop');
  writeStderr('PreToolUse: first call (' + tool + '), forcing await_op loop');
  safeExit({
    decision: 'block',
    reason: '[Anchor] Enter the Anchor event loop first. Call anchor_await_op(timeout_ms: 600000) — it will wait for user interactions from the webview. When an op arrives, process it with anchor_patch(), then call anchor_await_op() again. Do not summarize.'
  });
}

// ── PostToolUse ─────────────────────────────────────────────────────

function handlePostToolUse(ctx) {
  traceLog('PostToolUse tool=' + (ctx.tool_name || '?'));

  if (ctx.tool_name !== 'Write') {
    writeStderr('PostToolUse: not Write tool (' + (ctx.tool_name || '?') + '), skipping');
    safeExit({});
    return;
  }

  const filePath = ctx.tool_input?.file_path || '';
  traceLog('PostToolUse file=' + filePath);

  if (!filePath.endsWith('.html') && !filePath.includes('output')) {
    writeStderr('PostToolUse: not output HTML, skipping');
    safeExit({});
    return;
  }

  const absPath = path.isAbsolute(filePath)
    ? filePath
    : path.join(ctx.cwd || process.cwd(), filePath);

  try {
    if (!fs.existsSync(absPath)) {
      writeStderr('PostToolUse: file not found, skipping');
      safeExit({});
      return;
    }
    const html = fs.readFileSync(absPath, 'utf8');
    if (!html.includes('data-anc')) {
      writeStderr('PostToolUse: no data-anc, skipping');
      safeExit({});
      return;
    }
    traceLog('PostToolUse forwarding ' + html.length + ' bytes');
    postToBridge('/html', { html });
  } catch (e) {
    writeStderr('PostToolUse error: ' + e.message);
    safeExit({});
  }
}

// ── Stop ────────────────────────────────────────────────────────────

function handleStop(ctx) {
  traceLog('Stop active=' + (ctx.stop_hook_active ? 'yes' : 'no'));

  if (ctx.stop_hook_active) {
    writeStderr('Stop: already active, approving');
    safeExit({ decision: 'approve' });
    return;
  }

  // Phase 1 — drain pending.md if present (legacy / user-clicked path)
  try {
    if (fs.existsSync(PENDING_PROMPT)) {
      const prompt = fs.readFileSync(PENDING_PROMPT, 'utf8').trim();
      if (prompt) {
        fs.unlinkSync(PENDING_PROMPT);
        traceLog('Stop consumed ' + prompt.length + ' bytes → BLOCK');
        writeStderr('Stop: consumed prompt (' + prompt.length + ' bytes), BLOCKING');
        safeExit({
          decision: 'block',
          reason: '[Anchor] User interacted with the webview. Process this op in the current thread:\n\n' + prompt
        });
        return;
      }
      try { fs.unlinkSync(PENDING_PROMPT); } catch {}
    }
  } catch (e) {
    traceLog('Stop pending.md read error: ' + e.message);
  }

  // Phase 2 — consult /loop/active. Daemon reports queue depth + session state.
  // Three outcomes:
  //   pending_ops > 0  → work is buffered; CC must drain before resting
  //   active, no work  → session live but idle; enter bounded-timeout listen loop
  //   inactive         → session closed; CC may exit
  checkLoopStatus(function (status) {
    if (status.pending_ops > 0) {
      traceLog('Stop: ' + status.pending_ops + ' pending ops, draining');
      writeStderr('Stop: ' + status.pending_ops + ' pending op(s) buffered in daemon, blocking to drain');
      safeExit({
        decision: 'block',
        reason: '[Anchor] ' + status.pending_ops + ' op(s) buffered in daemon queue. Drain the queue: call anchor_get_pending_op() repeatedly — process each op with anchor_patch(), then call anchor_get_pending_op() again until it returns {pending:false}. Then call anchor_await_op(timeout_ms: 60000) to listen for more. Do not summarize.'
      });
    } else if (status.active) {
      traceLog('Stop: loop active, no pending ops — daemon holds queue, CC may rest');
      writeStderr('Stop: idle, daemon listening — approving');
      safeExit({ decision: 'approve' });
    } else {
      traceLog('Stop: loop inactive, approving');
      writeStderr('Stop: loop inactive, approving');
      safeExit({ decision: 'approve' });
    }
  });
}

function checkLoopStatus(cb) {
  let callbackFired = false;
  function done(status) {
    if (callbackFired) return;
    callbackFired = true;
    clearTimeout(timer);
    try { req.destroy(); } catch {}
    cb(status);
  }
  const timer = setTimeout(function () {
    traceLog('checkLoopStatus: hard timeout after 2s, treating as inactive');
    done({ active: false, pending_ops: 0 });
  }, 2000);
  const req = http.request({
    hostname: 'localhost', port: BRIDGE_PORT, path: '/loop/active',
    method: 'GET', timeout: 1500
  }, function (res) {
    let body = '';
    res.on('data', function (c) { body += c; });
    res.on('end', function () {
      try {
        const j = JSON.parse(body);
        done({ active: !!j.active, pending_ops: j.pending_ops || 0 });
      }
      catch { done({ active: false, pending_ops: 0 }); }
    });
  });
  req.on('error', function (e) {
    traceLog('checkLoopStatus: network error: ' + e.message + ', treating as inactive');
    done({ active: false, pending_ops: 0 });
  });
  req.on('timeout', function () {
    traceLog('checkLoopStatus: HTTP timeout, treating as inactive');
    done({ active: false, pending_ops: 0 });
  });
  req.end();
}

// ── Safe exit ───────────────────────────────────────────────────────

function safeExit(payload) {
  const out = payload && Object.keys(payload).length > 0
    ? payload
    : { decision: 'approve' };
  const decision = out.decision || 'approve';

  traceLog('safeExit decision=' + decision);
  writeStderr('exiting: decision=' + decision);

  // Write decision JSON to stdout (fd 1) — MUST be valid JSON
  writeStdout(JSON.stringify(out));

  // Flush trace BEFORE exit so we have a record on disk
  flushTrace();

  // process.exit can truncate pipe buffers on Windows.
  // Use a zero-delay setImmediate to let the event loop drain the pipe write.
  setImmediate(function () {
    process.exit(0);
  });
}

// ── HTTP forwarding ─────────────────────────────────────────────────

function postToBridge(endpoint, data) {
  var body = JSON.stringify(data);

  var req = http.request({
    hostname: 'localhost',
    port: BRIDGE_PORT,
    path: endpoint,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body)
    },
    timeout: 3000
  }, function (res) {
    var respData = '';
    res.on('data', function (chunk) { respData += chunk; });
    res.on('end', function () {
      try {
        var result = JSON.parse(respData);
        if (result.ok) {
          traceLog('Bridge forwarded OK: ' + (data.html ? data.html.length : 0) + ' bytes');
        }
      } catch (e) { traceLog('Bridge response parse error: ' + e.message); }
    });
    safeExit({});
  });

  req.on('error', function (e) {
    traceLog('Bridge unreachable: ' + e.message);
    writeStderr('Bridge unreachable: ' + e.message);
    safeExit({});
  });

  req.write(body);
  req.end();
}

// ── Boot ────────────────────────────────────────────────────────────

readStdin();
