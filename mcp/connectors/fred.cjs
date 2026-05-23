// mcp/connectors/fred.cjs
// Polls FRED (Federal Reserve Economic Data) for key macro series.
// Pushes only when a new observation date appears since last check.
'use strict';

const path = require('path');
const fs   = require('fs');
const { BaseConnector } = require('./_base.cjs');

const ROOT       = path.join(__dirname, '..', '..');
const STATE_FILE = path.join(ROOT, 'logs', 'workspace', 'fred-state.json');

const SERIES_META = {
  CPIAUCSL: { label: 'CPI（总体）',      unit: '同比',   domain: 'market' },
  UNRATE:   { label: '失业率',            unit: '%',      domain: 'market' },
  FEDFUNDS: { label: '联邦基金利率',      unit: '%',      domain: 'market' },
  DGS10:    { label: '10年国债收益率',    unit: '%',      domain: 'market' },
  DGS2:     { label: '2年国债收益率',     unit: '%',      domain: 'market' },
  VIXCLS:   { label: 'VIX 恐慌指数',     unit: 'pts',    domain: 'market' },
  M2SL:     { label: 'M2货币供应',        unit: 'B USD',  domain: 'market' },
  GDP:      { label: 'GDP（季度）',        unit: 'B USD',  domain: 'market' },
};

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}
function saveState(state) {
  try { fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), 'utf8'); } catch {}
}

class FredConnector extends BaseConnector {
  constructor() {
    super('fred', 'FRED Macro');
    this._state = {};
  }

  start() {
    if (!this._config.apiKey) {
      console.warn('[fred] no apiKey configured — skipping. Add apiKey to connectors.json.');
      return;
    }
    this._state = loadState();
    // Poll at ET 8:30 and 14:00 on weekdays
    this.scheduleCron('30 8,14 * * 1-5', 'America/New_York');
    setTimeout(() => this.poll(), 8000);
  }

  async poll() {
    const apiKey  = this._config.apiKey;
    const series  = this._config.series || Object.keys(SERIES_META);

    for (const seriesId of series) {
      try {
        await this._pollSeries(seriesId, apiKey);
      } catch (e) {
        console.error('[fred] error for series', seriesId + ':', e.message);
      }
    }
  }

  async _pollSeries(seriesId, apiKey) {
    const url = `https://api.stlouisfed.org/fred/series/observations` +
      `?series_id=${seriesId}&api_key=${apiKey}&sort_order=desc&limit=2&file_type=json`;

    const data = await this.httpGet(url);
    if (!data || !Array.isArray(data.observations) || data.observations.length === 0) return;

    const latest = data.observations[0];
    const prev   = data.observations[1];
    if (!latest || latest.value === '.') return;

    const extId = seriesId + ':' + latest.date;
    if (this._state[seriesId] === latest.date) return;  // already pushed

    const meta      = SERIES_META[seriesId] || { label: seriesId, unit: '', domain: 'market' };
    const latestVal = parseFloat(latest.value);
    const prevVal   = prev && prev.value !== '.' ? parseFloat(prev.value) : null;
    const arrow     = prevVal !== null
      ? (latestVal > prevVal ? ' ↑' : latestVal < prevVal ? ' ↓' : ' →')
      : '';

    const title   = `${meta.label}: ${latestVal}${meta.unit ? ' ' + meta.unit : ''}${arrow}`;
    const summary = prevVal !== null
      ? `${meta.label} 最新值 ${latest.date}: ${latestVal}${meta.unit}，前值 ${prevVal}${meta.unit}。数据来源: FRED`
      : `${meta.label} 最新值 ${latest.date}: ${latestVal}${meta.unit}。数据来源: FRED`;

    this.dedupePush({
      domain:  meta.domain,
      title,
      summary,
      source:  'feed:fred',
      payload: {
        external_id:  extId,
        kind:         'macro',
        series_id:    seriesId,
        value:        latestVal,
        prev_value:   prevVal,
        obs_date:     latest.date,
        published_at: new Date(latest.date).toISOString(),
        tickers:      []
      }
    });

    this._state[seriesId] = latest.date;
    saveState(this._state);
  }
}

module.exports = new FredConnector();
