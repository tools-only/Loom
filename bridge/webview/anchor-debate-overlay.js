/* Anchor Debate Overlay — standalone module, no framework dependencies */
(function () {
  'use strict';

  let _client = null;
  let _activeDebateId = null;
  const _history = [];

  // ── DOM references ───────────────────────────────────────────────────────
  let el = {};

  function $(id) { return document.getElementById(id); }

  function init(anchorClient) {
    _client = anchorClient;
    el.trigger       = $('anchor-debate-trigger');
    el.start         = $('anchor-debate-start');
    el.overlay       = $('anchor-debate-overlay');
    el.history       = $('anchor-debate-history');
    el.topicInput    = $('debate-topic-input');
    el.startBtn      = $('debate-start-btn');
    el.cancelBtn     = $('debate-cancel-btn');
    el.overlayTitle  = $('debate-overlay-title');
    el.roundBadge    = $('debate-round-badge');
    el.verdictBadge  = $('debate-verdict-badge');
    el.scopeBar      = $('debate-scope-bar');
    el.colProposer   = $('debate-col-proposer');
    el.colReviewer   = $('debate-col-reviewer');
    el.commitList    = $('debate-commit-list');
    el.abortBtn      = $('debate-abort-btn');
    el.hideBtn       = $('debate-hide-btn');
    el.historyToggle = $('debate-history-toggle');
    el.historyList   = $('debate-history-list');
    el.historyClose  = $('debate-history-close');

    if (el.trigger)       el.trigger.addEventListener('click', showStart);
    if (el.startBtn)      el.startBtn.addEventListener('click', submitStart);
    if (el.cancelBtn)     el.cancelBtn.addEventListener('click', hideStart);
    if (el.abortBtn)      el.abortBtn.addEventListener('click', abort);
    if (el.hideBtn)       el.hideBtn.addEventListener('click', hide);
    if (el.historyToggle) el.historyToggle.addEventListener('click', toggleHistory);
    if (el.historyClose)  el.historyClose.addEventListener('click', toggleHistory);

    if (el.topicInput) {
      el.topicInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitStart();
      });
    }

    loadHistory();
  }

  // ── Start panel ──────────────────────────────────────────────────────────
  function showStart() {
    if (el.start) {
      el.start.classList.add('visible');
      setTimeout(() => { if (el.topicInput) el.topicInput.focus(); }, 50);
    }
  }

  function hideStart() {
    if (el.start) el.start.classList.remove('visible');
  }

  function submitStart() {
    const topic = el.topicInput ? el.topicInput.value.trim() : '';
    if (!topic) return;
    hideStart();
    launchDebate(topic);
    if (el.topicInput) el.topicInput.value = '';
  }

  // ── Launch ───────────────────────────────────────────────────────────────
  function launchDebate(topic) {
    if (!_client) { console.warn('[DebateOverlay] not initialized'); return; }
    const debateId = 'ui_dbt_' + Date.now().toString(36);
    const envelope = {
      schema_version: '1.0',
      intent: {
        op: 'debate',
        target_kind: 'global',
        target_ref: '__debate_' + debateId + '__',
        instruction: topic,
      },
      provenance: {
        session_id: (_client._sessionId || 'ui'),
        event_id: 'evt_' + Date.now().toString(36),
        parent_event_id: null,
        timestamp: new Date().toISOString(),
        client_version: '1.0',
      },
      context_bundle: { subagent_id: null, context_mode: 'standard' },
      render_state: { anchor_tree: [], dom_signature: '' },
    };

    _activeDebateId = debateId;
    show();
    resetOverlay(topic);

    fetch('/envelope', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(envelope),
    }).catch(err => {
      appendSystemMessage('Failed to send debate request: ' + err.message);
    });
  }

  // ── Overlay show/hide ────────────────────────────────────────────────────
  function show() {
    if (el.overlay) el.overlay.classList.add('visible');
  }

  function hide() {
    if (el.overlay) el.overlay.classList.remove('visible');
  }

  function abort() {
    if (!_client || !_activeDebateId) return;
    fetch('/envelope', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        schema_version: '1.0',
        intent: { op: 'debate_abort', target_kind: 'global', target_ref: '__debate_' + _activeDebateId + '__', instruction: 'abort' },
        provenance: { session_id: 'ui', event_id: 'evt_' + Date.now().toString(36), parent_event_id: null, timestamp: new Date().toISOString(), client_version: '1.0' },
        context_bundle: {}, render_state: {},
      }),
    }).catch(() => {});
    appendSystemMessage('Abort requested…');
  }

  // ── Reset overlay state ──────────────────────────────────────────────────
  function resetOverlay(topic) {
    if (el.overlayTitle) el.overlayTitle.textContent = topic || 'Debate';
    if (el.roundBadge) el.roundBadge.textContent = 'Round 0';
    if (el.verdictBadge) { el.verdictBadge.textContent = ''; el.verdictBadge.className = 'debate-verdict-badge'; }
    if (el.scopeBar) el.scopeBar.innerHTML = '<span class="debate-scope-layer">problem</span> initializing…';
    if (el.colProposer) el.colProposer.innerHTML = '<div class="debate-col-header">Proposer · Claude</div>';
    if (el.colReviewer) el.colReviewer.innerHTML = '<div class="debate-col-header">Reviewer · GPT-5</div>';
    if (el.commitList) el.commitList.innerHTML = '';
  }

  function appendSystemMessage(text) {
    if (el.colProposer) {
      const div = document.createElement('div');
      div.className = 'debate-turn';
      div.style.opacity = '0.6';
      div.textContent = text;
      el.colProposer.appendChild(div);
      el.colProposer.scrollTop = el.colProposer.scrollHeight;
    }
  }

  // ── Event handler (called from anchor-client.js) ─────────────────────────
  function append(event) {
    const kind = event.kind || '';
    const payload = event.payload || {};

    if (!kind.startsWith('debate.') && kind !== 'agent.debate') return;
    const subkind = kind.replace(/^(agent\.)?debate\.?/, '');

    switch (subkind) {
      case 'start':
        _activeDebateId = payload.debate_id;
        show();
        resetOverlay(payload.topic);
        addHistoryEntry({ debate_id: payload.debate_id, topic: payload.topic, status: 'running', started: new Date().toISOString() });
        break;

      case 'round_open': {
        if (el.roundBadge) el.roundBadge.textContent = `Round ${payload.round}`;
        const scope = payload.scope || {};
        if (el.scopeBar) {
          el.scopeBar.innerHTML = `<span class="debate-scope-layer">${scope.layer || '?'}</span>${scope.focus || ''}`;
        }
        break;
      }

      case 'proposer_turn': {
        const card = makeTurnCard(payload.round, payload.text, null);
        if (el.colProposer) {
          el.colProposer.appendChild(card);
          el.colProposer.scrollTop = el.colProposer.scrollHeight;
        }
        break;
      }

      case 'reviewer_turn': {
        const card = makeTurnCard(payload.round, payload.text, payload.verdict);
        if (el.colReviewer) {
          el.colReviewer.appendChild(card);
          el.colReviewer.scrollTop = el.colReviewer.scrollHeight;
        }
        break;
      }

      case 'round_close': {
        const verdict = payload.verdict || 'continue';
        if (el.verdictBadge) {
          el.verdictBadge.textContent = verdict;
          el.verdictBadge.className = `debate-verdict-badge ${verdict}`;
        }
        (payload.commitments_delta || []).forEach(c => addCommitment(c));
        break;
      }

      case 'reviewer_fallback':
        appendSystemMessage('⚠ Reviewer fallback: ' + (payload.error || 'codex unavailable'));
        break;

      case 'complete':
        updateHistoryEntry(payload.debate_id, 'complete');
        if (payload.spec_path) {
          const link = document.createElement('a');
          link.href = 'file://' + payload.spec_path;
          link.textContent = '📄 Open Spec';
          link.target = '_blank';
          link.style.display = 'block';
          link.style.margin = '10px 14px';
          link.style.fontSize = '13px';
          link.style.color = '#7A5AF8';
          if (el.overlay) el.overlay.appendChild(link);
        }
        appendSystemMessage(`✓ Done in ${payload.rounds_used} rounds`);
        break;
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function makeTurnCard(round, text, verdict) {
    const div = document.createElement('div');
    div.className = 'debate-turn';
    const rLabel = document.createElement('div');
    rLabel.className = 'debate-turn-round';
    rLabel.textContent = `Round ${round}`;
    const body = document.createElement('div');
    body.className = 'debate-turn-text';
    body.textContent = text || '';
    div.appendChild(rLabel);
    div.appendChild(body);
    if (verdict) {
      const vTag = document.createElement('div');
      vTag.className = `debate-verdict-tag ${verdict}`;
      vTag.textContent = verdict.toUpperCase();
      div.appendChild(vTag);
    }
    return div;
  }

  function addCommitment(c) {
    if (!el.commitList) return;
    const chip = document.createElement('span');
    chip.className = 'debate-commitment-item';
    chip.innerHTML = `<span class="debate-commitment-layer">${c.layer}</span>${(c.statement || '').slice(0, 60)}`;
    el.commitList.appendChild(chip);
  }

  // ── History ───────────────────────────────────────────────────────────────
  const HISTORY_KEY = 'anchor_debate_history';

  function loadHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      if (raw) {
        const items = JSON.parse(raw);
        items.forEach(item => { _history.push(item); renderHistoryItem(item); });
      }
    } catch (_) {}
  }

  function addHistoryEntry(entry) {
    _history.unshift(entry);
    if (_history.length > 50) _history.pop();
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(_history)); } catch (_) {}
    if (el.historyList) {
      const item = buildHistoryItem(entry);
      el.historyList.insertBefore(item, el.historyList.firstChild);
    }
  }

  function updateHistoryEntry(debateId, status) {
    const entry = _history.find(h => h.debate_id === debateId);
    if (entry) { entry.status = status; }
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(_history)); } catch (_) {}
    if (el.historyList) {
      const existing = el.historyList.querySelector(`[data-debate-id="${debateId}"]`);
      if (existing) {
        const badge = existing.querySelector('.debate-history-status');
        if (badge) { badge.textContent = status; badge.className = `debate-history-status ${status}`; }
      }
    }
  }

  function renderHistoryItem(entry) {
    if (!el.historyList) return;
    el.historyList.appendChild(buildHistoryItem(entry));
  }

  function buildHistoryItem(entry) {
    const div = document.createElement('div');
    div.className = 'debate-history-item';
    div.setAttribute('data-debate-id', entry.debate_id || '');
    div.innerHTML = `
      <div class="debate-history-topic">${entry.topic || 'Untitled'}</div>
      <div class="debate-history-meta">
        <span class="debate-history-status ${entry.status || 'running'}">${entry.status || 'running'}</span>
        &nbsp;${entry.started ? new Date(entry.started).toLocaleString() : ''}
      </div>`;
    return div;
  }

  function toggleHistory() {
    if (el.history) el.history.classList.toggle('visible');
  }

  // ── Public API ────────────────────────────────────────────────────────────
  window.DebateOverlay = { init, append, show, hide, abort, launchDebate };
})();
