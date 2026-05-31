// mobile-lib/anchor-ws.js
// Source: extracted from anchor-client.js connectWS() for mobile-only use.
// Standalone WS factory with exponential backoff reconnect.
'use strict';

window.createAnchorWS = function (opts) {
  var url      = opts.url;
  var handlers = opts.handlers || {};

  var _ws          = null;
  var _pingTimer   = null;
  var _state       = 'connecting';
  var _backoff     = 1000;
  var _destroyed   = false;

  function _connect() {
    if (_destroyed) return;
    _state = 'connecting';
    try {
      _ws = new WebSocket(url);
    } catch (e) {
      console.error('[anchor-ws] construction failed:', e);
      _scheduleReconnect();
      return;
    }

    _ws.onopen = function () {
      _state = 'open';
      _backoff = 1000;
      if (handlers.open) handlers.open();
      _pingTimer = setInterval(function () {
        if (_ws && _ws.readyState === WebSocket.OPEN) {
          _ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    _ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        _dispatch(msg);
      } catch (e) {
        console.error('[anchor-ws] parse error:', e);
      }
    };

    _ws.onclose = function () {
      _clearPing();
      _state = 'closed';
      if (handlers.close) handlers.close();
      if (!_destroyed) _scheduleReconnect();
    };

    _ws.onerror = function () {
      // onclose fires after onerror — reconnect handled there
    };
  }

  function _dispatch(msg) {
    switch (msg.type) {
      case 'html':
        if (handlers.html) handlers.html(msg);
        // Auto send html_synced so server bookkeeping stays in sync
        var content = document.getElementById('anchor-content');
        if (content && _ws && _ws.readyState === WebSocket.OPEN) {
          _ws.send(JSON.stringify({
            type: 'html_synced',
            html: content.innerHTML,
            sig: 'sig:' + Date.now()
          }));
        }
        break;
      case 'patch':            if (handlers.patch)            handlers.patch(msg);            break;
      case 'ack':              if (handlers.ack)              handlers.ack(msg);              break;
      case 'error':            if (handlers.error)            handlers.error(msg);            break;
      case 'agent_event':      if (handlers.agent_event)      handlers.agent_event(msg);      break;
      case 'inbox_updated':    if (handlers.inbox_updated)    handlers.inbox_updated(msg);    break;
      case 'workspace_current':if (handlers.workspace_current)handlers.workspace_current(msg);break;
      case 'manifest_updated': if (handlers.manifest_updated) handlers.manifest_updated(msg); break;
      case 'branch_activated': if (handlers.branch_activated) handlers.branch_activated(msg); break;
      case 'pong':             if (handlers.pong)             handlers.pong(msg);             break;
      default: break;
    }
  }

  function _clearPing() {
    if (_pingTimer) { clearInterval(_pingTimer); _pingTimer = null; }
  }

  function _scheduleReconnect() {
    if (_destroyed) return;
    setTimeout(function () { _connect(); }, _backoff);
    _backoff = Math.min(_backoff * 2, 10000);
  }

  function send(obj) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  function sendEnvelope(envelope) {
    if (handlers.sending) handlers.sending(envelope);
    return send({ type: 'envelope', envelope: envelope });
  }

  function close() {
    _destroyed = true;
    _clearPing();
    if (_ws) { _ws.close(); _ws = null; }
    _state = 'closed';
  }

  function getState() { return _state; }

  _connect();

  return { send: send, sendEnvelope: sendEnvelope, close: close, getState: getState };
};
