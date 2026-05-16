# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Anchor is a bidirectional interaction loop where HTML is the shared language between user and AI.

### Primary Path: MCP Server (auto-starts with Claude Code)

The **MCP server** (`mcp/server.cjs`) is registered in `.claude/mcp.json` and auto-starts when Claude Code opens this project. It provides:

- **Tool `anchor_render(html)`** — push complete HTML to webview at http://localhost:3000. Also writes `output/current.html` as a side effect and records to session.
- **Tool `anchor_get_pending_op()`** — get and clear the pending user op from the webview. Returns `{pending:true, op, current_html}` or `{pending:false}`.
- **Tool `anchor_get_html()`** — get the currently rendered HTML.
- **Tool `anchor_emit_event(type, payload)`** — emit intermediate agent events (thinking / tool_call / partial_render / decision / complete / error) to the webview timeline panel.
- **Tool `anchor_replay_session(session_id, up_to_event_id?)`** — read back events from a recorded session.
- **Resource `anchor://pending-op`** — subscribable; server sends `notifications/resources/updated` when user interacts.

The loop: `Claude calls anchor_render(html) → MCP broadcasts to webview → user clicks handle → MCP stores op, notifies subscribers → Stop hook detects pending.md → Claude calls anchor_get_pending_op() → Claude processes op → calls anchor_render(new HTML) → repeat`

### Fallback: Hooks + Bridge

For backward compatibility, `bridge/server.js` can also be run manually (`cd bridge && node server.js`). Hooks in `hooks/anchor-hook.cjs` (PostToolUse + Stop) forward HTML and feed back ops via file-system. The MCP server handles the same HTTP/WS protocol on port 3000.

## Commands

```bash
# Install dependencies (first time)
cd bridge && npm install

# The MCP server auto-starts with Claude Code — no manual step needed.
# If running bridge manually:
cd bridge && node server.js
```

Then open http://localhost:3000 in a browser.

## Key directories

| Directory | Purpose |
|-----------|---------|
| `mcp/` | **MCP server** (auto-start, primary interface) |
| `bridge/` | Express + WebSocket server, webview frontend (legacy/manual) |
| `bridge/webview/` | Static HTML, CSS, vanilla JS client |
| `hooks/` | Claude Code hook (anchor-hook.cjs) — fallback loop |
| `output/` | AI-generated HTML (`current.html`) |
| `prompts/` | User interaction prompts (`pending.md`) |
| `logs/` | Operation log (`ops.jsonl`) |

## Anchor HTML Protocol

When generating HTML for Anchor, annotate semantic elements:

```html
<section data-anc="findings"
         data-handles="refine,expand,lock"
         data-deps="data-1,data-2">
  <h2>Findings</h2>
  <p data-anc="findings.summary"
     data-handles="refine,shorten,longer,edit">
    Revenue grew 23% YoY...
  </p>
</section>
```

### Attributes
- `data-anc` — unique, stable anchor id (dot-separated for hierarchy)
- `data-handles` — comma-separated list of allowed ops: refine, lock, expand, shorten, longer, edit, annotate, branch, restructure
- `data-deps` — comma-separated list of anchor ids this element depends on

### Available Ops
| Op | Meaning |
|----|---------|
| `refine` | Local modification with natural language |
| `lock` | Lock element from future regeneration |
| `expand` | Add more detail |
| `shorten` | Make more concise |
| `longer` | Make more detailed |
| `edit` | Direct text edit |
| `annotate` | Add a note/constraint |
| `branch` | Generate alternative version |
| `restructure` | Modify the skeleton/structure |

## CSS Class System

All styles use the **Bloom Design System** (`resource/colors_and_type.css`). Design tokens are CSS variables — use `var(--pastel-*)`, `var(--accent-*)`, `var(--ink)`, `var(--paper)`, etc. Never write hard-coded colors, shadows, or radii. The webview shell auto-includes Bloom tokens + Phosphor Icons CDN. Never reference external CSS or icon libraries.

### Section Cards

All section cards use the **gradient card system** from card1.html. Every colored modifier maps to one of the 10 themes below.

```html
<!-- Neutral outer section (no color modifier) — for containing gradient KPI cards -->
<section class="anc-section anc-section--gc" data-anc="id" data-handles="...">
  <h2>Section Title</h2>
  <div class="anc-kpi-grid">
    <div class="anc-kpi anc-kpi--aurora">...</div>
  </div>
</section>

<!-- Colored section — only when NOT containing colored KPI cards -->
<section class="anc-section anc-section--gc anc-section--arctic" data-anc="id" data-handles="...">
  <h2>Standalone Section</h2>
</section>
```

