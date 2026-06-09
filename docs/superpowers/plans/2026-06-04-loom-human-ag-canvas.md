# loom-human-ag Canvas Workspace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a freeform canvas whiteboard at `/canvas` where the agent generates positioned `data-anc` cards and the user can drag/rotate/scale them, with group-select + AI prompt loop.

**Architecture:** Standalone `canvas.html` page (like `mobile-target.html`) connects via WS to the existing Anchor server. Cards are `div`s with `data-anc-x/y/rot/scale/w/z` attributes; CSS `position:absolute` + `transform` renders them. A new `context_mode:'canvas'` envelope branch in `server.cjs` generates a canvas-format CC prompt. Phase 0 is entirely in `bridge/webview/` + 3 new server routes. No loom hand or schema changes in Phase 0.

**Tech Stack:** Vanilla JS (no build), CSS custom properties (Bloom tokens), existing WS/envelope pipeline, existing `anchor_patch` protocol.

---

## File Map

| File | Action | Description |
|---|---|---|
| `bridge/webview/canvas.html` | Create | Standalone canvas viewer entry point |
| `bridge/webview/canvas-client.js` | Create | Canvas interaction engine (viewport/cards/drag/WS/prompt) |
| `bridge/webview/canvas-styles.css` | Create | Canvas-specific CSS (no touching styles.css) |
| `mcp/server.cjs` | Modify | 3 routes: GET /canvas, GET /current-canvas, POST /canvas-state; canvas prompt format |
| `domains/loom-human-ag/manifest.json` | Create | Domain pack registration |
| `domains/loom-human-ag/hands/canvas/CLAUDE.md` | Create | Agent instructions for canvas hand (Phase 2 prerequisite) |
| `domains/loom-human-ag/hands/canvas/config.json` | Create | Hand config |

---

## Task 1: Create git branch

**Files:** none

- [ ] **Step 1: Create and switch to branch**

```bash
cd "D:/ai-native chrome"
git checkout -b loom-human-ag
```

Expected: `Switched to a new branch 'loom-human-ag'`

- [ ] **Step 2: Verify**

```bash
git branch --show-current
```

Expected: `loom-human-ag`

---

## Task 2: Domain pack scaffold

**Files:**
- Create: `domains/loom-human-ag/manifest.json`
- Create: `domains/loom-human-ag/hands/canvas/CLAUDE.md`
- Create: `domains/loom-human-ag/hands/canvas/config.json`

- [ ] **Step 1: Create manifest.json**

```json
{
  "id": "loom-human-ag",
  "name": "Loom Human-Agent Canvas",
  "runtime": "local-desktop-single-user",
  "version": "0.1.0",
  "description": "Free-form whiteboard for co-design: AI generates positioned cards, user drags/rotates/scales, group select + AI improvement loop.",
  "interface": "loom-agent-adapter",
  "routes": ["canvas"],
  "capabilities": ["canvas.create", "canvas.codesign"],
  "agentTasks": [
    {
      "id": "canvas.codesign",
      "label": "Canvas co-design",
      "agent": "canvas-agent",
      "adapter": "cc",
      "artifactContract": "canvas_html"
    }
  ],
  "compatibility": {
    "preserveExistingExperience": true,
    "preserveCssTemplates": true,
    "preserveUiDesign": true,
    "preserveColorSystem": true,
    "preserveConcreteFunctions": true
  },
  "paths": {
    "agentTasks": "./agent-tasks",
    "resources": "./resources",
    "policies": "./policies",
    "ui": "./ui"
  }
}
```

- [ ] **Step 2: Create hands/canvas/CLAUDE.md**

```markdown
# Canvas Hand — Agent Instructions

You are the Canvas Co-design hand. Your role: generate and update content cards on a freeform whiteboard canvas.

## Canvas HTML Format

All cards live inside a `canvas-root` div:

```html
<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:3000px;height:2000px;">
  <div class="anc-card anc-section anc-section--gc"
       data-anc="card-[unique-slug]"
       data-handles="refine,expand,shorten"
       data-anc-x="80"
       data-anc-y="80"
       data-anc-w="320"
       data-anc-rot="0"
       data-anc-scale="1"
       data-anc-z="1"
       style="position:absolute;left:80px;top:80px;width:320px;transform:rotate(0deg) scale(1);">
    <!-- Bloom CSS content -->
  </div>
