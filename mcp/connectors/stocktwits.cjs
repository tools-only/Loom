// mcp/connectors/stocktwits.cjs
// Polls StockTwits for sentiment on Mode C watch-list tickers.
// Pushes only when bullish/bearish ratio crosses thresholds.
'use strict';

const path = require('path');
const fs   = require('fs');
const { BaseConnector } = require('./_base.cjs');

const ROOT         = path.join(__dirname, '..', '..');
const TARGETS_FILE = path.join(ROOT, 'logs', 'workspace', 'targets.json');
const BULL_THRESH  = 0.70;
const BEAR_THRESH  = 0.30;

function loadTargetTickers(config) {
  const configured = config.tickers || [];
  try {
    const data = JSON.parse(fs.readFileSync(TARGETS_FILE, 'utf8'));
    const dynamic = Array.isArray(data) ? data.map(t => typeof t === 'string' ? t : t.ticker) : (data.tickers || []);
    return [...new Set([...configured, ...dynamic.filter(Boolean)])];
  } catch {
    return configured;
  }
}

class StocktwitsConnector extends BaseConnector {
  constructor() {
    super('stocktwits', 'StockTwits');
  }

  start() {
    // Hourly
    this.scheduleCron('0 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 25000);
  }

  async poll() {
    const tickers = loadTargetTickers(this._config);
    for (const ticker of tickers.slice(0, 15)) {
      try {
        await this._pollTicker(ticker);
        await new Promise(r => setTimeout(r, 500));
      } catch (e) {
        console.error('[stocktwits] error for', ticker + ':', e.message);
      }
    }
  }

  async _pollTicker(ticker) {
    const data = await this.httpGet(
      `https://api.stocktwits.com/api/2/streams/symbol/${ticker}.json`,
      { timeout: 10000 }
    );
    if (!data || !data.messages) return;

    const msgs    = data.messages.slice(0, 100);
    const bullish = msgs.filter(m => m.entities && m.entities.sentiment && m.entities.sentiment.basic === 'Bullish').length;
    const bearish = msgs.filter(m => m.entities && m.entities.sentiment && m.entities.sentiment.basic === 'Bearish').length;
    const total   = bullish + bearish;
    if (total < 5) return;

    const ratio = bullish / total;
    if (ratio >= BULL_THRESH || ratio <= BEAR_THRESH) {
      const sentiment = ratio >= BULL_THRESH ? 'bullish 🟢' : 'bearish 🔴';
      const pct       = Math.round(ratio * 100);
      const extId     = `stocktwits:${ticker}:${new Date().toISOString().slice(0, 13)}`;

      this.dedupePush({
        domain:  'sentiment',
        title:   `[情绪异动] ${ticker} 偏 ${sentiment} (${pct}%)`,
        summary: `StockTwits 最近 ${total} 条有效情绪: 看涨 ${bullish} / 看跌 ${bearish}，比率 ${pct}%`,
        source:  'feed:stocktwits',
        payload: {
          external_id:  extId,
          kind:         'social',
          ticker,
          bull_ratio:   ratio,
          bull_count:   bullish,
          bear_count:   bearish,
          published_at: new Date().toISOString(),
          tickers:      [ticker]
        }
      });
    }
  }
}

module.exports = new StocktwitsConnector();
