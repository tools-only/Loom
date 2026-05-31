// mobile/mobile-selection.js — Text selection action bar
'use strict';

window.MobileSelection = (function () {
  var _anchorRef  = null;
  var _selText    = null;
  var _debounce   = null;

  function _showBar() {
    var bar = document.getElementById('mob-sel-bar');
    if (bar) bar.removeAttribute('hidden');
  }

  function _hideBar() {
    var bar = document.getElementById('mob-sel-bar');
    if (bar) bar.setAttribute('hidden', '');
    _anchorRef = null;
    _selText   = null;
  }

  function _check() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) { _hideBar(); return; }

    var range   = sel.getRangeAt(0);
    var content = document.getElementById('anchor-content');
    if (!content || !content.contains(range.commonAncestorContainer)) { _hideBar(); return; }

    var el = range.commonAncestorContainer;
    if (el.nodeType === 3) el = el.parentElement;
    var anchorEl = el.closest('[data-anc]');
    if (!anchorEl) { _hideBar(); return; }

    _anchorRef = anchorEl.getAttribute('data-anc');
    _selText   = sel.toString().trim();
    _showBar();
  }

  function init() {
    var bar = document.getElementById('mob-sel-bar');
    if (!bar) return;

    bar.querySelectorAll('.mob-sel-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!_anchorRef || !window.AnchorEnvelope || !window.App) return;
        var container = document.getElementById('anchor-content');
        var envelope  = AnchorEnvelope.buildEnvelope({
          op:          btn.dataset.op,
          target_kind: 'selection',
          target_ref:  _anchorRef,
          instruction: null,
          selection:   { text: _selText, ancestor_anchor: _anchorRef },
          container:   container,
          sessionId:   App.state.sessionId
        });
        App.send(envelope);
        if (window.getSelection) window.getSelection().removeAllRanges();
        _hideBar();
      });
    });

    document.addEventListener('selectionchange', function () {
      clearTimeout(_debounce);
      _debounce = setTimeout(_check, 200);
    });
  }

  return { init: init };
})();
