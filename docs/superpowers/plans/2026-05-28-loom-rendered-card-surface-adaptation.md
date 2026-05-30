# Loom Rendered Card Surface Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the calm translucent report-card treatment to Loom content rendered in `#anchor-content` while leaving existing card assets and home-shell styling intact.

**Architecture:** Keep the existing `card1.html` gradient rules in `bridge/webview/styles.css` as legacy/fallback material. Add a later `#anchor-content`-scoped adaptation layer that overrides only rendered content surfaces and introduces lighter report-style card treatments without changing HTML contracts or JavaScript.

**Tech Stack:** CSS, Node.js built-in test runner, Loom static webview/browser verification

---

### Task 1: Lock The Rendered-Content Styling Contract

**Files:**
- Modify: `bridge/webview/styles.regression.test.cjs`
- Reference: `bridge/webview/styles.css`

- [x] **Step 1: Add failing regression assertions**

Add tests that require a named rendered-content adaptation block, require translucent top-level section rules, and ensure the block does not target `.home-` UI. Add a legacy-preservation assertion requiring the existing `card1.html` theme block to remain before the new override layer:

```js
test('rendered content sections use a translucent report surface without targeting home cards', () => {
  const layer = styles.match(/\/\* Rendered-content report surface adaptation\. \*\/([\s\S]*?)\/\* End rendered-content report surface adaptation\. \*\//);

  assert.ok(layer, 'expected a scoped rendered-content adaptation layer');
  assert.match(layer[1], /#anchor-content\s*>\s*\.anc-section\.anc-section--gc[\s\S]*?rgba\(255,\s*255,\s*255,\s*0\.72\)/);
  assert.match(layer[1], /#anchor-content\s+\.blog-header\.anc-section--gc/);
  assert.doesNotMatch(layer[1], /\.home-/);
});

test('legacy card1 gradients remain available before rendered content overrides', () => {
  const legacySourcePath = path.join(__dirname, '..', '..', 'resource', 'card', 'card1.html');
  const legacyRule = styles.indexOf('.anc-kpi--aurora {');
  const adaptationLayer = styles.indexOf('/* Rendered-content report surface adaptation. */');

  assert.ok(fs.existsSync(legacySourcePath), 'expected original card1 material to remain available');
  assert.ok(legacyRule >= 0, 'expected legacy aurora card material');
  assert.ok(adaptationLayer > legacyRule, 'expected scoped adaptation after legacy material');
  assert.match(styles.slice(legacyRule, adaptationLayer), /#4a5fd0/);
});
```

- [x] **Step 2: Run the CSS regression test and verify RED**

Run:

```powershell
node --test 'bridge/webview/styles.regression.test.cjs'
```

Expected: FAIL because `Rendered-content report surface adaptation.` does not yet exist.

### Task 2: Add The Scoped Translucent Card Adaptation

**Files:**
- Modify: `bridge/webview/styles.css`
- Test: `bridge/webview/styles.regression.test.cjs`

- [x] **Step 1: Implement an override layer after generated-content layout constraints**

Add a clearly marked block under the existing `#anchor-content` layout constraints, leaving the existing unscoped gradient material untouched. The block must:

- Use translucent milky-white surfaces for top-level content sections and `.blog-header`
- Use a slightly more opaque translucent surface for nested analysis sections
- Reduce hover elevation for large content surfaces
- Override `.anc-kpi` and `.blog-card` fallback backgrounds with light report gradients
- Override existing tone classes beneath `#anchor-content` with shallow `aurora`, `warm`, `cool`, `ocean`, `flame`, `berry`, `arctic`, `forest`, `sunset`, and `dusk` gradients

The added structure is:

```css
/* Rendered-content report surface adaptation. */
#anchor-content > .anc-section.anc-section--gc,
#anchor-content .blog-header.anc-section--gc {
  background:
    radial-gradient(circle at 6% 2%, rgba(191, 221, 238, 0.18), transparent 32%),
    radial-gradient(circle at 96% 8%, rgba(189, 232, 201, 0.14), transparent 30%),
    rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 18px 48px -38px rgba(17, 24, 39, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px) saturate(112%);
  -webkit-backdrop-filter: blur(14px) saturate(112%);
}

#anchor-content .anc-section > .anc-section:not(.blog-card) {
  background: rgba(255, 255, 255, 0.79);
  border: 1px solid rgba(255, 255, 255, 0.72);
}

#anchor-content > .anc-section.anc-section--gc:hover,
#anchor-content .blog-header.anc-section--gc:hover {
  transform: translateY(-1px);
}

#anchor-content .anc-kpi,
#anchor-content .blog-card.anc-section--gc {
  box-shadow: var(--shadow-inset-soft), 0 14px 32px -29px rgba(20, 21, 43, 0.34);
}

/* tone-specific light gradient overrides are included here */
/* End rendered-content report surface adaptation. */
```

- [x] **Step 2: Run the CSS regression test and verify GREEN**

Run:

```powershell
node --test 'bridge/webview/styles.regression.test.cjs'
```

Expected: PASS with the original responsive checks and the new preservation/surface checks.

### Task 3: Verify Visual Scope And Responsive Behavior

**Files:**
- Verify: `bridge/webview/styles.css`
- Verify: `bridge/webview/styles.regression.test.cjs`
- Verify: `bridge/webview/index.html`

- [x] **Step 1: Run source-scope verification**

Run:

```powershell
$css = Get-Content -LiteralPath 'bridge/webview/styles.css' -Raw -Encoding UTF8
$layer = [regex]::Match($css, '/\* Rendered-content report surface adaptation\. \*/([\s\S]*?)/\* End rendered-content report surface adaptation\. \*/').Groups[1].Value
if (-not $layer.Contains('#anchor-content')) { throw 'missing rendered-content scope' }
if ($layer.Contains('.home-')) { throw 'adaptation unexpectedly targets home shell' }
if (-not $css.Contains('/* Home cards rendered with the card1.html gradient family. */')) { throw 'existing home card material removed' }
```

Expected: exit code `0`.

- [x] **Step 2: Perform browser verification**

Open a rendered content route such as `#overview` or a generated report in the Loom webview. At desktop width, confirm translucent outer panels reveal the ambient surface and inner cards remain legible. At narrow width, confirm KPI and content cards stack without clipped Chinese text.

- [x] **Step 3: Review the changed-file boundary**

Run:

```powershell
git diff --name-only HEAD
```

Expected implementation paths:

```text
bridge/webview/styles.css
bridge/webview/styles.regression.test.cjs
docs/superpowers/plans/2026-05-28-loom-rendered-card-surface-adaptation.md
```

Pre-existing untracked report-template files may still appear in `git status`; they must not be modified or added for this task.
