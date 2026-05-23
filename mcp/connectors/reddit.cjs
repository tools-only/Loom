// mcp/connectors/reddit.cjs
// Polls Reddit top posts from financial subreddits (wallstreetbets, stocks, investing).
'use strict';

const { BaseConnector } = require('./_base.cjs');

const SUBREDDITS = ['wallstreetbets', 'stocks', 'investing', 'ValueInvesting'];
// Regex to extract $TICKER or standalone all-caps 2-5 char tickers
const TICKER_RE  = /\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b/g;
const STOP_WORDS = new Set(['THE','AND','FOR','ARE','NOT','BUT','CAN','HAS','ITS','NEW','NOW','ONE','OUT','WAS','YOU','THIS','THAT','WITH','FROM','WILL','HAVE','BEEN','WHAT','WHEN','MORE','ABOUT','THEY']);

function extractTickers(text) {
  const found = new Set();
  let m;
  while ((m = TICKER_RE.exec(text)) !== null) {
    const t = m[1] || m[2];
    if (t && !STOP_WORDS.has(t)) found.add(t);
  }
  return [...found].slice(0, 5);
}

class RedditConnector extends BaseConnector {
  constructor() {
    super('reddit', 'Reddit');
  }

  start() {
    // Every 4 hours
    this.scheduleCron('0 */4 * * *', 'America/New_York');
    setTimeout(() => this.poll(), 30000);
  }

  async poll() {
    for (const sub of SUBREDDITS) {
      try {
        await this._pollSubreddit(sub);
        await new Promise(r => setTimeout(r, 1000));
      } catch (e) {
        console.error('[reddit] error for r/' + sub + ':', e.message);
      }
    }
  }

  async _pollSubreddit(sub) {
    const data = await this.httpGet(
      `https://www.reddit.com/r/${sub}/top.json?t=day&limit=10`,
      { headers: { 'User-Agent': 'Loom/1.0 (personal research tool)' } }
    );
    if (!data || !data.data || !data.data.children) return;

    for (const post of data.data.children.slice(0, 5)) {
      const p     = post.data;
      const extId = `reddit:${p.id}`;
      const tickers = extractTickers(p.title);
      const upvotes = p.score || 0;

      this.dedupePush({
        domain:  'sentiment',
        title:   `[r/${sub}] ${p.title}`,
        summary: `${upvotes} upvotes · ${p.num_comments || 0} comments${tickers.length ? ' · 标的: ' + tickers.join(', ') : ''}`,
        source:  'feed:reddit',
        payload: {
          external_id:  extId,
          kind:         'social',
          subreddit:    sub,
          upvotes,
          url:          `https://reddit.com${p.permalink}`,
          published_at: new Date(p.created_utc * 1000).toISOString(),
          tickers
        }
      });
    }
  }
}

module.exports = new RedditConnector();
