/* canvas-client.js — loom-human-ag freeform canvas
   Stand-alone; does NOT import or depend on anchor-client.js          */
'use strict';
(function () {

// ─────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────
var state = {
  cards:       new Map(),    // anchor_id → { el, contentEl, x, y, w, h, rot, scale, z, localMoved }
  viewport:    { x: 0, y: 0, zoom: 1 },
  selected:    new Set(),    // anchor_ids currently selected
  connections: new Map(),    // connId → { id, fromId, toId }
};

var CANVAS_W = 3000;
var CANVAS_H = 2000;
var SNAP_GRID = 40;
var SNAP_THR  = 8;

var stage, viewport, promptInput, statusEl, emptyEl, marqueeEl, selBadgeEl, ws;
var suggBarEl, suggLabelEl, suggAcceptBtn, suggRejectBtn;
var snapBtnEl, connectBtnEl, exportBtnEl;
var _activeSuggestion = null;
var _syncTimer = null;

// ── Undo/redo ────────────────────────────────────────────────────────
var _undoStack = [];
var _redoStack = [];
var _dragStartSnap = null;

// ── Direct edit mode ────────────────────────────────────────────────
var _editingId   = null;
var EDITABLE_SEL = 'h1,h2,h3,h4,h5,h6,p,li,td,th,.kpi-value,.kpi-label,.kpi-label-top,.kpi-unit';

// ── Connect mode ────────────────────────────────────────────────────
var _connectMode = false;
var _connectFrom = null;   // anchor_id of the "from" card

// ── Snap ────────────────────────────────────────────────────────────
var _snapEnabled = true;

// ─────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  stage       = document.getElementById('canvas-stage');
  viewport    = document.getElementById('canvas-viewport');
  promptInput = document.getElementById('canvas-prompt-input');
  statusEl    = document.getElementById('canvas-status');
  emptyEl     = document.getElementById('canvas-empty');
  marqueeEl   = document.getElementById('canvas-marquee');
  selBadgeEl  = document.getElementById('canvas-sel-badge');
  suggBarEl   = document.getElementById('canvas-suggestion-bar');
  suggLabelEl = document.getElementById('canvas-suggestion-label');
  suggAcceptBtn = document.getElementById('canvas-suggestion-accept');
  suggRejectBtn = document.getElementById('canvas-suggestion-reject');
  if (suggAcceptBtn) suggAcceptBtn.addEventListener('click', acceptLayoutSuggestion);
  if (suggRejectBtn) suggRejectBtn.addEventListener('click', rejectLayoutSuggestion);
  snapBtnEl    = document.getElementById('canvas-snap-btn');
  connectBtnEl = document.getElementById('canvas-connect-btn');
  if (snapBtnEl)    snapBtnEl.addEventListener('click', toggleSnap);
  if (connectBtnEl) connectBtnEl.addEventListener('click', toggleConnectMode);
  exportBtnEl = document.getElementById('canvas-export-btn');
  if (exportBtnEl)  exportBtnEl.addEventListener('click', exportPNG);

  initViewport();
  initPromptUI();
  initWS();
  loadSavedCanvas();

  // Exit edit mode when clicking outside the edited card
  document.addEventListener('mousedown', function (e) {
    if (_editingId && !e.target.closest('.canvas-card-host[data-card-id="' + _editingId + '"]')) {
      exitEditMode();
    }
  }, true);
});

// ─────────────────────────────────────────────────────────────────────
// Viewport — pan (space-drag or middle-drag) + wheel zoom
// ─────────────────────────────────────────────────────────────────────
function initViewport() {
  var isPanning = false;
  var panStart  = null;
  var spaceDown = false;
  var _marquee  = null;

  document.addEventListener('keydown', function (e) {
    var inInput = document.activeElement === promptInput;

    // Edit mode — only Escape passes through; everything else is for the text editor
    if (_editingId) {
      if (e.key === 'Escape') { e.preventDefault(); exitEditMode(); }
      return;
    }

    if (e.code === 'Space' && !inInput) {
      spaceDown = true;
      document.body.classList.add('canvas-panning');
      e.preventDefault();
      return;
    }

    if (!inInput && (e.key === 'Delete' || e.key === 'Backspace') && state.selected.size > 0) {
      e.preventDefault();
      pushUndo();
      deleteSelected();
      return;
    }

    if (!inInput && (e.ctrlKey || e.metaKey)) {
      if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
      if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) { e.preventDefault(); redo(); return; }
      if (e.key === 'd') { e.preventDefault(); duplicateSelected(); return; }
    }

    if (!inInput && e.key === 'c' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      toggleConnectMode();
    }
    if (!inInput && e.key === 'Escape') {
      if (_connectMode) { toggleConnectMode(); }
      clearSelection();
    }
  });

  document.addEventListener('keyup', function (e) {
    if (e.code === 'Space') {
      spaceDown = false;
      document.body.classList.remove('canvas-panning');
      isPanning = false;
    }
  });

  viewport.addEventListener('mousedown', function (e) {
    if (spaceDown || e.button === 1) {
      isPanning = true;
      panStart = { x: e.clientX - state.viewport.x, y: e.clientY - state.viewport.y };
      e.preventDefault();
      return;
    }
    // Click on empty canvas → clear selection + start marquee
    if (e.target === viewport || e.target === stage) {
      clearSelection();
      var vr = viewport.getBoundingClientRect();
      _marquee = {
        startX: e.clientX - vr.left, startY: e.clientY - vr.top,
        endX:   e.clientX - vr.left, endY:   e.clientY - vr.top,
      };
      e.preventDefault();
    }
  });

  document.addEventListener('mousemove', function (e) {
    if (_marquee) {
      var vr = viewport.getBoundingClientRect();
      _marquee.endX = e.clientX - vr.left;
      _marquee.endY = e.clientY - vr.top;
      updateMarqueeEl(_marquee);
    }
    if (!isPanning || !panStart) return;
    state.viewport.x = e.clientX - panStart.x;
    state.viewport.y = e.clientY - panStart.y;
    applyViewportTransform();
  });

  document.addEventListener('mouseup', function () {
    if (_marquee) {
      finishMarquee(_marquee);
      _marquee = null;
      if (marqueeEl) marqueeEl.style.display = 'none';
    }
    isPanning = false;
  });

  // ── Touch: 1-finger pan, 2-finger pinch-zoom ───────────────────
  var _lastPinchDist = null;

  viewport.addEventListener('touchstart', function (e) {
    e.preventDefault();
    if (e.touches.length === 1) {
      var t = e.touches[0];
      isPanning = true;
      panStart = { x: t.clientX - state.viewport.x, y: t.clientY - state.viewport.y };
      _lastPinchDist = null;
    } else if (e.touches.length === 2) {
      isPanning = false;
      _lastPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
    }
  }, { passive: false });

  viewport.addEventListener('touchmove', function (e) {
    e.preventDefault();
    if (e.touches.length === 1 && isPanning && panStart) {
      var t = e.touches[0];
      state.viewport.x = t.clientX - panStart.x;
      state.viewport.y = t.clientY - panStart.y;
      applyViewportTransform();
    } else if (e.touches.length === 2) {
      var d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      if (_lastPinchDist) {
        var factor  = d / _lastPinchDist;
        var newZoom = Math.max(0.15, Math.min(5, state.viewport.zoom * factor));
        var cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        var cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        var vr = viewport.getBoundingClientRect();
        var ratio = newZoom / state.viewport.zoom;
        state.viewport.x = (cx - vr.left) + (state.viewport.x - (cx - vr.left)) * ratio;
        state.viewport.y = (cy - vr.top)  + (state.viewport.y - (cy - vr.top))  * ratio;
        state.viewport.zoom = newZoom;
        applyViewportTransform();
      }
      _lastPinchDist = d;
    }
  }, { passive: false });

  viewport.addEventListener('touchend', function (e) {
    e.preventDefault();
    if (e.touches.length === 0) { isPanning = false; _lastPinchDist = null; }
  }, { passive: false });

  viewport.addEventListener('wheel', function (e) {
    e.preventDefault();
    var factor  = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    var newZoom = Math.max(0.15, Math.min(5, state.viewport.zoom * factor));

    // Zoom toward cursor
    var rect  = viewport.getBoundingClientRect();
    var cx    = e.clientX - rect.left;
    var cy    = e.clientY - rect.top;
    var ratio = newZoom / state.viewport.zoom;
    state.viewport.x = cx + (state.viewport.x - cx) * ratio;
    state.viewport.y = cy + (state.viewport.y - cy) * ratio;
    state.viewport.zoom = newZoom;

    applyViewportTransform();
  }, { passive: false });
}

