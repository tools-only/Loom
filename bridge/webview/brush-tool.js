/**
 * Brush Tool — freeform paintbrush selection for Loom main page.
 *
 * Toggle via toolbar button or B key. Paint a stroke to select elements.
 * Closure is detected in real-time as you draw: when the stroke returns
 * near its starting region, the enclosed area fills and the dialog appears
 * automatically. You can also close by crossing your own path.
 */
window.BrushTool = {
  anchor: null,
  _active: false,
  _painting: false,
  _closed: false,        // true once a loop is detected during painting
  _path: null,           // [{x, y}, ...] viewport coords
  _canvas: null,
  _ctx: null,
  _cursorEl: null,
  _dialogEl: null,
  _dialogVisible: false,
  _capturedTargets: [],

  _brushRadius: 6,        // px — stroke radius
  _closeDist: 36,         // px — max gap to start-region to trigger closure
  _closeRatio: 0.25,      // check against first 25% of path points
  _minPathLen: 15,        // px — ignore tiny strokes

  /* ── Lifecycle ────────────────────────── */

  init(anchor) {
    this.anchor = anchor;
    this._canvas = document.getElementById('brush-canvas');
    if (!this._canvas) {
      this._canvas = document.createElement('canvas');
      this._canvas.id = 'brush-canvas';
      document.body.appendChild(this._canvas);
    }
    this._ctx = this._canvas.getContext('2d');

    this._cursorEl = document.getElementById('brush-cursor');
    if (!this._cursorEl) {
      this._cursorEl = document.createElement('div');
      this._cursorEl.id = 'brush-cursor';
      document.body.appendChild(this._cursorEl);
    }

    this._dialogEl = document.getElementById('brush-dialog');
    if (this._dialogEl) this._wireDialogButtons();

    var btn = document.getElementById('brush-mode-toggle');
    if (btn) btn.addEventListener('click', this.toggle.bind(this));

    this._wireEvents();
  },

  /* ── Toggle ───────────────────────────── */

  toggle() {
    this._active = !this._active;
    document.body.classList.toggle('brush-mode', this._active);
    var btn = document.getElementById('brush-mode-toggle');
    if (btn) btn.classList.toggle('active', this._active);
    if (!this._active) {
      this._dismissDialog();
      this._resetStroke();
      document.body.classList.remove('brush-painting', 'brush-closed');
    }
  },

  /* ── Events ───────────────────────────── */

  _wireEvents() {
    var stage = document.getElementById('anchor-content');
    if (!stage) return;
    var self = this;

    document.addEventListener('mousemove', function (e) {
      if (!self._active) return;
      if (self._cursorEl) {
        self._cursorEl.style.left = e.clientX + 'px';
        self._cursorEl.style.top = e.clientY + 'px';
      }
      if (!self._painting || !self._path) return;
      self._path.push({ x: e.clientX, y: e.clientY });
      self._drawStroke();

      // Real-time closure check
      if (!self._closed && self._detectClosure()) {
        self._closed = true;
        self._drawStroke(); // redraw with fill
        document.body.classList.add('brush-closed');
        self._showDialog(); // auto-pop
      }
    });

    stage.addEventListener('mousedown', function (e) {
      if (!self._active) return;
      if (e.button !== 0) return;
      if (e.target.closest('a, button, input, textarea, select, .anc-handle, .anc-handle-popup, #brush-dialog'))
        return;
      e.preventDefault();
      self._dismissDialog();
      self._resetStroke();
      self._painting = true;
      self._closed = false;
      self._path = [{ x: e.clientX, y: e.clientY }];
      document.body.classList.add('brush-painting');
      document.body.classList.remove('brush-closed');
      self._drawStroke();
    });

    document.addEventListener('mouseup', function () {
      if (!self._painting) return;
      self._painting = false;
      document.body.classList.remove('brush-painting');
      self._finishStroke();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && self._active) {
        if (self._dialogVisible) { self._dismissDialog(); }
        else { self.toggle(); }
      }
      if (e.key === 'b' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        var tag = document.activeElement && document.activeElement.tagName;
        if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
          self.toggle();
        }
      }
    });

    window.addEventListener('resize', function () {
      if (self._painting) { self._resetStroke(); }
    });
  },

  /* ── Stroke state ─────────────────────── */

  _resetStroke() {
    this._painting = false;
    this._closed = false;
    this._path = null;
    document.body.classList.remove('brush-painting', 'brush-closed');
    this._clearCanvas();
  },

  _pathLength() {
    if (!this._path || this._path.length < 2) return 0;
    var len = 0;
    for (var i = 1; i < this._path.length; i++) {
      var dx = this._path[i].x - this._path[i - 1].x;
      var dy = this._path[i].y - this._path[i - 1].y;
      len += Math.sqrt(dx * dx + dy * dy);
    }
    return len;
  },

  /* ── Closure detection ────────────────── */

  /**
   * Check if the current stroke tip is close to the starting region.
   * Tests the last point against the first 25% of the path.
   * Requires a minimum path length before triggering.
   */
  _detectClosure() {
    if (!this._path || this._path.length < 6) return false;
    if (this._pathLength() < 40) return false; // need meaningful stroke first

    var last = this._path[this._path.length - 1];
    var checkUpTo = Math.max(3, Math.floor(this._path.length * this._closeRatio));
    var thresholdSq = this._closeDist * this._closeDist;

    for (var i = 0; i < checkUpTo; i++) {
      var dx = last.x - this._path[i].x;
      var dy = last.y - this._path[i].y;
      if (dx * dx + dy * dy < thresholdSq) return true;
    }
    return false;
  },

  /* ── Canvas drawing ───────────────────── */

  _resizeCanvas() {
    if (!this._canvas) return;
    var dpr = window.devicePixelRatio || 1;
    var w = window.innerWidth;
    var h = window.innerHeight;
    if (this._canvas.width !== w * dpr || this._canvas.height !== h * dpr) {
      this._canvas.width = w * dpr;
      this._canvas.height = h * dpr;
      this._canvas.style.width = w + 'px';
      this._canvas.style.height = h + 'px';
      if (this._ctx) this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  },

  _clearCanvas() {
    if (!this._canvas || !this._ctx) return;
    this._resizeCanvas();
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
  },

  _drawStroke() {
    if (!this._ctx || !this._path || this._path.length < 2) return;
    this._resizeCanvas();
    var ctx = this._ctx;
    var r = this._brushRadius;

    ctx.clearRect(0, 0, this._canvas.width / (window.devicePixelRatio || 1), this._canvas.height / (window.devicePixelRatio || 1));

    // Stroked path
    ctx.strokeStyle = 'rgba(122, 90, 248, 0.55)';
    ctx.lineWidth = r * 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(this._path[0].x, this._path[0].y);
    for (var i = 1; i < this._path.length; i++) {
      ctx.lineTo(this._path[i].x, this._path[i].y);
    }
    ctx.stroke();

    // Fill when closed
    if (this._closed) {
      ctx.fillStyle = 'rgba(122, 90, 248, 0.10)';
      ctx.fill();
    }
  },

  /* ── Intersection ─────────────────────── */

  _finishStroke() {
    if (!this._path || this._path.length < 2 || this._pathLength() < this._minPathLen) {
      this._resetStroke();
      return;
    }

    // If dialog already shown via real-time closure, just update targets
    if (this._dialogVisible) {
      this._capturedTargets = this._collectTargets();
      var badge = this._dialogEl && this._dialogEl.querySelector('#brush-dialog-badge');
      if (badge) badge.textContent = this._capturedTargets.length + ' element' + (this._capturedTargets.length !== 1 ? 's' : '');
      return;
    }

    // Fallback: show dialog on mouseup even if not detected as closed
    // (for shapes that are closed but didn't trigger during paint, or for open strokes)
    this._capturedTargets = this._collectTargets();
    if (this._capturedTargets.length > 0) {
      this._closed = true; // treat as closed if we found targets
      this._showDialog();
    } else {
      var self = this;
      setTimeout(function () { self._clearCanvas(); }, 400);
    }
  },

  _collectTargets() {
    var stage = document.getElementById('anchor-content');
    if (!stage || !this._path || this._path.length < 2) return [];

    var r = this._brushRadius;
    var path = this._path;
    var closed = this._closed;

    // Path bounding box (expanded)
    var pbx1 = Infinity, pby1 = Infinity, pbx2 = -Infinity, pby2 = -Infinity;
    for (var i = 0; i < path.length; i++) {
      pbx1 = Math.min(pbx1, path[i].x - r);
      pby1 = Math.min(pby1, path[i].y - r);
      pbx2 = Math.max(pbx2, path[i].x + r);
      pby2 = Math.max(pby2, path[i].y + r);
    }

    var samples = this._samplePath(path, 5);
    var polygon = closed ? this._downsample(path, 3) : null;

    var seen = new Set();
    var results = [];
    var self = this;

    // Select all visible leaf elements — not just [data-anc]
    var allEls = stage.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, td, th, blockquote, pre, img, .anc-section, .anc-section--gc, .blog-card, .anc-kpi, .anc-kpi-grid, .anc-chart, table, ul, ol, figure, [data-anc]');
    allEls.forEach(function (el) {
      // Skip invisible / utility elements
      if (el.offsetParent === null || el.offsetWidth === 0 || el.offsetHeight === 0) return;
      if (el.closest('.anc-handle, .anc-handle-popup, #brush-dialog, #anchor-floating-toolbar')) return;
      if (el.tagName === 'BUTTON' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return;

      var id = el.getAttribute('data-anc') || self._elId(el, stage);
      if (!id || seen.has(id)) return;

      var cr = el.getBoundingClientRect();
      if (cr.right < pbx1 || cr.left > pbx2 || cr.bottom < pby1 || cr.top > pby2) return;

      var hit = false;
      if (closed && polygon) {
        var cx = (cr.left + cr.right) / 2;
        var cy = (cr.top + cr.bottom) / 2;
        hit = self._pointInPolygon(cx, cy, polygon)
           || self._circleIntersectsRect(samples, r, cr);
      } else {
        hit = self._circleIntersectsRect(samples, r, cr);
      }
      if (!hit) return;

      // De-duplicate nested: prefer outermost that's already selected
      var hasAncestorInSet = false;
      var p = el.parentElement;
      while (p && p !== stage) {
        var paId = p.getAttribute ? p.getAttribute('data-anc') || self._elId(p, stage) : null;
        if (paId && seen.has(paId)) { hasAncestorInSet = true; break; }
        p = p.parentElement;
      }
      if (!hasAncestorInSet) {
        seen.add(id);
        results.push({ anchor_id: id, target_html: el.outerHTML });
      }
    });

    return results;
  },

  /** Generate a stable ID for any element based on its DOM path. */
  _elId(el, root) {
    if (!el || el === root) return '';
    var parts = [];
    var cur = el;
    while (cur && cur !== root) {
      var tag = cur.tagName.toLowerCase();
      var anc = cur.getAttribute && cur.getAttribute('data-anc');
      if (anc) { parts.unshift(anc); break; } // use data-anc as anchor in path
      var nth = 1;
      var prev = cur.previousElementSibling;
      while (prev) {
        if (prev.tagName === cur.tagName) nth++;
        prev = prev.previousElementSibling;
      }
      parts.unshift(tag + ':nth-of-type(' + nth + ')');
      cur = cur.parentElement;
    }
    return 'el:' + parts.join('>');
  },

  _downsample(path, n) {
    var out = [];
    for (var i = 0; i < path.length; i += n) out.push(path[i]);
    var last = path[path.length - 1];
    if (out[out.length - 1] !== last) out.push(last);
    return out;
  },

  _samplePath(path, step) {
    if (path.length <= 1) return path.slice();
    var samples = [path[0]];
    var accumulated = 0;
    for (var i = 1; i < path.length; i++) {
      var dx = path[i].x - path[i - 1].x;
      var dy = path[i].y - path[i - 1].y;
      var segLen = Math.sqrt(dx * dx + dy * dy);
      if (accumulated + segLen >= step) {
        var t = (step - accumulated) / segLen;
        samples.push({ x: path[i - 1].x + dx * t, y: path[i - 1].y + dy * t });
        accumulated = -step * (1 - t);
      } else {
        accumulated += segLen;
      }
    }
    var last = path[path.length - 1];
    if (samples[samples.length - 1] !== last) samples.push(last);
    return samples;
  },

  _pointInPolygon(px, py, polygon) {
    var inside = false;
    for (var i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      var xi = polygon[i].x, yi = polygon[i].y;
      var xj = polygon[j].x, yj = polygon[j].y;
      if ((yi > py) !== (yj > py) &&
          px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  },

  _circleIntersectsRect(samples, r, rect) {
    var rsq = r * r;
    for (var i = 0; i < samples.length; i++) {
      var cx = samples[i].x, cy = samples[i].y;
      var closestX = Math.max(rect.left, Math.min(cx, rect.right));
      var closestY = Math.max(rect.top, Math.min(cy, rect.bottom));
      var dx = cx - closestX, dy = cy - closestY;
      if (dx * dx + dy * dy < rsq) return true;
    }
    return false;
  },

  /* ── Dialog ───────────────────────────── */

  _showDialog() {
    if (!this._dialogEl) return;
    var count = this._capturedTargets.length;
    var badge = this._dialogEl.querySelector('#brush-dialog-badge');
    if (badge) badge.textContent = count + ' element' + (count !== 1 ? 's' : '');

    var textarea = this._dialogEl.querySelector('#brush-dialog-input');
    if (textarea) {
      textarea.value = '';
      setTimeout(function () { textarea.focus(); }, 80);
    }

    this._positionDialog();
    this._dialogEl.classList.add('visible');
    this._dialogVisible = true;

    var self = this;
    setTimeout(function () {
      document.addEventListener('click', self._outsideClick = function (e) {
        if (!self._dialogEl || !self._dialogEl.contains(e.target)) self._dismissDialog();
      });
    }, 0);
  },

  _positionDialog() {
    if (!this._dialogEl) return;
    // Position near the center of the path's bounding box
    if (this._path && this._path.length > 0) {
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (var i = 0; i < this._path.length; i++) {
        minX = Math.min(minX, this._path[i].x);
        minY = Math.min(minY, this._path[i].y);
        maxX = Math.max(maxX, this._path[i].x);
        maxY = Math.max(maxY, this._path[i].y);
      }
      if (isFinite(minX)) {
        var top = maxY + 12;
        var left = minX;
        var dialogW = this._dialogEl.offsetWidth || 360;
        var dialogH = this._dialogEl.offsetHeight || 200;
        if (top + dialogH > window.innerHeight - 12) {
          top = minY - dialogH - 12;
          if (top < 8) top = 8;
        }
        if (left + dialogW > window.innerWidth - 8) left = window.innerWidth - dialogW - 8;
        if (left < 8) left = 8;
        this._dialogEl.style.top = top + 'px';
        this._dialogEl.style.left = left + 'px';
        return;
      }
    }
    // Fallback center
    this._dialogEl.style.top = Math.max(40, (window.innerHeight - 300) / 2) + 'px';
    this._dialogEl.style.left = Math.max(8, (window.innerWidth - 360) / 2) + 'px';
  },

  _dismissDialog() {
    if (!this._dialogEl) return;
    this._dialogEl.classList.remove('visible');
    this._dialogVisible = false;
    this._capturedTargets = [];
    if (this._outsideClick) {
      document.removeEventListener('click', this._outsideClick);
      this._outsideClick = null;
    }
    this._resetStroke();
  },

  _wireDialogButtons() {
    var self = this;
    var dialog = this._dialogEl;
    if (!dialog) return;

    dialog.querySelectorAll('button[data-brush-op]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        self._dispatchOp(btn.getAttribute('data-brush-op'));
      });
    });

    var cancel = dialog.querySelector('#brush-dialog-dismiss');
    if (cancel) cancel.addEventListener('click', function (e) { e.stopPropagation(); self._dismissDialog(); });

    var textarea = dialog.querySelector('#brush-dialog-input');
    if (textarea) {
      textarea.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          self._dispatchOp('refine');
        }
        if (e.key === 'Delete' || e.key === 'Backspace') {
          // Delete key when textarea is empty → delete selected
          if (!textarea.value.trim()) {
            e.preventDefault();
            self._dispatchOp('delete');
          }
        }
        if (e.key === 'Escape') { e.stopPropagation(); self._dismissDialog(); }
      });
    }
  },

  /* ── Dispatch ─────────────────────────── */

  _dispatchOp(op) {
    if (!this.anchor) return;

    // Delete is local — no agent round-trip needed
    if (op === 'delete') {
      var delTargets = this._capturedTargets.slice();
      if (window.LayoutTool) LayoutTool.deleteElements(delTargets);
      this._dismissDialog();
      return;
    }

    var textarea = this._dialogEl && this._dialogEl.querySelector('#brush-dialog-input');
    var instruction = textarea ? textarea.value.trim() : '';
    if (!instruction && op !== 'restructure') return;

    var targets = this._capturedTargets.slice();

    var brushRect = null;
    if (targets.length > 0) {
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      targets.forEach(function (t) {
        var el = document.querySelector('[data-anc="' + t.anchor_id.replace(/"/g, '\\"') + '"]');
        if (el) {
          var cr = el.getBoundingClientRect();
          minX = Math.min(minX, cr.left);
          minY = Math.min(minY, cr.top);
          maxX = Math.max(maxX, cr.right);
          maxY = Math.max(maxY, cr.bottom);
        }
      });
      if (isFinite(minX)) brushRect = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
    }

    this.anchor.sendEnvelope(this.anchor.buildEnvelope({
      op: op,
      target_kind: 'brush_selection',
      target_ref: 'brush:' + Date.now().toString(36),
      instruction: instruction,
      selection: null,
      brushPayload: { targets: targets, rect: brushRect }
    }));

    this._dismissDialog();
  },
};
