// mcp/scheduler.cjs
// Cron-based push scheduler. Schedules persisted to logs/workspace/schedules.json.
'use strict';

const fs   = require('fs');
const path = require('path');

const ROOT           = path.join(__dirname, '..');
const BRIDGE_NM      = path.join(ROOT, 'bridge', 'node_modules');
const SCHEDULES_FILE = path.join(ROOT, 'logs', 'workspace', 'schedules.json');

const nodeCron = require(path.join(BRIDGE_NM, 'node-cron'));

let _broker = null;
let _jobs   = new Map();  // id → cron task
let _specs  = [];         // schedule spec objects

function _save() {
  try { fs.writeFileSync(SCHEDULES_FILE, JSON.stringify(_specs, null, 2), 'utf8'); } catch {}
}

function _load() {
  try {
    const raw = fs.readFileSync(SCHEDULES_FILE, 'utf8');
    _specs = JSON.parse(raw);
    if (!Array.isArray(_specs)) _specs = [];
  } catch { _specs = []; }
}

function _register(spec) {
  if (!spec.enabled) return;
  if (!nodeCron.validate(spec.cron)) {
    console.warn('[scheduler] invalid cron expression for', spec.id, ':', spec.cron);
    return;
  }
  const task = nodeCron.schedule(spec.cron, () => {
    console.log('[scheduler] firing:', spec.id);
    _broker.push({
      domain:   spec.domain,
      title:    spec.title,
      summary:  spec.summary || '',
      source:   'cron',
      ccPrompt: spec.ccPrompt || undefined
    });
  }, { timezone: spec.timezone || 'Asia/Shanghai' });
  _jobs.set(spec.id, task);
}

function init(broker) {
  _broker = broker;
  _load();
  for (const spec of _specs) _register(spec);
  console.log('[scheduler] loaded', _specs.length, 'schedule(s)');
}

function add(spec) {
  if (!spec.id || !spec.cron || !spec.domain || !spec.title) {
    throw new Error('schedule requires id, cron, domain, title');
  }
  remove(spec.id);  // idempotent replace
  const entry = { ...spec, enabled: spec.enabled !== false };
  _specs.push(entry);
  _save();
  _register(entry);
  return entry;
}

function remove(id) {
  const task = _jobs.get(id);
  if (task) { task.stop(); _jobs.delete(id); }
  _specs = _specs.filter(s => s.id !== id);
  _save();
}

function list() { return _specs.slice(); }

module.exports = { init, add, remove, list };