function applyViewportTransform() {
  stage.style.transform = 'translate(' + state.viewport.x + 'px,' + state.viewport.y + 'px) scale(' + state.viewport.zoom + ')';
  stage.style.transformOrigin = '0 0';
}

function updateMarqueeEl(m) {
  if (!marqueeEl) return;
  var x = Math.min(m.startX, m.endX);
  var y = Math.min(m.startY, m.endY);
  var w = Math.abs(m.endX - m.startX);
  var h = Math.abs(m.endY - m.startY);
  if (w < 2 && h < 2) { marqueeEl.style.display = 'none'; return; }
  marqueeEl.style.cssText = 'display:block;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;';
}

function finishMarquee(m) {
  var w = Math.abs(m.endX - m.startX);
  var h = Math.abs(m.endY - m.startY);
  if (w < 5 && h < 5) return; // was a click, not a drag — selection cleared in mousedown
  var vr = viewport.getBoundingClientRect();
  var mx1 = Math.min(m.startX, m.endX) + vr.left;
  var my1 = Math.min(m.startY, m.endY) + vr.top;
  var mx2 = Math.max(m.startX, m.endX) + vr.left;
  var my2 = Math.max(m.startY, m.endY) + vr.top;
  state.cards.forEach(function (entry, id) {
    var cr = entry.el.getBoundingClientRect();
    if (cr.right > mx1 && cr.left < mx2 && cr.bottom > my1 && cr.top < my2) {
      selectCard(id);
    }
  });
}

// ─────────────────────────────────────────────────────────────────────
// Card rendering — parse agent HTML → positioned cards
// ─────────────────────────────────────────────────────────────────────
function renderFromHtml(html) {
  var tmp = document.createElement('div');
  tmp.innerHTML = html;

  // Find canvas-root container (agent may wrap in a full HTML doc)
  var canvasRoot = tmp.querySelector('[data-anc="canvas-root"]')
                || tmp.querySelector('#canvas-stage')
                || tmp;

  var cardEls = canvasRoot.querySelectorAll('[data-anc]:not([data-anc="canvas-root"])');
  if (cardEls.length === 0) {
    // Fallback: treat every data-anc element as a card
    cardEls = tmp.querySelectorAll('[data-anc]');
  }

  var newIds  = new Set();
  var autoX   = 80;
  var autoY   = 80;
  var autoCol = 0;

  cardEls.forEach(function (cardEl) {
    var id = cardEl.getAttribute('data-anc');
    if (!id || id === 'canvas-root') return;
    newIds.add(id);

    var hasPos = cardEl.getAttribute('data-anc-x') !== null;
    var x     = hasPos ? parseFloat(cardEl.getAttribute('data-anc-x'))     : autoX + autoCol * 360;
    var y     = hasPos ? parseFloat(cardEl.getAttribute('data-anc-y'))     : autoY;
    var w     = parseFloat(cardEl.getAttribute('data-anc-w')     || '320');
    var h     = parseFloat(cardEl.getAttribute('data-anc-h')     || '0');
    var rot   = parseFloat(cardEl.getAttribute('data-anc-rot')   || '0');
    var scale = parseFloat(cardEl.getAttribute('data-anc-scale') || '1');
    var z     = parseInt(  cardEl.getAttribute('data-anc-z')     || '1', 10);

    if (!hasPos) {
      autoCol++;
      if (autoCol >= 4) { autoCol = 0; autoY += 280; }
    }

    if (state.cards.has(id)) {
      var existing = state.cards.get(id);
      existing.contentEl.innerHTML = cardEl.innerHTML;
      if (!existing.localMoved) {
        existing.x = x; existing.y = y; existing.w = w; existing.h = h;
        existing.rot = rot; existing.scale = scale; existing.z = z;
        updateCardTransform(existing);
      }
    } else {
      addCard(id, cardEl.outerHTML, x, y, w, h, rot, scale, z);
    }
  });

  // Remove cards absent from new render only if the render included cards
  if (newIds.size > 0) {
    state.cards.forEach(function (card, id) {
      if (!newIds.has(id)) { card.el.remove(); state.cards.delete(id); }
    });
  }

  updateEmptyState();
}

