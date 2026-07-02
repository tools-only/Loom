# Loom Clickable Card Home Detail Pages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the Loom home page into a card-based hierarchy where every major home unit opens a richer Loom detail page in a floating overlay, and generated content follows the same summary-to-detail structure.

**Architecture:** Reuse the existing `LoomDetailOverlay` as the shared drill-down shell, but add a page mode for explicit home-card clicks. Home cards become L4 index entries, overlay pages expose L3 overview, L2 analysis groups, L1 evidence/actions, and L0 raw/source drawers; generated artifacts keep their current L0-L3 Brain/Hand layers and gain metadata that lets the same overlay present them as richer pages.

**Tech Stack:** Static HTML/CSS/vanilla JS in `bridge/webview`, Node built-in `node:test` regression tests, Python renderers in `loom/brain.py`, Brain presentation contract in `loom_core/agents/core_agent.py`.

---

## Context

The current homepage is partly card-like but not fully hierarchical:

- `bridge/webview/index.html:70` contains `#anchor-home` with `home-copy`, `home-prompt`, `home-suggestions`, `home-command-center`, `home-question-lab`, `home-proof-strip`, and `home-domain-grid`.
- `bridge/webview/styles.css:4524` currently collapses the daydream home into a minimal search-first page and hides `home-command-center`, `home-question-lab`, `home-proof-strip`, and `home-domain-grid`.
- `bridge/webview/anchor-client.js:890` binds every `#anchor-home button[data-prompt]` and `#anchor-home button[data-route]` to prompt selection and sometimes route navigation.
- `bridge/webview/anchor-client.js:4380` separately binds `.home-domain-card` clicks to route navigation.
- `bridge/webview/loom-detail-overlay.js:159` initializes a generic detail overlay. Its default interaction is hover-based and requires Ctrl.
- `bridge/webview/loom-detail-overlay.js:296` opens the overlay and renders sections from hidden `aside.anc-detail` content.
- `bridge/webview/loom-detail-overlay.js:525` only treats explicit opt-in elements as detail targets.
- `loom/brain.py:4417` already renders artifact detail sections from `artifact.layers` or `artifact.sections`.
- `loom/brain.py:5286` already renders generated Hand output as `anc-density-card` with visible L3 and hidden L2/L1/L0 detail layers.
- `loom_core/agents/core_agent.py:789` already distinguishes visible and detail layers in the Brain presentation contract.

The change should not make the home page a marketing hero. It should become a dense but readable workspace index: each card previews a domain/workflow/result, and opening it reveals a full Loom display page.

## Product Model

Use one shared hierarchy vocabulary:

- L4 `home-card`: index card on the homepage. Short label, state, one-line preview, icon, optional compact metric.
- L3 `overview`: first view in the floating Loom page. The card's purpose, current status, and primary next action.
- L2 `analysis`: grouped details such as workflow steps, question examples, domain capabilities, or generated analysis sections.
- L1 `evidence`: traceable rows, cards, prompt examples, source notes, or concrete actions.
- L0 `raw`: raw source items, original prompt text, source URLs, diagnostics, and internal metadata.

For generated content, Brain remains owner of final user-facing hierarchy. Hand agents should still return dense raw material; Loom projects it into this hierarchy.

## Non-Goals

- Do not rewrite the Brain/Hand contract from scratch.
- Do not remove existing Ctrl-hover detail behavior for generated cards.
- Do not replace route pages such as `market`, `position`, `target`, or `sentiment`.
- Do not add a separate frontend framework.
- Do not create a landing page or marketing hero.

## UX Rules

- The first screen is a card workspace, not a hero-only search page.
- Every major visible home element is clickable or has an explicit nested action.
- Card click opens detail page mode.
- Primary actions inside a card use compact icon buttons or a distinct `data-home-action` target.
- Prompt submit remains a direct action and must not be hijacked by the card click handler.
- Page mode overlay is larger than the existing hover detail popup and supports scrolling, section navigation, and a close button.
- Use existing Phosphor icon classes already loaded by the app.
- Keep cards at or under 8px border radius unless an existing Loom style requires otherwise. The existing home has larger radii; this plan intentionally introduces a denser card system with tighter radii for new surfaces.
- Avoid nested cards. In the overlay, use full-width bands, rows, tables, and panels rather than card-inside-card layouts.
- Do not hide large home sections on desktop after this change.

---

### Task 1: Add Static Regression Tests For Home Card Coverage

**Files:**

- Create: `bridge/webview/home-card-detail-page.test.cjs`
- Read: `bridge/webview/index.html`
- Read: `bridge/webview/anchor-client.js`
- Read: `bridge/webview/loom-detail-overlay.js`

**Step 1: Write the failing test**

Create `bridge/webview/home-card-detail-page.test.cjs`:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('home page exposes every major section as a drillable home card', () => {
  const index = read('bridge/webview/index.html');

  assert.match(index, /id="anchor-home"/);
  assert.match(index, /data-home-card="ask"/);
  assert.match(index, /data-home-card="operating-model"/);
  assert.match(index, /data-home-card="question-lab"/);
  assert.match(index, /data-home-card="proof-html-first"/);
  assert.match(index, /data-home-card="proof-agent-loop"/);
  assert.match(index, /data-home-card="proof-finance-lanes"/);
  assert.match(index, /data-home-card="domain-market"/);
  assert.match(index, /data-home-card="domain-position"/);
  assert.match(index, /data-home-card="domain-target"/);
  assert.match(index, /data-home-card="domain-sentiment"/);
  assert.match(index, /data-detail-page="loom-home"/);
  assert.match(index, /<template id="home-detail-ask"/);
});

