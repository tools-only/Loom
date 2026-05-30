'use strict';

const fs = require('fs');
const path = require('path');

const CONFIG_PATH = path.join(__dirname, '..', '.anchor.config.json');

const DEFAULTS = {
  provider: 'anthropic',
  model: 'claude-haiku-4-5-20251001',
  baseUrl: '',
  processingMode: 'spawn', // 'spawn' | 'inproc' — inproc requires API key + explicit opt-in
};

// Env var overrides (read once at module load, but can be refreshed)
function envOverrides() {
  const overrides = {};
  const ep = process.env.ANCHOR_PROVIDER;
  if (ep) overrides.provider = ep.toLowerCase();
  const em = process.env.ANCHOR_INPROC_MODEL;
  if (em) overrides.model = em;
  const eu = process.env.ANCHOR_BASE_URL;
  if (eu) overrides.baseUrl = eu;
  return overrides;
}

// ── Public API ──────────────────────────────────────────────────────

function load() {
  let file = {};
  try {
    const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
    file = JSON.parse(raw);
  } catch (_) {
    // File missing or invalid — use defaults; will auto-create on first save
  }
  return merge(DEFAULTS, file, envOverrides());
}

function save(partial) {
  // Read existing file config, apply partial, write back.
  // Never write env overrides to the file.
  let file = {};
  try {
    file = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (_) { /* use empty */ }

  if (partial.provider !== undefined) file.provider = partial.provider;
  if (partial.model !== undefined) file.model = partial.model;
  if (partial.baseUrl !== undefined) file.baseUrl = partial.baseUrl;
  if (partial.processingMode !== undefined) file.processingMode = partial.processingMode;

  try {
    const dir = path.dirname(CONFIG_PATH);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(file, null, 2) + '\n', 'utf8');
  } catch (e) {
    throw new Error('config-store: failed to write config: ' + e.message);
  }
  return merge(DEFAULTS, file, envOverrides());
}

function reset() {
  try { fs.unlinkSync(CONFIG_PATH); } catch (_) {}
  return merge(DEFAULTS, {}, envOverrides());
}

function getApiKey() {
  return process.env.ANCHOR_API_KEY || process.env.ANTHROPIC_API_KEY || null;
}

function hasApiKey() {
  return !!getApiKey();
}

function getConfigPath() {
  return CONFIG_PATH;
}

// ── Helpers ─────────────────────────────────────────────────────────

function merge(...sources) {
  const out = {};
  for (const src of sources) {
    for (const [k, v] of Object.entries(src)) {
      if (v !== undefined && v !== null && v !== '') out[k] = v;
    }
  }
  return { ...DEFAULTS, ...out };
}

module.exports = { load, save, reset, getApiKey, hasApiKey, getConfigPath, DEFAULTS };
