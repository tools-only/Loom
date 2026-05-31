// mcp/connectors/reuters-rss.cjs
// Polls Reuters Markets RSS feed.
'use strict';

const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

// reuters.com free RSS was shut down in 2020; replaced with AP Business News
const FEEDS = [
  'https://apnews.com/hub/business.rss',
  'https://apnews.com/hub/financial-markets.rss',
];

class ReutersRssConnector extends BaseConnector {
  constructor() {
    super('reuters-rss', 'Reuters');
  }

  start() {
    this.scheduleCron('*/10 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 6000);
  }

  async poll() {
    for (const url of FEEDS) {
      try {
        await this._pollFeed(url);
      } catch (e) {
        console.error('[reuters-rss] error:', e.message);
      }
    }
  }

  async _pollFeed(url) {
    const { items } = await fetchFeed(url);
    for (const item of items) {
      const extId = item.guid || item.link;
      if (!extId) continue;
      this.dedupePush({
        domain:  'market',
        title:   '[Reuters] ' + item.title,
        summary: item.summary,
        source:  'feed:reuters-rss',
        payload: {
          external_id:  extId,
          kind:         'news',
          url:          item.link,
          published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
          tickers:      []
        }
      });
    }
  }
}

module.exports = new ReutersRssConnector();