</div>
```

## Positioning Rules

- Default card width: 320px
- Grid layout: 4 columns, step (360, 280), starting at (80, 80)
- No overlapping cards
- For 5 cards: (80,80) (440,80) (800,80) (1160,80) (80,360)

## When Patching

- Preserve user-set `data-anc-x/y/rot/scale` unless instruction explicitly asks to move
- Update only `data-anc-z` and content inside the card
- Use `anchor_patch({patches:[{anchor_id, html_fragment}]})` — never `anchor_render` during op processing
```

- [ ] **Step 3: Create hands/canvas/config.json**

```json
{
  "hand_id": "canvas",
  "display_name": "Canvas Co-design",
  "description": "Generate and update positioned cards on a freeform canvas."
}
```

- [ ] **Step 4: Commit scaffold**

```bash
cd "D:/ai-native chrome"
git add domains/loom-human-ag/
git commit -m "feat(loom-human-ag): domain pack scaffold + canvas hand config"
```

---

## Task 3: canvas-styles.css

**Files:**
- Create: `bridge/webview/canvas-styles.css`

- [ ] **Step 1: Write canvas-styles.css**

Full content — uses Bloom tokens, no hard-coded colors:

```css
/* canvas-styles.css — loom-human-ag canvas workspace
   Uses Bloom Design System tokens from resource/colors_and_type.css
   NEVER touch styles.css                                            */

*, *::before, *::after { box-sizing: border-box; }

html, body {
  margin: 0; padding: 0;
  height: 100%; overflow: hidden;
  background: var(--paper, #f8f7f4);
  font-family: var(--font-body, 'Plus Jakarta Sans', sans-serif);
  color: var(--ink, #1a1a2e);
  user-select: none;
}

/* ── Toolbar ──────────────────────────────────────────────────── */
#canvas-toolbar {
  position: fixed; top: 0; left: 0; right: 0;
  height: 52px; z-index: 1000;
  display: flex; align-items: center; gap: 10px;
  padding: 0 16px;
  background: rgba(248, 247, 244, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0,0,0,0.06);
}

#canvas-toolbar h1 {
  font-family: var(--font-display, 'Bricolage Grotesque', sans-serif);
  font-size: 16px; font-weight: 800;
  margin: 0; letter-spacing: -0.02em;
  color: var(--ink);
}

.canvas-status {
  font-size: 11px; font-weight: 600;
  padding: 3px 10px; border-radius: 999px;
  background: rgba(0,0,0,0.06);
  color: var(--ink);
  border: 1px solid rgba(0,0,0,0.08);
  pointer-events: none;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.canvas-status--live {
  background: rgba(74, 222, 128, 0.15);
  color: #16a34a;
  border-color: rgba(74, 222, 128, 0.3);
}

.canvas-status--thinking {
  background: rgba(122, 90, 248, 0.1);
  color: var(--accent-brand, #7A5AF8);
  border-color: rgba(122, 90, 248, 0.2);
}

/* ── Prompt bar ───────────────────────────────────────────────── */
#canvas-prompt-bar {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  z-index: 1000;
  display: flex; align-items: center; gap: 8px;
  padding: 8px 8px 8px 16px;
  min-width: 480px; max-width: 700px; width: 60vw;
  background: var(--paper);
  border: 1px solid rgba(0,0,0,0.1);
  border-radius: 999px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.12), 0 1px 4px rgba(0,0,0,0.06);
}

#canvas-prompt-input {
  flex: 1; border: none; outline: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: 14px; color: var(--ink);
}

#canvas-prompt-input::placeholder { color: rgba(0,0,0,0.35); }

#canvas-prompt-send {
  flex-shrink: 0;
  width: 36px; height: 36px;
  border-radius: 50%; border: none; cursor: pointer;
  background: var(--accent-brand, #7A5AF8);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  transition: transform 0.12s, box-shadow 0.12s;
}

#canvas-prompt-send:hover { transform: scale(1.05); box-shadow: 0 2px 8px rgba(122,90,248,0.4); }
#canvas-prompt-send:active { transform: scale(0.95); }

/* ── Canvas viewport ──────────────────────────────────────────── */
#canvas-viewport {
  position: fixed;
  top: 52px; left: 0; right: 0; bottom: 0;
  overflow: hidden;
  cursor: default;
}

body.canvas-panning #canvas-viewport { cursor: grab; }
body.canvas-panning.canvas-dragging #canvas-viewport { cursor: grabbing; }

#canvas-stage {
  position: absolute;
  width: 3000px; height: 2000px;
  transform-origin: 0 0;
  will-change: transform;
}

/* ── Canvas cards ─────────────────────────────────────────────── */
.canvas-card-host {
  position: absolute;
  transform-origin: center center;
  cursor: grab;
  transition: box-shadow 0.15s;
}

.canvas-card-host:hover { z-index: 10 !important; }
.canvas-card-host:active { cursor: grabbing; }

.canvas-card-host .anc-section {
  margin: 0 !important;
  width: 100%;
  pointer-events: none; /* host handles all events */
}

/* ── Selection state ──────────────────────────────────────────── */
.canvas-card-host.canvas-selected {
  outline: 2px solid var(--accent-brand, #7A5AF8);
  outline-offset: 2px;
  border-radius: 16px;
  z-index: 100 !important;
}

/* ── Card handles (shown when selected) ──────────────────────── */
.card-handles {
  display: none;
  position: absolute;
  inset: -10px;
  pointer-events: none;
}

.canvas-card-host.canvas-selected .card-handles {
  display: block;
}

.resize-handle {
  position: absolute;
  width: 10px; height: 10px;
  background: #fff;
  border: 2px solid var(--accent-brand, #7A5AF8);
  border-radius: 2px;
  pointer-events: all;
  z-index: 200;
}

/* Position the 8 resize handles */
.resize-handle.resize-nw { top: 0;   left: 0;   cursor: nw-resize; transform: translate(-50%, -50%); }
.resize-handle.resize-n  { top: 0;   left: 50%; cursor: n-resize;  transform: translate(-50%, -50%); }
.resize-handle.resize-ne { top: 0;   left: 100%;cursor: ne-resize; transform: translate(-50%, -50%); }
.resize-handle.resize-e  { top: 50%; left: 100%;cursor: e-resize;  transform: translate(-50%, -50%); }
.resize-handle.resize-se { top: 100%;left: 100%;cursor: se-resize; transform: translate(-50%, -50%); }
.resize-handle.resize-s  { top: 100%;left: 50%; cursor: s-resize;  transform: translate(-50%, -50%); }
.resize-handle.resize-sw { top: 100%;left: 0;   cursor: sw-resize; transform: translate(-50%, -50%); }
.resize-handle.resize-w  { top: 50%; left: 0;   cursor: w-resize;  transform: translate(-50%, -50%); }

.rotate-handle {
  position: absolute;
  width: 18px; height: 18px;
  background: var(--accent-brand, #7A5AF8);
  border: 2px solid #fff;
  border-radius: 50%;
  top: -30px; left: 50%;
  transform: translateX(-50%);
  cursor: crosshair;
  pointer-events: all;
  z-index: 200;
  display: flex; align-items: center; justify-content: center;
}

.rotate-handle::after {
  content: '↻';
  color: #fff;
  font-size: 11px;
  line-height: 1;
}

/* Connector line from rotate handle to card */
.rotate-handle::before {
  content: '';
  position: absolute;
  top: 100%; left: 50%;
  width: 1px; height: 14px;
  background: var(--accent-brand, #7A5AF8);
  opacity: 0.5;
  transform: translateX(-50%);
}

/* ── Canvas grid bg ───────────────────────────────────────────── */
#canvas-viewport::before {
  content: '';
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}

/* ── Empty state ──────────────────────────────────────────────── */
#canvas-empty {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: rgba(0,0,0,0.3);
  pointer-events: none;
  transition: opacity 0.3s;
}

#canvas-empty.hidden { opacity: 0; }

#canvas-empty p {
  font-size: 14px; line-height: 1.6;
  margin: 8px 0 0;
}

#canvas-empty .canvas-empty-icon {
  font-size: 40px;
  opacity: 0.5;
}

/* ── Dragging ─────────────────────────────────────────────────── */
body.canvas-dragging * { cursor: grabbing !important; }
body.canvas-dragging .canvas-card-host { transition: none !important; }
```

