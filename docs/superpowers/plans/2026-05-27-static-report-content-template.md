# Static Report Content Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, reusable report HTML template with calm pastel card styling inspired by the supplied report screenshot, without any Loom runtime logic.

**Architecture:** Create one complete static document at `resource/ui_kits/report/index.html`. It links only the existing Bloom design token sheet for fonts/colors and defines all report-specific components in locally scoped CSS under `.report-template`; its HTML carries demonstration content and no scripting or Loom protocol attributes.

**Tech Stack:** Semantic HTML5, scoped CSS, existing `resource/colors_and_type.css`, browser visual verification, PowerShell source assertions.

---

### Task 1: Define The Static Artifact Contract

**Files:**
- Create: `resource/ui_kits/report/index.html`

- [ ] **Step 1: Run the pre-implementation contract check and verify it fails**

Run:

```powershell
$p = 'resource/ui_kits/report/index.html'; if (-not (Test-Path -LiteralPath $p)) { throw 'Expected RED: report template does not exist yet.' }
```

Expected: FAIL with `Expected RED: report template does not exist yet.`

- [ ] **Step 2: Establish the static page shell**

Create a complete HTML document with:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>行业研究报告模板 - 静态视觉样板</title>
  <link rel="stylesheet" href="../../colors_and_type.css">
  <style>
    .report-template { /* all report layout styles are scoped here */ }
  </style>
</head>
<body>
  <main class="report-template">
    <!-- static report components -->
  </main>
</body>
</html>
```

The document must contain no `<script>`, `data-anc`, `data-handles`, `data-deps`, or Loom asset/runtime references.

### Task 2: Implement Report Visual Components

**Files:**
- Create: `resource/ui_kits/report/index.html`

- [ ] **Step 1: Build the airy report hero**

Add an open hero region containing a kicker, Chinese title, subtitle/date metadata, and three pastel pills. Use the existing Bloom variables (`--ink`, `--smoke`, `--paper`, pastel tokens) rather than hard-coded brand replacements.

- [ ] **Step 2: Build the overview card and metric grid**

Add a rounded white overview panel with a heading, macro badge, concise summary paragraph, and four metric cards. Use these reusable visual classes:

```html
<section class="report-panel report-overview">
  <div class="report-section-head">...</div>
  <p class="report-lede">...</p>
  <div class="report-kpi-grid">
    <article class="report-kpi report-kpi--mint">...</article>
  </div>
</section>
```

Each metric card includes a short label, a prominent value, and one metadata line.

- [ ] **Step 3: Build repeatable analysis and supporting patterns**

Add a representative `report-layer` panel with company highlight cards and a `report-callout`; add secondary panels for a catalyst timeline and risks; add conclusion cards and a disclaimer footer. HTML comments will identify which panel can be copied for future chapters.

- [ ] **Step 4: Add responsive CSS**

Use media queries to collapse four KPI cards to two and then one, and to stack the lower content grid. Ensure long Chinese strings wrap naturally via `overflow-wrap: anywhere` only where metrics need it.

### Task 3: Verify The Standalone Template

**Files:**
- Verify: `resource/ui_kits/report/index.html`

- [ ] **Step 1: Run structural source verification**

Run:

```powershell
$p = 'resource/ui_kits/report/index.html'
$html = Get-Content -LiteralPath $p -Raw
if ($html -match '<script|data-anc|data-handles|data-deps|anchor-client|bridge/webview|loom') { throw 'Loom logic or script detected.' }
@('report-template','report-panel','report-kpi-grid','report-callout','report-timeline','report-risks') | ForEach-Object { if ($html -notmatch [regex]::Escape($_)) { throw "Missing required component: $_" } }
Write-Output 'Static report template contract verified.'
```

Expected: PASS with `Static report template contract verified.`

- [ ] **Step 2: Perform browser visual verification**

Open `resource/ui_kits/report/index.html` in the in-app browser at desktop width, capture a screenshot, then view it at a narrow width. Confirm card wrapping, readable Chinese type, whitespace, and that only the report canvas appears.

- [ ] **Step 3: Review changed files**

Run:

```powershell
git diff --name-only -- resource/ui_kits/report docs/superpowers/plans/2026-05-27-static-report-content-template.md
```

Expected: changes limited to the new report template and this implementation plan.