function addCard(id, outerHtml, x, y, w, h, rot, scale, z) {
  var host = document.createElement('div');
  host.className = 'canvas-card-host';
  host.dataset.cardId = id;
  var css = 'position:absolute;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;z-index:' + z + ';transform:rotate(' + rot + 'deg) scale(' + scale + ');';
  if (h > 0) css += 'height:' + h + 'px;overflow:hidden;';
  host.style.cssText = css;

  var inner = document.createElement('div');
  inner.innerHTML = outerHtml;
  var contentEl = inner.firstElementChild || inner;
  host.appendChild(contentEl);

  var handles = buildHandles(id);
  host.appendChild(handles);

  stage.appendChild(host);

  var entry = {
    el: host, contentEl: contentEl,
    x: x, y: y, w: w, h: h || 0, rot: rot, scale: scale, z: z,
    localMoved: false
  };
  state.cards.set(id, entry);
  bindCardEvents(id, host, entry);
  return entry;
}

// ─────────────────────────────────────────────────────────────────────
// Handles DOM
// ─────────────────────────────────────────────────────────────────────
function buildHandles(id) {
  var h = document.createElement('div');
  h.className = 'card-handles';
  h.setAttribute('data-for', id);
  h.innerHTML =
    '<div class="resize-handle resize-nw" data-dir="nw"></div>' +
    '<div class="resize-handle resize-n"  data-dir="n"></div>'  +
    '<div class="resize-handle resize-ne" data-dir="ne"></div>' +
    '<div class="resize-handle resize-e"  data-dir="e"></div>'  +
    '<div class="resize-handle resize-se" data-dir="se"></div>' +
    '<div class="resize-handle resize-s"  data-dir="s"></div>'  +
    '<div class="resize-handle resize-sw" data-dir="sw"></div>' +
    '<div class="resize-handle resize-w"  data-dir="w"></div>'  +
    '<div class="rotate-handle"           data-action="rotate"></div>';
  return h;
}

// ─────────────────────────────────────────────────────────────────────
// Drag state
// ─────────────────────────────────────────────────────────────────────
var _drag = null;

function bindCardEvents(id, host, entry) {
  host.addEventListener('mouseenter', function () {
    if (_drag || _connectMode || _editingId) return;
    clearSelection();
    selectCard(id);
  });
  // Double-click → enter direct edit mode
  host.addEventListener('dblclick', function (e) {
    if (e.target.closest('.card-handles')) return;
    e.stopPropagation();
    enterEditMode(id);
  });

  // Card body → select + move (or connect in connect mode)
  host.addEventListener('mousedown', function (e) {
    if (e.target.closest('.card-handles')) return;
    e.stopPropagation();
    if (_connectMode) { handleConnectClick(id); return; }
    if (_editingId === id) return; // let text cursor clicks through
    if (!e.shiftKey) clearSelection();
    selectCard(id);
    beginDrag(e, id, entry, 'move', null);
  });

  // Resize handles
  host.querySelectorAll('.resize-handle').forEach(function (rh) {
    rh.addEventListener('mousedown', function (e) {
      e.stopPropagation();
      if (!e.shiftKey) clearSelection();
      selectCard(id);
      beginDrag(e, id, entry, 'resize', rh.dataset.dir);
    });
  });

  // Rotate handle
  var rotH = host.querySelector('.rotate-handle');
  if (rotH) {
    rotH.addEventListener('mousedown', function (e) {
      e.stopPropagation();
      if (!e.shiftKey) clearSelection();
      selectCard(id);
      beginDrag(e, id, entry, 'rotate', null);
    });
  }
}

function beginDrag(e, id, entry, type, dir) {
  _dragStartSnap = snapshotCards();
  // Snapshot actual rendered height for resize (h=0 means auto so far)
  if (type === 'resize' && !entry.h) entry.h = entry.el.offsetHeight;

  var rect = entry.el.getBoundingClientRect();
  _drag = {
    type:     type,
    id:       id,
    dir:      dir,
    clientX0: e.clientX,
    clientY0: e.clientY,
    x0:  entry.x,
    y0:  entry.y,
    w0:  entry.w,
    h0:  entry.h || entry.el.offsetHeight,
    rot0: entry.rot,
    // Pre-compute card center for rotation
    cx: rect.left + rect.width  / 2,
    cy: rect.top  + rect.height / 2,
  };
  // Angle between cursor and card center at drag start
  _drag.ang0 = Math.atan2(e.clientY - _drag.cy, e.clientX - _drag.cx) - (entry.rot * Math.PI / 180);
  document.body.classList.add('canvas-dragging');
  e.preventDefault();
}

