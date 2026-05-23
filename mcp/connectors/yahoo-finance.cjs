// mcp/connectors/yahoo-finance.cjs
// Polls Yahoo Finance per-ticker RSS for the user's Mode C watch list.
// Tickers sourced from: connectors.json "yahoo-finance.tickers" (static list)
// or from logs/workspace/targets.json (dynamic Mode C list, if it exists).
'use strict';

const fs   = require('fs');
const path = require('path');
const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

const ROOT        = path.join(__dirname, '..', '..');
const TARGETS_FILE = path.join(ROOT, 'logs', 'workspace', 'targets.json');

function yahooFeedUrl(ticker) {
  return `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${encodeURIComponent(ticker)}&region=US&lang=en-US`;
}

function loadTargetTickers() {
  try {
    const data = JSON.parse(fs.readFileSync(TARGETS_FILE, 'utf8'));
    if (Array.isArray(data)) return data.map(t => typeof t === 'string' ? t : t.ticker).filter(Boolean);
    if (data.tickers) return data.tickers;
  } catch {}
  return [];
}

class YahooFinanceConnector extends BaseConnector {
  constructor() {
    super('yahoo-finance', 'Yahoo Finance');
  }

  start() {
    this.scheduleCron('*/20 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 10000);
  }

  _getTickers() {
    const configured = this._config.tickers || [];
    const dynamic    = loadTargetTickers();
    const merged     = [...new Set([...configured, ...dynamic])];
    return merged;
  }

  async poll() {
    const tickers = this._getTickers();
    if (tickers.length === 0) return;

    for (const ticker of tickers) {
      try {
        await this._pollTicker(ticker);
        // Small delay to be polite
        await new Promise(r => setTimeout(r, 300));
      } catch (e) {
        console.error('[yahoo-finance] error for', ticker + ':', e.message);
      }
    }
  }

  async _pollTicker(ticker) {
    const { items } = await fetchFeed(yahooFeedUrl(ticker));
    for (const item of items) {
      const extId = item.guid || item.link;
      if (!extId) continue;
      this.dedupePush({
        domain:  'target',
        title:   `[${ticker}] ${item.title}`,
        summary: item.summary,
        source:  'feed:yahoo-finance',
        payload: {
          external_id:  extId,
          kind:         'news',
          url:          item.link,
          published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
          tickers:      [ticker]
        }
      });
    }
  }
}

module.exports = new YahooFinanceConnector();