- [ ] **Step 2: Commit**

```bash
cd "D:/ai-native chrome"
git add bridge/webview/canvas-styles.css
git commit -m "feat(canvas): add canvas-styles.css (bloom tokens, no styles.css touch)"
```

---

## Task 4: canvas.html

**Files:**
- Create: `bridge/webview/canvas.html`

- [ ] **Step 1: Write canvas.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Canvas · Loom</title>
<link rel="stylesheet" href="resource/colors_and_type.css">
<link rel="stylesheet" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css">
<link rel="stylesheet" href="canvas-styles.css">
</head>
<body>

<!-- Toolbar -->
<div id="canvas-toolbar">
  <i class="ph-bold ph-squares-four" style="font-size:18px;color:var(--accent-brand,#7A5AF8)"></i>
  <h1>Canvas</h1>
  <span class="canvas-status" id="canvas-status">Connecting…</span>
  <span style="flex:1"></span>
  <a href="/" style="font-size:13px;color:var(--ink);opacity:0.5;text-decoration:none;">
    <i class="ph-bold ph-x"></i>
  </a>
</div>

<!-- Canvas area -->
<div id="canvas-viewport">
  <div id="canvas-stage">
    <!-- Cards are inserted here by canvas-client.js -->
  </div>
  <div id="canvas-empty">
    <div class="canvas-empty-icon"><i class="ph-bold ph-magic-wand"></i></div>
    <p>在下方输入，让 AI 在画布上生成内容卡片<br>拖动、旋转、缩放，选中后可继续提要求</p>
  </div>
