// mcp/inbox.cjs
// Flat-file inbox store. Items persisted to logs/workspace/inbox.json.
'use strict';

const fs   = require('fs');
const path = require('path');

const ROOT       = path.join(__dirname, '..');
const INBOX_FILE = path.join(ROOT, 'logs', 'workspace', 'inbox.json');

const DOMAINS = ['market', 'position', 'target', 'sentiment'];

let _items = [];  // in-memory cache

function _save() {
  try { fs.writeFileSync(INBOX_FILE, JSON.stringify(_items, null, 2), 'utf8'); } catch {}
}

function load() {
  try {
    const raw = fs.readFileSync(INBOX_FILE, 'utf8');
    _items = JSON.parse(raw);
    if (!Array.isArray(_items)) _items = [];
  } catch { _items = []; }
}

function append(item) {
  // Idempotent dedup: same source + external_id → return existing item
  if (item.payload && item.payload.external_id) {
    const src = item.source || 'manual';
    const exists = _items.find(it =>
      it.source === src &&
      it.payload && it.payload.external_id === item.payload.external_id
    );
    if (exists) return exists;
  }

  const entry = {
    id: Date.now() + '-' + Math.random().toString(36).slice(2, 7),
    domain: item.domain,
    title: String(item.title || ''),
    summary: String(item.summary || ''),
    payload: item.payload || {},
    source: item.source || 'manual',
    read: false,
    timestamp: new Date().toISOString()
  };
  _items.unshift(entry);

  // Sort newest-first by published_at (from feed) or ingestion timestamp
  _items.sort((a, b) => {
    const da = (a.payload && a.payload.published_at) || a.timestamp;
    const db = (b.payload && b.payload.published_at) || b.timestamp;
    return new Date(db) - new Date(da);
  });

  if (_items.length > 200) _items = _items.slice(0, 200);
  _save();
  return entry;
}

function markRead(id) {
  const item = _items.find(i => i.id === id);
  if (!item) return false;
  item.read = true;
  _save();
  return true;
}

function markAllRead(domain) {
  let changed = false;
  for (const item of _items) {
    if (!domain || item.domain === domain) { item.read = true; changed = true; }
  }
  if (changed) _save();
}

function list({ domain, unread } = {}) {
  let result = _items;
  if (domain) result = result.filter(i => i.domain === domain);
  if (unread)  result = result.filter(i => !i.read);
  return result;
}

function unreadCounts() {
  const counts = { market: 0, position: 0, target: 0, sentiment: 0, total: 0 };
  for (const item of _items) {
    if (!item.read && DOMAINS.includes(item.domain)) {
      counts[item.domain]++;
      counts.total++;
    }
  }
  return counts;
}

module.exports = { load, append, markRead, markAllRead, list, unreadCounts, DOMAINS };
