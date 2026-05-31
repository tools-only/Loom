// mcp/lib/rss-fetch.cjs
// Shared RSS/Atom fetcher for all connectors.
'use strict';

const path    = require('path');
const ROOT    = path.join(__dirname, '..', '..');
const BRIDGE_NM = path.join(ROOT, 'bridge', 'node_modules');
const Parser  = require(path.join(BRIDGE_NM, 'rss-parser'));

async function fetchFeed(url, opts = {}) {
  const parser = new Parser({
    headers: {
      'User-Agent': opts.userAgent || 'Loom/1.0 isq.zhou@gmail.com'
    },
    timeout: opts.timeout || 15000,
    customFields: { item: ['summary', 'description'] }
  });
  try {
    const feed = await parser.parseURL(url);
    return {
      title: feed.title || '',
      items: (feed.items || []).map(it => ({
        title:        (it.title   || '').trim(),
        link:         it.link     || it.guid   || '',
        pubDate:      it.pubDate  || it.isoDate || null,
        guid:         it.guid     || it.link    || '',
        summary:      (it.contentSnippet || it.content || it.summary || '').slice(0, 600)
      }))
    };
  } catch (e) {
    console.error('[rss-fetch] error', url + ':', e.message || e.code || String(e));
    return { title: '', items: [] };
  }
}

module.exports = { fetchFeed };
