// mcp/connectors/cnbc-rss.cjs
// Polls CNBC top news RSS.
'use strict';

const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

const FEED_URL = 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114';

class CnbcRssConnector extends BaseConnector {
  constructor() {
    super('cnbc-rss', 'CNBC');
  }

  start() {
    this.scheduleCron('*/10 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 9000);
  }

  async poll() {
    try {
      const { items } = await fetchFeed(FEED_URL);
      for (const item of items) {
        const extId = item.guid || item.link;
        if (!extId) continue;
        this.dedupePush({
          domain:  'market',
          title:   '[CNBC] ' + item.title,
          summary: item.summary,
          source:  'feed:cnbc-rss',
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
      console.error('[cnbc-rss] error:', e.message);
    }
  }
}

module.exports = new CnbcRssConnector();
