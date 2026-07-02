# Loom Completed Content Shelf Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users mark generated Loom canvas content as complete, fold it into an edge shelf, and protect it from later agent or user modification until explicitly restored.

**Architecture:** Add a card-level archive/lock state to the existing canvas runtime first, because `canvas-client.js` already owns selection, card transforms, serialization, undo/redo, and incoming patch application. Persist the state through `data-loom-completed` / `data-loom-locked` attributes and `/canvas-state`, filter archived cards out of active prompt context and agent patches, then later extend the same semantics to block-level selections inside a card.

**Tech Stack:** Anchor canvas HTML/CSS/JS (`bridge/webview/canvas.html`, `bridge/webview/canvas-client.js`, `bridge/webview/canvas-styles.css`), existing `/canvas-state` and `/current-canvas` persistence, Node `node:test` static/regression tests, optional Brain feedback/visual-interaction endpoints in `loom/brain.py`.

---

## Product Intent

The user needs a way to separate finished material from active work. Finished content should stay visible as part of the path/history, but should stop competing for space and should be excluded from future modifications.

The interaction should feel like putting desktop items into a folder at the edge of the workspace:

```text
active canvas cards
  -> user selects completed cards
  -> Archive / Complete action
  -> cards fold to edge shelf
  -> archived cards are locked and excluded from agent patch/refine context
  -> user can restore when needed
```

This is not just a visual collapse. It is a state transition:

- `active`: card can be selected, edited, sent to agent, patched.
- `completed`: card is folded to the edge, visible as a compact shelf item.
- `locked`: card is excluded from direct editing and incoming agent patch updates.
- `restored`: card returns to its last active position and can be modified again.

## MVP Decision

Build phase 1 at card granularity.

Do not implement text-range or partial-card shelving first. The current canvas already has card-level selection and persistence. Browser text range selection inside transformed draggable cards is significantly more fragile and should be a second phase after the state model is proven.

## UX Direction

Use a restrained workbench metaphor:

- Edge shelf on the right side of the canvas viewport.
- Shelf items are narrow strips with title, source card count, and restore button.
- Selected cards fold into the shelf with a short transform animation.
- Archived card bodies do not remain on the active canvas.
- The shelf remains visible while panning/zooming because it is viewport-fixed, not canvas-fixed.

Do not create a decorative folder UI. The goal is workspace control, not skeuomorphic decoration.

## Core Semantics

Archived cards must be excluded in three places:

1. Prompt context:
   - `serializeCanvasHtml()` should omit archived card bodies from the active canvas subtree.
   - The envelope should include `archived_refs` and `locked_refs` as metadata, not as editable HTML.

2. Incoming patches:
   - `applyPatches()` must skip patches targeting locked cards.
   - New patches may create new cards, but cannot overwrite archived content by anchor id.

3. Direct manipulation:
   - Archived cards cannot be selected by marquee.
   - Archived cards cannot enter edit mode.
   - Delete/duplicate/connect operations should ignore archived cards unless restored first.

---

### Task 1: Add Regression Tests for Shelf Semantics

**Files:**
- Modify: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Write failing static tests**

Add tests that assert the canvas client contains the expected feature hooks:

```javascript
test('canvas completed shelf has archive and restore actions', () => {
  assert.match(source, /archiveSelected/);
  assert.match(source, /restoreArchivedCard/);
  assert.match(source, /data-loom-completed/);
  assert.match(source, /data-loom-locked/);
});

test('canvas completed shelf excludes locked cards from patches and prompt context', () => {
  assert.match(source, /archived_refs/);
  assert.match(source, /locked_refs/);
  assert.match(source, /if\s*\(\s*entry\.locked\s*\)\s*return/);
  assert.match(source, /serializeActiveCanvasHtml/);
});
```

**Step 2: Run test to verify it fails**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: fail because shelf functions and attributes are not implemented.

**Step 3: Commit the failing tests**

```powershell
git add bridge\webview\canvas-feedback.test.cjs
git commit -m "test: describe completed canvas shelf behavior"
```

---

### Task 2: Add Toolbar Control and Shelf Container

