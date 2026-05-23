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

  // Build ccPrompt for push_analyze enrichment — follows market-news-analysis skill framework.
  _buildCcPrompt(item) {
    const kind   = item.payload && item.payload.kind;
    const url    = item.payload && item.payload.url;
    const source = item.source || 'unknown';
    const prefix = process.env.MARKET_SKILL_PREFIX || '使用 market-news-analysis skill (skills/market-news-analysis/) 分析市场情报。分析前加载 config/project-override.yaml 获取连接器-层级的映射和权重。';

    // Source tier tag per project-override.yaml connector_source_mapping
    const tierHint = (src) => {
      if (src.includes('sec-edgar') || src.includes('fred')) return '[Tier A — 事实底座]';
      if (src.includes('finnhub') || src.includes('yahoo') || src.includes('cftc') || src.includes('tradingview')) return '[Tier B — 数据供应商]';
      if (src.includes('reuters') || src.includes('marketwatch') || src.includes('cnbc')) return '[Tier C — 主流财经新闻]';
      if (src.includes('kol-rss')) return '[Tier F — 二级评论]';
      if (src.includes('stocktwits') || src.includes('reddit') || src.includes('fear-greed') || src.includes('aaii') || src.includes('naaim')) return '[Tier E — 情绪层]';
      return '';
    };

    if (kind === 'filing') {
      return `${prefix} 层级: core_ticker。${tierHint(source)} 分析此 SEC 申报文件摘要。给出页面结构: TickHero+FundamentalsSnapshot+CatalystRiskTimeline。输出200字中文概要、涉及的股票代码、重要性评分0-100（财报/并购/CEO变动=高）、reversal条件。申报: "${item.title}"。摘要: ${item.summary}${url ? `。原文链接: ${url}` : ''}`;
    }
    if (kind === 'macro') {
      return `${prefix} 层级: market_regime。${tierHint(source)} 分析此宏观经济数据变化。输出50字中文市场影响分析、受影响的板块列表、关注的事件风险。数据: "${item.title}"。详情: ${item.summary}`;
    }
    if (kind === 'commentary') {
      return `${prefix} 层级: sector_rotation / core_ticker。${tierHint(source)} 阅读此分析师文章。给出: 1) 100字中文核心论点 2) 关联美股板块/个股 3) 多空倾向(bullish/bearish/neutral) 4) 评分该观点的证据等级 5) 反转条件。标题: "${item.title}"${url ? `。链接: ${url}` : ''}`;
    }
    if (kind === 'news') {
      return `${prefix} 层级: market_regime / sector_rotation。${tierHint(source)} 分析此市场新闻。使用三层层级(market→sector→ticker)判断影响范围。给出: 1) 层面归属 2) 驱动因子(macro/rates/earnings/policy) 3) 50字中文概要 4) 受影响的标的。标题: "${item.title}"。摘要: ${item.summary}${url ? `。链接: ${url}` : ''}`;
    }
    if (kind === 'price_alert') {
      return `${prefix} 层级: core_ticker。${tierHint(source)} 股价预警触发。给出: MoveAttributionPanel(price结构+百分比)+OptionSentiment(量/IV/PCR)+NextCatalysts。标题: "${item.title}"。`;
    }
    return `${prefix} 使用三层层级(market→sector→ticker)分析此市场资讯。输出50字中文概要。标题: ${item.title}。摘要: ${item.summary}`;
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
