// mcp/connectors/investing-calendar.cjs
// Polls Investing.com economic calendar & news RSS.
'use strict';

const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

const FEEDS = [
  { url: 'https://www.investing.com/rss/news_25.rss', label: 'Economy' },
  { url: 'https://www.investing.com/rss/news_14.rss', label: 'Markets' },
];

class InvestingCalendarConnector extends BaseConnector {
  constructor() {
    super('investing-calendar', 'Investing.com');
  }

  start() {
    // Hourly — Investing.com has rate limits
    this.scheduleCron('0 * * * *', 'America/New_York');
    setTimeout(() => this.poll(), 12000);
  }

  async poll() {
    for (const { url, label } of FEEDS) {
      try {
        const { items } = await fetchFeed(url);
        for (const item of items) {
          const extId = item.guid || item.link;
          if (!extId) continue;
          this.dedupePush({
            domain:  'market',
            title:   `[Investing/${label}] ${item.title}`,
            summary: item.summary,
            source:  'feed:investing-calendar',
            payload: {
              external_id:  extId,
              kind:         'macro',
              url:          item.link,
              published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
              tickers:      []
            }
          });
        }
      } catch (e) {
        console.error('[investing-calendar] error:', e.message);
      }
    }
  }
}

module.exports = new InvestingCalendarConnector();