document.addEventListener('mousemove', function (e) {
  if (!_drag) return;
  var entry = state.cards.get(_drag.id);
  if (!entry) return;

  var zoom = state.viewport.zoom;
  var dx   = (e.clientX - _drag.clientX0) / zoom;
  var dy   = (e.clientY - _drag.clientY0) / zoom;

  if (_drag.type === 'move') {
    var rawX = _drag.x0 + dx;
    var rawY = _drag.y0 + dy;
    entry.x = _snapEnabled ? snap(rawX) : rawX;
    entry.y = _snapEnabled ? snap(rawY) : rawY;
    entry.localMoved = true;

  } else if (_drag.type === 'rotate') {
    var rect = entry.el.getBoundingClientRect();
    var cx   = rect.left + rect.width  / 2;
    var cy   = rect.top  + rect.height / 2;
    var ang  = Math.atan2(e.clientY - cy, e.clientX - cx);
    entry.rot = (ang - _drag.ang0) * 180 / Math.PI;
    entry.localMoved = true;

  } else if (_drag.type === 'resize') {
    var dir = _drag.dir;
    // Horizontal
    if (dir === 'e' || dir === 'se' || dir === 'ne') {
      entry.w = Math.max(160, _drag.w0 + dx);
    } else if (dir === 'w' || dir === 'sw' || dir === 'nw') {
      var nw = Math.max(160, _drag.w0 - dx);
      entry.x = _drag.x0 + (_drag.w0 - nw);
      entry.w = nw;
    }
    // Vertical
    if (dir === 's' || dir === 'se' || dir === 'sw') {
      entry.h = Math.max(80, _drag.h0 + dy);
    } else if (dir === 'n' || dir === 'ne' || dir === 'nw') {
      var nh = Math.max(80, _drag.h0 - dy);
      entry.y = _drag.y0 + (_drag.h0 - nh);
      entry.h = nh;
    }
    entry.localMoved = true;
  }

  updateCardTransform(entry);
  if (state.connections.size > 0) renderConnections();
});

document.addEventListener('mouseup', function () {
  if (_drag) {
    var movedEntry = state.cards.get(_drag.id);
    if (movedEntry && movedEntry.localMoved && _dragStartSnap) {
      _undoStack.push(_dragStartSnap);
      if (_undoStack.length > 30) _undoStack.shift();
      _redoStack = [];
    }
    _dragStartSnap = null;
    scheduleSync();
    _drag = null;
    document.body.classList.remove('canvas-dragging');
  }
});

function updateCardTransform(entry) {
  entry.el.style.left      = entry.x   + 'px';
  entry.el.style.top       = entry.y   + 'px';
  entry.el.style.width     = entry.w   + 'px';
  entry.el.style.zIndex    = entry.z;
  entry.el.style.transform = 'rotate(' + entry.rot + 'deg) scale(' + entry.scale + ')';
  if (entry.h > 0) {
    entry.el.style.height   = entry.h + 'px';
    entry.el.style.overflow = 'hidden';
  } else {
    entry.el.style.height   = '';
    entry.el.style.overflow = '';
  }

  // Keep data-anc-* on content element in sync (so serialization is correct)
  var c = entry.contentEl;
  if (c) {
    c.setAttribute('data-anc-x',     entry.x);
    c.setAttribute('data-anc-y',     entry.y);
    c.setAttribute('data-anc-w',     entry.w);
    c.setAttribute('data-anc-rot',   entry.rot);
    c.setAttribute('data-anc-scale', entry.scale);
    c.setAttribute('data-anc-z',     entry.z);
    if (entry.h > 0) c.setAttribute('data-anc-h', entry.h);
    else c.removeAttribute('data-anc-h');
  }
}

// ─────────────────────────────────────────────────────────────────────
// Selection
// ─────────────────────────────────────────────────────────────────────
function selectCard(id) {
  state.selected.add(id);
  var e = state.cards.get(id);
  if (e) e.el.classList.add('canvas-selected');
  updateSelectionUI();
}

function clearSelection() {
  state.selected.forEach(function (id) {
    var e = state.cards.get(id);
    if (e) e.el.classList.remove('canvas-selected');
  });
  state.selected.clear();
  updateSelectionUI();
}

function deleteSelected() {
  // Prune connections that reference deleted cards
  var deadConns = [];
  state.connections.forEach(function (conn, cid) {
    if (state.selected.has(conn.fromId) || state.selected.has(conn.toId)) deadConns.push(cid);
  });
  deadConns.forEach(function (cid) { state.connections.delete(cid); });
  if (deadConns.length) renderConnections();

  state.selected.forEach(function (id) {
    var entry = state.cards.get(id);
    if (entry) { entry.el.remove(); state.cards.delete(id); }
  });
  state.selected.clear();
  updateEmptyState();
  updateSelectionUI();
  scheduleSync();
}

// ─────────────────────────────────────────────────────────────────────
// Layout suggestion — ghost preview + Accept / Reject
// ─────────────────────────────────────────────────────────────────────
function showLayoutSuggestion(payload) {
  if (_activeSuggestion) dismissLayoutSuggestion();
  _activeSuggestion = payload;

  payload.moves.forEach(function (mv) {
    var entry = state.cards.get(mv.anchor_id);
    if (!entry) return;
    var ghost = entry.el.cloneNode(true);
    ghost.classList.add('canvas-ghost');
    ghost.classList.remove('canvas-selected');
    ghost.dataset.ghostFor = mv.anchor_id;
    ghost.style.left      = (mv.x !== undefined ? mv.x : entry.x) + 'px';
    ghost.style.top       = (mv.y !== undefined ? mv.y : entry.y) + 'px';
    ghost.style.transform = 'rotate(' + (mv.rot !== undefined ? mv.rot : entry.rot) + 'deg) scale(' + (mv.scale !== undefined ? mv.scale : entry.scale) + ')';
    ghost.style.zIndex    = 50;
    stage.appendChild(ghost);
  });

  if (suggBarEl) {
    if (suggLabelEl) suggLabelEl.textContent = 'AI 建议重排 ' + payload.moves.length + ' 张卡片';
    suggBarEl.classList.remove('hidden');
  }
}

function dismissLayoutSuggestion() {
  stage.querySelectorAll('.canvas-ghost').forEach(function (el) { el.remove(); });
  if (suggBarEl) suggBarEl.classList.add('hidden');
  _activeSuggestion = null;
}

function acceptLayoutSuggestion() {
  if (!_activeSuggestion) return;
  _activeSuggestion.moves.forEach(function (mv) {
    var entry = state.cards.get(mv.anchor_id);
    if (!entry) return;
    entry.el.style.transition = 'left 0.4s ease, top 0.4s ease';
    if (mv.x !== undefined) entry.x = mv.x;
    if (mv.y !== undefined) entry.y = mv.y;
    if (mv.rot   !== undefined) entry.rot   = mv.rot;
    if (mv.scale !== undefined) entry.scale = mv.scale;
    entry.localMoved = true;
    updateCardTransform(entry);
    setTimeout(function () { entry.el.style.transition = ''; }, 450);
  });
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'suggestion_accept', suggestion_id: _activeSuggestion.suggestion_id }));
  }
  dismissLayoutSuggestion();
  if (state.connections.size) renderConnections();
  scheduleSync();
}

