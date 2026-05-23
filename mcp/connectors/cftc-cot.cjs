// mcp/connectors/cftc-cot.cjs
// Polls CFTC COT (Commitment of Traders) report — weekly Friday release.
'use strict';

const { BaseConnector } = require('./_base.cjs');

class CftcCotConnector extends BaseConnector {
  constructor() {
    super('cftc-cot', 'CFTC COT');
  }

  start() {
    // Weekly Friday after 12pm ET (COT release typically Mon/Tue, delayed)
    this.scheduleCron('0 14 * * 5', 'America/New_York');
    setTimeout(() => this.poll(), 40000);
  }

  async poll() {
    try {
      // CME futures tickers we track
      const SERIES = [
        { id: '13874', label: '10-Year Treasury',  ticker: 'ZN'     },
        { id: '13873', label: '5-Year Treasury',    ticker: 'ZF'     },
        { id: '12460', label: 'S&P 500',           ticker: 'ES'     },
        { id: '13873', label: 'Nasdaq 100',         ticker: 'NQ'     }, // same as 5yr placeholder
        { id: '12461', label: 'VIX',                ticker: 'VIX'    },
      ];

      for (const series of SERIES) {
        await this._fetchSeries(series);
        await new Promise(r => setTimeout(r, 800));
      }
    } catch (e) {
      console.error('[cftc-cot] error:', e.message);
    }
  }

  async _fetchSeries(series) {
    // CFTC disaggregated futures data — CSV download
    const url = `https://www.cftc.gov/files/dea/futures/financialfuts.txt`;
    try {
      const text = await this.httpGet(url, { timeout: 20000 });
      if (!text) return;
      // Parse key lines: format is fixed-width CSV
      // Cols: CFTC Contract Code, Market, Report Date, Long, Short, Open Interest
      const lines = text.split('\n').filter(l => l.includes(series.ticker) || l.includes(series.label));
      if (!lines.length) return;

      const parseRow = (row) => {
        const cols = row.split(',');
        return {
          date: cols[2] || '',
          longs: parseInt(cols[3] || '0'),
          shorts: parseInt(cols[4] || '0'),
          oi: parseInt(cols[5] || '0'),
        };
      };

      const latest = parseRow(lines[0]);
      if (!latest.date) return;

      const net = latest.longs - latest.shorts;
      const pct = latest.oi > 0 ? Math.round((latest.longs / latest.oi) * 100) : 0;

      this.dedupePush({
        domain:  'market',
        title:   `[COT] ${series.label} 净多头 ${net > 0 ? '+' : ''}${net}`,
        summary: `CFTF COT 持仓报告（${latest.date}）：多头 ${latest.longs} / 空头 ${latest.shorts} / 未平净 ${latest.oi}，净多头占比 ${pct}%`,
        source:  'feed:cftc-cot',
        payload: {
          external_id:  `cftc-cot:${series.id}:${latest.date}`,
          kind:         'macro',
          ticker:       series.ticker,
          label:        series.label,
          longs:         latest.longs,
          shorts:       latest.shorts,
          net_position: net,
          pct_long:     pct,
          report_date:  latest.date,
          published_at: new Date().toISOString(),
          tickers:      [series.ticker]
        }
      });
    } catch (e) {
      console.error('[cftc-cot] error fetching', series.ticker + ':', e.message);
    }
  }
}

module.exports = new CftcCotConnector();