// mcp/push-broker.cjs
// Routes push events to the inbox and optionally spawns CC to enrich them.
'use strict';

class PushBroker {
  // opts: { inbox, pendingOps, notifyPendingChanged, broadcastBrowserMessage }
  constructor(opts) {
    this._inbox = opts.inbox;
    this._pendingOps = opts.pendingOps;
    this._notifyPendingChanged = opts.notifyPendingChanged;
    this._broadcast = opts.broadcastBrowserMessage;
  }

  // event: { domain, title, summary, payload?, source, ccPrompt? }
  push(event) {
    if (!event || !event.domain || !event.title) {
      console.error('[push-broker] invalid event:', event);
      return null;
    }
    const item = this._inbox.append({
      domain: event.domain,
      title: event.title,
      summary: event.summary || '',
      payload: event.payload || {},
      source: event.source || 'broker'
    });
    const counts = this._inbox.unreadCounts();
    this._broadcast({ type: 'inbox_updated', counts });

    if (event.ccPrompt) {
      this._pendingOps.push({
        intent: {
          op: 'push_analyze',
          target_ref: 'inbox.' + event.domain,
          instruction: event.ccPrompt,
          inbox_item_id: item.id
        },
        context_bundle: {}
      });
      this._notifyPendingChanged();
    }
    return item;
  }
}

module.exports = { PushBroker };
