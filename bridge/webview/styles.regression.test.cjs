const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const stylesPath = path.join(__dirname, 'styles.css');
const styles = fs.readFileSync(stylesPath, 'utf8');

test('plain KPI cards have a gradient fallback instead of a blank surface', () => {
  const baseCardRule = styles.match(/\.anc-kpi\s*\{([\s\S]*?)\n\}/);

  assert.ok(baseCardRule, 'expected a base .anc-kpi rule');
  assert.match(baseCardRule[1], /background:\s*[\s\S]*linear-gradient/);
});

test('six-card KPI groups use complete responsive rows', () => {
  assert.match(
    styles,
    /#anchor-content\s+\.anc-kpi-grid:has\(>\s*\.anc-kpi:nth-child\(6\):last-child\)\s*\{[\s\S]*?grid-template-columns:\s*repeat\(6,/,
  );
  assert.match(
    styles,
    /@media\s*\(max-width:\s*1520px\)[\s\S]*?#anchor-content\s+\.anc-kpi-grid:has\(>\s*\.anc-kpi:nth-child\(6\):last-child\)\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,/,
  );
});

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

test('rendered KPI and blog cards receive the light report tone family', () => {
  const layer = styles.match(/\/\* Rendered-content report surface adaptation\. \*\/([\s\S]*?)\/\* End rendered-content report surface adaptation\. \*\//);
  const tones = ['warm', 'cool', 'aurora', 'ocean', 'flame', 'berry', 'arctic', 'forest', 'sunset', 'dusk'];

  assert.ok(layer, 'expected a scoped rendered-content adaptation layer');
  assert.match(layer[1], /#anchor-content\s+\.anc-section\s*>\s*\.anc-section:not\(\.blog-card\)[\s\S]*?rgba\(255,\s*255,\s*255,\s*0\.79\)/);
  assert.match(layer[1], /#anchor-content\s+\.anc-kpi,[\s\S]*?#anchor-content\s+\.blog-card\.anc-section--gc[\s\S]*?linear-gradient\(135deg,\s*#f0fdfa/);
  for (const tone of tones) {
    assert.match(layer[1], new RegExp(`#anchor-content\\s+\\.anc-kpi--${tone}`));
  }
});
