// mcp/connectors/index.cjs
// Connector registry — loads enabled connectors from connectors.json config.
'use strict';

const fs   = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..', '..');
const CONFIG_FILE = path.join(ROOT, 'logs', 'workspace', 'connectors.json');

// ── Phase 1 connectors ────────────────────────────────────────────────
const secEdgar      = require('./sec-edgar.cjs');
const fred          = require('./fred.cjs');
const reutersRss    = require('./reuters-rss.cjs');
const marketwatchRss = require('./marketwatch-rss.cjs');
const yahooFinance  = require('./yahoo-finance.cjs');

// ── Phase 2 connectors ────────────────────────────────────────────────
const cnbcRss       = require('./cnbc-rss.cjs');
const investingCal  = require('./investing-calendar.cjs');
const finnhub       = require('./finnhub.cjs');
const kolRss        = require('./kol-rss.cjs');

// ── Phase 3 connectors ────────────────────────────────────────────────
const stocktwits    = require('./stocktwits.cjs');
const reddit        = require('./reddit.cjs');
const fearGreed     = require('./fear-greed.cjs');
const aaii          = require('./aaii.cjs');

// ── Phase 4 connectors ────────────────────────────────────────────────
const tradingviewWh = require('./tradingview-webhook.cjs');
const cftcCot       = require('./cftc-cot.cjs');
const naaim         = require('./naaim.cjs');

const CONNECTORS = [
  secEdgar, fred, reutersRss, marketwatchRss, yahooFinance,
  cnbcRss, investingCal, finnhub, kolRss,
  stocktwits, reddit, fearGreed, aaii,
  tradingviewWh, cftcCot, naaim,
];

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function saveConfig(config) {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
  } catch (e) {
    console.error('[connectors] save config failed:', e.message);
  }
}

let _broker = null;
let _scheduler = null;
const _instances = {};  // connector.id → { connector, cfg }

function loadAll(broker, scheduler) {
  _broker = broker;
  _scheduler = scheduler;
  const config = loadConfig();
  let count = 0;
  for (const connector of CONNECTORS) {
    const cfg = config[connector.id] || {};
    if (cfg.enabled === false) {
      console.log('[connectors] skipped (disabled):', connector.id);
      _instances[connector.id] = { connector, cfg: { ...cfg, enabled: false }, running: false };
      continue;
    }
    try {
      connector.init(broker, { connectorConfig: cfg || {}, scheduler });
      _instances[connector.id] = { connector, cfg: { ...cfg, enabled: true }, running: true };
      console.log('[connectors] loaded:', connector.id);
      count++;
    } catch (e) {
      console.error('[connectors] failed to load', connector.id + ':', e.message);
      _instances[connector.id] = { connector, cfg: { ...cfg, enabled: false }, running: false, error: e.message };
    }
  }
  console.log('[connectors] loaded', count, 'connector(s)');
}

const PURPOSES = {
  'sec-edgar':          'SEC  filings — 公司披露 / 财报 / 内幕交易',
  'fred':               'FRED 宏观数据 — CPI / 利率 / 就业 / 货币供应',
  'reuters-rss':        '路透社金融新闻',
  'marketwatch-rss':    'MarketWatch 市场快讯',
  'yahoo-finance':      'Yahoo Finance 行情数据',
  'cnbc-rss':           'CNBC 商业新闻',
  'investing-calendar': '财经日历 — 经济数据 / 财报日程',
  'finnhub':            'Finnhub 基本面 & 情绪数据',
  'kol-rss':            'KOL 博客 — Lyn Alden / Damodaran 等',
  'stocktwits':         'StockTwits 社交情绪',
  'reddit':             'Reddit 论坛讨论 (r/wallstreetbets 等)',
  'fear-greed':         'CNN Fear & Greed 恐惧贪婪指数',
  'aaii':               'AAII 散户情绪调查',
  'tradingview-webhook':'TradingView 策略信号 Webhook',
  'cftc-cot':           'CFTC COT 持仓报告',
  'naaim':              'NAAIM 基金经理仓位调查',
};

function list() {
  return CONNECTORS.map(c => {
    const inst = _instances[c.id];
    const cfg = inst ? inst.cfg : {};
    return {
      id: c.id,
      name: c.name || c.id,
      purpose: PURPOSES[c.id] || '',
      enabled: cfg.enabled !== false,
      running: inst ? !!inst.running : false,
      error: inst ? inst.error : null,
    };
  });
}

function toggle(id, enabled) {
  const config = loadConfig();
  if (!config[id]) config[id] = {};
  config[id].enabled = enabled !== false;
  saveConfig(config);

  const entry = _instances[id];
  if (!entry) throw new Error('connector not found: ' + id);

  if (enabled !== false) {
    // Start the connector
    const cfg = config[id] || {};
    try {
      entry.connector.init(_broker, { connectorConfig: cfg, scheduler: _scheduler });
      entry.cfg = { ...cfg, enabled: true };
      entry.running = true;
      entry.error = null;
    } catch (e) {
      entry.error = e.message;
      throw e;
    }
  } else {
    // Stop the connector
    if (typeof entry.connector.stop === 'function') {
      entry.connector.stop();
    }
    entry.cfg = { ...cfg || entry.cfg, enabled: false };
    entry.running = false;
  }
  return { id, enabled: enabled !== false, running: entry.running };
}

module.exports = { loadAll, list, toggle };