function rejectLayoutSuggestion() {
  if (!_activeSuggestion) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'suggestion_reject', suggestion_id: _activeSuggestion.suggestion_id }));
  }
  dismissLayoutSuggestion();
}

// ─────────────────────────────────────────────────────────────────────
// Patch apply (incoming from agent via WS)
// ─────────────────────────────────────────────────────────────────────
function applyPatches(patches) {
  patches.forEach(function (p) {
    var entry = state.cards.get(p.anchor_id);

    if (!entry) {
      // New card from agent (canvas_create style)
      var tmp = document.createElement('div');
      tmp.innerHTML = p.html_fragment;
      var el = tmp.firstElementChild;
      if (!el) return;
      var x     = parseFloat(el.getAttribute('data-anc-x')     || '0');
      var y     = parseFloat(el.getAttribute('data-anc-y')     || '0');
      var w     = parseFloat(el.getAttribute('data-anc-w')     || '320');
      var h     = parseFloat(el.getAttribute('data-anc-h')     || '0');
      var rot   = parseFloat(el.getAttribute('data-anc-rot')   || '0');
      var scale = parseFloat(el.getAttribute('data-anc-scale') || '1');
      var z     = parseInt(  el.getAttribute('data-anc-z')     || '1', 10);
      var cardEntry = addCard(p.anchor_id, p.html_fragment, x, y, w, h, rot, scale, z);
      // Stamp episode_id + goal_id from HTML fragment attributes onto host element
      if (cardEntry) {
        var epId = el.getAttribute('data-episode-id') || p.episode_id || '';
        var goalId = el.getAttribute('data-goal-id') || p.goal_id || '';
        if (epId)   cardEntry.el.dataset.episodeId = epId;
        if (goalId) cardEntry.el.dataset.goalId    = goalId;
      }
      return;
    }

    // Existing card: update content, respect user's local position
    var tmp2 = document.createElement('div');
    tmp2.innerHTML = p.html_fragment;
    var newCard = tmp2.firstElementChild;
    if (!newCard) return;

    entry.contentEl.innerHTML = newCard.innerHTML;

    // Stamp episode_id on card host element (most recent episode wins)
    var epId2 = (newCard && newCard.getAttribute('data-episode-id')) || p.episode_id || '';
    var goalId2 = (newCard && newCard.getAttribute('data-goal-id')) || p.goal_id || '';
    if (epId2)   entry.el.dataset.episodeId = epId2;
    if (goalId2) entry.el.dataset.goalId    = goalId2;

    // Only update position if user hasn't moved this card locally
    if (!entry.localMoved && newCard.getAttribute('data-anc-x')) {
      entry.x     = parseFloat(newCard.getAttribute('data-anc-x'));
      entry.y     = parseFloat(newCard.getAttribute('data-anc-y'));
      entry.h     = parseFloat(newCard.getAttribute('data-anc-h')     || '0');
      entry.rot   = parseFloat(newCard.getAttribute('data-anc-rot')   || '0');
      entry.scale = parseFloat(newCard.getAttribute('data-anc-scale') || '1');
      updateCardTransform(entry);
    }
  });
  updateEmptyState();
  if (state.connections.size) renderConnections();
}

// Submit human feedback for the episode linked to a card
function submitCardFeedback(anchorId, signal, comment) {
  var entry = state.cards.get(anchorId);
  if (!entry || !entry.el.dataset.episodeId) return;
  fetch('http://localhost:3002/flywheel/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      episode_id: entry.el.dataset.episodeId,
      signal: signal || 'thumbs_up',
      comment: comment || ''
    })
  }).catch(function() {});
}

// ─────────────────────────────────────────────────────────────────────
// WebSocket
// ─────────────────────────────────────────────────────────────────────
function initWS() {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  try {
    ws = new WebSocket(proto + '//' + location.host);
  } catch (e) {
    setStatus('Error');
    return;
  }

  ws.onopen = function () {
    ws.send(JSON.stringify({ type: 'view', page: 'canvas' }));
    setStatus('Live', 'live');
  };

  ws.onclose = function () {
    setStatus('Reconnecting…');
    setTimeout(initWS, 3000);
  };

  ws.onmessage = function (evt) {
    var msg;
    try { msg = JSON.parse(evt.data); } catch (e) { return; }

    if (msg.type === 'html' || msg.type === 'msg') {
      var html = msg.html || msg.content || '';
      if (html) { renderFromHtml(html); setStatus('Live', 'live'); }

    } else if (msg.type === 'patch' && Array.isArray(msg.patches)) {
      applyPatches(msg.patches);

    } else if (msg.type === 'layout_suggest') {
      showLayoutSuggestion(msg);
      setStatus('建议重排…', 'thinking');

    } else if (msg.type === 'suggestion_accepted') {
      // Already applied locally; this echo from server is a no-op
    } else if (msg.type === 'suggestion_rejected') {
      // May arrive if another client rejected
      if (_activeSuggestion && _activeSuggestion.suggestion_id === msg.suggestion_id) {
        dismissLayoutSuggestion();
      }

    } else if (msg.type === 'agent_event') {
      handleAgentEvent((msg.event && msg.event.payload) || msg.event || msg);

    } else if (msg.type === 'event') {
      handleAgentEvent(msg);

    } else if (msg.type === 'error') {
      setStatus('Error: ' + (msg.message || msg.code || ''), null);
    }
  };

  ws.onerror = function () { setStatus('Error'); };
}

function handleAgentEvent(msg) {
  var t = msg.event_type || msg.type;
  if (t === 'thinking') {
    setStatus((msg.payload && msg.payload.summary) || 'Thinking…', 'thinking');
  } else if (t === 'complete') {
    setStatus('Done', 'live');
  } else if (t === 'error') {
    setStatus('Error');
  }
}

// ─────────────────────────────────────────────────────────────────────
// Prompt UI
// ─────────────────────────────────────────────────────────────────────
function initPromptUI() {
  var btn = document.getElementById('canvas-prompt-send');
  btn.addEventListener('click', handleSend);
  promptInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });
}

