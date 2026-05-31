// mobile/mobile-anchor.js — Inline action row (zero-popup anchor interactions)
'use strict';

window.MobileAnchor = (function () {
  var _currentAnchorId = null;
  var _currentRow      = null;
  var _removing        = false;

  var OP_LABELS = {
    refine: 'Refine', lock: 'Lock', expand: 'Expand', shorten: 'Shorten',
    longer: 'Longer', branch: 'Branch', restructure: 'Restructure',
    ask: 'Ask', annotate: 'Annotate', edit: 'Edit', custom: 'Custom'
  };
  var OP_PLACEHOLDERS = {
    refine: 'How should this be refined?',
    ask: 'What do you want to know?',
    annotate: 'Add a note…',
    edit: 'New text…'
  };
  var ORDERED_PRIMARY = ['refine', 'lock', 'expand', 'shorten', 'longer', 'ask'];

  function _opLabel(op) { return OP_LABELS[op] || op; }
  function _opPlaceholder(op) { return OP_PLACEHOLDERS[op] || 'Instruction…'; }

  function _sendOp(op, anchorId, instruction) {
    var container = document.getElementById('anchor-content');
    if (!container || !window.AnchorEnvelope || !window.App) return;
    var envelope = AnchorEnvelope.buildEnvelope({
      op: op,
      target_kind: 'anchor',
      target_ref: anchorId,
      instruction: instruction || null,
      selection: null,
      container: container,
      sessionId: App.state.sessionId
    });
    App.send(envelope);
  }

  function _morphToInput(row, anchorId, op) {
    row.classList.add('mob-actions--input');
    row.innerHTML =
      '<div class="mob-action-input-row">' +
      '<textarea class="mob-action-input" placeholder="' + _opPlaceholder(op) + '" rows="2"></textarea>' +
      '<button class="mob-action-send">Send \u2192</button>' +
      '</div>';

    requestAnimationFrame(function () {
      var input = row.querySelector('.mob-action-input');
      if (input) {
        input.focus();
        document.body.classList.add('kbd-open');
        input.addEventListener('blur', function () {
          document.body.classList.remove('kbd-open');
        }, { once: true });
      }
    });

    var sendBtn = row.querySelector('.mob-action-send');
    if (sendBtn) {
      sendBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        var instruction = (row.querySelector('.mob-action-input') || {}).value;
        instruction = instruction ? instruction.trim() : '';
        if (!instruction) return;
        _sendOp(op, anchorId, instruction);
        _dismissCurrent();
      });
    }
  }

  function _buildBtnRow(handles, anchorId, row) {
    var primary = ORDERED_PRIMARY.filter(function (op) { return handles.indexOf(op) !== -1; }).slice(0, 3);
    var extra   = handles.filter(function (op) { return primary.indexOf(op) === -1; });

    var btnRow = document.createElement('div');
    btnRow.className = 'mob-action-btn-row';

    primary.forEach(function (op) {
      var btn = document.createElement('button');
      btn.className = 'mob-action-btn';
      btn.dataset.op = op;
      btn.textContent = _opLabel(op);
      btnRow.appendChild(btn);
    });

    if (extra.length > 0) {
      var moreBtn = document.createElement('button');
      moreBtn.className = 'mob-action-btn mob-action-btn--more';
      moreBtn.dataset.op = 'more';
      moreBtn.dataset.extra = extra.join(',');
      moreBtn.textContent = 'More';
      btnRow.appendChild(moreBtn);
    }

    row.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-op]');
      if (!btn) return;
      e.stopPropagation();
      var op = btn.dataset.op;

      if (op === 'more') {
        var extraOps = (btn.dataset.extra || '').split(',').filter(Boolean);
        extraOps.forEach(function (extraOp) {
          var eb = document.createElement('button');
          eb.className = 'mob-action-btn';
          eb.dataset.op = extraOp;
          eb.textContent = _opLabel(extraOp);
          btnRow.insertBefore(eb, btn);
        });
        btn.remove();
        return;
      }

      if (op === 'refine' || op === 'ask' || op === 'annotate' || op === 'edit') {
        _morphToInput(row, anchorId, op);
        return;
      }

      _sendOp(op, anchorId, null);
      _dismissCurrent();
    });

    row.appendChild(btnRow);
  }

  function _openActionRow(card, anchorId) {
    // Dismiss any existing row immediately (no animation wait)
    if (_currentRow) {
      _currentRow.remove();
      _currentRow = null;
      _currentAnchorId = null;
      _removing = false;
    }

    var handlesAttr = card.getAttribute('data-handles') || 'refine,lock,expand';
    var handles = handlesAttr.split(',').map(function (s) { return s.trim(); }).filter(Boolean);

    var row = document.createElement('div');
    row.className = 'mob-actions';
    row.dataset.for = anchorId;

    _buildBtnRow(handles, anchorId, row);

    card.after(row);
    _currentAnchorId = anchorId;
    _currentRow = row;

    requestAnimationFrame(function () { row.classList.add('is-open'); });
  }

  function _dismissCurrent(callback) {
    if (!_currentRow) { if (callback) callback(); return; }
    if (_removing) {
      if (_currentRow) { _currentRow.remove(); }
      _currentRow = null; _currentAnchorId = null; _removing = false;
      if (callback) callback();
      return;
    }
    var row = _currentRow;
    _removing = true;
    row.classList.remove('is-open');

    var done = function () {
      if (row.parentNode) row.remove();
      if (_currentRow === row) { _currentRow = null; _currentAnchorId = null; }
      _removing = false;
      if (callback) callback();
    };
    row.addEventListener('transitionend', done, { once: true });
    setTimeout(done, 300); // fallback
  }

  function init() {
    document.addEventListener('click', function (e) {
      if (e.target.closest('.mob-actions')) return;

      var content = document.getElementById('anchor-content');
      var card = e.target.closest('[data-anc]');

      if (!card || !content || !content.contains(card)) {
        _dismissCurrent();
        return;
      }

      // Ignore nested anchors inside an active card's action row context
      var anchorId = card.getAttribute('data-anc');
      if (_currentAnchorId === anchorId) {
        _dismissCurrent();
      } else {
        _openActionRow(card, anchorId);
      }
    });
  }

  function bindAll() { /* no-op: using delegation */ }

  function bindOne(anchorId) {
    if (_currentAnchorId === anchorId) _dismissCurrent();
  }

  function dismissAll() { _dismissCurrent(); }

  return { init: init, bindAll: bindAll, bindOne: bindOne, dismissAll: dismissAll };
})();
