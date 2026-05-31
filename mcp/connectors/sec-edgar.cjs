// mcp/connectors/sec-edgar.cjs
// Polls SEC EDGAR Atom feeds for recent filings (8-K, 10-K, 10-Q, Form 4).
'use strict';

const path        = require('path');
const { BaseConnector } = require('./_base.cjs');
const { fetchFeed }     = require('../lib/rss-fetch.cjs');

// SEC EDGAR full-text Atom feed for each form type
const EDGAR_FEED = (type) =>
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=${encodeURIComponent(type)}&dateb=&owner=include&count=20&search_text=&output=atom`;

// Extract accession number from SEC entry link/id
function extractAccession(url) {
  const m = (url || '').match(/(\d{10}-\d{2}-\d{6})/);
  return m ? m[1] : null;
}

// Extract company name and form type from SEC entry title
// Typical format: "4 - INSIDERNAME for COMPANY (0001234567) (Accession Number ...)"
// or "8-K - COMPANY INC (0001234567)"
function parseTitle(raw, formType) {
  const cleaned = (raw || '').replace(/\s+/g, ' ').trim();
  // Strip leading "FORM - " prefix
  const body = cleaned.replace(/^\S+\s*-\s*/, '');
  // Truncate at the CIK parens
  const company = body.replace(/\s*\(\d{10}\).*$/, '').trim();
  return `[${formType}] ${company || cleaned}`;
}

class SecEdgarConnector extends BaseConnector {
  constructor() {
    super('sec-edgar', 'SEC EDGAR');
  }

  start() {
    const forms = (this._config.forms || ['8-K', '10-K', '10-Q', '4']);
    this._forms = forms;
    // Poll every 15 minutes during US market hours and surrounding window
    this.scheduleCron('*/15 * * * *', 'America/New_York');
    // Eager first poll
    setTimeout(() => this.poll(), 5000);
  }

  async poll() {
    for (const formType of this._forms) {
      try {
        await this._pollForm(formType);
      } catch (e) {
        console.error('[sec-edgar] poll error for form', formType + ':', e.message);
      }
    }
  }

  async _pollForm(formType) {
    const url = EDGAR_FEED(formType);
    const { items } = await fetchFeed(url, {
      // SEC EDGAR requires a real email in User-Agent per https://www.sec.gov/privacy.htm#security
      userAgent: 'Loom/1.0 isq.zhou@gmail.com'
    });

    for (const item of items) {
      const accession = extractAccession(item.guid) || extractAccession(item.link);
      if (!accession) continue;

      const title   = parseTitle(item.title, formType);
      const summary = item.summary
        ? item.summary.slice(0, 400)
        : `SEC filing: ${formType}`;

      this.dedupePush({
        domain:  'market',
        title,
        summary,
        source:  'feed:sec-edgar',
        payload: {
          external_id:  accession,
          kind:         'filing',
          form_type:    formType,
          url:          item.link,
          published_at: item.pubDate ? new Date(item.pubDate).toISOString() : null,
          tickers:      []
        }
      });
    }
  }
}

module.exports = new SecEdgarConnector();
