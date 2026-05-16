// Anchor Client — injects interactive handles and captures user ops
// Uses WebSocket for receiving HTML and sending ops

const Anchor = {
  ws: null,
  _pingTimer: null,
  container: null,
  statusEl: null,
  infoEl: null,
  currentHtml: '',
  openPopup: null,
  pendingOps: [],   // { op, target, instruction, anchorId, timestamp }

  opDefs: {
    refine:    { label: 'Refine',     icon: '✦', needsInput: true,  inputLabel: 'What to change?' },
    lock:      { label: 'Lock',       icon: 'L',  needsInput: 'optional', inputLabel: 'Reason (optional)' },
    expand:    { label: 'Expand',     icon: '↔', needsInput: 'optional', inputLabel: 'What to expand? (optional)' },
    shorten:   { label: 'Shorten',    icon: '↔', needsInput: 'optional', inputLabel: 'Any specifics? (optional)' },
    longer:    { label: 'Longer',     icon: '↔', needsInput: 'optional', inputLabel: 'Any specifics? (optional)' },
    edit:      { label: 'Edit text',  icon: '✎', needsInput: true,  inputLabel: 'Edit to:' },
    annotate:  { label: 'Annotate',   icon: '✎', needsInput: true,  inputLabel: 'Note:' },
    branch:    { label: 'Branch',     icon: '⑂', needsInput: true,  inputLabel: 'Alternative direction:' },
    restructure: { label: 'Restructure', icon: '⊞', needsInput: true, inputLabel: 'What to restructure?' },
  },

  // Fixed platform handles — always available regardless of model output.
  // The model may extend via data-handles, but can never reduce below this set.
  defaultHandles: ['refine', 'expand', 'shorten', 'annotate', 'branch', 'edit'],

  init() {
    this.container = document.getElementById('anchor-content');
    this.statusEl = document.getElementById('status');
    this.infoEl = document.getElementById('info');
    this.processingEl = document.getElementById('processing');
    this.processingLabel = this.processingEl?.querySelector('.processing-label');
    this.processingTarget = this.processingEl?.querySelector('.processing-target');
    this._processingAnchors = new Set();
    this._processingTimer = null;
    this.sessionId = this._loadOrCreateSessionId();
    this.connect();

    // Wire up Phase 1/3/4 modules
    if (window.ContextPanel)     ContextPanel.init(this);
    if (window.SelectionToolbar) SelectionToolbar.init(this);
    if (window.TimelinePanel)    TimelinePanel.init(this);
    if (window.HistoryPanel)     HistoryPanel.init(this);
    this._initSidePanelToggles();
    this._initExecuteAll();
  },

  _initExecuteAll() {
    const btn = document.getElementById('anchor-execute-all');
    if (!btn) return;
    btn.addEventListener('click', () => this.executeAll());
  },

  _initSidePanelToggles() {
    // Toggle buttons inside panel headers
    document.querySelectorAll('.side-panel-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-target');
        document.getElementById(id)?.classList.add('collapsed');
      });
    });

    // Floating trigger tabs — click to expand, mouseleave to collapse
    this._initFloatingTrigger('trigger-context', 'anchor-context-panel');
    this._initFloatingTrigger('trigger-timeline', 'anchor-timeline-panel');

    // Resize handles
    this._initPanelResize('anchor-context-panel');
    this._initPanelResize('anchor-timeline-panel');
  },

  _initFloatingTrigger(triggerId, panelId) {
    const trigger = document.getElementById(triggerId);
    const panel = document.getElementById(panelId);
    if (!trigger || !panel) return;

    let hideTimer = null;

    const showPanel = () => {
      panel.classList.remove('collapsed');
      trigger.style.opacity = '0';
      trigger.style.pointerEvents = 'none';
    };
    const hidePanel = () => {
      panel.classList.add('collapsed');
      trigger.style.opacity = '';
      trigger.style.pointerEvents = '';
    };

    trigger.addEventListener('click', () => {
      if (panel.classList.contains('collapsed')) showPanel();
      else hidePanel();
    });

    // Click on stage area collapses panels
    document.getElementById('anchor-stage')?.addEventListener('click', (e) => {
      if (!panel.classList.contains('collapsed') && !panel.contains(e.target) && e.target !== trigger) {
        hidePanel();
      }
    });

    panel.addEventListener('mouseenter', () => {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    });

    panel.addEventListener('mouseleave', () => {
      hideTimer = setTimeout(hidePanel, 500);
    });
  },

  _initPanelResize(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;

    // Create resize handle
    const handle = document.createElement('div');
    handle.className = 'panel-resize-handle';
    panel.appendChild(handle);

    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragging = true;
      startX = e.clientX;
      startWidth = panel.offsetWidth;
      handle.classList.add('active');
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const delta = startX - e.clientX; // drag left = wider
      const newWidth = Math.min(600, Math.max(200, startWidth + delta));
      panel.style.width = newWidth + 'px';
      // Persist width
      try { localStorage.setItem('anchor.' + panelId + '.width', newWidth); } catch (_) {}
    });

    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('active');
      document.body.style.userSelect = '';
    });

    // Restore saved width
    try {
      const saved = localStorage.getItem('anchor.' + panelId + '.width');
      if (saved) panel.style.width = saved + 'px';
    } catch (_) {}
  },

  _loadOrCreateSessionId() {
    let id = localStorage.getItem('anchor.sessionId');
    if (!id) {
      id = 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      localStorage.setItem('anchor.sessionId', id);
    }
    return id;
  },

  // WebSocket for bidirectional communication
  connect() {
    this.setStatus('', 'connecting...');
    this.connectWS();
  },

  connectWS() {
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = protocol + '//' + location.host;

    try {
      this.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.error('[anchor] WebSocket construction failed:', e);
      this.setStatus('', 'Retrying...');
      setTimeout(() => this.connectWS(), 2000);
      return;
    }

    this.ws.onopen = () => {
      this.setStatus('live', 'Connected');
      this._pingTimer = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.error('[anchor] parse error:', e);
      }
    };

    this.ws.onclose = () => {
      if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
      this.setStatus('', 'Disconnected. Reconnecting...');
      setTimeout(() => this.connectWS(), 2000);
    };

    this.ws.onerror = () => {
      // onclose fires after onerror, which triggers reconnect
    };
  },

  handleMessage(msg) {
    switch (msg.type) {
      case 'html':
        this.clearProcessing();
        this.render(msg.content);
        break;
      case 'ack':
        this.toast(msg.message || 'OK');
        break;
      case 'error':
        this.toast('Error: ' + msg.message);
        this.clearProcessing();
        break;
      case 'agent_event':
        if (window.TimelinePanel) TimelinePanel.append(msg.event);
        this._handleAgentEvent(msg.event);
        break;
      case 'pong':
        break;
    }
  },

  _handleAgentEvent(evt) {
    var kind = evt.kind || '';
    var payload = evt.payload || {};
    if (kind === 'agent.thinking' || kind === 'agent.decision' || kind === 'agent.tool_call') {
      this.showProcessing(payload.target_anchor || payload.summary || 'AI working...');
    } else if (kind === 'agent.complete' || kind === 'agent.error' || kind === 'agent.partial_render') {
      // Don't clear yet — wait for the final html message
      if (kind === 'agent.error') {
        this.showProcessing('Error: ' + (payload.message || 'unknown'), true);
      }
    }
  },

  // ── Processing state ─────────────────────────────────────────────

  showProcessing(label, isError) {
    if (!this.processingEl) return;
    this.processingEl.style.display = 'flex';
    this.processingLabel.textContent = label || 'AI 处理中';
    this.processingTarget.textContent = '';
    this.processingEl.className = 'toolbar-processing' + (isError ? ' is-error' : '');
    // Auto-hide after 30s if no response
    var self = this;
    if (this._processingTimer) clearTimeout(this._processingTimer);
    this._processingTimer = setTimeout(function () {
      self.hideProcessing();
    }, 30000);
  },

  hideProcessing() {
    if (!this.processingEl) return;
    this.processingEl.style.display = 'none';
    this.processingEl.className = 'toolbar-processing';
    if (this._processingTimer) { clearTimeout(this._processingTimer); this._processingTimer = null; }
  },

  markAnchorProcessing(targetRef) {
    if (!targetRef) return;
    this._processingAnchors.add(targetRef);
    var el = this.container.querySelector('[data-anc="' + targetRef + '"]');
    if (el) el.classList.add('anc-processing');
  },

  clearProcessing() {
    this.hideProcessing();
    var self = this;
    this._processingAnchors.forEach(function (ref) {
      var el = self.container.querySelector('[data-anc="' + ref + '"]');
      if (el) el.classList.remove('anc-processing');
    });
    this._processingAnchors.clear();
  },

  // Rendering
  render(html) {
    if (this.currentHtml && this.currentHtml !== html) {
      // Save previous version to history
      if (window.HistoryPanel) HistoryPanel.save(this.currentHtml, this.countAnchors());
    }
    this.currentHtml = html;
    this.container.innerHTML = html;
    this.injectHandles();
    this.infoEl.textContent = this.countAnchors() + ' anchors';
  },

  injectHandles() {
    const elements = this.container.querySelectorAll('[data-anc]');
    elements.forEach(el => {
      this.wrapElement(el);
      this.addHandleTrigger(el);
    });
  },

  wrapElement(el) {
    if (el.classList.contains('anc-element')) return;
    if (el === this.container) return;
    el.classList.add('anc-element');
    const style = getComputedStyle(el);
    if (style.position === 'static') {
      el.style.position = 'relative';
    }
  },

  addHandleTrigger(el) {
    const anchorId = el.getAttribute('data-anc');
    // Merge model-specified handles with fixed platform defaults.
    // The platform guarantees a minimum set of operations; data-handles only extends.
    const modelHandles = (el.getAttribute('data-handles') || '').split(',').map(h => h.trim()).filter(Boolean);
    const merged = new Set([...this.defaultHandles, ...modelHandles]);
    const handlesStr = Array.from(merged).join(',');
    const existing = Array.from(el.children).find(c => c.classList.contains('anc-handle'));
    if (existing) existing.remove();
    const trigger = document.createElement('span');
    trigger.className = 'anc-handle';
    trigger.textContent = '+';
    trigger.title = 'Actions for ' + anchorId;
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      this.togglePopup(el, trigger, anchorId, handlesStr);
    });
    el.appendChild(trigger);
  },

  // Popup
  _tempOverride: null,  // per-op context override

  togglePopup(el, trigger, anchorId, handlesStr) {
    this.closePopup();
    this._tempOverride = null;
    const handles = handlesStr.split(',').map(h => h.trim()).filter(Boolean);
    if (handles.length === 0) return;
    const popup = document.createElement('div');
    popup.className = 'anc-handle-popup open';
    // Position fixed relative to viewport — always on top
    const triggerRect = trigger.getBoundingClientRect();
    popup.style.position = 'fixed';
    popup.style.top = (triggerRect.bottom + 4) + 'px';
    popup.style.right = (window.innerWidth - triggerRect.right) + 'px';
    popup.style.zIndex = '99999';
    const header = document.createElement('div');
    header.className = 'popup-header';
    header.textContent = anchorId;
    popup.appendChild(header);

    // B.1.7 — Context override chip
    const chip = document.createElement('span');
    chip.className = 'context-chip';
    chip.textContent = this._formatContextChipText();
    chip.title = 'Click to override context for this op';
    let overrideOpen = false;
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      overrideOpen = !overrideOpen;
      chip.classList.toggle('expanded', overrideOpen);
      if (overrideOpen) this._renderMiniContext(popup, chip);
      else { const mc = popup.querySelector('.mini-context-view'); if (mc) mc.remove(); }
    });
    popup.appendChild(chip);

    handles.forEach(opName => {
      const def = this.opDefs[opName];
      if (!def) return;
      // All operations show an input step — required or optional
      if (def.needsInput) {
        const btn = document.createElement('button');
        btn.textContent = (def.icon || '') + ' ' + def.label;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.showOpInput(popup, opName, anchorId, def);
        });
        popup.appendChild(btn);
      } else {
        const btn = document.createElement('button');
        btn.textContent = (def.icon || '') + ' ' + def.label;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.sendOp(opName, anchorId);
          this.closePopup();
        });
        popup.appendChild(btn);
      }
    });
    document.body.appendChild(popup);
    trigger.classList.add('open');
    this.openPopup = { popup, trigger };
    setTimeout(() => {
      document.addEventListener('click', this._outsideClickHandler = (e) => {
        if (!popup.contains(e.target) && e.target !== trigger) {
          this.closePopup();
        }
      });
    }, 0);
  },

  showOpInput(popup, opName, anchorId, def) {
    const existing = popup.querySelector('.op-input-row');
    if (existing) existing.remove();
    var optional = def.needsInput === 'optional';
    var row = document.createElement('div');
    row.className = 'op-input-row';
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = def.inputLabel || 'Enter instruction...';
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        var instruction = input.value.trim();
        if (instruction || optional) {
          this.sendOp(opName, anchorId, instruction ? { instruction: instruction } : undefined);
          this.closePopup();
        }
      }
      e.stopPropagation();
    }.bind(this));
    var executeBtn = document.createElement('button');
    executeBtn.textContent = '执行';
    executeBtn.className = 'btn-execute-now';
    executeBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var instruction = input.value.trim();
      if (instruction || optional) {
        this.sendOp(opName, anchorId, instruction ? { instruction: instruction } : undefined);
        this.closePopup();
      }
    }.bind(this));
    var queueBtn = document.createElement('button');
    queueBtn.textContent = '暂存';
    queueBtn.className = 'btn-queue';
    queueBtn.title = '加入批量执行队列';
    queueBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var instruction = input.value.trim();
      this.queueOp(opName, anchorId, instruction);
      this.closePopup();
    }.bind(this));
    row.appendChild(input);
    row.appendChild(executeBtn);
    row.appendChild(queueBtn);
    popup.appendChild(row);
    setTimeout(function () { input.focus(); }, 50);
  },

  _formatContextChipText() {
    const b = this._tempOverride || (window.ContextPanel ? ContextPanel.getBundle() : {});
    const mc = (b.memory_ids || (b.memory || [])).length;
    const sc = (b.skill_ids || (b.skills || [])).length;
    const ac = (b.subagent_ids || (b.subagents || [])).length;
    const rc = (b.resource_ids || (b.resources || [])).length;
    const total = mc + sc + ac + rc;
    return 'Context: ' + (total || 'default') + ' (' + mc + 'm ' + sc + 's ' + ac + 'a ' + rc + 'r) ▾';
  },

  _renderMiniContext(popup, chip) {
    const view = document.createElement('div');
    view.className = 'mini-context-view';
    const groups = [
      { key: 'memory', label: 'Memory', ids: (this._tempOverride?.memory_ids) || (window.ContextPanel?.selected?.memory ? Array.from(ContextPanel.selected.memory) : []) },
      { key: 'skills', label: 'Skills', ids: (this._tempOverride?.skill_ids) || (window.ContextPanel?.selected?.skills ? Array.from(ContextPanel.selected.skills) : []) },
      { key: 'subagents', label: 'Subagents', ids: (this._tempOverride?.subagent_ids) || (window.ContextPanel?.selected?.subagents ? Array.from(ContextPanel.selected.subagents) : []) },
      { key: 'resources', label: 'Resources', ids: (this._tempOverride?.resource_ids) || (window.ContextPanel?.selected?.resources ? Array.from(ContextPanel.selected.resources) : []) }
    ];
    groups.forEach(g => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:12px;padding:2px 0;';
      const label = document.createElement('span');
      label.textContent = g.label + ': ';
      label.style.cssText = 'font-weight:500;';
      const count = document.createElement('span');
      count.textContent = g.ids.length + ' selected';
      count.style.cssText = 'color:var(--muted,#888);';
      row.appendChild(label); row.appendChild(count);
      // Quick toggles: all / none links
      if (g.ids.length > 0) {
        const clearAll = document.createElement('a');
        clearAll.textContent = 'clear';
        clearAll.style.cssText = 'color:var(--brand);cursor:pointer;margin-left:auto;font-size:11px;';
        clearAll.addEventListener('click', (e) => { e.stopPropagation(); this._setTempOverrideGroup(g.key, []); this._renderMiniContext(popup, chip); });
        row.appendChild(clearAll);
      }
      view.appendChild(row);
    });
    const existing = popup.querySelector('.mini-context-view');
    if (existing) existing.remove();
    chip.after(view);
  },

  _setTempOverrideGroup(group, ids) {
    if (!this._tempOverride) {
      // Clone current bundle as starting point
      const b = window.ContextPanel ? ContextPanel.getBundle() : {};
      this._tempOverride = {
        memory_ids: [...(b.memory_ids || [])],
        skill_ids: [...(b.skill_ids || [])],
        subagent_ids: [...(b.subagent_ids || [])],
        resource_ids: [...(b.resource_ids || [])],
        transient_override: true
      };
    }
    const key = group === 'memory' ? 'memory_ids' : group === 'skills' ? 'skill_ids' : group === 'subagents' ? 'subagent_ids' : 'resource_ids';
    this._tempOverride[key] = ids;
  },

  closePopup() {
    if (this.openPopup) {
      this.openPopup.popup.remove();
      this.openPopup.trigger.classList.remove('open');
      this.openPopup = null;
    }
    if (this._outsideClickHandler) {
      document.removeEventListener('click', this._outsideClickHandler);
      this._outsideClickHandler = null;
    }
  },

  // ── Phase 2: Envelope construction & dispatch ─────────────────────

  buildEnvelope({ op, target_kind, target_ref, instruction, selection, overrideBundle }) {
    const eventId = 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
    const bundle = overrideBundle || (window.ContextPanel ? ContextPanel.getBundle() : null);
    return {
      schema_version: '1.0',
      intent: { op, target_kind, target_ref, instruction },
      selection: selection || null,
      context_bundle: bundle || {
        memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
        scope_hint: 'standard', transient_override: !!overrideBundle
      },
      render_state: this._snapshotRenderState(),
      provenance: {
        session_id: this.sessionId,
        event_id: eventId,
        parent_event_id: null,  // TODO: thread from last agent.complete
        timestamp: new Date().toISOString(),
        client_version: '0.1.0'
      }
    };
  },

  _snapshotRenderState() {
    const anchors = Array.from(this.container.querySelectorAll('[data-anc]'))
      .map(el => el.getAttribute('data-anc'));
    return {
      anchor_tree: anchors,
      dom_signature: 'sig:' + anchors.length,  // TODO: real hash
      viewport: {
        scroll_top: window.scrollY | 0,
        visible_anchors: []  // TODO: compute via IntersectionObserver
      }
    };
  },

  sendEnvelope(envelope) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      var targetRef = envelope.intent && envelope.intent.target_ref;
      if (targetRef) {
        this.markAnchorProcessing(targetRef);
        this.showProcessing(targetRef);
      }
      this.ws.send(JSON.stringify({ type: 'envelope', envelope }));
      this.toast('Sent: ' + envelope.intent.op + ' → ' + targetRef);
    } else {
      this.toast('Connection lost — reconnecting...');
    }
  },

  // ── Queue management ─────────────────────────────────────────────

  queueOp(opName, anchorId, instruction) {
    this.pendingOps.push({
      op: opName,
      target: anchorId,
      instruction: instruction || '',
      timestamp: Date.now()
    });
    this.updateQueueBadge();
    this.toast('Queued: ' + opName + ' → ' + anchorId + ' (' + this.pendingOps.length + ' total)');
  },

  executeAll() {
    if (this.pendingOps.length === 0) return;
    const count = this.pendingOps.length;

    // Build combined instruction from all queued ops
    const parts = this.pendingOps.map((q, i) =>
      (i + 1) + '. **' + q.op + '** on `' + q.target + '`' +
      (q.instruction ? ': ' + q.instruction : '')
    );
    const combinedInstruction = 'Batch of ' + count + ' operations:\n\n' + parts.join('\n');

    // Send as single envelope targeting the first op's target as primary
    const first = this.pendingOps[0];
    const envelope = this.buildEnvelope({
      op: first.op,
      target_kind: 'anchor',
      target_ref: first.target,
      instruction: combinedInstruction,
      selection: null,
      overrideBundle: this._tempOverride || null
    });
    // Attach all ops for server-side awareness
    envelope._batch_ops = this.pendingOps.map(q => ({ op: q.op, target_ref: q.target, instruction: q.instruction }));

    this.sendEnvelope(envelope);
    this.pendingOps = [];
    this.updateQueueBadge();
    this._tempOverride = null;
    this.toast('Executing ' + count + ' ops...');
  },

  updateQueueBadge() {
    const btn = document.getElementById('anchor-execute-all');
    const badge = btn?.querySelector('.execute-badge');
    if (!btn || !badge) return;
    const n = this.pendingOps.length;
    badge.textContent = n;
    if (n > 0) {
      btn.classList.remove('hidden');
      btn.querySelector('.execute-label').textContent = 'Execute All (' + n + ')';
    } else {
      btn.classList.add('hidden');
      btn.querySelector('.execute-label').textContent = 'Execute All';
    }
  },

  // Op dispatch via WebSocket — now builds envelope when context is active
  sendOp(opName, anchorId, args) {
    const sel = window.getSelection();
    let selection = null;
    const el = this.container.querySelector('[data-anc="' + anchorId + '"]');
    if (sel && sel.toString().trim() && el && el.contains(sel.anchorNode)) {
      selection = { text: sel.toString(), start_offset: sel.anchorOffset, end_offset: sel.focusOffset };
    }
    if (opName === 'lock' && el) {
      el.setAttribute('data-anc-locked', '');
      this.toast('Locked: ' + anchorId);
    }
    // Build envelope (includes context bundle)
    const envelope = this.buildEnvelope({
      op: opName,
      target_kind: 'anchor',
      target_ref: anchorId,
      instruction: args?.instruction || '',
      selection,
      overrideBundle: this._tempOverride || null
    });
    this.sendEnvelope(envelope);
    this._tempOverride = null;  // reset per-op override
  },

  // Helpers
  countAnchors() {
    return this.container.querySelectorAll('[data-anc]').length;
  },

  setStatus(cls, text) {
    this.statusEl.textContent = text;
    this.statusEl.className = 'toolbar-status ' + (cls || '');
  },

  toast(message) {
    let el = document.querySelector('.anc-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'anc-toast';
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 1 — ContextPanel: 4-group multi-select (memory/skills/subagents/resources)
// ────────────────────────────────────────────────────────────────────

window.ContextPanel = {
  panel: null,
  anchor: null,
  manifest: { memory: [], skills: [], subagents: [], resources: [] },
  selected: { memory: new Set(), skills: new Set(), subagents: new Set(), resources: new Set() },
  userResources: [],

  init(anchor) {
    this.anchor = anchor;
    this.panel = document.getElementById('anchor-context-panel');
    if (!this.panel) return;
    this._loadFromStorage();
    this._loadUserResources();
    this._wireFilters();
    this._wireResourceForm();
    this.refresh();
  },

  _wireResourceForm() {
    const addBtn = this.panel.querySelector('.resource-add-btn');
    const nameInput = this.panel.querySelector('.resource-name-input');
    const urlInput = this.panel.querySelector('.resource-url-input');
    if (!addBtn) return;
    addBtn.addEventListener('click', () => {
      const name = (nameInput?.value || '').trim();
      const url = (urlInput?.value || '').trim();
      if (!name) return;
      this.addUserResource(name, url);
      if (nameInput) nameInput.value = '';
      if (urlInput) urlInput.value = '';
    });
  },

  addUserResource(name, url) {
    const id = 'ures_' + Date.now().toString(36);
    this.userResources.push({ id, name, url: url || '', addedAt: Date.now() });
    this._saveUserResources();
    this._renderGroup('resources');
  },

  removeUserResource(id) {
    this.userResources = this.userResources.filter(r => r.id !== id);
    this.selected.resources.delete(id);
    this._saveUserResources();
    this._saveToStorage();
    this._renderGroup('resources');
  },

  async refresh() {
    try {
      const res = await fetch('/context-manifest');
      this.manifest = await res.json();
      this._renderAllGroups();
    } catch (e) {
      console.error('[ContextPanel] manifest load failed:', e);
    }
  },

  _renderAllGroups() {
    ['memory', 'skills', 'subagents', 'resources'].forEach(group => this._renderGroup(group));
  },

  _renderGroup(group) {
    const root = this.panel.querySelector(`details[data-group="${group}"] .group-list`);
    const countEl = this.panel.querySelector(`details[data-group="${group}"] .group-count`);
    if (!root) return;
    root.innerHTML = '';
    let items = this.manifest[group] || [];
    // Merge user resources
    if (group === 'resources') {
      items = [...items, ...this.userResources.map(r => ({
        id: r.id, name: r.name, description: r.url || 'user link', type: 'user', _isUser: true
      }))];
    }
    items.forEach(item => root.appendChild(this._renderItem(group, item)));
    if (countEl) countEl.textContent = this.selected[group].size + '/' + items.length;
  },

  _renderItem(group, item) {
    const row = document.createElement('label');
    row.className = 'context-item';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = this.selected[group].has(item.id);
    cb.addEventListener('change', () => this._toggle(group, item.id, cb.checked));
    const meta = document.createElement('div');
    meta.className = 'item-meta';
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = item.name || item.id;
    const desc = document.createElement('span');
    desc.className = 'item-desc';
    desc.textContent = item.description || '';
    if (item._isUser && item.description && item.description.startsWith('http')) {
      const link = document.createElement('a');
      link.href = item.description;
      link.textContent = item.description;
      link.target = '_blank';
      link.style.cssText = 'color:var(--brand);font-size:11px;word-break:break-all;';
      desc.textContent = '';
      desc.appendChild(link);
    }
    meta.appendChild(name);
    meta.appendChild(desc);
    row.appendChild(cb);
    row.appendChild(meta);
    // Delete button for user resources
    if (item._isUser) {
      const delBtn = document.createElement('button');
      delBtn.textContent = '×';
      delBtn.className = 'btn-remove-resource';
      delBtn.title = 'Remove this resource';
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        this.removeUserResource(item.id);
      });
      row.appendChild(delBtn);
    }
    return row;
  },

  _toggle(group, id, checked) {
    if (checked) this.selected[group].add(id);
    else this.selected[group].delete(id);
    this._saveToStorage();
    this._renderGroup(group);
    this._notifyChanged();
  },

  _wireFilters() {
    this.panel.querySelectorAll('.group-filter').forEach(input => {
      input.addEventListener('input', () => {
        const term = input.value.toLowerCase();
        const parent = input.closest('details');
        const items = parent.querySelectorAll('.context-item');
        items.forEach(el => {
          const text = (el.querySelector('.item-name')?.textContent || '') + ' ' +
                       (el.querySelector('.item-desc')?.textContent || '');
          el.style.display = term ? (text.toLowerCase().includes(term) ? '' : 'none') : '';
        });
      });
    });
  },

  _notifyChanged() {
    if (this.anchor?.ws?.readyState === WebSocket.OPEN) {
      this.anchor.ws.send(JSON.stringify({ type: 'context_changed', bundle: this.getBundle() }));
    }
  },

  getBundle() {
    return {
      memory_ids:    Array.from(this.selected.memory),
      skill_ids:     Array.from(this.selected.skills),
      subagent_ids:  Array.from(this.selected.subagents),
      resource_ids:  Array.from(this.selected.resources),
      scope_hint:    'standard',
      transient_override: false
    };
  },

  _loadFromStorage() {
    try {
      const raw = localStorage.getItem('anchor.contextBundle');
      if (!raw) return;
      const data = JSON.parse(raw);
      ['memory', 'skills', 'subagents', 'resources'].forEach(g => {
        this.selected[g] = new Set(data[g] || []);
      });
    } catch (e) { /* ignore */ }
  },

  _saveToStorage() {
    const data = {
      memory:     Array.from(this.selected.memory),
      skills:     Array.from(this.selected.skills),
      subagents:  Array.from(this.selected.subagents),
      resources:  Array.from(this.selected.resources)
    };
    localStorage.setItem('anchor.contextBundle', JSON.stringify(data));
  },

  _loadUserResources() {
    try {
      const raw = localStorage.getItem('anchor.userResources');
      if (raw) this.userResources = JSON.parse(raw);
    } catch { this.userResources = []; }
  },

  _saveUserResources() {
    try {
      localStorage.setItem('anchor.userResources', JSON.stringify(this.userResources));
    } catch { /* ignore */ }
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 3 — SelectionToolbar: free text selection → floating op buttons
// ────────────────────────────────────────────────────────────────────

window.SelectionToolbar = {
  toolbar: null,
  anchor: null,
  _debounce: null,

  init(anchor) {
    this.anchor = anchor;
    this.toolbar = document.getElementById('anchor-floating-toolbar');
    if (!this.toolbar) return;
    this._wireButtons();
    document.addEventListener('selectionchange', () => this._onSelectionChange());
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
  },

  _wireButtons() {
    this.toolbar.querySelectorAll('button[data-op]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        this._dispatch(btn.getAttribute('data-op'));
      });
    });
  },

  _onSelectionChange() {
    clearTimeout(this._debounce);
    this._debounce = setTimeout(() => this._evaluate(), 100);
  },

  _evaluate() {
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || !this._isWithinAnchorContent(sel)) {
      this.hide();
      return;
    }
    this._positionFor(sel);
  },

  _isWithinAnchorContent(sel) {
    if (!sel.anchorNode) return false;
    return !!(this.anchor.container && this.anchor.container.contains(sel.anchorNode));
  },

  _positionFor(sel) {
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    if (!rect.width && !rect.height) { this.hide(); return; }
    const toolbarW = this.toolbar.offsetWidth || 240;
    const toolbarH = this.toolbar.offsetHeight || 40;
    let top = rect.bottom + 8;
    // Switch above if too close to bottom edge
    if (top + toolbarH > window.innerHeight) {
      top = rect.top - toolbarH - 8;
      if (top < 0) top = rect.bottom + 4; // fallback: tiny gap
    }
    let left = rect.left;
    if (left + toolbarW > window.innerWidth - 8) {
      left = window.innerWidth - toolbarW - 8;
    }
    if (left < 4) left = 4;
    this.toolbar.classList.remove('hidden');
    this.toolbar.style.top  = (window.scrollY + top) + 'px';
    this.toolbar.style.left = (window.scrollX + left) + 'px';
  },

  hide() { this.toolbar?.classList.add('hidden'); },

  _dispatch(op) {
    const sel = window.getSelection();
    const text = sel?.toString();
    if (!text) return;
    const meta = this._buildSelectionMeta(sel);
    // B.3.4: if no ancestor anchor, treat as global
    const targetKind = meta.ancestor_anchor ? 'selection' : 'global';
    const targetRef = targetKind === 'global' ? 'global' : ('selection:' + meta.ancestor_anchor + ':' + this._hash(text));

    // ops that need instruction → show inline input row
    if (['refine','branch','annotate','ask'].includes(op)) {
      this._showInstructionPrompt(op, targetKind, targetRef, meta);
    } else {
      this._doDispatch(op, targetKind, targetRef, '', meta);
    }
  },

  _showInstructionPrompt(op, targetKind, targetRef, meta) {
    const existing = this.toolbar.querySelector('.selection-input-row');
    if (existing) existing.remove();
    const row = document.createElement('div');
    row.className = 'selection-input-row';
    row.style.cssText = 'display:flex;gap:4px;padding:4px 0;';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'What to change?';
    input.style.cssText = 'flex:1;min-width:120px;padding:2px 6px;border:1px solid var(--border);border-radius:6px;background:transparent;color:inherit;font:inherit;';
    const submit = document.createElement('button');
    submit.textContent = 'Go';
    submit.className = 'btn btn--sm';
    const cancel = document.createElement('button');
    cancel.textContent = '×';
    cancel.className = 'btn btn--ghost btn--sm';
    row.appendChild(input); row.appendChild(submit); row.appendChild(cancel);
    this.toolbar.appendChild(row);
    input.focus();
    const finish = (instr) => {
      row.remove();
      this._doDispatch(op, targetKind, targetRef, instr || '', meta);
    };
    submit.addEventListener('click', (e) => { e.stopPropagation(); finish(input.value.trim()); });
    cancel.addEventListener('click', (e) => { e.stopPropagation(); row.remove(); this.hide(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.stopPropagation(); finish(input.value.trim()); }
      if (e.key === 'Escape') { e.stopPropagation(); row.remove(); this.hide(); }
    });
  },

  _doDispatch(op, targetKind, targetRef, instruction, meta) {
    const envelope = this.anchor.buildEnvelope({
      op, target_kind: targetKind, target_ref: targetRef, instruction, selection: meta
    });
    this.anchor.sendEnvelope(envelope);
    this.hide();
  },

  _buildSelectionMeta(sel) {
    const text = sel.toString();
    let ancestor = sel.anchorNode;
    while (ancestor && !(ancestor.nodeType === 1 && ancestor.hasAttribute('data-anc'))) {
      ancestor = ancestor.parentNode;
    }
    // Compute offsets within the ancestor's text content
    let startOffset = 0;
    let endOffset = text.length;
    if (ancestor) {
      const ancText = ancestor.textContent;
      const selStart = ancText.indexOf(text);
      if (selStart >= 0) {
        startOffset = selStart;
        endOffset = selStart + text.length;
      }
    }
    // Compute simplified dom_path from #anchor-content
    let domPath = '';
    try {
      const parts = [];
      let node = sel.anchorNode;
      while (node && node !== this.anchor.container) {
        if (node.nodeType === 1) {
          const tag = node.tagName.toLowerCase();
          let sel = tag;
          if (node.getAttribute && node.hasAttribute('data-anc')) {
            sel += '[data-anc="' + node.getAttribute('data-anc') + '"]';
          } else if (node.id) {
            sel += '#' + node.id;
          } else {
            const parent = node.parentNode;
            if (parent) {
              const idx = Array.from(parent.children).indexOf(node) + 1;
              sel += ':nth-child(' + idx + ')';
            }
          }
          parts.unshift(sel);
        }
        node = node.parentNode;
      }
      domPath = parts.join(' > ');
    } catch (e) { domPath = ''; }

    return {
      text, start_offset: startOffset, end_offset: endOffset,
      ancestor_anchor: ancestor ? ancestor.getAttribute('data-anc') : null,
      dom_path: domPath
    };
  },

  _hash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h).toString(36).slice(0, 8);
  }
};

