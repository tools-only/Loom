// mcp/connectors/marketwatch-rss.cjs
// Polls MarketWatch top stories RSS feed.
'use strict';

const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

const FEED_URL = 'https://feeds.content.dowjones.io/public/rss/mw_topstories';

class MarketwatchRssConnector extends BaseConnector {
  constructor() {
    super('marketwatch-rss', 'MarketWatch');
  }

  start() {
    this.scheduleCron('*/10 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 7000);
  }

  async poll() {
    try {
      const { items } = await fetchFeed(FEED_URL);
      for (const item of items) {
        const extId = item.guid || item.link;
        if (!extId) continue;
        this.dedupePush({
          domain:  'market',
          title:   '[MW] ' + item.title,
          summary: item.summary,
          source:  'feed:marketwatch-rss',
          payload: {
            external_id:  extId,
            kind:         'news',
            url:          item.link,
            published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
            tickers:      []
          }
        });
      }
    } catch (e) {
      console.error('[marketwatch-rss] error:', e.message);
    }
  }
}

module.exports = new MarketwatchRssConnector();
