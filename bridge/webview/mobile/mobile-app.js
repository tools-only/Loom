// mobile/mobile-app.js — Main controller: WS wiring, state, App global
'use strict';

(function () {

  // ── Tiny event emitter ─────────────────────────────────────
  function makeEmitter() {
    var _cbs = {};
    return {
      on:   function (e, cb) { (_cbs[e] = _cbs[e] || []).push(cb); },
      off:  function (e, cb) { _cbs[e] = (_cbs[e] || []).filter(function (f) { return f !== cb; }); },
      emit: function (e, d) { (_cbs[e] || []).forEach(function (f) { try { f(d); } catch (err) { console.error('[app-events]', err); } }); }
    };
  }

  // ── App state ──────────────────────────────────────────────
  window.App = {
    state: {
      currentRoute:   'home',
      sessionId:      null,
      hasContent:     false,
      activityEvents: [],   // [{kind, payload, ts}]
      inboxItems:     [],   // [{domain, title, summary, source, payload, ts}]
      handsConfig:    {}
    },
    send: function (envelope) {
      if (_ws) _ws.sendEnvelope(envelope);
      else console.warn('[app] WS not ready');
    },
    events: makeEmitter()
  };

  // ── DOM helpers ────────────────────────────────────────────
  var _statusEl = document.getElementById('mob-status');
  var _toastEl  = document.getElementById('toast');
  var _toastTimer;

  function setStatus(kind, text) {
    if (!_statusEl) return;
    _statusEl.textContent = text;
    _statusEl.className = 'mob-status' + (kind ? ' mob-status--' + kind : '');
  }

  function toast(msg) {
    if (!_toastEl) return;
    _toastEl.textContent = msg;
    _toastEl.classList.add('is-visible');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () { _toastEl.classList.remove('is-visible'); }, 3000);
  }

  // ── Content arrival ────────────────────────────────────────
  function onHtml(msg) {
    var content = document.getElementById('anchor-content');
    if (!content) return;
    content.innerHTML = msg.content || msg.html || '';
    App.state.hasContent = true;

    // Show anchor-content, hide empty home screen
    var homeEmpty = document.getElementById('mob-home-empty');
    if (homeEmpty) homeEmpty.setAttribute('hidden', '');
    content.removeAttribute('hidden');

    // Switch to home route so content is visible
    if (window.MobileRoutes && MobileRoutes.current() !== 'home') {
      MobileRoutes.mount('home');
    }

    // Bind anchor interactions
    if (window.MobileAnchor) MobileAnchor.bindAll();

    // Show sticky prompt bar
    var promptBar = document.getElementById('mob-prompt-bar');
    if (promptBar) promptBar.removeAttribute('hidden');

    App.events.emit('state:content', null);
    toast('Rendered');
  }

  function onPatch(msg) {
    var patches = msg.patches || [];
    var content = document.getElementById('anchor-content');
    if (!content || !window.AnchorPatch) return;

    // Dismiss action rows for patched anchors before swap
    patches.forEach(function (p) {
      if (window.MobileAnchor) MobileAnchor.bindOne(p.anchor_id);
    });

    AnchorPatch.applyPatches(content, patches, {
      onAfterSwap: function (anchorId) {
        if (window.MobileAnchor) MobileAnchor.bindOne(anchorId);
      }
    });
  }

  function onAgentEvent(msg) {
    var evt = msg.event || msg;
    App.state.activityEvents.push({
      kind:    evt.kind || 'event',
      payload: evt.payload || {},
      ts:      Date.now()
    });
    // Keep last 200 events
    if (App.state.activityEvents.length > 200) App.state.activityEvents.shift();
    App.events.emit('state:activity', null);
  }

  function onInboxUpdated(msg) {
    var items = msg.items || [];
    items.forEach(function (item) {
      App.state.inboxItems.unshift({
        domain:  item.domain  || 'general',
        title:   item.title   || '',
        summary: item.summary || '',
        source:  item.source  || '',
        payload: item.payload || {},
        ts: Date.now()
      });
    });
    if (App.state.inboxItems.length > 500) App.state.inboxItems.length = 500;

    // Badge the inbox tab
    var inboxBtn = document.querySelector('.mob-nav-btn[data-route="inbox"]');
    if (inboxBtn && !inboxBtn.querySelector('.mob-badge')) {
      var badge = document.createElement('span');
      badge.className = 'mob-badge';
      inboxBtn.appendChild(badge);
    }

    App.events.emit('state:inbox', null);
  }

  function onManifestUpdated(msg) {
    if (msg.config) App.state.handsConfig = msg.config;
    App.events.emit('state:hands', null);
  }

  // ── Prompt submission ──────────────────────────────────────
  function submitPrompt(text) {
    text = (text || '').trim();
    if (!text || !window.AnchorEnvelope) return;
    var content = document.getElementById('anchor-content');
    // Use a placeholder container if no content yet
    if (!content) return;
    var envelope = AnchorEnvelope.buildEnvelope({
      op:          'initial_render',
      target_kind: 'global',
      target_ref:  null,
      instruction: text,
      selection:   null,
      container:   content,
      sessionId:   App.state.sessionId
    });
    App.send(envelope);
    toast('Sent…');
  }

  function _bindPrompt(inputEl, btnEl) {
    if (!inputEl || !btnEl) return;
    btnEl.addEventListener('click', function () {
      submitPrompt(inputEl.value);
      inputEl.value = '';
    });
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitPrompt(inputEl.value);
        inputEl.value = '';
      }
    });
  }

  // ── Suggestion cards ───────────────────────────────────────
  function _bindSuggestions() {
    document.querySelectorAll('.mob-suggestions button[data-prompt]').forEach(function (btn) {
      btn.addEventListener('click', function () { submitPrompt(btn.dataset.prompt); });
    });
  }

  // ── WebSocket ──────────────────────────────────────────────
  var _ws = null;

  function _initWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url   = proto + '//' + location.host;

    _ws = createAnchorWS({
      url: url,
      handlers: {
        open: function () {
          setStatus('live', 'Connected');
        },
        close: function () {
          setStatus('', 'Reconnecting…');
        },
        html:             onHtml,
        patch:            onPatch,
        agent_event:      onAgentEvent,
        inbox_updated:    onInboxUpdated,
        manifest_updated: onManifestUpdated,
        ack: function (msg) {
          if (msg.session_id) App.state.sessionId = msg.session_id;
        },
        error: function (msg) {
          toast('Error: ' + (msg.message || 'unknown'));
          setStatus('error', 'Error');
        }
      }
    });
  }

  // ── Boot ───────────────────────────────────────────────────
  function boot() {
    if (!window.createAnchorWS || !window.AnchorEnvelope || !window.AnchorPatch) {
      console.error('[mobile-app] mobile-lib not loaded');
      return;
    }

    // Ensure anchor-content is hidden until first html arrives
    var content = document.getElementById('anchor-content');
    if (content) content.setAttribute('hidden', '');
    var promptBar = document.getElementById('mob-prompt-bar');
    if (promptBar) promptBar.setAttribute('hidden', '');

    // Init sub-modules (they rely on App being defined)
    if (window.MobileRoutes)    MobileRoutes.init();
    if (window.MobileAnchor)    MobileAnchor.init();
    if (window.MobileSelection) MobileSelection.init();

    // Bind home prompt inputs
    _bindPrompt(
      document.getElementById('mob-prompt-input'),
      document.getElementById('mob-prompt-submit')
    );
    _bindPrompt(
      document.getElementById('mob-bar-input'),
      document.getElementById('mob-bar-submit')
    );
    _bindSuggestions();

    // Clear inbox badge when switching to inbox tab
    App.events.on('route:change', function (name) {
      if (name === 'inbox') {
        var badge = document.querySelector('.mob-nav-btn[data-route="inbox"] .mob-badge');
        if (badge) badge.remove();
      }
    });

    setStatus('', 'Connecting…');
    _initWS();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