// ────────────────────────────────────────────────────────────────────
// Phase 4 — TimelinePanel: render agent_event stream
// ────────────────────────────────────────────────────────────────────

window.TimelinePanel = {
  panel: null,
  list: null,
  anchor: null,
  _currentGroup: null,

  init(anchor) {
    this.anchor = anchor;
    this.panel = document.getElementById('anchor-timeline-panel');
    this.list = document.getElementById('timeline-events');
  },

  append(event) {
    if (!this.list) return;
    if (event.kind === 'user.intent') {
      // Auto-fold previous group
      if (this._currentGroup) {
        this._currentGroup.removeAttribute('open');
        this._currentGroup = null;
      }
      this._startNewGroup();
    }
    const card = this._renderEvent(event);
    // If we have an open group, append to it, else directly to list
    const groupOpen = this.list.querySelector('details.timeline-group[open]');
    if (groupOpen) {
      groupOpen.appendChild?.(card);
      // details elements use a nested structure, append to its last child if needed
      // Actually, let's keep things simple: append to the group's own .group-body or directly
      let body = groupOpen.querySelector('.group-body');
      if (!body) {
        body = document.createElement('div');
        body.className = 'group-body';
        groupOpen.appendChild(body);
      }
      body.appendChild(card);
    } else {
      this.list.appendChild(card);
    }
    this.list.scrollTop = this.list.scrollHeight;
    // On agent.complete, wrap current events in a group
    if (event.kind === 'agent.complete') {
      this._wrapCurrentGroup(event);
    }
  },

  _renderEvent(event) {
    const details = document.createElement('details');
    const kind = (event.kind || 'unknown').replace(/^agent\./, '');
    details.className = 'timeline-event kind-' + kind;
    const summary = document.createElement('summary');
    summary.className = 'event-summary';
    summary.textContent = this._summaryFor(event);
    // Time relative to previous event, or absolute
    const timeSpan = document.createElement('span');
    timeSpan.className = 'event-time';
    timeSpan.textContent = this._formatTime(event.timestamp);
    summary.appendChild(timeSpan);
    details.appendChild(summary);
    // Expanded payload
    const payloadDiv = document.createElement('pre');
    payloadDiv.style.cssText = 'font-size:11px;margin:4px 0 0;padding:4px 8px;border-radius:6px;background:rgba(0,0,0,0.1);max-height:200px;overflow-y:auto;white-space:pre-wrap;';
    payloadDiv.textContent = JSON.stringify(event.payload || {}, null, 2);
    details.appendChild(payloadDiv);
    return details;
  },

  _summaryFor(event) {
    const p = event.payload || {};
    const kind = event.kind || '';
    if (kind.includes('thinking'))  return 'Thinking: ' + (p.summary || '(thinking)');
    if (kind.includes('tool_call')) return 'Tool: ' + (p.tool || '?') + (p.status ? ' [' + p.status + ']' : '');
    if (kind.includes('partial_render')) return 'Partial render' + (p.target_anchor ? ' (target: ' + p.target_anchor + ')' : '');
    if (kind.includes('decision')) return 'Decision: ' + (p.choice || '?');
    if (kind.includes('render'))   return 'Rendered (' + (p.html_size || '?') + ' bytes)';
    if (kind.includes('complete')) return 'Done' + (p.summary ? ': ' + p.summary : '');
    if (kind.includes('error'))    return 'Error: ' + (p.message || '?');
    if (kind.includes('user.intent')) return 'User: ' + ((event.payload?.intent || event.payload)?.op || '?').toString();
    if (kind.includes('session_start')) return 'Session started';
    if (kind.includes('session_end'))   return 'Session ended';
    return kind + (p.summary ? ': ' + p.summary : '');
  },

  _formatTime(ts) {
    if (!ts) return '';
    if (this._lastTs) {
      try {
        const delta = Math.round((new Date(ts) - new Date(this._lastTs)) / 1000);
        this._lastTs = ts;
        return delta > 60 ? Math.floor(delta/60) + 'm' : delta + 's';
      } catch { this._lastTs = ts; return ''; }
    }
    this._lastTs = ts;
    try { return new Date(ts).toLocaleTimeString(); } catch { return ''; }
  },

  _startNewGroup() {
    this._lastTs = null;
  },

  _wrapCurrentGroup(completeEvent) {
    // Gather all non-details elements or loose cards since the last separator
    const recent = [];
    let el = this.list.lastElementChild;
    while (el && !el.classList.contains('timeline-group-separator')) {
      if (!el.classList.contains('timeline-group')) recent.unshift(el);
      el = el.previousElementSibling;
    }
    if (recent.length === 0) return;
    const group = document.createElement('details');
    group.className = 'timeline-group';
    group.setAttribute('open', '');
    const gSummary = document.createElement('summary');
    gSummary.style.cssText = 'font-size:12px;font-weight:500;padding:4px 0;cursor:pointer;color:var(--muted,#888);';
    gSummary.textContent = 'Completed  ·  ' + recent.length + ' step(s)';
    group.appendChild(gSummary);
    const body = document.createElement('div');
    body.className = 'group-body';
    recent.forEach(c => { c.remove(); body.appendChild(c); });
    group.appendChild(body);
    this.list.appendChild(group);
    this._currentGroup = group;
  }
};

