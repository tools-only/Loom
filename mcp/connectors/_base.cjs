// mcp/connectors/_base.cjs
// Base class for all market-data connectors.
'use strict';

const path    = require('path');
const ROOT    = path.join(__dirname, '..', '..');
const BRIDGE_NM = path.join(ROOT, 'bridge', 'node_modules');
const nodeCron = require(path.join(BRIDGE_NM, 'node-cron'));
const axios   = require(path.join(BRIDGE_NM, 'axios'));

class BaseConnector {
  constructor(id, name) {
    this.id       = id;
    this.name     = name;
    this._broker  = null;
    this._config  = {};
    this._cronJob = null;
    this._seen    = new Set();  // external_id dedup cache (session-scoped)
  }

  // Called by connectorRegistry.loadAll
  init(broker, { connectorConfig = {} } = {}) {
    this._broker = broker;
    this._config = connectorConfig;
    this.start();
  }

  // Subclasses override to set up cron schedule and optional eager first poll
  start() {}

  // Schedule poll() on a cron expression (tz defaults to US/Eastern)
  scheduleCron(expr, tz = 'America/New_York') {
    if (!nodeCron.validate(expr)) {
      console.warn('[' + this.id + '] invalid cron expr:', expr);
      return;
    }
    this._cronJob = nodeCron.schedule(expr, () => {
      try { this.poll(); } catch (e) {
        console.error('[' + this.id + '] poll error:', e.message);
      }
    }, { timezone: tz });
    console.log('[' + this.id + '] scheduled:', expr, tz);
  }

  // Push an item with session-level dedup on external_id.
  // Returns true if pushed, false if duplicate.
  dedupePush(item) {
    const extId = item.payload && item.payload.external_id;
    if (extId) {
      const key = (item.source || this.id) + '::' + extId;
      if (this._seen.has(key)) return false;
      // Keep set bounded
      if (this._seen.size > 600) {
        const oldest = [...this._seen].slice(0, 100);
        oldest.forEach(k => this._seen.delete(k));
      }
      this._seen.add(key);
    }
    this._broker.push(item);
    return true;
  }

  // HTTP GET helper — returns response data or throws
  async httpGet(url, opts = {}) {
    const res = await axios.default.get(url, {
      timeout:  opts.timeout || 15000,
      headers: {
        'User-Agent': 'Loom/1.0 (personal research workspace)',
        ...(opts.headers || {})
      },
      responseType: opts.responseType || 'json'
    });
    return res.data;
  }

  // Override in subclass
  poll() {}

  stop() {
    if (this._cronJob) { this._cronJob.stop(); this._cronJob = null; }
  }
}

module.exports = { BaseConnector };
