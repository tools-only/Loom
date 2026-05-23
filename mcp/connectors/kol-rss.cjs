// mcp/connectors/kol-rss.cjs
// Aggregates RSS feeds from KOL analysts / Substacks.
// Feed list configured in connectors.json "kol-rss.feeds".
'use strict';

const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

const DEFAULT_FEEDS = [
  { id: 'lyn-alden',       url: 'https://www.lynalden.com/feed/' },
  { id: 'pragcap',         url: 'https://www.pragcap.com/feed/' },
  { id: 'wolfstreet',      url: 'https://wolfstreet.com/feed/' },
  { id: 'mishtalk',        url: 'https://mishtalk.com/feed/' },
  { id: 'heisenberg',      url: 'https://heisenbergreport.com/feed/' },
  { id: 'calculated-risk', url: 'https://www.calculatedriskblog.com/feeds/posts/default' },
  { id: 'ritholtz',        url: 'https://ritholtz.com/feed/' },
  { id: 'stratechery',     url: 'https://stratechery.com/feed/' },
  { id: 'tomtunguz',       url: 'https://tomtunguz.com/index.xml' },
  { id: 'net-interest',    url: 'https://www.netinterest.co/feed' },
  { id: 'damodaran',       url: 'https://aswathdamodaran.blogspot.com/feeds/posts/default' },
];

// Friendly display names
const AUTHOR_LABELS = {
  'lyn-alden':       'Lyn Alden',
  'pragcap':         'Cullen Roche',
  'wolfstreet':      'Wolf Street',
  'mishtalk':        'Mish',
  'heisenberg':      'Heisenberg',
  'calculated-risk': 'Calculated Risk',
  'ritholtz':        'Barry Ritholtz',
  'stratechery':     'Ben Thompson',
  'tomtunguz':       'Tom Tunguz',
  'net-interest':    'Net Interest',
  'damodaran':       'Damodaran',
};

class KolRssConnector extends BaseConnector {
  constructor() {
    super('kol-rss', 'KOL RSS');
  }

  start() {
    this._feeds = this._config.feeds || DEFAULT_FEEDS;
    // Every 2 hours
    this.scheduleCron('0 */2 * * *', 'America/New_York');
    setTimeout(() => this.poll(), 20000);
  }

  async poll() {
    for (const feed of this._feeds) {
      try {
        await this._pollFeed(feed);
        await new Promise(r => setTimeout(r, 500));
      } catch (e) {
        console.error('[kol-rss] error for', feed.id + ':', e.message);
      }
    }
  }

  async _pollFeed({ id, url }) {
    const { items } = await fetchFeed(url);
    const author    = AUTHOR_LABELS[id] || id;

    for (const item of items.slice(0, 5)) {
      const extId = item.guid || item.link;
      if (!extId) continue;
      this.dedupePush({
        domain:  'market',
        title:   `[${author}] ${item.title}`,
        summary: item.summary,
        source:  `feed:kol-rss:${id}`,
        payload: {
          external_id:  extId,
          kind:         'commentary',
          author:       author,
          feed_id:      id,
          url:          item.link,
          published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
          tickers:      []
        }
      });
    }
  }
}

module.exports = new KolRssConnector();
