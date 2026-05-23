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
    // Attach ccPrompt for Agent enrichment if enrichWithAgent is configured
    const enriched = this._config.enrichWithAgent
      ? { ...item, ccPrompt: this._buildCcPrompt(item) }
      : item;
    this._broker.push(enriched);
    return true;
  }

  // Build ccPrompt for push_analyze enrichment. Subclasses may override.
  _buildCcPrompt(item) {
    const kind = item.payload && item.payload.kind;
    const url  = item.payload && item.payload.url;
    if (kind === 'filing') {
      return `分析此 SEC 申报文件摘要，给出：1) 200字中文概要 2) 涉及的股票代码列表 3) 重要性评分0-100（财报/并购/CEO变动=高）。申报: "${item.title}"。摘要: ${item.summary}${url ? `。原文链接: ${url}` : ''}`;
    }
    if (kind === 'commentary') {
      return `阅读此分析师文章，给出：1) 100字中文核心论点 2) 关联美股板块或个股 3) 多空倾向（bullish/bearish/neutral）。标题: "${item.title}"${url ? `。链接: ${url}` : ''}`;
    }
    if (kind === 'macro') {
      return `分析此宏观经济数据变化，给出50字中文市场影响分析。数据: "${item.title}"。详情: ${item.summary}`;
    }
    return `用50字中文概括此市场资讯的关键信息：${item.title}`;
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
