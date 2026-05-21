#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const RUNTIME_DIR = path.join(ROOT, 'logs', 'runtime');
const REGISTRY = path.join(RUNTIME_DIR, 'anchor-processes.json');
const SHUTDOWN_LOG = path.join(RUNTIME_DIR, 'shutdown.log');

function log(msg, extra) {
  const entry = { ts: new Date().toISOString(), source: 'stop-helper', msg, ...(extra || {}) };
  try {
    fs.mkdirSync(RUNTIME_DIR, { recursive: true });
    fs.appendFileSync(SHUTDOWN_LOG, JSON.stringify(entry) + '\n', 'utf8');
  } catch {}
  console.log('[anchor-stop] ' + msg + (extra ? ' ' + JSON.stringify(extra) : ''));
}

function isAlive(pid) {
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

function forceKill(pid) {
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

async function main() {
  if (!fs.existsSync(REGISTRY)) {
    log('no registry found; nothing to stop', { registry: REGISTRY });
    return;
  }

  let data;
  try {
    data = JSON.parse(fs.readFileSync(REGISTRY, 'utf8'));
  } catch (e) {
    log('registry parse failed', { error: e.message, registry: REGISTRY });
    process.exitCode = 1;
    return;
  }

  const registryRoot = path.resolve(data.root || '');
  if (registryRoot.toLowerCase() !== ROOT.toLowerCase()) {
    log('registry root mismatch; refusing to stop processes', { registryRoot, root: ROOT });
    process.exitCode = 1;
    return;
  }

  const processes = (data.processes || [])
    .filter(p => p && p.pid && p.pid !== process.pid)
    .sort((a, b) => (a.role === 'anchor-service' ? 1 : 0) - (b.role === 'anchor-service' ? 1 : 0));

  for (const proc of processes) {
    if (!isAlive(proc.pid)) {
      log('already stopped', { role: proc.role, pid: proc.pid });
      continue;
    }
    log('sending graceful stop', { role: proc.role, pid: proc.pid });
    try { process.kill(proc.pid, 'SIGTERM'); } catch {}
  }

  await delay(4000);

  for (const proc of processes) {
    if (!isAlive(proc.pid)) continue;
    log('force killing', { role: proc.role, pid: proc.pid });
    await forceKill(proc.pid);
  }

  try { fs.unlinkSync(REGISTRY); } catch {}
  log('stop complete');
}

main().catch(e => {
  log('stop failed', { error: e.message });
  process.exit(1);
});
