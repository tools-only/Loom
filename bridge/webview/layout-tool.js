/**
 * Layout Tool — drag-to-move, 8-dir resize, delete, smart auto-arrange.
 *
 * Hover any element → grab cursor + resize handles appear.
 * Hold left-click & move > 6px → break out of flow, drag.
 * Click → select element (blue outline). Shift+click → multi-select.
 * Delete / Backspace → remove selected elements.
 * Escape → cancel drag or deselect.
 * G → toggle snap-to-grid (40px).
 */
window.LayoutTool = {
  anchor: null,
  _snapEnabled: true,
  _snapGrid: 40,
  _snapThreshold: 8,
  _dragThreshold: 6,
  _minW: 160,
  _minH: 48,

  _drag: null,
  _pending: null,
  _zCounter: 100,
  _handleContainer: null,
  _handleTarget: null,
  _selected: new Set(),

  /* ── Lifecycle ────────────────────────── */

  init(anchor) {
    this.anchor = anchor;
    var c = document.getElementById('anchor-content');
    if (c) { c.style.position = 'relative'; c.classList.add('layout-canvas'); }
    this._ensureHandles();
    this._createSnapIndicator();
    this._wireEvents();
  },

  _ensureHandles() {
    if (document.getElementById('layout-resize-handles')) return;
    var hc = document.createElement('div');
    hc.id = 'layout-resize-handles';
    var dirs = ['nw','n','ne','e','se','s','sw','w'];
    var self = this;
    dirs.forEach(function (d) {
      var h = document.createElement('div');
      h.className = 'layout-rsz layout-rsz-' + d;
      h.addEventListener('mousedown', function (e) {
        e.stopPropagation(); e.preventDefault();
        self._beginResize(e, d);
      });
      hc.appendChild(h);
    });
    document.body.appendChild(hc);
    this._handleContainer = hc;
  },

  _createSnapIndicator() {
    if (document.getElementById('layout-snap-indicator')) return;
    var el = document.createElement('div');
    el.id = 'layout-snap-indicator';
    document.body.appendChild(el);
  },

  /* ── Element helpers ──────────────────── */

  _elId(el) {
    var anc = el.getAttribute && el.getAttribute('data-anc');
    if (anc) return anc;
    var c = document.getElementById('anchor-content'), parts = [], cur = el;
    while (cur && cur !== c) {
      var a = cur.getAttribute && cur.getAttribute('data-anc');
      if (a) { parts.unshift(a); break; }
      var t = cur.tagName.toLowerCase(), n = 1, p = cur.previousElementSibling;
      while (p) { if (p.tagName === cur.tagName) n++; p = p.previousElementSibling; }
      parts.unshift(t + ':nth-of-type(' + n + ')');
      cur = cur.parentElement;
    }
    return 'el:' + parts.join('>');
  },

  _findById(id) {
    var c = document.getElementById('anchor-content'); if (!c) return null;
    var el = c.querySelector('[data-anc="' + id + '"]'); if (el) return el;
    if (id.indexOf('el:') !== 0) return null;
    try {
      var parts = id.slice(3).split('>'), cur = c;
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (part.indexOf(':nth-of-type(') === -1) {
          var s = cur.querySelector('[data-anc="' + part + '"]');
          if (s) { cur = s; continue; }
        }
        var m = part.match(/^(\w+):nth-of-type\((\d+)\)$/);
        if (!m) return null;
        var tag = m[1], n = parseInt(m[2],10), kids = cur.children, cnt = 0;
        for (var j = 0; j < kids.length; j++) {
          if (kids[j].tagName.toLowerCase() === tag) { cnt++; if (cnt === n) { cur = kids[j]; break; } }
        }
        if (cnt < n) return null;
      }
      return cur !== c ? cur : null;
    } catch (_) { return null; }
  },

  _isDraggable(el) {
    if (!el || el === document.getElementById('anchor-content')) return false;
    if (el.closest('.anc-handle, .anc-handle-popup, #brush-dialog, #anchor-floating-toolbar, #layout-resize-handles, a, button, input, textarea, select')) return false;
    if (['BUTTON','INPUT','TEXTAREA','SELECT'].indexOf(el.tagName) >= 0) return false;
    if (el.offsetParent === null || el.offsetWidth === 0 || el.offsetHeight === 0) return false;
    return true;
  },

  /* ── Selection ────────────────────────── */

  _select(el, add) {
    if (!add) this._deselectAll();
    this._selected.add(el);
    el.classList.add('layout-selected');
    this._showHandles(el);
  },

  _deselectAll() {
    var self = this;
    this._selected.forEach(function (e) { e.classList.remove('layout-selected'); });
    this._selected.clear();
    this._hideHandles();
  },

  /* ── Handles ──────────────────────────── */

  _showHandles(el) {
    if (!this._handleContainer) return;
    this._handleTarget = el;
    var r = el.getBoundingClientRect();
    var hc = this._handleContainer;
    hc.style.display = 'block';
    hc.style.top = r.top + 'px'; hc.style.left = r.left + 'px';
    hc.style.width = r.width + 'px'; hc.style.height = r.height + 'px';
    var w = r.width, h = r.height, s = 5; // half handle size
    var dirs = {
      nw:[ -s, -s ], n:[ w/2 - s, -s ], ne:[ w - s, -s ],
      e:[ w - s, h/2 - s ], se:[ w - s, h - s ],
      s:[ w/2 - s, h - s ], sw:[ -s, h - s ], w:[ -s, h/2 - s ]
    };
    var self = this;
    Object.keys(dirs).forEach(function (d) {
      var hd = hc.querySelector('.layout-rsz-' + d);
      if (hd) { hd.style.left = dirs[d][0] + 'px'; hd.style.top = dirs[d][1] + 'px'; }
    });
  },

  _hideHandles() {
    if (this._handleContainer) this._handleContainer.style.display = 'none';
  },

  /* ── Events ───────────────────────────── */

  _wireEvents() {
    var self = this, stage = document.getElementById('anchor-content');
    if (!stage) return;

    // Hover → show handles + grab cursor
    stage.addEventListener('mousemove', function (e) {
      if (self._drag) return;
      if (document.body.classList.contains('brush-mode')) return;
      // Find the deepest draggable element under the cursor
      var el = document.elementFromPoint(e.clientX, e.clientY);
      while (el && el !== stage && !self._isDraggable(el)) el = el.parentElement;
      if (el && el !== stage && self._isDraggable(el)) {
        if (self._handleTarget !== el) self._showHandles(el);
        // Update cursor
        stage.style.cursor = 'grab';
      } else {
        if (!self._selected.size) self._hideHandles();
        self._handleTarget = null;
        stage.style.cursor = '';
      }
    });

    // mousedown → selection or start potential drag
    stage.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      if (document.body.classList.contains('brush-mode')) return;
      if (e.target.closest('#layout-resize-handles')) return;

      var target = e.target;
      while (target && target !== stage && !self._isDraggable(target)) target = target.parentElement;
      if (!target || target === stage || !self._isDraggable(target)) {
        // Clicked empty space → deselect
        if (!e.target.closest('.anc-handle, .anc-handle-popup, a, button, input, textarea, select')) {
          self._deselectAll();
        }
        return;
      }

      // Record as potential drag
      self._pending = { el: target, id: self._elId(target), clientX0: e.clientX, clientY0: e.clientY };
    });

    // document mousemove → drag update
    document.addEventListener('mousemove', function (e) {
      if (self._drag) {
        if (self._drag.type === 'resize') { self._updateResize(e); return; }
        var dx = e.clientX - self._drag.clientX0, dy = e.clientY - self._drag.clientY0;
        self._drag.el.style.left = self._snap(self._drag.x0 + dx) + 'px';
        self._drag.el.style.top  = self._snap(self._drag.y0 + dy) + 'px';
        if (self._drag.el === self._handleTarget) self._showHandles(self._drag.el);
        return;
      }
      if (!self._pending) return;
      var dx = e.clientX - self._pending.clientX0, dy = e.clientY - self._pending.clientY0;
      if (Math.abs(dx) >= self._dragThreshold || Math.abs(dy) >= self._dragThreshold) {
        self._beginDrag(self._pending.el, self._pending.id, self._pending.clientX0, self._pending.clientY0);
        self._pending = null;
      }
    });

    // mouseup — drop or select
    document.addEventListener('mouseup', function (e) {
      if (self._drag) {
        if (self._drag.type === 'move') self._endDrag(false);
        else self._endResize(false);
        return;
      }
      if (self._pending) {
        // Was a click (not a drag). Select the element.
        self._select(self._pending.el, e ? e.shiftKey : false);
        self._pending = null;
      }
    });

    // Keyboard
    document.addEventListener('keydown', function (e) {
      var tag = document.activeElement && document.activeElement.tagName;
      var inInput = (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT');

      if (e.key === 'Escape') {
        if (self._drag) { self._endDrag(true); return; }
        if (self._selected.size) { self._deselectAll(); return; }
      }

      if ((e.key === 'Delete' || e.key === 'Backspace') && !inInput) {
        if (self._selected.size) {
          self._deleteSelected();
          e.preventDefault();
        }
      }

      if (e.key === 'g' && !e.ctrlKey && !e.metaKey && !e.altKey && !inInput) {
        self._snapEnabled = !self._snapEnabled;
        self._flashSnapIndicator(self._snapEnabled ? 'Snap: ON' : 'Snap: OFF');
      }
    });
  },

  /* ── Drag ─────────────────────────────── */

  _beginDrag(target, elId, clientX, clientY) {
    if (this._drag) { this._endDrag(true); this._endResize(true); }
    var c = document.getElementById('anchor-content');
    var cr = c.getBoundingClientRect();
    var er = target.getBoundingClientRect();
    var x0 = er.left - cr.left + c.scrollLeft;
    var y0 = er.top - cr.top + c.scrollTop;

    var orig = { pos: target.style.position, l: target.style.left, t: target.style.top,
      w: target.style.width, h: target.style.height, z: target.style.zIndex,
      xf: target.style.transform, m: target.style.margin };

    target.style.position = 'absolute';
    target.style.left = x0 + 'px'; target.style.top = y0 + 'px';
    target.style.width = er.width + 'px'; target.style.height = er.height + 'px';
    target.style.zIndex = ++this._zCounter; target.style.margin = '0';
    target.classList.add('anc-dragging', 'anc-user-positioned');
    document.body.classList.add('layout-dragging');

    this._drag = { type: 'move', id: elId, el: target, x0: x0, y0: y0, clientX0: clientX, clientY0: clientY, orig: orig };
  },

  _endDrag(cancel) {
    if (!this._drag || this._drag.type !== 'move') return;
    var d = this._drag;
    d.el.classList.remove('anc-dragging');
    document.body.classList.remove('layout-dragging');

    if (cancel) {
      d.el.style.position = d.orig.pos; d.el.style.left = d.orig.l; d.el.style.top = d.orig.t;
      d.el.style.width = d.orig.w; d.el.style.height = d.orig.h;
      d.el.style.zIndex = d.orig.z; d.el.style.transform = d.orig.xf; d.el.style.margin = d.orig.m;
      d.el.classList.remove('anc-user-positioned');
      ['data-anc-x','data-anc-y','data-anc-w','data-anc-h'].forEach(function (a) { d.el.removeAttribute(a); });
    } else {
      this._autoArrange(d);
    }
    this._drag = null;
  },

  /* ── Resize ───────────────────────────── */

  _beginResize(e, dir) {
    var el = this._handleTarget; if (!el) return;
    var c = document.getElementById('anchor-content');
    var cr = c.getBoundingClientRect(), er = el.getBoundingClientRect();
    var x0 = er.left - cr.left + c.scrollLeft, y0 = er.top - cr.top + c.scrollTop;

    if (el.style.position !== 'absolute') {
      el.style.position = 'absolute';
      el.style.left = x0 + 'px'; el.style.top = y0 + 'px';
      el.style.width = er.width + 'px'; el.style.height = er.height + 'px';
      el.style.zIndex = ++this._zCounter; el.style.margin = '0';
      el.classList.add('anc-user-positioned');
    }
    el.classList.add('anc-dragging');
    document.body.classList.add('layout-dragging');

    this._drag = { type: 'resize', id: this._elId(el), el: el, dir: dir,
      clientX0: e.clientX, clientY0: e.clientY,
      x0: parseFloat(el.style.left), y0: parseFloat(el.style.top),
      w0: parseFloat(el.style.width), h0: parseFloat(el.style.height) };
  },

  _updateResize(e) {
    var d = this._drag, dir = d.dir, dx = e.clientX - d.clientX0, dy = e.clientY - d.clientY0;
    var nw = d.w0, nh = d.h0, nx = d.x0, ny = d.y0;
    if (dir.indexOf('e') >= 0) nw = Math.max(this._minW, d.w0 + dx);
    if (dir.indexOf('w') >= 0) { var tw = Math.max(this._minW, d.w0 - dx); nx = d.x0 + (d.w0 - tw); nw = tw; }
    if (dir.indexOf('s') >= 0) nh = Math.max(this._minH, d.h0 + dy);
    if (dir.indexOf('n') >= 0) { var th = Math.max(this._minH, d.h0 - dy); ny = d.y0 + (d.h0 - th); nh = th; }
    d.el.style.left = this._snap(nx) + 'px'; d.el.style.top = this._snap(ny) + 'px';
    d.el.style.width = Math.round(nw) + 'px'; d.el.style.height = Math.round(nh) + 'px';
    this._showHandles(d.el);
  },

  _endResize(cancel) {
    if (!this._drag || this._drag.type !== 'resize') return;
    var d = this._drag;
    d.el.classList.remove('anc-dragging');
    document.body.classList.remove('layout-dragging');
    if (cancel) {
      d.el.style.position = ''; d.el.style.left = ''; d.el.style.top = '';
      d.el.style.width = ''; d.el.style.height = ''; d.el.style.zIndex = '';
      d.el.classList.remove('anc-user-positioned');
    } else {
      d.el.setAttribute('data-anc-x', Math.round(parseFloat(d.el.style.left)));
      d.el.setAttribute('data-anc-y', Math.round(parseFloat(d.el.style.top)));
      d.el.setAttribute('data-anc-w', Math.round(parseFloat(d.el.style.width)));
      d.el.setAttribute('data-anc-h', Math.round(parseFloat(d.el.style.height)));
    }
    this._drag = null;
  },

  /* ── Auto-arrange ─────────────────────── */

  _autoArrange(d) {
    var el = d.el, c = document.getElementById('anchor-content');
    var cw = c.clientWidth;
    var curX = parseFloat(el.style.left) || 0, curY = parseFloat(el.style.top) || 0;
    var curW = parseFloat(el.style.width) || cw, curH = parseFloat(el.style.height) || 120;

    // Snap x to grid
    var x = this._snap(curX);
    var y = this._snap(curY);

    // Clamp x within container
    x = Math.max(0, Math.min(x, cw - this._minW));

    // Align x to container edges if close
    if (x <= this._snapGrid) x = 0;
    if (Math.abs(x + curW - cw) <= this._snapGrid) x = cw - curW;

    // Align x to nearby positioned siblings
    var alignThresh = 24;
    var gap = 12;
    var siblings = [].slice.call(c.querySelectorAll('.anc-user-positioned')).filter(function (s) { return s !== el; });

    // Build per-x-group: find the best-fit column
    var groups = {};
    siblings.forEach(function (s) {
      var sx = parseFloat(s.style.left) || 0;
      var sw = parseFloat(s.style.width) || cw;
      // Group by left-edge proximity
      var matched = false;
      Object.keys(groups).forEach(function (gx) {
        if (Math.abs(sx - parseFloat(gx)) < alignThresh) { groups[gx].push(s); matched = true; }
      });
      if (!matched) groups[sx] = [s];
    });

    // Try to match our x to an existing group
    var matchedGroup = null;
    Object.keys(groups).forEach(function (gx) {
      if (Math.abs(curX - parseFloat(gx)) < alignThresh) matchedGroup = groups[gx];
    });
    if (matchedGroup) {
      x = parseFloat(matchedGroup[0].style.left);
      // Align width too
      var gw = parseFloat(matchedGroup[0].style.width) || curW;
      if (Math.abs(curW - gw) < alignThresh) {
        el.style.width = gw + 'px';
        el.setAttribute('data-anc-w', Math.round(gw));
        curW = gw;
      }
      // Stack below the last element in this group
      var maxBot = 0;
      matchedGroup.forEach(function (s) {
        var sy = parseFloat(s.style.top) || 0;
        var sh = parseFloat(s.style.height) || 120;
        maxBot = Math.max(maxBot, sy + sh);
      });
      y = maxBot + gap;
    }

    el.style.left = (x = this._snap(x)) + 'px';
    el.style.top  = (y = this._snap(y)) + 'px';
    el.setAttribute('data-anc-x', x);
    el.setAttribute('data-anc-y', y);

    // Collision: push overlapping elements down
    var changed = true, pushed = new Set([el]);
    while (changed) {
      changed = false;
      siblings.forEach(function (s) {
        if (pushed.has(s)) return;
        var sx = parseFloat(s.style.left) || 0, sy = parseFloat(s.style.top) || 0;
        var sw = parseFloat(s.style.width) || cw, sh = parseFloat(s.style.height) || 120;
        // H-overlap?
        if (x + curW <= sx + 4 || sx + sw <= x + 4) return;
        // V-overlap?
        if (y + curH <= sy + 4 || sy + sh <= y + 4) return;
        // Push down
        var ny2 = y + curH + gap;
        s.style.top = ny2 + 'px';
        s.setAttribute('data-anc-y', ny2);
        pushed.add(s);
        changed = true;
      });
    }
  },

  /* ── Delete ───────────────────────────── */

  _deleteSelected() {
    var self = this, container = document.getElementById('anchor-content');
    if (!container) return;
    this._selected.forEach(function (el) { el.remove(); });
    var count = this._selected.size;
    this._selected.clear();
    this._hideHandles();
    if (this.anchor && count > 0) {
      this.anchor.currentHtml = container.innerHTML;
      if (window.WorkspacePanel) WorkspacePanel.persistCurrentHtml(container.innerHTML);
      this.anchor.infoEl.textContent = this.anchor.countAnchors() + ' anchors';
    }
  },

  deleteElements(targets) {
    if (!targets || targets.length === 0) return;
    var container = document.getElementById('anchor-content'), self = this, removed = 0;
    targets.forEach(function (t) {
      var el = self._findById(t.anchor_id || t);
      if (el) { self._selected.delete(el); el.remove(); removed++; }
    });
    this._hideHandles();
    if (this.anchor && removed > 0) {
      this.anchor.currentHtml = container.innerHTML;
      if (window.WorkspacePanel) WorkspacePanel.persistCurrentHtml(container.innerHTML);
      this.anchor.infoEl.textContent = this.anchor.countAnchors() + ' anchors';
    }
  },

  /* ── Position persistence ─────────────── */

  savePositions() {
    var map = new Map(), c = document.getElementById('anchor-content'), self = this;
    if (!c) return map;
    c.querySelectorAll('[data-anc-x][data-anc-y]').forEach(function (el) {
      var id = self._elId(el), x = parseInt(el.getAttribute('data-anc-x'),10), y = parseInt(el.getAttribute('data-anc-y'),10);
      var w = parseInt(el.getAttribute('data-anc-w'),10), h = parseInt(el.getAttribute('data-anc-h'),10);
      if (id && !isNaN(x) && !isNaN(y)) map.set(id, { x:x, y:y, w:isNaN(w)?null:w, h:isNaN(h)?null:h });
    });
    return map;
  },

  restorePositions(savedMap) {
    if (!savedMap || savedMap.size === 0) return;
    var c = document.getElementById('anchor-content'), self = this;
    savedMap.forEach(function (pos, id) {
      var el = self._findById(id); if (!el) return;
      var ew = pos.w || el.getBoundingClientRect().width, eh = pos.h || el.getBoundingClientRect().height;
      el.style.position = 'absolute'; el.style.left = pos.x + 'px'; el.style.top = pos.y + 'px';
      el.style.width = ew + 'px'; el.style.height = eh + 'px';
      el.style.zIndex = ++self._zCounter; el.style.margin = '0';
      el.setAttribute('data-anc-x', pos.x); el.setAttribute('data-anc-y', pos.y);
      if (pos.w) el.setAttribute('data-anc-w', pos.w);
      if (pos.h) el.setAttribute('data-anc-h', pos.h);
      el.classList.add('anc-user-positioned');
    });
  },

  /* ── Snap ─────────────────────────────── */

  _snap(val) {
    if (!this._snapEnabled) return val;
    var r = val % this._snapGrid;
    if (Math.abs(r) <= this._snapThreshold) return val - r;
    if (Math.abs(r - this._snapGrid) <= this._snapThreshold) return val - r + this._snapGrid;
    if (Math.abs(r + this._snapGrid) <= this._snapThreshold) return val - r - this._snapGrid;
    return val;
  },

  _flashSnapIndicator(text) {
    var el = document.getElementById('layout-snap-indicator');
    if (!el) return;
    el.textContent = text; el.style.display = 'block'; el.style.opacity = '1';
    clearTimeout(this._snapTimer);
    var self = this;
    this._snapTimer = setTimeout(function () {
      el.style.opacity = '0'; el.style.transition = 'opacity 0.4s';
      setTimeout(function () { el.style.display = 'none'; el.style.transition = ''; }, 400);
    }, 1200);
  },
};