// ────────────────────────────────────────────────────────────────────
// HistoryPanel — version history with rollback
// ────────────────────────────────────────────────────────────────────

window.HistoryPanel = {
  MAX_ENTRIES: 50,
  entries: [],

  init(anchor) {
    this.anchor = anchor;
    this._loadFromStorage();
    this._render();
  },

  save(html, anchorCount) {
    const entry = {
      id: 'hist_' + Date.now().toString(36),
      timestamp: new Date().toISOString(),
      anchorCount,
      html,
      summary: anchorCount + ' anchors, ' + html.length + ' bytes'
    };
    this.entries.unshift(entry);
    if (this.entries.length > this.MAX_ENTRIES) this.entries.pop();
    this._saveToStorage();
    this._render();
  },

  restore(entryId) {
    const entry = this.entries.find(e => e.id === entryId);
    if (!entry || !this.anchor) return;
    this.anchor.currentHtml = entry.html;
    this.anchor.container.innerHTML = entry.html;
    this.anchor.injectHandles();
    this.anchor.infoEl.textContent = entry.anchorCount + ' anchors (restored)';
    this.anchor.toast('Restored: ' + entry.summary);
  },

  _render() {
    const root = document.querySelector('details[data-group="history"] .group-list');
    const countEl = document.querySelector('details[data-group="history"] .group-count');
    if (!root) return;
    root.innerHTML = '';
    this.entries.forEach(entry => {
      const row = document.createElement('div');
      row.className = 'history-entry';
      const meta = document.createElement('div');
      meta.className = 'history-meta';
      const time = document.createElement('span');
      time.className = 'history-time';
      try { time.textContent = new Date(entry.timestamp).toLocaleString(); } catch { time.textContent = entry.timestamp; }
      const summary = document.createElement('span');
      summary.className = 'history-summary';
      summary.textContent = entry.summary;
      meta.appendChild(time);
      meta.appendChild(summary);
      const restoreBtn = document.createElement('button');
      restoreBtn.className = 'btn btn--ghost btn--sm';
      restoreBtn.textContent = 'Restore';
      restoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.restore(entry.id);
      });
      row.appendChild(meta);
      row.appendChild(restoreBtn);
      // Click row to preview (tooltip style — just restore for now)
      row.addEventListener('click', () => this.restore(entry.id));
      row.style.cursor = 'pointer';
      root.appendChild(row);
    });
    if (countEl) countEl.textContent = this.entries.length;
  },

  _loadFromStorage() {
    try {
      const raw = localStorage.getItem('anchor.history');
      if (raw) this.entries = JSON.parse(raw);
    } catch { /* ignore */ }
  },

  _saveToStorage() {
    try {
      // Don't store full HTML in localStorage (size limits); keep last 20
      const toSave = this.entries.slice(0, 20);
      localStorage.setItem('anchor.history', JSON.stringify(toSave));
    } catch (e) {
      // If quota exceeded, trim further
      try {
        const slim = this.entries.slice(0, 5).map(e => ({ ...e, html: e.html.substring(0, 5000) }));
        localStorage.setItem('anchor.history', JSON.stringify(slim));
      } catch { /* give up */ }
    }
  }
};

// ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() { Anchor.init(); });