function handleSend() {
  var instruction = (promptInput.value || '').trim();
  if (!instruction) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) { setStatus('Not connected'); return; }
  promptInput.value = '';
  var op = state.cards.size > 0 ? 'refine' : 'initial_render';
  sendEnvelope(instruction, op);
  setStatus('Sending…');
}

function sendEnvelope(instruction, op) {
  var sessionId = localStorage.getItem('canvas-session-id');
  if (!sessionId) {
    sessionId = 'canvas-' + Date.now().toString(36);
    localStorage.setItem('canvas-session-id', sessionId);
  }

  var selectedIds = Array.from(state.selected);
  var isGroup = selectedIds.length > 0;

  var envelope = {
    schema_version: '1.0',
    intent: {
      op: op || 'initial_render',
      target_kind: isGroup ? 'group' : 'global',
      target_refs: isGroup ? selectedIds : undefined,
      instruction: instruction
    },
    selection: null,
    context_bundle: {
      memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
      scope_hint: null, transient_override: null,
      subagent_id: null,
      context_mode: 'canvas',
      file_id: null,
      card_anchor_ids: selectedIds
    },
    render_state: {
      anchor_tree: [], anchor_index: {}, dom_signature: '',
      relevant_subtree: {
        target_ref: 'canvas-root',
        target_html: serializeCanvasHtml(),
        forward_deps: {}, reverse_deps: {}
      },
      selected_subtrees: buildSelectedSubtrees(),
      viewport: { x: state.viewport.x, y: state.viewport.y, zoom: state.viewport.zoom }
    },
    domain: null,
    provenance: {
      session_id: sessionId,
      event_id: 'evt-' + Date.now().toString(36),
      parent_event_id: null,
      timestamp: new Date().toISOString(),
      client_version: '0.1.0-canvas'
    }
  };

  ws.send(JSON.stringify({ type: 'envelope', envelope: envelope }));
  captureCanvasIntent(instruction, envelope);
}

function captureCanvasIntent(instruction, envelope) {
  if (!instruction || !instruction.trim()) return;
  var intent = envelope.intent || {};
  var selectedIds = intent.target_refs || [];
  var selected = envelope.render_state && envelope.render_state.selected_subtrees || {};
  var targetId = selectedIds.length ? selectedIds.join(',') : 'canvas-root';
  var previewHtml = '';
  if (selectedIds.length) {
    previewHtml = selectedIds.map(function (id) {
      return selected[id] && selected[id].target_html || '';
    }).join('\n');
  } else {
    var rs = envelope.render_state && envelope.render_state.relevant_subtree;
    previewHtml = rs && rs.target_html || '';
  }
  fetch('http://localhost:3002/intent/capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      input_type: 'query',
      raw_input: instruction.trim(),
      extra_context: 'canvas target:' + targetId,
      session_id: envelope.provenance && envelope.provenance.session_id || '',
      anchor_op: intent.op || '',
      anchor_id: targetId,
      anchor_kind: intent.target_kind || '',
      anchor_content: stripHtmlPreview(previewHtml)
    })
  }).catch(function() {});
}

function stripHtmlPreview(html) {
  if (!html) return '';
  var tmp = document.createElement('div');
  tmp.innerHTML = html;
  return (tmp.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 2000);
}

function buildSelectedSubtrees() {
  var out = {};
  state.selected.forEach(function (id) {
    var entry = state.cards.get(id);
    if (entry && entry.contentEl) {
      out[id] = { target_html: entry.contentEl.outerHTML };
    }
  });
  return out;
}

// ─────────────────────────────────────────────────────────────────────
// Persistence
// ─────────────────────────────────────────────────────────────────────
function serializeConnections() {
  var arr = [];
  state.connections.forEach(function (c) { arr.push({ id: c.id, fromId: c.fromId, toId: c.toId }); });
  try { localStorage.setItem('canvas-connections', JSON.stringify(arr)); } catch (e) {}
}

function restoreConnections() {
  try {
    var raw = localStorage.getItem('canvas-connections');
    if (!raw) return;
    var arr = JSON.parse(raw);
    arr.forEach(function (c) { state.connections.set(c.id, c); });
    if (state.connections.size) renderConnections();
  } catch (e) {}
}

function serializeCanvasHtml() {
  var html = '<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:' + CANVAS_W + 'px;height:' + CANVAS_H + 'px;">';
  state.cards.forEach(function (entry) {
    if (entry.contentEl) {
      // Ensure data-anc-* are current before serializing
      entry.contentEl.setAttribute('data-anc-x',     entry.x);
      entry.contentEl.setAttribute('data-anc-y',     entry.y);
      entry.contentEl.setAttribute('data-anc-w',     entry.w);
      entry.contentEl.setAttribute('data-anc-rot',   entry.rot);
      entry.contentEl.setAttribute('data-anc-scale', entry.scale);
      entry.contentEl.setAttribute('data-anc-z',     entry.z);
      if (entry.h > 0) entry.contentEl.setAttribute('data-anc-h', entry.h);
      else entry.contentEl.removeAttribute('data-anc-h');
      html += entry.contentEl.outerHTML;
    }
  });
  html += '</div>';
  return html;
}

function scheduleSync() {
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(function () { saveToServer(); serializeConnections(); }, 600);
}

function saveToServer() {
  var html = serializeCanvasHtml();
  fetch('/canvas-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      html: html,
      viewport: { x: state.viewport.x, y: state.viewport.y, zoom: state.viewport.zoom },
      selection: Array.from(state.selected),
    })
  }).catch(function () {});
}

