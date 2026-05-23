// mcp/connectors/fear-greed.cjs
// Polls CNN Fear & Greed Index — pushes only on threshold crossings.
'use strict';

const path = require('path');
const fs   = require('fs');
const { BaseConnector } = require('./_base.cjs');

const ROOT       = path.join(__dirname, '..', '..');
const STATE_FILE = path.join(ROOT, 'logs', 'workspace', 'fear-greed-state.json');
const THRESHOLDS = [25, 50, 75];

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return { lastScore: null }; }
}
function saveState(state) {
  try { fs.writeFileSync(STATE_FILE, JSON.stringify(state), 'utf8'); } catch {}
}

function scoreLabel(score) {
  if (score <= 25)  return '极度恐慌 😱';
  if (score <= 45)  return '恐慌 😨';
  if (score <= 55)  return '中性 😐';
  if (score <= 75)  return '贪婪 😁';
  return '极度贪婪 🤑';
}

class FearGreedConnector extends BaseConnector {
  constructor() {
    super('fear-greed', 'CNN Fear & Greed');
    this._state = loadState();
  }

  start() {
    // Daily at ET 16:30 (after market close)
    this.scheduleCron('30 16 * * 1-5', 'America/New_York');
    setTimeout(() => this.poll(), 35000);
  }

  async poll() {
    try {
      const data = await this.httpGet(
        'https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
        { timeout: 10000 }
      );
      if (!data || !data.fear_and_greed) return;
      const score = Math.round(data.fear_and_greed.score);
      this._maybePublish(score);
    } catch (e) {
      console.error('[fear-greed] error:', e.message);
    }
  }

  _maybePublish(score) {
    const last = this._state.lastScore;
    const crossed = last !== null && THRESHOLDS.some(t =>
      (last < t && score >= t) || (last >= t && score < t)
    );
    const isFirst = last === null;

    if (isFirst || crossed) {
      const label  = scoreLabel(score);
      const extId  = `fear-greed:${new Date().toISOString().slice(0, 10)}`;

      this.dedupePush({
        domain:  'sentiment',
        title:   `[恐慌贪婪] ${score} — ${label}`,
        summary: `CNN 恐慌与贪婪指数: ${score}/100 (${label})${last !== null ? `，前值 ${last}` : ''}`,
        source:  'feed:fear-greed',
        payload: {
          external_id:  extId,
          kind:         'social',
          score,
          prev_score:   last,
          published_at: new Date().toISOString(),
          tickers:      []
        }
      });

      this._state.lastScore = score;
      saveState(this._state);
    }
  }
}

module.exports = new FearGreedConnector();
