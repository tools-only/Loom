// mcp/connectors/aaii.cjs
// Polls AAII Investor Sentiment Survey — weekly Thursday results.
'use strict';

const { loadModule } = require('./_base.cjs');

// AAII publishes results every Thursday at 4pm ET;
// we pull Friday morning to ensure data is available.
class AaiiConnector {
  constructor() {
    this._id   = 'aaii';
    this._name = 'AAII Sentiment';
    this._cron = '0 9 * * 5'; // 9am ET every Friday
  }

  start() {
    this.scheduleCron(this._cron, 'America/New_York');
    setTimeout(() => this.poll(), 20000);
  }

  async poll() {
    try {
      const res = await this.httpGet('https://www.aaii.com/sentimentsurvey/sent_results', {
        headers: { 'User-Agent': 'Loom/1.0 (personal research tool)' },
        timeout: 15000
      });
      if (!res) return;

      // Try to extract sentiment values via regex from HTML
      // Typical page contains: "Bullish: 38.5%" / "Neutral: 31.1%" / "Bearish: 30.4%"
      const text = typeof res === 'string' ? res : JSON.stringify(res);
      const bullM = text.match(/Bullish\s*[:\-]?\s*([\d.]+)/i);
      const bearM = text.match(/Bearish\s*[:\-]?\s*([\d.]+)/i);
      const neutM = text.match(/Neutral\s*[:\-]?\s*([\d.]+)/i);

      if (!bullM || !bearM) {
        console.error('[aaii] could not parse sentiment values from page');
        return;
      }

      const bullish = parseFloat(bullM[1]);
      const bearish = parseFloat(bearM[1]);
      const neutral = neutM ? parseFloat(neutM[1]) : (100 - bullish - bearish);
      const score   = Math.round(bullish - bearish + 50); // 0-100 scale normalized

      this.dedupePush({
        domain:  'sentiment',
        title:   `[AAII] 看涨 ${bullish}% / 看跌 ${bearish}% / 中性 ${neutral.toFixed(1)}%`,
        summary: `AAII 散户情绪调查：看涨 ${bullish}%（前周 ${bearish}%），看跌 ${bearish}%，中性 ${neutral.toFixed(1)}%`,
        source:  'feed:aaii',
        payload: {
          external_id:  `aaii:${new Date().toISOString().slice(0, 10)}`,
          kind:         'social',
          bullish_pct:  bullish,
          bearish_pct:  bearish,
          neutral_pct:  neutral,
          score,
          published_at: new Date().toISOString(),
          tickers:      []
        }
      });
    } catch (e) {
      console.error('[aaii] error:', e.message);
    }
  }
}

module.exports = new AaiiConnector();