</div>

<!-- Prompt bar -->
<div id="canvas-prompt-bar">
  <input
    id="canvas-prompt-input"
    type="text"
    placeholder="描述你想在画布上生成的内容…"
    autocomplete="off"
    spellcheck="false"
  />
  <button id="canvas-prompt-send" title="发送 (Enter)">
    <i class="ph-bold ph-paper-plane-tilt"></i>
  </button>
</div>

<script src="canvas-client.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
cd "D:/ai-native chrome"
git add bridge/webview/canvas.html
git commit -m "feat(canvas): add canvas.html standalone entry (viewport + prompt bar)"
```

---

## Task 5: canvas-client.js

**Files:**
- Create: `bridge/webview/canvas-client.js`

- [ ] **Step 1: Write canvas-client.js — full file**

```javascript
/* canvas-client.js — loom-human-ag freeform canvas
   Stand-alone; does NOT import or depend on anchor-client.js          */
'use strict';
(function () {

// ─────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────
const state = {
  cards:    new Map(),    // anchor_id → { el, contentEl, x, y, w, rot, scale, z, localMoved }
  viewport: { x: 0, y: 0, zoom: 1 },
  selected: new Set(),    // anchor_ids currently selected
};

const CANVAS_W = 3000;
const CANVAS_H = 2000;

let stage, viewport, promptInput, statusEl, emptyEl, ws;
let _syncTimer = null;

// ─────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  stage      = document.getElementById('canvas-stage');
  viewport   = document.getElementById('canvas-viewport');
  promptInput = document.getElementById('canvas-prompt-input');
  statusEl   = document.getElementById('canvas-status');
  emptyEl    = document.getElementById('canvas-empty');

  initViewport();
  initPromptUI();
  initWS();
  loadSavedCanvas();
});