**Files:**
- Modify: `bridge/webview/canvas.html`
- Modify: `bridge/webview/canvas-styles.css`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Add the toolbar button**

In `bridge/webview/canvas.html`, add a button near the existing snap/connect/export controls:

```html
<button class="canvas-tool-btn" id="canvas-archive-btn" title="Mark selected cards complete">
  <i class="ph-bold ph-archive"></i>
</button>
```

If `ph-archive` is unavailable in Phosphor, use `ph-bold ph-tray` or `ph-bold ph-folder-simple`.

**Step 2: Add the fixed shelf container**

Inside `#canvas-viewport`, after `#canvas-marquee`, add:

```html
<aside id="canvas-completed-shelf" aria-label="Completed content shelf">
  <div class="canvas-shelf-head">
    <i class="ph-bold ph-archive"></i>
    <span>Completed</span>
    <span id="canvas-shelf-count">0</span>
  </div>
  <div id="canvas-shelf-list"></div>
</aside>
```

**Step 3: Add shelf styles**

In `bridge/webview/canvas-styles.css`, add:

```css
#canvas-completed-shelf {
  position: fixed;
  top: 68px;
  right: 12px;
  bottom: 84px;
  width: 176px;
  z-index: 900;
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.canvas-shelf-head {
  height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(248, 247, 244, 0.92);
  backdrop-filter: blur(10px);
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink);
}

#canvas-shelf-count {
  margin-left: auto;
  color: var(--ink-3, rgba(0,0,0,0.45));
  font-variant-numeric: tabular-nums;
}

#canvas-shelf-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
  padding-right: 2px;
}

.canvas-shelf-item {
  min-height: 44px;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(255,255,255,0.76);
  border-radius: 8px;
  padding: 8px;
  box-shadow: 0 8px 20px rgba(0,0,0,0.08);
}

.canvas-shelf-title {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.canvas-shelf-meta {
  margin-top: 3px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: var(--ink-3, rgba(0,0,0,0.45));
}

.canvas-shelf-restore {
  margin-left: auto;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 6px;
  background: rgba(122,90,248,0.10);
  color: var(--accent-brand, #7A5AF8);
  cursor: pointer;
}

.canvas-card-host.canvas-archiving {
  transition: left 180ms ease, top 180ms ease, transform 180ms ease, opacity 180ms ease;
  opacity: 0;
}
```

**Step 4: Run static tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: still fail until JS hooks are implemented, but HTML/CSS should be in place.

**Step 5: Commit**

```powershell
git add bridge\webview\canvas.html bridge\webview\canvas-styles.css
git commit -m "feat: add completed content shelf UI shell"
```

---

### Task 3: Add Card State Fields and Shelf Rendering

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Add DOM refs**

Near existing DOM refs:

```javascript
var archiveBtnEl, shelfEl, shelfListEl, shelfCountEl;
```

In `DOMContentLoaded`:

```javascript
archiveBtnEl = document.getElementById('canvas-archive-btn');
shelfEl = document.getElementById('canvas-completed-shelf');
shelfListEl = document.getElementById('canvas-shelf-list');
shelfCountEl = document.getElementById('canvas-shelf-count');
if (archiveBtnEl) archiveBtnEl.addEventListener('click', archiveSelected);
```

**Step 2: Extend card entries**

In `addCard()`, read persisted attributes from `contentEl`:

```javascript
var completed = contentEl.getAttribute('data-loom-completed') === 'true';
var locked = contentEl.getAttribute('data-loom-locked') === 'true';
var restoreX = parseFloat(contentEl.getAttribute('data-loom-restore-x') || x);
var restoreY = parseFloat(contentEl.getAttribute('data-loom-restore-y') || y);
```

Extend `entry`:

```javascript
completed: completed,
locked: locked,
restoreX: restoreX,
restoreY: restoreY,
restoreW: w,
restoreH: h || 0,
```

If completed:

```javascript
host.style.display = 'none';
```

Call `renderCompletedShelf()` after adding/restoring cards.

**Step 3: Add title helper**

Add:

```javascript
function cardTitle(entry, fallbackId) {
  if (!entry || !entry.contentEl) return fallbackId;
  var heading = entry.contentEl.querySelector('h1,h2,h3,h4,[data-title]');
  var text = heading ? (heading.textContent || '') : (entry.contentEl.textContent || '');
  return text.replace(/\s+/g, ' ').trim().slice(0, 80) || fallbackId;
}
```

**Step 4: Render the shelf**

Add:

```javascript
function renderCompletedShelf() {
  if (!shelfListEl) return;
  var items = [];
  state.cards.forEach(function (entry, id) {
    if (!entry.completed) return;
    items.push({ id: id, entry: entry });
  });

  if (shelfCountEl) shelfCountEl.textContent = String(items.length);
  shelfListEl.innerHTML = '';

  items.forEach(function (item) {
    var row = document.createElement('div');
    row.className = 'canvas-shelf-item';
    row.dataset.cardId = item.id;
    row.innerHTML =
      '<span class="canvas-shelf-title"></span>' +
      '<div class="canvas-shelf-meta">' +
      '<i class="ph-bold ph-lock-simple"></i>' +
      '<span>locked</span>' +
      '<button class="canvas-shelf-restore" title="Restore"><i class="ph-bold ph-arrow-bend-up-left"></i></button>' +
      '</div>';
    row.querySelector('.canvas-shelf-title').textContent = cardTitle(item.entry, item.id);
    row.querySelector('.canvas-shelf-restore').addEventListener('click', function (e) {
      e.stopPropagation();
      restoreArchivedCard(item.id);
    });
    row.addEventListener('dblclick', function () { restoreArchivedCard(item.id); });
    shelfListEl.appendChild(row);
  });
}
```

**Step 5: Run test**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: still fail until archive/restore/filter logic exists.

**Step 6: Commit**

```powershell
git add bridge\webview\canvas-client.js
git commit -m "feat: render completed canvas shelf"
```

---

### Task 4: Archive and Restore Selected Cards

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Implement `archiveSelected()`**

Add:

```javascript
function archiveSelected() {
  if (state.selected.size === 0) return;
  pushUndo();

  var ids = Array.from(state.selected);
  ids.forEach(function (id) {
    var entry = state.cards.get(id);
    if (!entry || entry.completed) return;

    entry.restoreX = entry.x;
    entry.restoreY = entry.y;
    entry.restoreW = entry.w;
    entry.restoreH = entry.h;
    entry.completed = true;
    entry.locked = true;
    entry.localMoved = true;

    stampArchiveAttrs(entry);
    entry.el.classList.add('canvas-archiving');
    setTimeout(function () {
      entry.el.style.display = 'none';
      entry.el.classList.remove('canvas-archiving', 'canvas-selected');
    }, 190);
  });

  clearSelection();
  renderCompletedShelf();
  updateSelectionUI();
  scheduleSync();
  setStatus(ids.length + ' completed', 'live');
}
```

**Step 2: Implement `restoreArchivedCard()`**

Add:

```javascript
function restoreArchivedCard(id) {
  var entry = state.cards.get(id);
  if (!entry || !entry.completed) return;
  pushUndo();

  entry.completed = false;
  entry.locked = false;
  entry.x = Number.isFinite(entry.restoreX) ? entry.restoreX : entry.x;
  entry.y = Number.isFinite(entry.restoreY) ? entry.restoreY : entry.y;
  entry.w = entry.restoreW || entry.w;
  entry.h = entry.restoreH || entry.h;

  clearArchiveAttrs(entry);
  entry.el.style.display = '';
  updateCardTransform(entry);
  renderCompletedShelf();
  scheduleSync();
  setStatus('Restored', 'live');
}
```

**Step 3: Implement attribute helpers**

Add:

```javascript
function stampArchiveAttrs(entry) {
  if (!entry || !entry.contentEl) return;
  entry.contentEl.setAttribute('data-loom-completed', 'true');
  entry.contentEl.setAttribute('data-loom-locked', 'true');
  entry.contentEl.setAttribute('data-loom-restore-x', entry.restoreX);
  entry.contentEl.setAttribute('data-loom-restore-y', entry.restoreY);
  entry.contentEl.setAttribute('data-loom-restore-w', entry.restoreW);
  entry.contentEl.setAttribute('data-loom-restore-h', entry.restoreH);
}

function clearArchiveAttrs(entry) {
  if (!entry || !entry.contentEl) return;
  entry.contentEl.removeAttribute('data-loom-completed');
  entry.contentEl.removeAttribute('data-loom-locked');
  entry.contentEl.removeAttribute('data-loom-restore-x');
  entry.contentEl.removeAttribute('data-loom-restore-y');
  entry.contentEl.removeAttribute('data-loom-restore-w');
  entry.contentEl.removeAttribute('data-loom-restore-h');
}
```

**Step 4: Add keyboard shortcut**

In the keydown handler, add:

```javascript
if (!inInput && e.key === 'e' && !e.ctrlKey && !e.metaKey && state.selected.size > 0) {
  e.preventDefault();
  archiveSelected();
  return;
}
```

Use `E` for "complete" only if it does not conflict with existing canvas editing flow. If it feels too hidden, rely on the toolbar button only.

**Step 5: Run tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: first shelf action test passes; patch/context test may still fail.

**Step 6: Commit**

```powershell
git add bridge\webview\canvas-client.js
git commit -m "feat: archive and restore completed canvas cards"
```

---

### Task 5: Exclude Archived Cards from Prompt Context

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Add active serialization**

Rename or wrap the existing `serializeCanvasHtml()` behavior:

```javascript
function serializeActiveCanvasHtml() {
  return serializeCanvasHtml({ includeArchived: false });
}
```

Change `serializeCanvasHtml()` to accept options:

```javascript
function serializeCanvasHtml(options) {
  options = options || {};
  var includeArchived = options.includeArchived !== false;
  var html = '<div id="canvas-stage" data-anc="canvas-root" style="position:relative;width:' + CANVAS_W + 'px;height:' + CANVAS_H + 'px;">';
  state.cards.forEach(function (entry) {
    if (!includeArchived && entry.completed) return;
    // existing serialization...
  });
  html += '</div>';
  return html;
}
```

**Step 2: Use active serialization in the prompt envelope**

In `sendEnvelope()`, change:

```javascript
target_html: serializeCanvasHtml(),
```

to:

```javascript
target_html: serializeActiveCanvasHtml(),
```

Add archive metadata:

```javascript
archive_state: buildArchiveState(),
```

inside `render_state`.

**Step 3: Add metadata helper**

Add:

```javascript
function buildArchiveState() {
  var archived = [];
  var locked = [];
  state.cards.forEach(function (entry, id) {
    if (entry.completed) archived.push(id);
    if (entry.locked) locked.push(id);
  });
  return {
    archived_refs: archived,
    locked_refs: locked,
  };
}
```

**Step 4: Filter selected subtrees**

In `buildSelectedSubtrees()`:

```javascript
if (entry && entry.locked) return;
```

This prevents a restored-looking but still locked entry from being sent to the agent.

**Step 5: Save full state, not active-only state**

Keep `saveToServer()` using:

```javascript
var html = serializeCanvasHtml({ includeArchived: true });
```

This preserves archived card bodies across reloads.

**Step 6: Run tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: context-related regexes pass except patch filtering if not implemented yet.

**Step 7: Commit**

```powershell
git add bridge\webview\canvas-client.js
git commit -m "feat: omit completed cards from active prompt context"
```

---

### Task 6: Skip Incoming Patches for Locked Cards

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Filter existing-card patches**

In `applyPatches()`, after resolving `entry` and before applying `newCard.innerHTML`:

```javascript
if (entry && entry.locked) {
  setStatus('Skipped locked card update', 'live');
  return;
}
```

Keep this exact structure so the static test can assert it:

```javascript
if (entry.locked) return;
```

or:

```javascript
if (entry && entry.locked) return;
```

**Step 2: Prevent renderFromHtml from overwriting completed cards**

In `renderFromHtml()`, where an existing card is found:

```javascript
if (existing.locked) return;
```

This matters because a full render may include the same `data-anc`.

**Step 3: Do not remove archived cards absent from new render**

Change the removal loop:

