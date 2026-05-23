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
// const cnbcRss       = require('./cnbc-rss.cjs');
// const investingCal  = require('./investing-calendar.cjs');
// const finnhub       = require('./finnhub.cjs');
// const kolRss        = require('./kol-rss.cjs');

// ── Phase 3 connectors ────────────────────────────────────────────────
// const stocktwits    = require('./stocktwits.cjs');
// const reddit        = require('./reddit.cjs');
// const fearGreed     = require('./fear-greed.cjs');
// const aaii          = require('./aaii.cjs');

// ── Phase 4 connectors ────────────────────────────────────────────────
// const tradingviewWh = require('./tradingview-webhook.cjs');
// const cftcCot       = require('./cftc-cot.cjs');
// const naaim         = require('./naaim.cjs');

const CONNECTORS = [
  secEdgar, fred, reutersRss, marketwatchRss, yahooFinance,
  // cnbcRss, investingCal, finnhub, kolRss,
  // stocktwits, reddit, fearGreed, aaii,
  // tradingviewWh, cftcCot, naaim,
];

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function loadAll(broker, scheduler) {
  const config = loadConfig();
  let count = 0;
  for (const connector of CONNECTORS) {
    const cfg = config[connector.id];
    if (cfg && cfg.enabled === false) {
      console.log('[connectors] skipped (disabled):', connector.id);
      continue;
    }
    try {
      connector.init(broker, { connectorConfig: cfg || {}, scheduler });
      console.log('[connectors] loaded:', connector.id);
      count++;
    } catch (e) {
      console.error('[connectors] failed to load', connector.id + ':', e.message);
    }
  }
  console.log('[connectors] loaded', count, 'connector(s)');
}

module.exports = { loadAll, CONNECTORS };
