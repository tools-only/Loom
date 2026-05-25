'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const logsDir = path.join(__dirname, '../../logs');
if (!fs.existsSync(logsDir)) fs.mkdirSync(logsDir, { recursive: true });
const LOG_FILE = path.join(logsDir, 'codex_bridge.log');

function appendLog(line) {
  try { fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${line}\n`); } catch (_) {}
}

function trySpawn(cmd, args, input, timeout) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (err) {
      return reject(Object.assign(new Error('codex not found'), { code: 'CODEX_NOT_FOUND' }));
    }

    let stdout = '';
    let stderr = '';
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
      reject(Object.assign(new Error('timeout'), { code: 'CODEX_TIMEOUT' }));
    }, timeout);

    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });

    child.on('error', err => {
      clearTimeout(timer);
      if (err.code === 'ENOENT') {
        reject(Object.assign(new Error('codex not found'), { code: 'CODEX_NOT_FOUND' }));
      } else {
        reject(err);
      }
    });

    child.on('close', code => {
      clearTimeout(timer);
      if (timedOut) return;
      if (code !== 0) {
        reject(Object.assign(new Error('codex error'), { code: 'CODEX_ERROR', exitCode: code, stderr }));
      } else {
        resolve(stdout);
      }
    });

    child.stdin.write(input);
    child.stdin.end();
  });
}

async function callGpt5(prompt, options = {}) {
  const timeout = options.timeout || 120000;
  appendLog(`CALL prompt_len=${prompt.length}`);

  let rawOutput;
  try {
    rawOutput = await trySpawn('codex', [], prompt, timeout);
  } catch (err) {
    if (err.code === 'CODEX_NOT_FOUND') {
      try {
        rawOutput = await trySpawn('npx', ['codex'], prompt, timeout);
      } catch (err2) {
        appendLog(`ERROR err=${err2.message}`);
        throw err2;
      }
    } else {
      appendLog(`ERROR err=${err.message}`);
      throw err;
    }
  }

  const raw = rawOutput.slice(0, 2000);
  let text = rawOutput.trim();
  let model = 'gpt-unknown';

  try {
    const parsed = JSON.parse(rawOutput.trim());
    if (parsed && typeof parsed === 'object') {
      text = parsed.text || parsed.content || parsed.response || rawOutput.trim();
      model = parsed.model || parsed.model_name || 'gpt-unknown';
    }
  } catch (_) {}

  appendLog(`RESULT model=${model} raw_head=${raw.slice(0, 200).replace(/\n/g, ' ')}`);
  return { text, model, raw };
}

async function selfTest() {
  const prompt = 'Respond with JSON only: {"signature":"gpt5-resp","model":"<your model name>"}';
  try {
    const result = await callGpt5(prompt, { timeout: 30000 });
    const hasSignature = result.raw.includes('gpt5-resp') || result.text.includes('gpt5-resp');
    if (hasSignature) {
      return { ok: true, model: result.model };
    }
    return { ok: false, error: 'signature gpt5-resp not found in response' };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

module.exports = { callGpt5, selfTest };

if (require.main === module && process.argv[2] === '--selftest') {
  selfTest().then(r => { console.log(JSON.stringify(r, null, 2)); process.exit(r.ok ? 0 : 1); });
}
