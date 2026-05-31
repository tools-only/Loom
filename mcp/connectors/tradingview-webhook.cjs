// mcp/connectors/tradingview-webhook.cjs
// TradingView alert webhook receiver — loaded passively, no cron.
// Handled by POST /webhook/:connectorId in server.cjs.
// This file exists to document the expected webhook payload format.
'use strict';

const { BaseConnector } = require('./_base.cjs');

class TradingviewWebhookConnector extends BaseConnector {
  constructor() {
    super('tradingview', 'TradingView Alerts');
  }

  // Called by server.cjs webhook route — not via scheduler
  handle(body) {
    // body expected: { symbol, price, condition, interval, ... }
    const symbol  = body.symbol || body.ticker || 'UNKNOWN';
    const price   = body.price;
    const cond    = body.condition || body.alert_name || '';
    const extId   = `tradingview:${symbol}:${Date.now()}`;

    this.dedupePush({
      domain:  'market',
      title:   `[TV Alert] ${symbol} ${cond}${price ? ' @ ' + price : ''}`,
      summary: `TradingView 报警：${symbol} ${cond}${price ? ' 价格 ' + price : ''}`,
      source:  'webhook:tradingview',
      payload: {
        external_id:  extId,
        kind:        'price_alert',
        symbol,
        price,
        condition:   cond,
        interval:    body.interval || '',
        published_at: new Date().toISOString(),
        tickers:     [symbol]
      }
    });
  }
}

module.exports = new TradingviewWebhookConnector();