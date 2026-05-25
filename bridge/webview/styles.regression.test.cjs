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
    /@media\s*\(max-width:\s*1680px\)[\s\S]*?#anchor-content\s+\.anc-kpi-grid:has\(>\s*\.anc-kpi:nth-child\(6\):last-child\)\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,/,
  );
});
