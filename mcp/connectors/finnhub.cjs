// mcp/connectors/finnhub.cjs
// Polls Finnhub free tier: earnings calendar, IPO calendar, analyst recommendations.
// Requires free API key at finnhub.io — set in connectors.json "finnhub.apiKey".
'use strict';

const path = require('path');
const fs   = require('fs');
const { BaseConnector } = require('./_base.cjs');

const ROOT       = path.join(__dirname, '..', '..');
const TARGETS_FILE = path.join(ROOT, 'logs', 'workspace', 'targets.json');

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}
function futureStr(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
function loadTargetTickers() {
  try {
    const data = JSON.parse(fs.readFileSync(TARGETS_FILE, 'utf8'));
    if (Array.isArray(data)) return data.map(t => typeof t === 'string' ? t : t.ticker).filter(Boolean);
    if (data.tickers) return data.tickers;
  } catch {}
  return [];
}

class FinnhubConnector extends BaseConnector {
  constructor() {
    super('finnhub', 'Finnhub');
  }

  start() {
    if (!this._config.apiKey) {
      console.warn('[finnhub] no apiKey — skipping. Register free at finnhub.io and set in connectors.json.');
      return;
    }
    // Daily at ET 8:00 weekdays
    this.scheduleCron('0 8 * * 1-5', 'America/New_York');
    // Weekly IPO calendar on Mondays
    this.scheduleCron('0 8 * * 1', 'America/New_York');
    setTimeout(() => this.poll(), 15000);
  }

  async poll() {
    const key = this._config.apiKey;
    await this._pollEarnings(key);
    await this._pollIPO(key);
    await this._pollRecommendations(key);
  }

  async _pollEarnings(key) {
    try {
      const from = todayStr();
      const to   = futureStr(7);
      const data = await this.httpGet(
        `https://finnhub.io/api/v1/calendar/earnings?from=${from}&to=${to}&token=${key}`
      );
      const items = (data && data.earningsCalendar) ? data.earningsCalendar : [];
      for (const ev of items.slice(0, 20)) {
        const extId = `earnings:${ev.symbol}:${ev.date}`;
        this.dedupePush({
          domain:  'market',
          title:   `[财报日] ${ev.symbol} — ${ev.date}`,
          summary: `${ev.symbol} 财报预定于 ${ev.date}，预期 EPS: ${ev.epsEstimate ?? '未知'}，收入预期: ${ev.revenueEstimate ?? '未知'}`,
          source:  'feed:finnhub',
          payload: {
            external_id:  extId,
            kind:         'event',
            published_at: new Date(ev.date).toISOString(),
            tickers:      [ev.symbol],
            eps_estimate: ev.epsEstimate,
            revenue_est:  ev.revenueEstimate
          }
        });
      }
    } catch (e) {
      console.error('[finnhub] earnings error:', e.message);
    }
  }

  async _pollIPO(key) {
    try {
      const from = todayStr();
      const to   = futureStr(30);
      const data = await this.httpGet(
        `https://finnhub.io/api/v1/calendar/ipo?from=${from}&to=${to}&token=${key}`
      );
      const items = (data && data.ipoCalendar) ? data.ipoCalendar : [];
      for (const ev of items.slice(0, 10)) {
        const extId = `ipo:${ev.symbol}:${ev.date}`;
        this.dedupePush({
          domain:  'market',
          title:   `[IPO] ${ev.name} (${ev.symbol}) — ${ev.date}`,
          summary: `${ev.name} IPO 预定 ${ev.date}，价格区间: ${ev.price ?? '未知'}，交易所: ${ev.exchange ?? '未知'}`,
          source:  'feed:finnhub',
          payload: {
            external_id:  extId,
            kind:         'event',
            published_at: new Date(ev.date).toISOString(),
            tickers:      [ev.symbol]
          }
        });
      }
    } catch (e) {
      console.error('[finnhub] IPO error:', e.message);
    }
  }

  async _pollRecommendations(key) {
    const tickers = loadTargetTickers();
    for (const ticker of tickers.slice(0, 10)) {
      try {
        const data = await this.httpGet(
          `https://finnhub.io/api/v1/stock/recommendation?symbol=${ticker}&token=${key}`
        );
        if (!Array.isArray(data) || data.length === 0) continue;
        const latest = data[0];
        const extId = `rec:${ticker}:${latest.period}`;
        this.dedupePush({
          domain:  'market',
          title:   `[评级] ${ticker} — 买入${latest.buy}/ 持有${latest.hold}/ 卖出${latest.sell}`,
          summary: `${ticker} 分析师评级（${latest.period}）: 买入 ${latest.buy}，持有 ${latest.hold}，卖出 ${latest.sell}，强力买入 ${latest.strongBuy}`,
          source:  'feed:finnhub',
          payload: {
            external_id:  extId,
            kind:         'analyst',
            published_at: new Date(latest.period + '-01').toISOString(),
            tickers:      [ticker],
            buy:          latest.buy,
            hold:         latest.hold,
            sell:         latest.sell
          }
        });
        await new Promise(r => setTimeout(r, 200));
      } catch (e) {
        console.error('[finnhub] rec error for', ticker + ':', e.message);
      }
    }
  }
}

module.exports = new FinnhubConnector();
