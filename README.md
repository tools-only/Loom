# Loom — AI-Native Workspace
**Think it. Live it.** [[Demo]](https://tools-only.github.io/Loom/demo.html)

Loom is an AI-native desktop workspace where HTML is the shared language between user and AI. Describe anything — dashboards, reports, prototypes — and watch it take shape. Click any element to refine, expand, or branch.

An AI-generated market research report rendered with the Bloom Design System. Hover over any section or KPI card to see available AI operations. No agent connection — pure interactive preview.

## Architecture

```
Browser ──op/envelope──► Anchor Service (daemon, port 3000)
                               │ push via /ws/agent WebSocket
                               ▼
                          MCP Shim ──stdio JSON-RPC──► Claude Code
                               ▲
                          anchor_patch / anchor_render
```

- **`mcp/server.cjs`** — persistent HTTP + WebSocket daemon
- **`mcp/shim.cjs`** — thin stdio bridge; MCP tools for Claude Code
- **`bridge/webview/`** — frontend (Bloom Design System, vanilla JS)
- **`electron/`** — desktop wrapper (Electron + system tray)

## Quick Start

```bash
# Install dependencies
npm install
cd bridge && npm install && cd ..

# Run in browser (dev mode)
scripts\start-anchor.bat
# → open http://localhost:3000

# Run as desktop app
npm start

# Build Windows installer
npm run build
```

## Anchor HTML Protocol

Elements are annotated with `data-anc` and `data-handles` for AI interaction:

```html
<section class="anc-section anc-section--gc"
         data-anc="analysis.summary"
         data-handles="refine,expand,shorten,annotate">
  <h2>Summary</h2>
  <p data-anc="analysis.summary.text" data-handles="refine,edit">...</p>
</section>
```

Available ops: `refine` · `expand` · `shorten` · `edit` · `annotate` · `branch` · `restructure` · `lock`

## Bloom Design System

All UI uses CSS variables from `resource/colors_and_type.css`. Never hard-code colors — use `var(--accent-iris)`, `var(--pastel-*)`, `var(--shadow-*)`, etc.

| Component | Class |
|-----------|-------|
| Section card | `anc-section anc-section--gc` |
| KPI card | `anc-kpi anc-kpi--aurora` (7 gradient themes) |
| Status pill | `anc-pill anc-pill--active` |
| Button | `btn btn--brand` |