test('home actions are distinct from card page open actions', () => {
  const index = read('bridge/webview/index.html');
  const client = read('bridge/webview/anchor-client.js');

  assert.match(index, /data-home-action="submit"/);
  assert.match(index, /data-home-action="route"/);
  assert.match(index, /data-home-action="prompt"/);
  assert.match(client, /_initHomeCardDetails\(\)/);
  assert.match(client, /closest\('\[data-home-action\]'\)/);
  assert.match(client, /LoomDetailOverlay\.openPage/);
});

test('home card pages use overlay page mode without changing ctrl-hover defaults', () => {
  const overlay = read('bridge/webview/loom-detail-overlay.js');

  assert.match(overlay, /function openPage\(targetOrId/);
  assert.match(overlay, /loom-detail--page/);
  assert.match(overlay, /data-detail-page/);
  assert.match(overlay, /clickToOpen:\s*false/);
  assert.match(overlay, /requireCtrlForHover:\s*true/);
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs
```

Expected: FAIL because `data-home-card`, `_initHomeCardDetails`, and `openPage` do not exist yet.

**Step 3: Commit**

```bash
git add bridge/webview/home-card-detail-page.test.cjs
git commit -m "test: cover home card detail pages"
```

---

### Task 2: Add Home Card Detail Markup And Templates

**Files:**

- Modify: `bridge/webview/index.html:70-186`
- Modify: `bridge/webview/index.html:594-612`
- Test: `bridge/webview/home-card-detail-page.test.cjs`

**Step 1: Convert the visible home shell into card index markup**

In `bridge/webview/index.html`, keep `#anchor-prompt-input`, `#anchor-task-domain`, and `#anchor-prompt-submit` IDs stable. Add explicit card metadata to the major home units.

Use this structure as the target shape, adapting the existing text where needed:

```html
<section id="anchor-home" class="anchor-home" aria-label="Loom home">
  <div class="home-inner home-inner--cards">
    <section class="home-card home-card--ask"
      data-home-card="ask"
      data-detail-root="home.ask"
      data-detail-page="loom-home"
      data-detail-template="home-detail-ask"
      data-detail-title="Ask Loom"
      data-detail-subtitle="Start from a prompt, then let Loom project the result into cards, pages, and canvas anchors.">
      <div class="home-card-head">
        <span class="home-card-icon"><i class="ph-bold ph-sparkle"></i></span>
        <div>
          <p class="home-card-kicker">Start</p>
          <h1>Think it. Live it.</h1>
        </div>
      </div>
      <div class="home-prompt" role="search">
        <i class="ph-bold ph-magnifying-glass"></i>
        <input id="anchor-prompt-input" class="anchor-prompt-input home-prompt-input" type="text" placeholder="选择一个工作模式开始...">
        <select id="anchor-task-domain" class="home-prompt-domain" aria-label="Task domain">
          <option value="market" selected>Market</option>
          <option value="target">Targets</option>
          <option value="position">Portfolio</option>
        </select>
        <label class="home-prompt-visual" title="Render this task into the Loom visual workspace">
          <input id="anchor-visualize-toggle" type="checkbox" checked>
          <span>Visual</span>
        </label>
        <button id="anchor-prompt-submit" class="btn btn--brand home-prompt-submit" type="button" title="Generate" data-home-action="submit">
          <i class="ph-bold ph-arrow-right"></i><span>Generate</span>
        </button>
      </div>
      <div class="home-suggestions" aria-label="Prompt starters">
        <button type="button" data-home-action="prompt" data-route="market" data-prompt="\market 今日市场简报：宏观信号、板块轮动、风险事件"><span>Today Market Brief</span><i class="ph-bold ph-arrow-right"></i></button>
        <button type="button" data-home-action="prompt" data-route="position" data-prompt="\position 基于我的仓位生成一份交易复盘，并标出需要 agent 继续跟进的节点"><span>Portfolio Analysis</span><i class="ph-bold ph-arrow-right"></i></button>
        <button type="button" data-home-action="prompt" data-route="target" data-prompt="\target 为 NVDA、AAPL、TSLA 建立一个可交互的跟踪页面"><span>Target Tracking</span><i class="ph-bold ph-arrow-right"></i></button>
        <button type="button" data-home-action="prompt" data-route="sentiment" data-prompt="\sentiment 把市场情绪、Reddit、Stocktwits 和 Fear & Greed 指标合成一个情绪摘要"><span>Sentiment Pulse</span><i class="ph-bold ph-arrow-right"></i></button>
      </div>
    </section>

    <section class="home-card home-card--workflow"
      data-home-card="operating-model"
      data-detail-root="home.operating-model"
      data-detail-page="loom-home"
      data-detail-template="home-detail-operating-model"
      data-detail-title="Operating Model"
      data-detail-subtitle="How Loom turns generated content into editable anchors and agent tasks.">
      <!-- Move current .home-command-center content here. -->
    </section>

    <section class="home-card home-card--question-lab"
      data-home-card="question-lab"
      data-detail-root="home.question-lab"
      data-detail-page="loom-home"
      data-detail-template="home-detail-question-lab"
      data-detail-title="Question Lab"
      data-detail-subtitle="Common finance questions mapped to Loom routes and generated page structures.">
      <!-- Move current .home-question-lab content here. -->
    </section>

    <section class="home-card-strip" aria-label="Workspace proof points">
      <button class="home-card home-card--proof" type="button"
        data-home-card="proof-html-first"
        data-detail-root="home.proof.html-first"
        data-detail-page="loom-home"
        data-detail-template="home-detail-proof-html-first"
        data-detail-title="HTML-first"
        data-detail-subtitle="Semantic anchors make generated output editable by people and agents.">
        <strong>HTML-first</strong><span>语义锚点可被 AI 精确修改</span>
      </button>
      <button class="home-card home-card--proof" type="button"
        data-home-card="proof-agent-loop"
        data-detail-root="home.proof.agent-loop"
        data-detail-page="loom-home"
        data-detail-template="home-detail-proof-agent-loop"
        data-detail-title="Agent Loop"
        data-detail-subtitle="User actions become structured agent follow-up tasks.">
        <strong>Agent loop</strong><span>浏览器操作直接进入执行队列</span>
      </button>
      <button class="home-card home-card--proof" type="button"
        data-home-card="proof-finance-lanes"
        data-detail-root="home.proof.finance-lanes"
        data-detail-page="loom-home"
        data-detail-template="home-detail-proof-finance-lanes"
        data-detail-title="Finance Lanes"
        data-detail-subtitle="Market, target, position, and sentiment pages stay separated but composable.">
        <strong>Finance lanes</strong><span>市场、标的、仓位、情绪分域沉淀</span>
      </button>
    </section>

    <section class="home-card-grid" aria-label="Domain entries">
      <button class="home-domain-card home-card" type="button"
        data-home-card="domain-market"
        data-home-action="route"
        data-domain="market"
        data-detail-root="home.domain.market"
        data-detail-page="loom-home"
        data-detail-template="home-detail-domain-market"
        data-detail-title="Market Intelligence"
        data-detail-subtitle="Market brief, macro signal, sector rotation, and risk event workspace.">
        <!-- Keep existing domain card inner content. -->
      </button>
      <!-- Repeat for position, target, sentiment. -->
    </section>
  </div>
</section>
```

Important implementation notes:

- If a card contains nested interactive controls, the card click handler from Task 4 must ignore those controls via `data-home-action`.
- The `domain-*` cards can still route when the user clicks their route icon/action. Do not let the primary card open route and detail page at the same time.
- Keep `.home-domain-card` class for existing code until Task 4 updates domain wiring.

**Step 2: Add hidden templates for static home detail pages**

Place the templates before the script tags near `bridge/webview/index.html:594`, after existing page content and before JS includes:

```html
<div id="home-detail-templates" hidden>
  <template id="home-detail-ask">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Ask Loom starts a generated workspace. The home card stays compact; the page view explains what will be rendered and what actions remain available.</p>
    </section>
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="generation-flow" data-detail-label="Generation Flow" data-layer-type="analysis">
      <h3>Generation Flow</h3>
      <ol>
        <li>User chooses a route or prompt.</li>
        <li>Brain plans the visible hierarchy.</li>
        <li>Hands return source-backed material.</li>
        <li>Loom renders cards, anchors, detail layers, and editable canvas blocks.</li>
      </ol>
    </section>
    <section class="anc-detail-section anc-detail-section--sources" data-detail-section="actions" data-detail-label="Actions" data-layer-type="evidence">
      <h3>Actions</h3>
      <ul class="anc-source-list">
        <li><strong>Generate</strong><small>Use the prompt bar to create or update the workspace.</small></li>
        <li><strong>Visual</strong><small>Keep the generated answer projected into the Loom visual workspace.</small></li>
      </ul>
    </section>
  </template>

  <template id="home-detail-operating-model">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>The operating model describes the path from generated content to anchored, editable, replayable work.</p>
    </section>
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="steps" data-detail-label="Steps" data-layer-type="analysis">
      <h3>Steps</h3>
      <ol>
        <li>Render the workspace as semantic HTML.</li>
        <li>Expose anchor handles for refinement, branching, and annotation.</li>
        <li>Route user interactions into agents.</li>
        <li>Patch and replay without losing decision history.</li>
      </ol>
    </section>
  </template>

  <template id="home-detail-question-lab">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Question Lab collects repeatable finance questions and maps each one to the route that can generate a more structured Loom page.</p>
    </section>
    <section class="anc-detail-section anc-detail-section--sources" data-detail-section="question-map" data-detail-label="Question Map" data-layer-type="evidence">
      <h3>Question Map</h3>
      <ul class="anc-source-list">
        <li><strong>Market intelligence</strong><small>Macro, news, catalysts, and risk preference.</small></li>
        <li><strong>Position review</strong><small>Exposure, size, risk drivers, and review triggers.</small></li>
        <li><strong>Target tracking</strong><small>Price, news, earnings, sentiment, and invalidation triggers.</small></li>
        <li><strong>Sentiment synthesis</strong><small>Retail tone, crowding, contrarian risk, and signal quality.</small></li>
      </ul>
    </section>
  </template>

  <template id="home-detail-proof-html-first">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>HTML-first output lets Loom attach stable anchors, detail sections, and action handles to generated content.</p>
    </section>
  </template>

  <template id="home-detail-proof-agent-loop">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Agent loop means clicks, selections, annotations, and refinements become structured follow-up tasks instead of one-off chat messages.</p>
    </section>
  </template>

  <template id="home-detail-proof-finance-lanes">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Finance lanes keep market, target, position, and sentiment work separated enough to edit safely while still allowing Brain to synthesize them.</p>
    </section>
  </template>

  <template id="home-detail-domain-market">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Market Intelligence turns macro signals, sector rotation, news catalysts, and risk events into a structured page.</p>
    </section>
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="expected-page" data-detail-label="Expected Page" data-layer-type="analysis">
      <h3>Expected Page</h3>
      <ul>
        <li>Regime judgment</li>
        <li>Driver groups</li>
        <li>Evidence rows</li>
        <li>Source freshness and gaps</li>
      </ul>
    </section>
  </template>

  <template id="home-detail-domain-position">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Position Management converts holdings and review questions into exposure, risk, and action constraints.</p>
    </section>
  </template>

  <template id="home-detail-domain-target">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Target Tracking creates a persistent object around a ticker or company with triggers, catalysts, sources, and monitoring state.</p>
    </section>
  </template>

  <template id="home-detail-domain-sentiment">
    <section class="anc-detail-section anc-detail-section--content" data-detail-section="overview" data-detail-label="Overview" data-layer-type="summary">
      <h3>Overview</h3>
      <p>Sentiment Monitoring groups crowd tone, positioning, contrarian risk, and signal quality into a reviewable page.</p>
    </section>
  </template>
</div>
```

**Step 3: Run the coverage test**

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs
```

Expected: still FAIL because the JS page-mode API is not implemented.

**Step 4: Commit**

```bash
git add bridge/webview/index.html bridge/webview/home-card-detail-page.test.cjs
git commit -m "feat: mark home sections as detail cards"
```

---

### Task 3: Extend LoomDetailOverlay With Explicit Page Mode

**Files:**

- Modify: `bridge/webview/loom-detail-overlay.js:69-74`
- Modify: `bridge/webview/loom-detail-overlay.js:244-312`
- Modify: `bridge/webview/loom-detail-overlay.js:321-404`
- Modify: `bridge/webview/loom-detail-overlay.js:516-547`
- Test: `bridge/webview/home-card-detail-page.test.cjs`
- Test: `bridge/webview/detail-overlay.regression.test.cjs`

**Step 1: Add a close button and page-mode state**

In `ensureOverlay()`, update the header markup:

```js
overlay.innerHTML = [
  '<div class="loom-detail-backdrop"></div>',
  '<article class="loom-detail-card" role="dialog" aria-modal="true" aria-labelledby="loom-detail-title">',
  '  <header class="loom-detail-header">',
  '    <div>',
  '      <h2 id="loom-detail-title" class="loom-detail-title"></h2>',
  '      <div class="loom-detail-subtitle"></div>',
  '    </div>',
  '    <button class="loom-detail-close" type="button" title="Close"><i class="ph-bold ph-x"></i></button>',
  '  </header>',
  '  <div class="loom-detail-pills"></div>',
  '  <nav class="loom-detail-tabs" role="tablist"></nav>',
  '  <div class="loom-detail-body"></div>',
  '</article>'
].join('');
```

After `card` is found, wire close:

```js
var closeBtn = overlay.querySelector('.loom-detail-close');
if (closeBtn) closeBtn.addEventListener('click', close);
```

**Step 2: Add `openPage` next to `open`**

Add:

```js
function openPage(targetOrId, contentEl) {
  ensureOverlay();
  var target = contentEl || resolveTarget(targetOrId);
  if (!target) return false;

  clearHover();
  cancelClose();
  activeTarget = target;
  overlay.classList.add('loom-detail--page');
  renderTarget(target, targetOrId, { pageMode: true });
  _renderDensityBar(overlay);
  _filterSectionsByDensity(overlay);
  centerCard({ pageMode: true });
  requestAnimationFrame(function () {
    overlay.classList.add('loom-detail--open');
  });
  return true;
}
```

Update `open()` to clear page mode:

```js
overlay.classList.remove('loom-detail--page');
renderTarget(target, targetOrId, { pageMode: false });
centerCard({ pageMode: false });
```

Update `close()`:

```js
overlay.classList.remove('loom-detail--open');
overlay.classList.remove('loom-detail--page');
```

**Step 3: Let render target read templates**

Change function signature:

```js
function renderTarget(target, fallbackId, renderOptions) {
  renderOptions = renderOptions || {};
  ...
}
```

Before `collectFallbackSections(target)`, collect template sections:

```js
var sections = collectSections(target);
if (!sections.length) {
  sections = collectTemplateSections(target);
}
if (!sections.length) {
  sections = collectFallbackSections(target);
}
```

Add:

```js
function collectTemplateSections(target) {
  var templateId = target.getAttribute('data-detail-template');
  if (!templateId) return [];
  var tpl = document.getElementById(templateId);
  if (!tpl || !('content' in tpl)) return [];
  var host = document.createElement('div');
  host.appendChild(tpl.content.cloneNode(true));
  var sections = [];
  host.querySelectorAll('[data-detail-section], .anc-detail-section').forEach(function (section) {
    sections.push(sectionFromElement(section));
  });
  return sections;
}
```

**Step 4: Treat home detail pages as explicit targets**

Update `refresh()` selector:

```js
root.querySelectorAll('[data-detail-root], [data-has-detail="true"], [data-detail-page], aside.anc-detail').forEach(function (el) {
```

Update `isDetailTarget()`:

```js
return el.hasAttribute('data-detail-root') ||
  el.hasAttribute('data-detail-page') ||
  el.getAttribute('data-has-detail') === 'true' ||
  !!el.querySelector('aside.anc-detail');
```

Update `getTitle()` if needed so `data-detail-title` wins:

```js
return target.getAttribute('data-detail-title') ||
  cleanText(target.querySelector('h1,h2,h3,strong,.domain-card-title,.home-card-title')?.textContent || '');
```

**Step 5: Export the new API**

At the bottom export object, add `openPage`:

```js
window.LoomDetailOverlay = {
  init: init,
  refresh: refresh,
  open: open,
  openPage: openPage,
  close: close
};
```

**Step 6: Run overlay tests**

Run:

```bash
node --test bridge/webview/detail-overlay.regression.test.cjs bridge/webview/home-card-detail-page.test.cjs
```

Expected: `detail-overlay.regression.test.cjs` should PASS and home test should now pass its overlay assertions, though it may still fail for `anchor-client.js` wiring.

**Step 7: Commit**

```bash
git add bridge/webview/loom-detail-overlay.js bridge/webview/home-card-detail-page.test.cjs
git commit -m "feat: add page mode to loom detail overlay"
```

---

### Task 4: Wire Home Card Clicks Separately From Home Actions

**Files:**

- Modify: `bridge/webview/anchor-client.js:70-73`
- Modify: `bridge/webview/anchor-client.js:890-917`
- Modify: `bridge/webview/anchor-client.js:4380-4387`
- Test: `bridge/webview/home-card-detail-page.test.cjs`

**Step 1: Initialize home card detail wiring**

In `Anchor.init()`, after `_initHomeSuggestions()` add:

```js
this._initHomeCardDetails();
```

**Step 2: Add `_initHomeCardDetails`**

Add near `_initHomeSuggestions()`:

```js
_initHomeCardDetails() {
  const home = document.getElementById('anchor-home');
  if (!home || home.__loomHomeCardDetailsBound) return;
  home.__loomHomeCardDetailsBound = true;

  home.addEventListener('click', (event) => {
    if (event.target.closest('[data-home-action]')) return;
    if (event.target.closest('input, textarea, select, label, a')) return;

    const card = event.target.closest('[data-home-card][data-detail-page]');
    if (!card || !home.contains(card)) return;
    event.preventDefault();
    event.stopPropagation();

    if (window.LoomDetailOverlay && typeof window.LoomDetailOverlay.openPage === 'function') {
      window.LoomDetailOverlay.openPage(card);
    }
  });
}
```

**Step 3: Narrow prompt-suggestion wiring to prompt actions**

Replace:

```js
document.querySelectorAll('#anchor-home button[data-prompt], #anchor-home button[data-route]').forEach(btn => {
```

with:

```js
document.querySelectorAll('#anchor-home [data-home-action="prompt"][data-prompt]').forEach(btn => {
```

Keep existing prompt-selection behavior. Do not auto-route on selection unless the existing behavior is required; if keeping route navigation, make sure it only happens for `data-home-action="prompt"` and not for card open clicks.

**Step 4: Update domain card route handling**

Change `_initDomainCards()` so it only routes when the click came from route intent:

```js
function _initDomainCards() {
  document.querySelectorAll('.home-domain-card[data-domain]').forEach(card => {
    card.addEventListener('click', (event) => {
      if (!event.target.closest('[data-home-action="route"]')) return;
      const domain = card.dataset.domain;
      if (domain) _openDomain(domain);
    });
  });
}
```

If the whole domain card should open the detail page and a small icon should route, add the icon action inside each domain card:

```html
<span class="domain-card-route" data-home-action="route" title="Open route">
  <i class="ph-bold ph-arrow-right"></i>
</span>
```

**Step 5: Run tests**

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs bridge/webview/detail-overlay.regression.test.cjs
```

Expected: PASS.

**Step 6: Commit**

```bash
git add bridge/webview/anchor-client.js bridge/webview/index.html
git commit -m "feat: separate home card details from home actions"
```

---

### Task 5: Build The Card-Based Home Layout

**Files:**

- Modify: `bridge/webview/styles.css:4524-4728`
- Modify: `bridge/webview/styles.css:3927-4418`
- Modify: `bridge/webview/loom-detail-overlay.css:31-229`
- Test: `bridge/webview/styles.regression.test.cjs`
- Test: `bridge/webview/home-card-detail-page.test.cjs`

**Step 1: Add layout assertions**

Extend `bridge/webview/home-card-detail-page.test.cjs`:

```js
test('home card layout does not hide the hierarchy on desktop', () => {
  const styles = read('bridge/webview/styles.css');

  assert.match(styles, /\.home-inner--cards/);
  assert.match(styles, /\.home-card\b/);
  assert.match(styles, /\.home-card-grid/);
  assert.match(styles, /\.home-card-strip/);
  assert.doesNotMatch(styles, /\.home-inner--cards[\s\S]{0,240}\.home-command-center,[\s\S]{0,240}display:\s*none/);
});

test('detail overlay page mode has a larger page-like layout', () => {
  const css = read('bridge/webview/loom-detail-overlay.css');

  assert.match(css, /#loom-detail-overlay\.loom-detail--page/);
  assert.match(css, /\.loom-detail--page\s+\.loom-detail-card/);
  assert.match(css, /--loom-detail-page-w/);
  assert.match(css, /\.loom-detail-close/);
});
```

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs
```

Expected: FAIL.

**Step 2: Add home card CSS**

In `bridge/webview/styles.css`, append a new section after the current home styles so it wins the cascade:

```css
/* Home card hierarchy workspace. */
.home-inner--cards {
  width: min(1180px, 100%);
  min-height: calc(100vh - 170px);
  display: grid;
  grid-template-columns: minmax(420px, 1.08fr) minmax(360px, 0.92fr);
  grid-auto-rows: min-content;
  align-content: start;
  gap: 14px;
  text-align: left;
}

.home-inner--cards::before {
  display: none;
}

.home-card {
  position: relative;
  min-width: 0;
  border: 1px solid rgba(18, 24, 38, 0.10);
  border-radius: 8px;
  background: rgba(255,255,255,0.82);
  color: var(--fg-1);
  box-shadow: 0 16px 38px -32px rgba(17,24,39,0.52);
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 180ms ease, background 180ms ease;
}

.home-card[data-detail-page] {
  cursor: pointer;
}

.home-card[data-detail-page]:hover,
.home-card[data-detail-page]:focus-visible {
  transform: translateY(-2px);
  border-color: rgba(74, 95, 208, 0.26);
  box-shadow: 0 22px 46px -34px rgba(17,24,39,0.62);
  outline: none;
}

.home-card--ask {
  grid-column: 1;
  padding: 18px;
}

.home-card--workflow {
  grid-column: 2;
  grid-row: span 2;
  padding: 16px;
}

.home-card--question-lab {
  grid-column: 1 / -1;
  padding: 16px;
}

.home-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.home-card-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(74, 95, 208, 0.12);
  color: #3348b8;
  flex: 0 0 auto;
}

.home-card-kicker {
  margin: 0 0 3px;
  color: var(--fg-3);
  font-size: 11px;
  font-weight: 760;
  text-transform: uppercase;
  letter-spacing: 0;
}

.home-inner--cards .home-copy,
.home-inner--cards .home-command-center,
.home-inner--cards .home-question-lab,
.home-inner--cards .home-proof-strip,
.home-inner--cards .home-domain-grid {
  display: contents;
}

.home-inner--cards h1 {
  margin: 0;
  font-size: 38px;
  line-height: 1.04;
  letter-spacing: 0;
  color: var(--fg-1);
}

.home-card-strip {
  grid-column: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.home-card--proof {
  min-height: 94px;
  padding: 13px;
  text-align: left;
  font: inherit;
}

.home-card-grid {
  grid-column: 2;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.home-inner--cards .home-domain-card {
  min-height: 96px;
  align-items: flex-start;
  padding: 14px;
}

.domain-card-route {
  position: absolute;
  right: 12px;
  top: 12px;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(255,255,255,0.74);
  color: #3348b8;
}

@media (max-width: 1100px) {
  .home-inner--cards {
    grid-template-columns: 1fr;
  }

  .home-card--ask,
  .home-card--workflow,
  .home-card--question-lab,
  .home-card-strip,
  .home-card-grid {
    grid-column: 1;
    grid-row: auto;
  }
}

@media (max-width: 720px) {
  .home-card-strip,
  .home-card-grid,
  .question-grid {
    grid-template-columns: 1fr;
  }

  .home-inner--cards h1 {
    font-size: 30px;
  }

  .home-card--ask,
  .home-card--workflow,
  .home-card--question-lab {
    padding: 14px;
  }
}
```

Remove or override the current minimal-search rule that hides major home hierarchy:

```css
.home-inner--daydream .home-command-center,
.home-inner--daydream .home-question-lab,
.home-inner--daydream .home-proof-strip,
.home-inner--daydream .home-domain-grid {
  display: none;
}
```

Do not leave that rule active for `.home-inner--cards`.

**Step 3: Add overlay page-mode CSS**

In `bridge/webview/loom-detail-overlay.css`, add:

```css
#loom-detail-overlay {
  --loom-detail-page-w: min(1120px, calc(100vw - 40px));
}

.loom-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.loom-detail-close {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(18, 24, 38, 0.10);
  border-radius: 8px;
  background: rgba(255,255,255,0.72);
  color: var(--fg-2, #555);
  cursor: pointer;
}

#loom-detail-overlay.loom-detail--page {
  pointer-events: auto;
}

#loom-detail-overlay.loom-detail--page .loom-detail-backdrop {
  pointer-events: auto;
}

.loom-detail--page .loom-detail-card {
  left: 50%;
  top: 50%;
  width: var(--loom-detail-page-w);
  max-height: min(88vh, 920px);
  border-radius: 12px;
  transform: translate(-50%, -46%) scale(0.98);
}

#loom-detail-overlay.loom-detail--open.loom-detail--page .loom-detail-card {
  transform: translate(-50%, -50%) scale(1);
}

.loom-detail--page .loom-detail-body {
  padding: 0;
}

.loom-detail--page .loom-detail-panel--active {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  padding: 18px 22px 24px;
}
```

**Step 4: Run tests**

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs bridge/webview/styles.regression.test.cjs bridge/webview/detail-overlay.regression.test.cjs
```

Expected: PASS.

**Step 5: Commit**

```bash
git add bridge/webview/styles.css bridge/webview/loom-detail-overlay.css bridge/webview/home-card-detail-page.test.cjs
git commit -m "style: render home as a card hierarchy"
```

---

### Task 6: Add Richer Page Sections For Generated Content

**Files:**

- Modify: `loom/brain.py:4417-4471`
- Modify: `loom/brain.py:5285-5317`
- Modify: `loom_core/agents/core_agent.py:789-807`
- Test: create `tests/test_loom_detail_hierarchy.py` or extend the nearest existing Python renderer test if one exists

**Step 1: Write renderer tests**

First find existing Python tests:

```bash
rg --files -g '*test*.py'
```

If no direct renderer test exists, create `tests/test_loom_detail_hierarchy.py`:

```python
from loom.brain import _render_artifact


def test_artifact_cards_declare_loom_detail_page_and_levels():
    html = _render_artifact(
        {
            "narrative": "Market risk is mixed.",
            "sections": [
                {"id": "analysis", "title": "Drivers", "summary": "Rates and breadth matter.", "bullets": ["Rates up", "Breadth narrow"]},
            ],
            "evidence": [
                {"claim": "Rates are a headwind", "support": "10Y yield rose", "source": "market-data", "freshness": "today", "confidence": 0.7},
            ],
            "metadata": {"key_claims": ["Mixed regime"], "gaps": ["Need updated breadth"], "source_notes": []},
            "raw_items": [{"title": "Raw signal", "summary": "Breadth sample", "url": "https://example.test"}],
            "raw_sources": [{"id": "src-1", "source_type": "data", "summary": "Market data"}],
        },
        "market",
    )

    assert 'data-has-detail="true"' in html
    assert 'data-detail-page="loom-generated"' in html
    assert 'data-card-level="l4-summary"' in html
    assert 'data-density="l3"' in html
    assert 'data-density="l2"' in html
    assert 'data-density="l1"' in html
    assert 'data-density="l0"' in html
    assert 'data-layer-type="analysis"' in html
    assert 'data-layer-type="evidence"' in html
    assert 'data-layer-type="raw_item"' in html
```

Run:

```bash
python -m pytest tests/test_loom_detail_hierarchy.py -q
```

Expected: FAIL because `data-detail-page="loom-generated"` and `data-card-level` do not exist yet.

**Step 2: Add generated card metadata**

In `loom/brain.py:5286`, change the opening section:

```python
parts: list[str] = [
    (
        f'<section class="anc-section anc-section--gc anc-density-card" '
        f'data-anc="{anchor_id}" data-handles="refine" data-has-detail="true" '
        f'data-detail-page="loom-generated" data-card-level="l4-summary" '
        f'data-detail-title="{label}" data-detail-subtitle="{html.escape(hand_id)} generated detail hierarchy">'
    ),
    ...
]
```

Keep the existing `data-density="l3/l2/l1/l0"` layers.

**Step 3: Add stable section labels for page mode**

In `_render_artifact_sections`, map layer types to better detail labels when `layer.get("title")` is missing:

```python
_LT_LABELS = {
    "summary": "Overview",
    "analysis": "Analysis",
    "evidence": "Evidence",
    "gaps": "Gaps",
    "raw_source": "Raw Sources",
    "raw_item": "Raw Items",
}
title = _html_text(layer.get("title") or _LT_LABELS.get(str(layer.get("layer_type", "")).lower()) or layer.get("id") or f"Layer {idx + 1}")
```

**Step 4: Update Brain presentation contract to name the page hierarchy**

In `loom_core/agents/core_agent.py:789`, add a page hierarchy field under `ui_contract`:

```python
"page_hierarchy": {
    "l4": "home or canvas summary card",
    "l3": "visible overview",
    "l2": "expandable analysis groups",
    "l1": "structured evidence and source notes",
    "l0": "raw items, raw sources, diagnostics",
},
```

Do not make Hands produce display HTML. This is guidance for structured artifact material only.

**Step 5: Run Python tests**

Run:

```bash
python -m pytest tests/test_loom_detail_hierarchy.py -q
```

Expected: PASS.

If this repo does not use `pytest`, use the existing Python test runner discovered by `rg --files -g '*test*.py'`.

**Step 6: Commit**

```bash
git add loom/brain.py loom_core/agents/core_agent.py tests/test_loom_detail_hierarchy.py
git commit -m "feat: tag generated cards with detail hierarchy"
```

---

### Task 7: Add Page-Mode Source Resolution For Future Dynamic Detail Data

**Files:**

- Modify: `bridge/webview/loom-detail-overlay.js`
- Test: `bridge/webview/home-card-detail-page.test.cjs`

**Step 1: Add a deferred detail-source contract test**

Add to `bridge/webview/home-card-detail-page.test.cjs`:

```js
test('detail overlay can resolve page content from template or inline detail sections', () => {
  const overlay = read('bridge/webview/loom-detail-overlay.js');

  assert.match(overlay, /function collectTemplateSections\(target\)/);
  assert.match(overlay, /function collectSections\(target\)/);
  assert.match(overlay, /collectTemplateSections\(target\)/);
});
```

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs
```

Expected: PASS after Task 3.

**Step 2: Add placeholder support for dynamic endpoints, behind metadata only**

Do not fetch dynamic data yet. Add a helper that reads a URL if present but returns no sections:

```js
function getDetailSource(target) {
  return {
    template: target.getAttribute('data-detail-template') || '',
    endpoint: target.getAttribute('data-detail-endpoint') || '',
    page: target.getAttribute('data-detail-page') || ''
  };
}
```

Use it inside `collectTemplateSections`:

```js
var source = getDetailSource(target);
var templateId = source.template;
```

This creates a stable extension point for a later endpoint such as `/episodes/{episode_id}/hierarchy` without adding async overlay complexity in this iteration.

**Step 3: Run tests**

Run:

```bash
node --test bridge/webview/home-card-detail-page.test.cjs bridge/webview/detail-overlay.regression.test.cjs
```

Expected: PASS.

**Step 4: Commit**

```bash
git add bridge/webview/loom-detail-overlay.js bridge/webview/home-card-detail-page.test.cjs
git commit -m "refactor: centralize detail page source metadata"
```

---

### Task 8: Manual UI Verification

**Files:**

- No source edits expected unless verification reveals layout issues.

**Step 1: Start the app**

Run:

```bash
npm run dev
```

Expected: Electron opens Loom.

**Step 2: Verify home card behavior**

Check:

- Home is a card dashboard, not only a large hero and search bar.
- Ask card is visible and prompt input still focuses normally.
- Clicking card background opens a large floating Loom page.
- Clicking `Generate` submits, not opens a detail page.
- Clicking suggestion buttons still fills the prompt and selected route.
- Domain cards open detail page from card body.
- Domain card route icon navigates to the route.
- `Esc` closes the page overlay.
- The close icon closes the page overlay.
- On mobile-sized window, cards stack without text overflow.

**Step 3: Verify generated content behavior**

Generate one visual task. Check:

- Brain synthesis and Hand cards still render.
- Ctrl-hover detail overlay still works for generated cards.
- Explicit page-mode opening works if you add a temporary manual call in DevTools:

```js
LoomDetailOverlay.openPage(document.querySelector('.anc-density-card'))
```

- L3 overview, L2 analysis, L1 evidence, and L0 raw sections are visible through tabs/density controls when present.

**Step 4: Run full relevant regression suite**

Run:

```bash
node --test bridge/webview/*.test.cjs
```

Expected: PASS.

Run the Python tests selected in Task 6.

Expected: PASS.

**Step 5: Commit any verification fixes**

If layout or interaction fixes were needed:

```bash
git add bridge/webview/index.html bridge/webview/styles.css bridge/webview/anchor-client.js bridge/webview/loom-detail-overlay.css bridge/webview/loom-detail-overlay.js
git commit -m "fix: polish home card detail interactions"
```

---

### Task 9: Optional Follow-Up - Dynamic Episode Detail Pages

**Files:**

- Modify: `loom/brain.py`
- Modify: `bridge/webview/loom-detail-overlay.js`
- Create: `bridge/webview/generated-detail-page.test.cjs`

Only do this after the static card system is stable.

**Step 1: Add a backend endpoint**

Add an endpoint near `loom/brain.py:5320`:

```python
@app.get("/episodes/{episode_id}/hierarchy")
async def episode_hierarchy(episode_id: str):
    detail = _flywheel.load_detail(episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {episode_id}"}
    return {
        "ok": True,
        "episode_id": episode_id,
        "question": detail.get("question", ""),
        "presentation": detail.get("presentation", {}),
        "hand_artifacts": detail.get("hand_artifacts", {}),
        "synthesis": detail.get("synthesis", {}),
    }
```

**Step 2: Add async overlay loading**

Add support for:

```html
data-detail-endpoint="http://localhost:3002/episodes/{episode_id}/hierarchy"
```

Do not block Task 1-8 on this. Static templates and inline detail sections already satisfy the requested hierarchy.

---

## Implementation Order

1. Add tests for home card detail coverage.
2. Add home card metadata and templates.
3. Extend `LoomDetailOverlay` with page mode.
4. Split card-open clicks from prompt/route actions.
5. Build the denser card dashboard layout.
6. Tag generated content with page hierarchy metadata.
7. Add source-resolution extension point.
8. Manually verify UI.
9. Optionally add dynamic episode detail endpoint.

## Risk Notes

- The current homepage has multiple late CSS overrides. Put new `.home-inner--cards` rules late in `styles.css` or remove conflicting minimal-search rules.
- `anchor-client.js` currently binds broad `button[data-route]` selectors. Narrow this before making whole cards clickable.
- `LoomDetailOverlay` currently closes when Ctrl is released because hover mode requires Ctrl. Page mode must not close on Ctrl keyup; update the keyup handler to only close on Control when `!overlay.classList.contains('loom-detail--page')`.
- Generated content already uses `data-has-detail="true"`; adding `data-detail-page` must not make every hover target open page mode. Only explicit home-card clicks or direct `openPage()` calls should use page mode.
- Avoid adding a new overlay implementation. Two overlays would make density controls, close behavior, keyboard behavior, and future completed-content shelving harder to maintain.

## Definition Of Done

- `#anchor-home` renders as a hierarchy of clickable cards.
- Every major home unit has `data-home-card`, `data-detail-page`, and a detail template or inline detail sections.
- Clicking card bodies opens a larger floating Loom display page.
- Prompt, suggestion, and route actions remain explicit and functional.
- Generated cards keep existing Ctrl-hover detail behavior.
- Generated cards expose stable hierarchy metadata for page-mode expansion.
- Relevant Node and Python tests pass.
- Manual verification confirms no text overlap on desktop or mobile-sized windows.