function loadSavedCanvas() {
  fetch('/current-canvas')
    .then(function (r) { return r.ok ? r.text() : ''; })
    .then(function (html) {
      if (html && html.trim()) renderFromHtml(html);
      restoreConnections();
    })
    .catch(function () {});
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────
// Direct card editing (double-click)
// ─────────────────────────────────────────────────────────────────────
function enterEditMode(id) {
  if (_editingId === id) return;
  if (_editingId) exitEditMode();

  var entry = state.cards.get(id);
  if (!entry || !entry.contentEl) return;

  pushUndo();
  _editingId = id;
  entry.el.classList.add('canvas-editing');
  entry.el.classList.remove('canvas-selected');
  clearSelection();

  var els = entry.contentEl.querySelectorAll(EDITABLE_SEL);
  var first;
  if (els.length > 0) {
    els.forEach(function (el) {
      el.setAttribute('contenteditable', 'true');
      el.setAttribute('spellcheck', 'false');
    });
    first = els[0];
  } else {
    // Fallback: make the card container itself editable
    entry.contentEl.setAttribute('contenteditable', 'true');
    entry.contentEl.setAttribute('spellcheck', 'false');
    first = entry.contentEl;
  }

  // Focus + move cursor to end of first editable element
  if (first) {
    first.focus();
    try {
      var range = document.createRange();
      range.selectNodeContents(first);
      range.collapse(false);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (e) {}
  }
}

function exitEditMode() {
  if (!_editingId) return;
  var entry = state.cards.get(_editingId);
  _editingId = null;
  if (!entry) return;

  entry.el.classList.remove('canvas-editing');
  entry.contentEl.querySelectorAll('[contenteditable]').forEach(function (el) {
    el.removeAttribute('contenteditable');
    el.removeAttribute('spellcheck');
  });
  // Also clean up container-level fallback editable
  if (entry.contentEl.hasAttribute('contenteditable')) {
    entry.contentEl.removeAttribute('contenteditable');
    entry.contentEl.removeAttribute('spellcheck');
  }
  // Sync data-anc-* attrs and save
  updateCardTransform(entry);
  scheduleSync();
}

// ─────────────────────────────────────────────────────────────────────
// Snap-to-grid
// ─────────────────────────────────────────────────────────────────────
function snap(v) {
  var s = Math.round(v / SNAP_GRID) * SNAP_GRID;
  return Math.abs(v - s) < SNAP_THR ? s : v;
}

function toggleSnap() {
  _snapEnabled = !_snapEnabled;
  if (snapBtnEl) snapBtnEl.classList.toggle('active', _snapEnabled);
}

// ─────────────────────────────────────────────────────────────────────
// Undo / redo
// ─────────────────────────────────────────────────────────────────────
function snapshotCards() {
  var snap = [];
  state.cards.forEach(function (entry, id) {
    snap.push({
      id: id,
      html: entry.contentEl ? entry.contentEl.outerHTML : '',
      x: entry.x, y: entry.y, w: entry.w, h: entry.h,
      rot: entry.rot, scale: entry.scale, z: entry.z,
    });
  });
  return snap;
}

function pushUndo() {
  _undoStack.push(snapshotCards());
  if (_undoStack.length > 30) _undoStack.shift();
  _redoStack = [];
}

function restoreSnapshot(snap) {
  clearSelection();
  var snapIds = new Set(snap.map(function (s) { return s.id; }));
  // Remove cards not in snapshot
  state.cards.forEach(function (entry, id) {
    if (!snapIds.has(id)) { entry.el.remove(); state.cards.delete(id); }
  });
  snap.forEach(function (s) {
    if (state.cards.has(s.id)) {
      var entry = state.cards.get(s.id);
      // Replace content element
      var tmp = document.createElement('div');
      tmp.innerHTML = s.html;
      var newContent = tmp.firstElementChild || tmp;
      entry.el.replaceChild(newContent, entry.contentEl);
      entry.contentEl = newContent;
      entry.x = s.x; entry.y = s.y; entry.w = s.w; entry.h = s.h;
      entry.rot = s.rot; entry.scale = s.scale; entry.z = s.z;
      entry.localMoved = true;
      updateCardTransform(entry);
    } else {
      addCard(s.id, s.html, s.x, s.y, s.w, s.h, s.rot, s.scale, s.z);
    }
  });
  updateEmptyState();
  if (state.connections.size) renderConnections();
}

function undo() {
  if (_undoStack.length === 0) return;
  _redoStack.push(snapshotCards());
  restoreSnapshot(_undoStack.pop());
  scheduleSync();
  setStatus('Undo');
}

function redo() {
  if (_redoStack.length === 0) return;
  _undoStack.push(snapshotCards());
  restoreSnapshot(_redoStack.pop());
  scheduleSync();
  setStatus('Redo');
}

// ─────────────────────────────────────────────────────────────────────
// Duplicate (Ctrl+D)
// ─────────────────────────────────────────────────────────────────────
function duplicateSelected() {
  if (state.selected.size === 0) return;
  pushUndo();
  var newIds = [];
  state.selected.forEach(function (id) {
    var entry = state.cards.get(id);
    if (!entry || !entry.contentEl) return;
    var newId = id.replace(/-copy-[a-z0-9]+$/, '') + '-copy-' + Date.now().toString(36);
    var tmp = document.createElement('div');
    tmp.innerHTML = entry.contentEl.outerHTML;
    var el = tmp.firstElementChild;
    if (el) el.setAttribute('data-anc', newId);
    addCard(newId, tmp.innerHTML, entry.x + 24, entry.y + 24, entry.w, entry.h, entry.rot, entry.scale, entry.z + 1);
    newIds.push(newId);
  });
  clearSelection();
  newIds.forEach(function (id) { selectCard(id); });
  scheduleSync();
}

// ─────────────────────────────────────────────────────────────────────
// Connector arrows (SVG overlay)
// ─────────────────────────────────────────────────────────────────────
function toggleConnectMode() {
  _connectMode = !_connectMode;
  _connectFrom = null;
  document.body.classList.toggle('canvas-connect-mode', _connectMode);
  if (connectBtnEl) connectBtnEl.classList.toggle('active', _connectMode);
  // Clear pending-source highlight
  stage.querySelectorAll('.canvas-connect-src').forEach(function (el) {
    el.classList.remove('canvas-connect-src');
  });
}

function handleConnectClick(id) {
  if (_connectFrom === null) {
    _connectFrom = id;
    var entry = state.cards.get(id);
    if (entry) entry.el.classList.add('canvas-connect-src');
  } else if (_connectFrom === id) {
    // Cancel
    var e = state.cards.get(id);
    if (e) e.el.classList.remove('canvas-connect-src');
    _connectFrom = null;
  } else {
    // Complete connection
    var fromEntry = state.cards.get(_connectFrom);
    if (fromEntry) fromEntry.el.classList.remove('canvas-connect-src');
    var connId = 'conn-' + Date.now().toString(36);
    state.connections.set(connId, { id: connId, fromId: _connectFrom, toId: id });
    _connectFrom = null;
    renderConnections();
    serializeConnections();
    // Stay in connect mode so user can add more connections
  }
}

function _cardCenter(entry) {
  var h = entry.h > 0 ? entry.h : (entry.el ? entry.el.offsetHeight : 200);
  return { x: entry.x + entry.w / 2, y: entry.y + h / 2 };
}

function renderConnections() {
  var svg = document.getElementById('canvas-connectors');
  if (!svg) return;
  // Remove old groups (keep <defs>)
  Array.from(svg.querySelectorAll('g')).forEach(function (g) { g.remove(); });

  state.connections.forEach(function (conn) {
    var fe = state.cards.get(conn.fromId);
    var te = state.cards.get(conn.toId);
    if (!fe || !te) return;
    var f = _cardCenter(fe);
    var t = _cardCenter(te);
    var dx = t.x - f.x;
    var d = 'M ' + f.x + ' ' + f.y +
            ' C ' + (f.x + dx * 0.4) + ' ' + f.y +
            ' '  + (t.x - dx * 0.4) + ' ' + t.y +
            ' '  + t.x + ' ' + t.y;

    var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('data-conn', conn.id);
    g.style.cursor = 'pointer';

    // Wide invisible hit area
    var hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    hit.setAttribute('d', d);
    hit.setAttribute('stroke', 'transparent');
    hit.setAttribute('stroke-width', '14');
    hit.setAttribute('fill', 'none');
    hit.style.pointerEvents = 'stroke';

    // Visible line
    var vis = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    vis.setAttribute('d', d);
    vis.setAttribute('stroke', '#7A5AF8');
    vis.setAttribute('stroke-width', '2');
    vis.setAttribute('stroke-opacity', '0.55');
    vis.setAttribute('fill', 'none');
    vis.setAttribute('marker-end', 'url(#canvas-arrow)');
    vis.style.pointerEvents = 'none';

    g.appendChild(hit);
    g.appendChild(vis);
    // Double-click to delete connection
    g.addEventListener('dblclick', function (e) {
      e.stopPropagation();
      state.connections.delete(conn.id);
      renderConnections();
      serializeConnections();
    });
    // Hover feedback on visible path
    g.addEventListener('mouseenter', function () { vis.setAttribute('stroke-opacity', '0.9'); vis.setAttribute('stroke-width', '3'); });
    g.addEventListener('mouseleave', function () { vis.setAttribute('stroke-opacity', '0.55'); vis.setAttribute('stroke-width', '2'); });

    svg.appendChild(g);
  });
}

// ─────────────────────────────────────────────────────────────────────
// Export PNG
// ─────────────────────────────────────────────────────────────────────
function exportPNG() {
  if (!window.html2canvas) { setStatus('导出库加载中，请稍后重试'); return; }
  if (state.cards.size === 0) { setStatus('画布为空'); return; }

  var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  state.cards.forEach(function (entry) {
    var h = entry.h > 0 ? entry.h : (entry.el ? entry.el.offsetHeight : 300);
    minX = Math.min(minX, entry.x);
    minY = Math.min(minY, entry.y);
    maxX = Math.max(maxX, entry.x + entry.w);
    maxY = Math.max(maxY, entry.y + h);
  });

  var pad = 48;
  var cx = Math.max(0, minX - pad);
  var cy = Math.max(0, minY - pad);
  var cw = Math.min(maxX - minX + pad * 2, CANVAS_W);
  var ch = Math.min(maxY - minY + pad * 2, CANVAS_H);

  // Reset viewport so stage is at (0,0) scale(1) before capture
  var svx = state.viewport.x, svy = state.viewport.y, svz = state.viewport.zoom;
  state.viewport.x = 0; state.viewport.y = 0; state.viewport.zoom = 1;
  applyViewportTransform();

  setStatus('导出中…', 'thinking');

  setTimeout(function () {
    window.html2canvas(stage, {
      x: cx, y: cy, width: cw, height: ch,
      scale: 2,
      useCORS: true,
      backgroundColor: '#f8f7f4',
      logging: false,
      ignoreElements: function (el) {
        var id = el.id || '';
        return id === 'canvas-suggestion-bar' || id === 'canvas-toolbar' ||
               id === 'canvas-prompt-bar'     || id === 'canvas-marquee';
      },
    }).then(function (canvas) {
      state.viewport.x = svx; state.viewport.y = svy; state.viewport.zoom = svz;
      applyViewportTransform();
      var a = document.createElement('a');
      a.download = 'canvas-' + new Date().toISOString().slice(0, 10) + '.png';
      a.href = canvas.toDataURL('image/png');
      a.click();
      setStatus('已导出', 'live');
    }).catch(function () {
      state.viewport.x = svx; state.viewport.y = svy; state.viewport.zoom = svz;
      applyViewportTransform();
      setStatus('导出失败');
    });
  }, 60);
}

function updateEmptyState() {
  if (!emptyEl) return;
  if (state.cards.size > 0) {
    emptyEl.classList.add('hidden');
  } else {
    emptyEl.classList.remove('hidden');
  }
}

function updateSelectionUI() {
  var n = state.selected.size;
  if (selBadgeEl) {
    if (n > 0) {
      selBadgeEl.textContent = n + ' 卡片已选中';
      selBadgeEl.classList.add('visible');
    } else {
      selBadgeEl.classList.remove('visible');
    }
  }
  if (promptInput) {
    promptInput.placeholder = n > 0
      ? '对选中的 ' + n + ' 张卡片发出指令…'
      : '描述你想在画布上生成的内容…';
  }
}

function setStatus(text, kind) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.className = 'canvas-status' + (kind ? ' canvas-status--' + kind : '');
}

})();
