// PromptPanel — left-edge push sidebar with ctrl+click context and inline editing
window.PromptPanel = {
  anchor: null,
  panel: null,
  hoverZone: null,
  input: null,
  chipsEl: null,
  submitBtn: null,
  pinBtn: null,

  _selected: new Map(),   // anchorId -> { label, html }
  _isPinned: false,
  _hideTimer: null,

  init(anchor) {
    this.anchor    = anchor;
    this.panel     = document.getElementById('anchor-prompt-panel');
    this.hoverZone = document.getElementById('prompt-hover-zone');
    this.input     = document.getElementById('prompt-panel-input');
    this.chipsEl   = document.getElementById('prompt-chips');
    this.submitBtn = document.getElementById('prompt-panel-submit');
    this.pinBtn    = document.getElementById('prompt-pin-btn');

    if (!this.panel) return;

    // Hover zone (thin left-edge strip) → show panel on mouseenter
    if (this.hoverZone) {
      this.hoverZone.addEventListener('mouseenter', () => this.show());
      this.hoverZone.addEventListener('mouseleave', () => {
        if (!this._isPinned) this._scheduleHide();
      });
    }

    // Close button
    const toggleBtn = this.panel.querySelector('.prompt-panel-toggle');
    if (toggleBtn) toggleBtn.addEventListener('click', () => this._forceHide());

    // Pin button
    if (this.pinBtn) this.pinBtn.addEventListener('click', () => this._togglePin());

    // Submit
    if (this.submitBtn) this.submitBtn.addEventListener('click', () => this.submit());

    if (this.input) {
      this.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          this.submit();
        }
      });
      this.input.addEventListener('input', () => this._resizeInput());
    }

    // Ctrl+K toggles panel
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        const tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        e.preventDefault();
        this.toggle();
      }
    });

    // Auto-hide on mouseleave (unless pinned)
    this.panel.addEventListener('mouseenter', () => this._cancelHide());
    this.panel.addEventListener('mouseleave', () => {
      if (!this._isPinned) this._scheduleHide();
    });

    // Ctrl+click any element → append text to input
    document.addEventListener('click', (e) => {
      if (!e.ctrlKey) return;
      const stage = document.getElementById('anchor-stage');
      if (!stage || !stage.contains(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
      const el = e.target.closest('[data-anc], p, li, td, th, h1, h2, h3, h4, blockquote, .anc-kpi, .anc-section');
      if (!el) return;
      const text = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 300);
      if (!text) return;
      this._appendToInput(text);
      el.classList.add('anc-ctrl-flash');
      setTimeout(() => el.classList.remove('anc-ctrl-flash'), 500);
    }, true);

    // Dblclick any text in stage → inline contenteditable
    document.addEventListener('dblclick', (e) => {
      const stage = document.getElementById('anchor-stage');
      if (!stage || !stage.contains(e.target)) return;
      // Skip buttons/inputs/already-editing
      if (e.target.closest('button, input, textarea, select, a')) return;
      const el = e.target.closest('p, h1, h2, h3, h4, li, td, th, em, strong, span, .kpi-value, .kpi-label, .kpi-unit, .kpi-label-top');
      if (!el) return;
      if (el.isContentEditable) return;
      el.contentEditable = 'true';
      el.dataset.ancEditing = '1';
      el.focus();
      // Select all text on activation
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      el.addEventListener('blur', () => {
        el.contentEditable = 'false';
        delete el.dataset.ancEditing;
      }, { once: true });
      el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); el.blur(); }
        if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); el.blur(); }
      }, { once: true });
    });

    // Restore pinned state
    try { this._isPinned = localStorage.getItem('anchor.promptPinned') === '1'; } catch (_) {}
    if (this._isPinned) this.show();
  },

  _appendToInput(text) {
    if (!this.input) return;
    const cur = this.input.value.trim();
    this.input.value = cur ? cur + '\n' + text : text;
    this._resizeInput();
    this.show();
    setTimeout(() => { try { this.input.focus(); } catch (_) {} }, 80);
  },

  show() {
    this._cancelHide();
    this.panel.classList.remove('collapsed');
    document.body.classList.add('ask-panel-open');
    if (this._isPinned) {
      this.panel.classList.add('is-pinned');
      if (this.pinBtn) this.pinBtn.classList.add('is-pinned');
    }
    setTimeout(() => { try { this.input && this.input.focus(); } catch (_) {} }, 120);
    // Expand hover zone to cover full panel so mouseleave fires correctly
    if (this.hoverZone) this.hoverZone.style.width = '300px';
  },

  hide() {
    if (this._isPinned) return;
    this.panel.classList.add('collapsed');
    document.body.classList.remove('ask-panel-open');
    this.panel.classList.remove('is-pinned');
    // Shrink hover zone back to edge strip
    if (this.hoverZone) this.hoverZone.style.width = '';
  },

  _forceHide() {
    this._isPinned = false;
    try { localStorage.setItem('anchor.promptPinned', '0'); } catch (_) {}
    if (this.pinBtn) this.pinBtn.classList.remove('is-pinned');
    this.panel.classList.remove('is-pinned');
    this.hide();
  },

  _scheduleHide() {
    this._cancelHide();
    this._hideTimer = setTimeout(() => this.hide(), 500);
  },

  _cancelHide() {
    if (this._hideTimer) { clearTimeout(this._hideTimer); this._hideTimer = null; }
  },

  toggle() {
    if (this.panel.classList.contains('collapsed')) this.show();
    else this.hide();
  },

  _togglePin() {
    this._isPinned = !this._isPinned;
    if (this._isPinned) this.show();
    try { localStorage.setItem('anchor.promptPinned', this._isPinned ? '1' : '0'); } catch (_) {}
    if (this.pinBtn) this.pinBtn.classList.toggle('is-pinned', this._isPinned);
    this.panel.classList.toggle('is-pinned', this._isPinned);
  },

  // ── Anchor card selection ──────────────────────────────

  selectAnchor(anchorId, label, html) {
    if (this._selected.has(anchorId)) return;
    this._selected.set(anchorId, { label, html });
    this._renderChips();
    if (!this._isPinned && this.panel.classList.contains('collapsed')) this.show();
  },

  deselectAnchor(anchorId) {
    this._selected.delete(anchorId);
    const el = document.querySelector('[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]');
    if (el) el.classList.remove('anc-selected');
    this._renderChips();
  },

  toggleAnchor(anchorId, label, html) {
    if (this._selected.has(anchorId)) {
      this.deselectAnchor(anchorId);
    } else {
      this.selectAnchor(anchorId, label, html);
      const el = document.querySelector('[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]');
      if (el) el.classList.add('anc-selected');
    }
  },

  getSelectedAnchors() {
    const ids = [];
    const subtrees = {};
    this._selected.forEach((val, id) => {
      ids.push(id);
      subtrees[id] = { target_html: val.html };
    });
    return { ids, subtrees };
  },

  clearSelection() {
    this._selected.forEach((_, id) => {
      const el = document.querySelector('[data-anc="' + id.replace(/"/g, '\\"') + '"]');
      if (el) el.classList.remove('anc-selected');
    });
    this._selected.clear();
    this._renderChips();
  },

  _renderChips() {
    if (!this.chipsEl) return;
    this.chipsEl.innerHTML = '';
    if (this._selected.size === 0) {
      this.chipsEl.innerHTML = '<span class="prompt-chips-placeholder">Ctrl+click any content to add context</span>';
      return;
    }
    this._selected.forEach((val, id) => {
      const chip = document.createElement('span');
      chip.className = 'prompt-chip';
      chip.innerHTML =
        '<span class="chip-label" title="' + _escHtml(id) + '">' +
        _escHtml(val.label || id.split('.').pop()) +
        '</span>' +
        '<button class="chip-remove" data-anchor="' + _escHtml(id) + '" title="Remove">&times;</button>';
      chip.querySelector('.chip-remove').addEventListener('click', (e) => {
        e.stopPropagation();
        this.deselectAnchor(id);
      });
      chip.addEventListener('click', () => {
        const el = document.querySelector('[data-anc="' + id.replace(/"/g, '\\"') + '"]');
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      this.chipsEl.appendChild(chip);
    });
  },

  // ── Submit ─────────────────────────────────────────────

  _resizeInput() {
    if (!this.input) return;
    this.input.style.height = 'auto';
    this.input.style.height = Math.min(this.input.scrollHeight, 260) + 'px';
  },

  _inferRoute() {
    const hash = window.location.hash.slice(1);
    if (['market','position','target','sentiment'].includes(hash)) return hash;
    return 'overview';
  },

  submit() {
    const text = (this.input && this.input.value || '').trim();
    if (!text) return;

    if (!this.anchor.ws || this.anchor.ws.readyState !== WebSocket.OPEN) {
      if (this.anchor.toast) this.anchor.toast('Not connected');
      return;
    }

    this.anchor._allowIncomingHtml = true;

    const sel = this.getSelectedAnchors();
    const rawBundle = (window.ContextPanel && ContextPanel.getBundle) ? ContextPanel.getBundle() : null;

    const renderState = this.anchor._snapshotRenderState();
    if (sel.ids.length > 0) {
      renderState.selected_subtrees = sel.subtrees;
    }

    const bundle = Object.assign({
      memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
      scope_hint: 'standard',
      card_anchor_ids: sel.ids
    }, rawBundle || {});

    const route = this._inferRoute();
    bundle.file_id = (window.WorkspacePanel && WorkspacePanel.currentFileId) || this.anchor.currentFileId || null;
    // If submitting from a hand-agent domain, tag it so the server calls Brain /run first
    if (['market','sentiment','target','position'].includes(route)) bundle.loom_hand = route;

    const envelope = {
      schema_version: '1.0',
      intent: {
        op: 'initial_render',
        target_kind: 'global',
        target_ref: null,
        instruction: text
      },
      selection: null,
      context_bundle: bundle,
      render_state: renderState,
      provenance: {
        session_id: this.anchor.sessionId,
        event_id: 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8),
        parent_event_id: null,
        timestamp: new Date().toISOString(),
        client_version: '0.1.0'
      }
    };

    this.input.value = '';
    this._resizeInput();
    this.clearSelection();

    history.pushState(null, '', '#' + route);
    this.anchor._syncHomeVisibility();
    this.anchor._updateToolbarTabs(route);
    this.anchor.showProcessing('Generating...');

    this.anchor.ws.send(JSON.stringify({ type: 'envelope', envelope }));
    if (this.anchor.toast) this.anchor.toast('Prompt sent' + (sel.ids.length > 0 ? ' with ' + sel.ids.length + ' context anchors' : ''));
  }
};
