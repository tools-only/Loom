// mcp/connectors/naaim.cjs
// Polls NAAIM (National Association of Active Investment Managers) Exposure Index.
// Released weekly, typically Wednesday/Thursday.
'use strict';

const path = require('path');
const fs   = require('fs');
const { BaseConnector } = require('./_base.cjs');

const ROOT       = path.join(__dirname, '..', '..');
const STATE_FILE = path.join(ROOT, 'logs', 'workspace', 'naaim-state.json');

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return { lastValue: null }; }
}
function saveState(state) {
  try { fs.writeFileSync(STATE_FILE, JSON.stringify(state), 'utf8'); } catch {}
}

class NaaimConnector extends BaseConnector {
  constructor() {
    super('naaim', 'NAAIM Exposure');
    this._state = loadState();
  }

  start() {
    // Weekly Thursday 10am ET (index publishes mid-week)
    this.scheduleCron('0 10 * * 4', 'America/New_York');
    setTimeout(() => this.poll(), 45000);
  }

  async poll() {
    try {
      // NAAIM publishes via press release, page content varies
      const text = await this.httpGet('https://www.naaim.org/programs/naaim-exposure-index/', {
        headers: { 'User-Agent': 'Loom/1.0 (personal research tool)' },
        timeout: 15000
      });
      if (!text) return;

      // Try to extract the exposure value from page content
      // Typical format: "NAAIM Exposure Index: 65.4%" or "65.4%"
      const str   = typeof text === 'string' ? text : JSON.stringify(text);
      const match = str.match(/([\d.]+)\s*%?\s*<\/div>/);
      const val   = match ? parseFloat(match[1]) : null;
      if (val === null) {
        console.error('[naaim] could not extract exposure value');
        return;
      }

      const last   = this._state.lastValue;
      const extId  = `naaim:${new Date().toISOString().slice(0, 10)}`;

      // Only push if value changed meaningfully
      if (last === null || Math.abs(val - last) > 5) {
        const label = val > 80 ? '极高仓位' : val > 50 ? '高仓位' : val > 20 ? '中性偏高' : val < 0 ? '空仓' : '低仓位';
        this.dedupePush({
          domain:  'sentiment',
          title:   `[NAAIM] 经理股票暴露度 ${val}% — ${label}`,
          summary: `NAAIM 主动投资经理暴露度指数：${val}%${last !== null ? '（前周 ' + last + '%）' : ''}`,
          source:  'feed:naaim',
          payload: {
            external_id: extId,
            kind:       'social',
            exposure_pct: val,
            prev_pct:    last,
            label,
            published_at: new Date().toISOString(),
            tickers:     []
          }
        });

        this._state.lastValue = val;
        saveState(this._state);
      }
    } catch (e) {
      console.error('[naaim] error:', e.message);
    }
  }
}

module.exports = new NaaimConnector();