**Rule**: Do NOT nest colored gradient cards inside colored gradient sections. Outer section cards use `anc-section--gc` without a color modifier (neutral white). Inner KPI cards get gradient color themes.

#### 7 Gradient Themes (card1.html)

| KPI class | Section class | Name | Colors |
|-----------|--------------|------|--------|
| `anc-kpi--warm` | `anc-section--warm` | Warm | coral × lavender |
| `anc-kpi--cool` | `anc-section--cool` | Cool | teal × sky blue |
| `anc-kpi--aurora` | `anc-section--aurora` | Aurora | indigo × emerald |
| `anc-kpi--ocean` | `anc-section--ocean` | Ocean | deep blue × coral |
| `anc-kpi--berry` | `anc-section--berry` | Berry | deep purple × wine |
| `anc-kpi--arctic` | `anc-section--arctic` | Arctic | ice blue × mint |
| `anc-kpi--flame` | `anc-section--flame` | Flame | orange × deep rose |

### Buttons (pill-shaped, fully rounded)

```html
<button class="btn btn--brand">Action</button>
<button class="btn btn--ghost">Cancel</button>
```

All buttons use `border-radius: 999px` (fully pill-shaped). Hover: `translateY(-1px)` + shadow growth. Active: `scale(0.97)`.

- `btn` — base button (pill, 10px 22px padding)
- `btn--brand` — Iris (#7A5AF8) accent, white text
- `btn--pink` — Hot pink accent, dark text
- `btn--green` — Lime accent, dark text
- `btn--ghost` — transparent with ink border, reverses on hover
- `btn--sm` / `btn--lg` — size modifiers
- `btn--icon` — circular 40×40 icon button

### Status Pills

```html
<span class="anc-pill anc-pill--active">Active</span>
```

- `anc-pill--lock` — locked/immutable (neutral)
- `anc-pill--edit` — edited/modified (warning yellow)
- `anc-pill--gen` — AI-generated (Iris, pulsing dot)
- `anc-pill--active` — live/active (green, pulsing dot)
- `anc-pill--draft` — draft/WIP (petal pink)
- `anc-pill--review` — under review (sky blue)
- `anc-pill--done` — completed (lavender)
- `anc-pill--warn` — warning/caution (amber)

Use `anc-pill-row` to lay out multiple pills horizontally:
```html
<div class="anc-pill-row">
  <span class="anc-pill anc-pill--active">Live</span>
  <span class="anc-pill anc-pill--gen">AI Gen</span>
</div>
```

### KPI / Stat Cards

Two layouts available: **full** (icon + label top, value + unit bottom) and **centered** (add `anc-kpi--center`).

#### Full Layout (default)

```html
<div class="anc-kpi anc-kpi--aurora">
  <div class="kpi-top">
    <div class="kpi-label-top">上游<br>算力基础设施</div>
    <div class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/></svg></div>
  </div>
  <div class="kpi-bottom">
    <div class="kpi-value">$485B</div>
    <div class="kpi-unit">市场规模</div>
  </div>
</div>
```

Uses 4-layer gradient backgrounds — corner radial glows blend into white center. 20px radius, 42px value text, smooth hover lift (translateY -4px). Icon sits in frosted-glass circle (36×36). `kpi-label-top` is 15px semibold.

#### Centered Variant

```html
<div class="anc-kpi anc-kpi--aurora anc-kpi--center">
  <div class="kpi-value">$1.2T</div>
  <div class="kpi-label">全球市场规模</div>
</div>
```

Centered text, 48px value. No icon. Good for simple stat grids.

#### 10 Gradient Color Themes (from card1.html)

| Class | Name | Corner colors | Best for |
|-------|------|-------------|----------|
| `anc-kpi--warm` | Warm | coral × lavender | Warm, approachable |
| `anc-kpi--cool` | Cool | teal × sky blue | Calm, technical |
| `anc-kpi--aurora` | Aurora | indigo × emerald | Primary/accent data |
| `anc-kpi--sunset` | Sunset | rose × gold | Alerts, emphasis |
| `anc-kpi--ocean` | Ocean | deep blue × coral pink | Depth, contrast |
| `anc-kpi--forest` | Forest | pine × chestnut | Positive, success |
| `anc-kpi--berry` | Berry | deep purple × wine | Premium, bold |
| `anc-kpi--arctic` | Arctic | ice blue × mint | Info, data |
| `anc-kpi--dusk` | Dusk | gray-blue × dusty pink | Neutral, secondary |
| `anc-kpi--flame` | Flame | flame orange × deep rose | Warnings, highlights |

These also work as section modifiers: `anc-section--warm`, `anc-section--cool`, etc. (combine with `anc-section--gc`).

KPI values use Bricolage Grotesque (display font) at 42px (48px centered). Color variants set the gradient background. Hover shadow tint matches the corner color.

### Other Elements

- `anc-divider` — 1px solid section divider (`<hr class="anc-divider">`)
- `anc-chart` — chart/diagram container placeholder
- `anc-branch-container` / `anc-branch-panel` — side-by-side branch comparison (injected by client)
- `anc-annotations` / `anc-annotation-pill` — annotation display (injected by client)

### Typography

Use standard HTML tags — the CSS styles them globally: `h1`–`h4`, `p`, `ul`, `ol`, `li`, `strong`, `code`, `pre`, `blockquote`, `table`, `th`, `td`. No class needed. Headings use Bricolage Grotesque (display), body uses Plus Jakarta Sans, code uses JetBrains Mono.

### Rules

1. Every `data-anc` element SHOULD have `class="anc-section"` (or a variant)
2. Use color modifiers semantically: green/mint for success/positive, pink/petal for alerts/emphasis, amber/butter for warnings, brand/lavender for primary content
3. Never write inline `style=""` attributes
4. Never reference external CSS or icon libraries (Phosphor Icons and Bloom tokens are auto-included by the webview shell)
5. Use `anc-pill` + `anc-pill-row` to display status metadata
6. Use `var(--*)` CSS tokens from Bloom — never hard-code colors, radii, or shadows

## Workflow (MCP)

The MCP server auto-starts with Claude Code. The loop runs in this same agent thread:

```
Claude calls anchor_render(html) → MCP broadcasts to webview → browser renders
  → User interacts (clicks handles in browser)
  → MCP stores pending op, writes prompts/pending.md
  → User returns here, sends any message
  → Stop hook detects pending.md, blocks with prompt
  → Claude calls anchor_get_pending_op() → gets op + current HTML
  → Claude processes op, calls anchor_render(updated HTML) → loop
```

**No manual server start. Everything runs in this agent thread.**

To begin: open http://localhost:3000, then ask Claude to generate an Anchor page.

## MCP Tools

Always use these MCP tools when working with Anchor:

| Tool | When to use |
|------|-------------|
| `anchor_render(html)` | Push HTML to webview. ALWAYS use this instead of writing to `output/current.html` directly. |
| `anchor_get_pending_op()` | After a Stop hook block, call to get the pending user interaction (op, target, instruction). Clears the pending op on read. |
| `anchor_get_html()` | Get the currently rendered HTML from the webview. |

## Processing Pending Ops

When the Stop hook blocks with an Anchor prompt:

1. Call `anchor_get_pending_op()` — get the op with target, instruction, and current HTML
2. Apply the requested change ONLY to the target element and its data-deps
3. Call `anchor_render(updated_html)` with the COMPLETE updated HTML

If the user explicitly asks to "process pending" or "check prompts", call `anchor_get_pending_op()` directly.

## Output Convention

Generate complete HTML documents with all anchor annotations. Call `anchor_render(html)` to push to webview. The MCP server also writes `output/current.html` as a side effect.

## Anchor Agent Events

When processing a pending user op, call `anchor_emit_event` at key milestones to surface agent progress in the webview timeline panel:

| Event type | When to emit | Payload shape |
|---|---|---|
| `thinking` | Before starting op processing | `{summary: "I'll modify the DCF section to use 8.5% WACC, recalculating all dependent numbers"}` |
| `tool_call` | Before/after each read or search tool | `{tool: "Read", status: "start", input_summary: "reading financials section"}` / `{tool: "Read", status: "end", result_summary: "read 340 lines"}` |
| `decision` | When making a significant content choice | `{choice: "use 8.5% WACC", alternatives: ["9%", "8%", "10%"], reason: "user explicitly requested 8.5%"}` |
| `partial_render` | If producing an intermediate draft worth previewing | `{html_fragment: "<section>...</section>", target_anchor: "valuation"}` |
| `complete` | After `anchor_render` succeeds | `{success: true, summary: "updated DCF with 8.5% WACC, cascaded changes to summary KPI"}` |
| `error` | If processing fails | `{message: "could not locate target anchor", retriable: true}` |

**Minimum expected**: `thinking` at start, `complete` at end. The timeline panel collapses each user-envelope round into a group.

Process flow: `anchor_get_pending_op()` → `anchor_emit_event(thinking, …)` → read/search as needed (emit `tool_call` events) → `anchor_emit_event(decision, …)` if branching → `anchor_render(new_html)` → `anchor_emit_event(complete, …)`.

## Cross-Task Usage

The same anchor protocol works across domains:
- **Code**: Use `data-anc-kind="code"` with Monaco/CodeMirror containers
- **Data analysis**: Use charts, tables, KPI cards
- **Research**: Hypothesis trees with confidence encoding
- **Documents**: Section-based with text handles