```javascript
if (!newIds.has(id) && !card.completed) {
  card.el.remove();
  state.cards.delete(id);
}
```

Archived cards should persist even when agent render omits them.

**Step 4: Run tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: pass.

**Step 5: Commit**

```powershell
git add bridge\webview\canvas-client.js bridge\webview\canvas-feedback.test.cjs
git commit -m "feat: protect completed canvas cards from patches"
```

---

### Task 7: Make Undo/Redo Preserve Completed State

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Extend snapshots**

In `snapshotCards()` add:

```javascript
completed: !!entry.completed,
locked: !!entry.locked,
restoreX: entry.restoreX,
restoreY: entry.restoreY,
restoreW: entry.restoreW,
restoreH: entry.restoreH,
```

**Step 2: Restore fields**

In `restoreSnapshot()`, after restoring transform fields:

```javascript
entry.completed = !!s.completed;
entry.locked = !!s.locked;
entry.restoreX = s.restoreX;
entry.restoreY = s.restoreY;
entry.restoreW = s.restoreW;
entry.restoreH = s.restoreH;
if (entry.completed) {
  stampArchiveAttrs(entry);
  entry.el.style.display = 'none';
} else {
  clearArchiveAttrs(entry);
  entry.el.style.display = '';
}
```

For newly added cards after `addCard()`, set the same fields on the returned entry.

**Step 3: Re-render shelf after restore**

At the end of `restoreSnapshot()`:

```javascript
renderCompletedShelf();
```

**Step 4: Add static test**

Add:

```javascript
test('canvas undo snapshots preserve completed state', () => {
  assert.match(source, /completed:\s*!!entry\.completed/);
  assert.match(source, /locked:\s*!!entry\.locked/);
  assert.match(source, /renderCompletedShelf\(\)/);
});
```

**Step 5: Run tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: pass.

**Step 6: Commit**

```powershell
git add bridge\webview\canvas-client.js bridge\webview\canvas-feedback.test.cjs
git commit -m "feat: preserve completed shelf state in undo"
```

---

### Task 8: Persist Completed State Through Canvas Save/Load

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Optional Modify: `mcp/server.cjs`
- Test: `bridge/webview/canvas-feedback.test.cjs`

**Step 1: Confirm current persistence is enough**

Current `saveToServer()` posts serialized HTML to `/canvas-state`, and `loadSavedCanvas()` calls `renderFromHtml()`. If archived attributes are serialized onto `contentEl`, no server changes should be needed.

**Step 2: Add explicit save payload metadata**

Optionally include metadata in `saveToServer()`:

```javascript
archive_state: buildArchiveState(),
```

This is useful for future server-side filtering, even if v1 does not consume it.

**Step 3: Add static test**

Add:

```javascript
test('canvas save payload includes archive state metadata', () => {
  assert.match(source, /archive_state:\s*buildArchiveState\(\)/);
});
```

**Step 4: Run tests**

Run:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: pass.

**Step 5: Commit**

```powershell
git add bridge\webview\canvas-client.js bridge\webview\canvas-feedback.test.cjs
git commit -m "feat: persist completed shelf metadata"
```

---

### Task 9: Record Completed Shelf Actions as Visual Interactions

**Files:**
- Modify: `bridge/webview/canvas-client.js`
- Modify: `loom/brain.py`
- Test: `tests/test_visual_interaction.py`

**Step 1: Add client-side event post**

Add helper:

```javascript
function recordArchiveInteraction(action, ids) {
  ids = ids || [];
  if (!ids.length) return;
  var first = ids[0];
  var entry = state.cards.get(first);
  var episodeId = entry && entry.el.dataset.episodeId || '';
  if (!episodeId) return;
  fetch('http://localhost:3002/episodes/' + encodeURIComponent(episodeId) + '/visual-interactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      episode_id: episodeId,
      anchor_type: 'canvas_card',
      anchor_id: first,
      gesture: action,
      comment: ids.join(','),
      visual_context: {
        card_anchor_ids: ids,
        archive_action: action,
      },
    }),
  }).catch(function () {});
}
```

Call:

```javascript
recordArchiveInteraction('complete_archive', ids);
recordArchiveInteraction('restore_archive', [id]);
```

**Step 2: Extend signal inference**

In `loom/brain.py` `_infer_signals()`, add:

```python
elif gesture == "complete_archive":
    signals.append({"type": "content_completed", "target": anchor_id, "confidence": 0.9})
elif gesture == "restore_archive":
    signals.append({"type": "content_reactivated", "target": anchor_id, "confidence": 0.85})
```

**Step 3: Write Python test**

In `tests/test_visual_interaction.py`, assert inference:

```python
def test_archive_gestures_infer_completed_content_signals(self):
    signals = brain._infer_signals("complete_archive", "canvas_card", "card-1")
    self.assertEqual("content_completed", signals[0]["type"])
```

**Step 4: Run test**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_visual_interaction
```

Expected: pass.

**Step 5: Commit**

```powershell
git add bridge\webview\canvas-client.js loom\brain.py tests\test_visual_interaction.py
git commit -m "feat: record completed shelf interactions"
```

---

### Task 10: Phase 2 Design for Partial-Card Content Shelving

**Files:**
- Create: `docs/plans/2026-07-01-loom-partial-content-shelf-phase-2.md`

**Step 1: Document why this is separate**

Partial-card shelving requires:

- Text range capture inside transformed cards.
- Stable block identifiers for `sections`, `evidence`, `raw_items`, and arbitrary generated HTML.
- A way to remove or ghost selected blocks without breaking card layout.
- Patch filtering below the card level.

**Step 2: Define stable block identity**

Propose:

```html
<section data-loom-block-id="artifact:t1:section:evidence" data-loom-lockable="true">
```

For existing artifacts, Brain rendering should emit block IDs for:

- `metadata.key_claims[n]`
- `sections[n]`
- `evidence[n]`
- `raw_items[n]`
- `raw_sources[n]`

**Step 3: Define a block shelf record**

```json
{
  "block_id": "artifact:t1:section:evidence",
  "card_id": "loom-market",
  "html": "<section ...>...</section>",
  "title": "Evidence",
  "completed": true,
  "locked": true,
  "restore_policy": "restore_in_original_card"
}
```

**Step 4: Define patch filtering**

For partial-card locks, patch filtering must happen before `entry.contentEl.innerHTML = newCard.innerHTML`; it should merge unlocked blocks and preserve locked blocks from the current DOM.

Do not implement this in phase 1.

**Step 5: Commit**

```powershell
git add docs\plans\2026-07-01-loom-partial-content-shelf-phase-2.md
git commit -m "docs: plan partial content shelving phase two"
```

---

## Final Verification

Run the frontend static tests:

```powershell
node bridge\webview\canvas-feedback.test.cjs
```

Expected: all tests pass.

Run the Python visual interaction test if Task 9 is implemented:

```powershell
D:\conda\python.exe -m unittest tests.test_visual_interaction
```

Expected: pass.

Manual smoke test:

1. Start Anchor.

```powershell
scripts\start-anchor.bat
```

2. Open:

```text
http://localhost:3000/canvas
```

3. Generate several cards.
4. Select one or more cards.
5. Click the archive/shelf toolbar button.
6. Confirm the selected cards fold into the right shelf.
7. Send a new prompt that would normally rewrite the canvas.
8. Confirm archived cards are not modified.
9. Double-click or click restore on a shelf item.
10. Confirm the card returns to its prior position and can be edited again.

## Rollback Plan

If the shelf breaks canvas workflows:

1. Hide the toolbar button and shelf container in `canvas.html`.
2. Keep serialized `data-loom-completed` attributes harmless.
3. Change `serializeActiveCanvasHtml()` to call `serializeCanvasHtml({ includeArchived: true })`.
4. Remove the `entry.locked` guard from `applyPatches()`.

This restores current behavior without deleting archived content from saved canvas state.

## Design Checkpoint

Before implementation, confirm the first interaction granularity:

```text
Recommended MVP: selected cards only.
Later phase: selected text/blocks inside a card.
```

This matches the current canvas architecture and avoids fragile browser selection work in the first pass.