// ─────────────────────────────────────────────────────────────────────
// Viewport — pan (space-drag or middle-drag) + wheel zoom
// ─────────────────────────────────────────────────────────────────────
function initViewport() {
  let isPanning = false;
  let panStart  = null;
  let spaceDown = false;

  document.addEventListener('keydown', function (e) {
    if (e.code === 'Space' && document.activeElement !== promptInput) {
      spaceDown = true;
      document.body.classList.add('canvas-panning');
      e.preventDefault();
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
    // Click on empty canvas → clear selection
    if (e.target === viewport || e.target === stage) {
      clearSelection();
    }
  });

  document.addEventListener('mousemove', function (e) {
    if (!isPanning || !panStart) return;
    state.viewport.x = e.clientX - panStart.x;
    state.viewport.y = e.clientY - panStart.y;
    applyViewportTransform();
  });

  document.addEventListener('mouseup', function () {
    isPanning = false;
  });

  viewport.addEventListener('wheel', function (e) {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const newZoom = Math.max(0.15, Math.min(5, state.viewport.zoom * factor));

    // Zoom toward cursor
    const rect  = viewport.getBoundingClientRect();
    const cx    = e.clientX - rect.left;
    const cy    = e.clientY - rect.top;
    const ratio = newZoom / state.viewport.zoom;
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
    // Fallback: if agent returned non-canvas HTML, treat every top-level section as a card
    cardEls = tmp.querySelectorAll('[data-anc]');
  }

  var newIds = new Set();
  var autoX = 80, autoY = 80, autoCol = 0;

  cardEls.forEach(function (cardEl) {
    var id = cardEl.getAttribute('data-anc');
    if (!id || id === 'canvas-root') return;
    newIds.add(id);

    var x = parseFloat(cardEl.getAttribute('data-anc-x') || autoX);
    var y = parseFloat(cardEl.getAttribute('data-anc-y') || autoY);
    var w = parseFloat(cardEl.getAttribute('data-anc-w') || '320');
    var rot   = parseFloat(cardEl.getAttribute('data-anc-rot')   || '0');
    var scale = parseFloat(cardEl.getAttribute('data-anc-scale') || '1');
    var z     = parseInt(  cardEl.getAttribute('data-anc-z')     || '1', 10);

    // Auto-grid if no explicit position
    if (!cardEl.getAttribute('data-anc-x')) {
      x = 80 + autoCol * 360;
      y = autoY;
      autoCol++;
      if (autoCol >= 4) { autoCol = 0; autoY += 280; }
    }

    if (state.cards.has(id)) {
      var existing = state.cards.get(id);
      existing.contentEl.innerHTML = cardEl.innerHTML;
      if (!existing.localMoved) {
        existing.x = x; existing.y = y; existing.w = w;
        existing.rot = rot; existing.scale = scale; existing.z = z;
      }
      updateCardTransform(existing);
    } else {
      addCard(id, cardEl.outerHTML, x, y, w, rot, scale, z);
    }
  });

  // Remove cards not in new set (only if agent sent full re-render)
  if (newIds.size > 0) {
    state.cards.forEach(function (card, id) {
      if (!newIds.has(id)) { card.el.remove(); state.cards.delete(id); }
    });
  }

  updateEmptyState();
}

function addCard(id, outerHtml, x, y, w, rot, scale, z) {
  var host = document.createElement('div');
  host.className = 'canvas-card-host';
  host.dataset.cardId = id;
  host.style.cssText = 'position:absolute;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;z-index:' + z + ';';
  host.style.transform = 'rotate(' + rot + 'deg) scale(' + scale + ')';

  var inner = document.createElement('div');
  inner.innerHTML = outerHtml;
  var contentEl = inner.firstElementChild || inner;
  host.appendChild(contentEl);

  var handles = buildHandles(id);
  host.appendChild(handles);

  stage.appendChild(host);

  var entry = { el: host, contentEl: contentEl, x: x, y: y, w: w, rot: rot, scale: scale, z: z, localMoved: false };
  state.cards.set(id, entry);
  bindCardEvents(id, host, entry);
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
    '<div class="resize-handle resize-n"  data-dir="n"></div>' +
    '<div class="resize-handle resize-ne" data-dir="ne"></div>' +
    '<div class="resize-handle resize-e"  data-dir="e"></div>' +
    '<div class="resize-handle resize-se" data-dir="se"></div>' +
    '<div class="resize-handle resize-s"  data-dir="s"></div>' +
    '<div class="resize-handle resize-sw" data-dir="sw"></div>' +
    '<div class="resize-handle resize-w"  data-dir="w"></div>' +
    '<div class="rotate-handle"           data-action="rotate"></div>';
  return h;
}

// ─────────────────────────────────────────────────────────────────────
// Drag state
// ─────────────────────────────────────────────────────────────────────
var _drag = null;

function bindCardEvents(id, host, entry) {
  // Card body → select + move
  host.addEventListener('mousedown', function (e) {
    if (e.target.closest('.card-handles')) return;
    e.stopPropagation();
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
  var rh = host.querySelector('.rotate-handle');
  if (rh) {
    rh.addEventListener('mousedown', function (e) {
      e.stopPropagation();
      if (!e.shiftKey) clearSelection();
      selectCard(id);
      beginDrag(e, id, entry, 'rotate', null);
    });
  }
}

function beginDrag(e, id, entry, type, dir) {
  var rect = entry.el.getBoundingClientRect();
  _drag = {
    type:  type,
    id:    id,
    dir:   dir,
    clientX0: e.clientX,
    clientY0: e.clientY,
    x0:    entry.x,
    y0:    entry.y,
    w0:    entry.w,
    rot0:  entry.rot,
    // Rotate: compute angle to card center at mousedown
    cx: rect.left + rect.width  / 2,
    cy: rect.top  + rect.height / 2,
  };
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
    entry.x = _drag.x0 + dx;
    entry.y = _drag.y0 + dy;
    entry.localMoved = true;

  } else if (_drag.type === 'rotate') {
    var rect = entry.el.getBoundingClientRect();
    var cx = rect.left + rect.width  / 2;
    var cy = rect.top  + rect.height / 2;
    var ang = Math.atan2(e.clientY - cy, e.clientX - cx);
    entry.rot = (ang - _drag.ang0) * 180 / Math.PI;
    entry.localMoved = true;

  } else if (_drag.type === 'resize') {
    var dir = _drag.dir;
    if (dir === 'e' || dir === 'se' || dir === 'ne') {
      entry.w = Math.max(160, _drag.w0 + dx);
    } else if (dir === 'w' || dir === 'sw' || dir === 'nw') {
      var nw = Math.max(160, _drag.w0 - dx);
      entry.x = _drag.x0 + (_drag.w0 - nw);
      entry.w = nw;
    }
    entry.localMoved = true;
  }

  updateCardTransform(entry);
});

document.addEventListener('mouseup', function () {
  if (_drag) {
    var entry = state.cards.get(_drag.id);
    if (entry) scheduleSync();
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

  // Keep data-anc-* on content element in sync
  var c = entry.contentEl;
  if (c) {
    c.setAttribute('data-anc-x',     entry.x);
    c.setAttribute('data-anc-y',     entry.y);
    c.setAttribute('data-anc-w',     entry.w);
    c.setAttribute('data-anc-rot',   entry.rot);
    c.setAttribute('data-anc-scale', entry.scale);
    c.setAttribute('data-anc-z',     entry.z);
  }
}

// ─────────────────────────────────────────────────────────────────────
// Selection
// ─────────────────────────────────────────────────────────────────────
function selectCard(id) {
  state.selected.add(id);
  var e = state.cards.get(id);
  if (e) e.el.classList.add('canvas-selected');
}

function clearSelection() {
  state.selected.forEach(function (id) {
    var e = state.cards.get(id);
    if (e) e.el.classList.remove('canvas-selected');
  });
  state.selected.clear();
}

// ─────────────────────────────────────────────────────────────────────
// Patch apply (from agent)
// ─────────────────────────────────────────────────────────────────────
function applyPatches(patches) {
  patches.forEach(function (p) {
    var entry = state.cards.get(p.anchor_id);
    if (!entry) {
      // New card from agent (canvas_create style)
      var tmp = document.createElement('div');
      tmp.innerHTML = p.html_fragment;
      var el = tmp.firstElementChild;
      if (el) {
        var x = parseFloat(el.getAttribute('data-anc-x') || '0');
        var y = parseFloat(el.getAttribute('data-anc-y') || '0');
        var w = parseFloat(el.getAttribute('data-anc-w') || '320');
        var rot   = parseFloat(el.getAttribute('data-anc-rot')   || '0');
        var scale = parseFloat(el.getAttribute('data-anc-scale') || '1');
        var z     = parseInt(  el.getAttribute('data-anc-z')     || '1', 10);
        addCard(p.anchor_id, p.html_fragment, x, y, w, rot, scale, z);
      }
      return;
    }
    // Existing card: update content, respect user's local position
    var tmp = document.createElement('div');
    tmp.innerHTML = p.html_fragment;
    var newCard = tmp.firstElementChild;
    if (!newCard) return;

    entry.contentEl.innerHTML = newCard.innerHTML;
    if (!entry.localMoved && newCard.getAttribute('data-anc-x')) {
      entry.x     = parseFloat(newCard.getAttribute('data-anc-x'));
      entry.y     = parseFloat(newCard.getAttribute('data-anc-y'));
      entry.rot   = parseFloat(newCard.getAttribute('data-anc-rot')   || '0');
      entry.scale = parseFloat(newCard.getAttribute('data-anc-scale') || '1');
      updateCardTransform(entry);
    }
  });
  updateEmptyState();
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

    } else if (msg.type === 'event') {
      handleAgentEvent(msg);

    } else if (msg.type === 'ack') {
      // Sent ok
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
  var instruction = promptInput.value.trim();
  if (!instruction || !ws || ws.readyState !== WebSocket.OPEN) return;
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

  var canvasHtml = serializeCanvasHtml();

  var envelope = {
    schema_version: '1.0',
    intent: {
      op: op || 'initial_render',
      target_kind: 'global',
      target_ref: null,
      instruction: instruction
    },
    selection: null,
    context_bundle: {
      memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [],
      scope_hint: null, transient_override: null,
      subagent_id: null,
      context_mode: 'canvas',
      file_id: null,
      card_anchor_ids: Array.from(state.selected)
    },
    render_state: {
      anchor_tree: [], anchor_index: {}, dom_signature: '',
      relevant_subtree: {
        target_ref: 'canvas-root',
        target_html: canvasHtml,
        forward_deps: {}, reverse_deps: {}
      },
      selected_subtrees: buildSelectedSubtrees(),
      viewport: {
        x: state.viewport.x,
        y: state.viewport.y,
        zoom: state.viewport.zoom
      }
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
function serializeCanvasHtml() {
  var html = '<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:' + CANVAS_W + 'px;height:' + CANVAS_H + 'px;">';
  state.cards.forEach(function (entry, id) {
    if (entry.contentEl) {
      // Ensure data-anc-* are up to date
      entry.contentEl.setAttribute('data-anc-x',     entry.x);
      entry.contentEl.setAttribute('data-anc-y',     entry.y);
      entry.contentEl.setAttribute('data-anc-w',     entry.w);
      entry.contentEl.setAttribute('data-anc-rot',   entry.rot);
      entry.contentEl.setAttribute('data-anc-scale', entry.scale);
      entry.contentEl.setAttribute('data-anc-z',     entry.z);
      html += entry.contentEl.outerHTML;
    }
  });
  html += '</div>';
  return html;
}

function scheduleSync() {
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(saveToServer, 600);
}

function saveToServer() {
  var html = serializeCanvasHtml();
  fetch('/canvas-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ html: html })
  }).catch(function () {});
}

function loadSavedCanvas() {
  fetch('/current-canvas')
    .then(function (r) { return r.ok ? r.text() : ''; })
    .then(function (html) {
      if (html && html.trim()) renderFromHtml(html);
    })
    .catch(function () {});
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────
function updateEmptyState() {
  if (!emptyEl) return;
  if (state.cards.size > 0) {
    emptyEl.classList.add('hidden');
  } else {
    emptyEl.classList.remove('hidden');
  }
}

function setStatus(text, kind) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.className = 'canvas-status' + (kind ? ' canvas-status--' + kind : '');
}

})();
```

- [ ] **Step 2: Commit**

```bash
cd "D:/ai-native chrome"
git add bridge/webview/canvas-client.js
git commit -m "feat(canvas): add canvas-client.js (viewport pan/zoom, card drag/rotate/resize, WS, prompt)"
```

---

## Task 6: Update mcp/server.cjs

**Files:**
- Modify: `mcp/server.cjs`

Three changes:
1. Add `CANVAS_HTML` path constant near top
2. Add `GET /canvas`, `GET /current-canvas`, `POST /canvas-state` routes
3. Add `context_mode:'canvas'` branch in `formatEnvelopeAsPrompt`

- [ ] **Step 1: Add path constant**

After line 28 (`const CURRENT_HTML = ...`), add:

```javascript
const CANVAS_HTML    = path.join(OUTPUT_DIR, 'canvas.html');
```

- [ ] **Step 2: Add routes after the `/current-html` route (around line 1000)**

After the block ending with `app.get('/current-html', ...)`:

```javascript
app.get('/canvas', (req, res) => {
  res.sendFile(path.join(WEBVIEW_DIR, 'canvas.html'));
});

app.get('/current-canvas', (req, res) => {
  try {
    if (fs.existsSync(CANVAS_HTML)) {
      res.type('text/html').send(fs.readFileSync(CANVAS_HTML, 'utf8'));
    } else {
      res.type('text/html').send('');
    }
  } catch { res.type('text/html').send(''); }
});

app.post('/canvas-state', (req, res) => {
  const html = req.body?.html || '';
  if (!html) return res.json({ ok: false, error: 'html required' });
  try {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    fs.writeFileSync(CANVAS_HTML, html, 'utf8');
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});
```

- [ ] **Step 3: Add canvas prompt format branch in `formatEnvelopeAsPrompt`**

At the top of `formatEnvelopeAsPrompt` (line ~2611), BEFORE the existing `if (intent.op === 'initial_render')` check, add:

```javascript
  // Canvas co-design mode
  if (bundle.context_mode === 'canvas') {
    const cardContext = (() => {
      const subtree = rs.relevant_subtree;
      if (!subtree || !subtree.target_html || subtree.target_html.length < 50) return '';
      return `\n### Current Canvas State\n\`\`\`html\n${subtree.target_html.substring(0, 8000)}\n\`\`\`\n`;
    })();
    const selectedCtx = (() => {
      const subs = rs.selected_subtrees || {};
      const ids = Object.keys(subs);
      if (ids.length === 0) return '';
      return '\n### Selected Cards\n' + ids.map(id =>
        `**\`${id}\`**:\n\`\`\`html\n${(subs[id].target_html || '').substring(0, 2000)}\n\`\`\``
      ).join('\n') + '\n';
    })();

    return [
      `## Canvas Co-design Request`,
      ``,
      `**Op**: ${intent.op || 'initial_render'}`,
      `**Instruction**: ${intent.instruction || '(none)'}`,
      cardContext,
      selectedCtx,
      `## Canvas HTML Format`,
      ``,
      `All cards must be children of \`<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:3000px;height:2000px;">\`.`,
      ``,
      `Each card:`,
      `\`\`\`html`,
      `<div class="anc-card anc-section anc-section--gc"`,
      `     data-anc="card-[unique-slug]"`,
      `     data-handles="refine,expand,shorten"`,
      `     data-anc-x="80"`,
      `     data-anc-y="80"`,
      `     data-anc-w="320"`,
      `     data-anc-rot="0"`,
      `     data-anc-scale="1"`,
      `     data-anc-z="1"`,
      `     style="position:absolute;left:80px;top:80px;width:320px;transform:rotate(0deg) scale(1);">`,
      `  <!-- Bloom CSS card content -->`,
      `</div>`,
      `\`\`\``,
      ``,
      `**Placement**: grid 4 columns, step (360,280) from (80,80). No overlap.`,
      `**For initial_render or global ops**: Generate all cards and call \`anchor_render(html)\` with the full HTML doc containing the canvas-root.`,
      `**For refine/patch ops on selected cards**: Call \`anchor_patch({patches:[...]})\` — preserve user-set data-anc-x/y/rot unless instruction says to move.`,
      ``,
      anchorLayoutContract(),
    ].join('\n');
  }
```

- [ ] **Step 4: Commit**

```bash
cd "D:/ai-native chrome"
git add mcp/server.cjs
git commit -m "feat(canvas): add /canvas /current-canvas /canvas-state routes + canvas prompt format"
```

---

## Task 7: End-to-end verification

- [ ] **Step 1: Start the Anchor service (if not running)**

```
scripts\start-anchor.bat
```

Or confirm already running: `curl http://localhost:3000/debug/status`

- [ ] **Step 2: Open canvas in browser**

Navigate to: `http://localhost:3000/canvas`

Expected: blank canvas with grid dots, prompt bar at bottom, toolbar at top, "Canvas" title.

- [ ] **Step 3: Send a prompt**

Type in prompt bar: `生成 5 张关于 AI 安全的思考卡` and press Enter.

Expected:
- Status changes to "Sending…" then "Thinking…"
- After ~10-30s, 5 cards appear on the canvas, each with content, positioned in a grid
- Status returns to "Done" → "Live"

- [ ] **Step 4: Test drag**

Drag a card to a new position. Expected: card moves smoothly, stays at new position when releasing.

- [ ] **Step 5: Test rotate**

Click a card to select it (blue outline appears). Drag the purple circular rotate handle above the card. Expected: card rotates.

- [ ] **Step 6: Test resize**

With card selected, drag the SE corner handle. Expected: card gets wider.

- [ ] **Step 7: Test persistence**

Drag a card, then hard-refresh the page (Ctrl+Shift+R). Expected: card appears at the same position (loaded from `output/canvas.html`).

- [ ] **Step 8: Regression — verify existing webview unaffected**

Open `http://localhost:3000`. Expected: normal Anchor blog-flow page, loom-fin tabs working, no visual change.

- [ ] **Step 9: Commit if all tests pass**

```bash
cd "D:/ai-native chrome"
git tag phase0-canvas-mvp
```

---

## Phase 1 (next): Multi-select + Group ops

Tasks to follow once Phase 0 is verified:
- Marquee selection (drag on empty canvas → rect → select cards inside)
- Shift-click multi-select (already supported via `shiftKey` in Step 1 card events — just wire up marquee)
- Floating "Ask AI" prompt near selection rect
- Schema extension: `target_kind: 'group'`, `target_refs: string[]`
- `formatEnvelopeAsPrompt` group branch

## Phase 2 (later): Canvas-state model + Layout suggestion

- `mcp/lib/canvas-state.cjs` module
- New ops: `canvas_create`, `canvas_move`, `canvas_arrange`
- `layout_suggest` event → ghost preview → accept/reject
- Wire `loom/hands/canvas.py` + `loom/hand_registry.py` for Brain enrichment
- `skills/canvas-codesign/SKILL.md`
