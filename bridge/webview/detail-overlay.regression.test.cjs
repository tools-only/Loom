const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const overlayPath = path.join(__dirname, 'loom-detail-overlay.js');
const anchorPath = path.join(__dirname, 'anchor-client.js');
const overlay = fs.readFileSync(overlayPath, 'utf8');
const anchor = fs.readFileSync(anchorPath, 'utf8');

function extractFunction(source, name) {
  const pattern = new RegExp('  function ' + name + '\\([\\s\\S]*?\\n  \\}', 'm');
  const match = source.match(pattern);
  assert.ok(match, 'expected function ' + name);
  return match[0];
}

test('detail overlay targets are explicit opt-in only', () => {
  const scanRule = overlay.match(/root\.querySelectorAll\('([^']+)'\)/);
  const targetRule = overlay.match(/function isDetailTarget\(el\) \{([\s\S]*?)\n  \}/);

  assert.ok(scanRule, 'expected refresh scan selector');
  assert.ok(targetRule, 'expected isDetailTarget implementation');
  assert.doesNotMatch(scanRule[1], /\.anc-section--gc/);
  assert.doesNotMatch(scanRule[1], /\.blog-card/);
  assert.doesNotMatch(targetRule[1], /classList\.contains\('anc-section--gc'\)/);
  assert.doesNotMatch(targetRule[1], /classList\.contains\('blog-card'\)/);
  assert.match(targetRule[1], /data-detail-disabled/);
});

test('detail overlay opens only through ctrl hover', () => {
  assert.match(overlay, /clickToOpen:\s*false/);
  assert.match(overlay, /requireCtrlForHover:\s*true/);
  assert.match(overlay, /function canHoverOpen\(event\)/);
  assert.match(overlay, /return !options\.requireCtrlForHover \|\| !!\(event && event\.ctrlKey\);/);
  assert.match(overlay, /event\.key === 'Control'[\s\S]*?close\(\)/);
  assert.match(overlay, /init\(\{ root: document, clickToOpen: false, hoverToOpen: true, requireCtrlForHover: true \}\)/);
});

test('portfolio hub remains a stable configuration surface', () => {
  const hubMarkup = anchor.match(/const renderPositionHubShell = \(\) => `([\s\S]*?)`;/);

  assert.ok(hubMarkup, 'expected portfolio hub shell');
  assert.match(hubMarkup[1], /class="[^"]*portfolio-hub[^"]*"/);
  assert.match(hubMarkup[1], /data-detail-disabled="true"/);
  assert.match(hubMarkup[1], /id="portfolio-tracking-view"/);
  assert.match(hubMarkup[1], /id="portfolio-setup-view" hidden/);
  assert.doesNotMatch(hubMarkup[1], /data-has-detail="true"/);
  assert.doesNotMatch(hubMarkup[1], /<aside class="anc-detail"/);
});

test('full renders close any stale detail overlay', () => {
  assert.match(anchor, /if \(window\.LoomDetailOverlay\) window\.LoomDetailOverlay\.close\(\);\s*this\.container\.innerHTML = html;/);
});

test('detail overlay synthesizes an Agent tab for cards without explicit agent details', () => {
  assert.match(overlay, /function ensureAgentSection\(target,\s*sections\)/);
  assert.match(overlay, /id:\s*'agents'/);
  assert.match(overlay, /label:\s*'Hand Agent'/);
  assert.match(overlay, /Current card processing hand agent/);
  assert.match(overlay, /sections\.push\(ensureAgentSection\(target,\s*sections\)\)/);
});

test('domain cards expose hand agent metadata without injecting hidden detail UI', () => {
  assert.match(anchor, /data-agent-hand="\$\{_escHtml\(agentMeta\.hand\)\}"/);
  assert.match(anchor, /data-agent-role="\$\{_escHtml\(agentMeta\.role\)\}"/);
  assert.doesNotMatch(anchor, /function renderItemDetail/);
  assert.doesNotMatch(anchor, /data-detail-section="agents"/);
  assert.doesNotMatch(anchor, /Current card processing hand agent/);
});

test('synthesized Hand Agent section renders card hand metadata', () => {
  const factory = new Function('target', [
    extractFunction(overlay, 'escapeHtml'),
    extractFunction(overlay, 'inferAgentMeta'),
    extractFunction(overlay, 'ensureAgentSection'),
    'return ensureAgentSection(target, []);'
  ].join('\n'));
  const attrs = {
    'data-anc': 'market.card.42',
    'data-agent-hand': 'market-hand',
    'data-agent-executor': 'codex',
    'data-agent-domain': 'market',
    'data-agent-kind': 'filing',
    'data-agent-role': 'Reads filings and flags risk catalysts.'
  };
  const section = factory({
    getAttribute(name) {
      return attrs[name] || '';
    }
  });

  assert.equal(section.id, 'agents');
  assert.equal(section.label, 'Hand Agent');
  assert.match(section.html, /market-hand/);
  assert.match(section.html, /codex \/ market \/ filing/);
  assert.match(section.html, /Reads filings and flags risk catalysts\./);
});

test('hand agent summary is visible in the popup chrome and not density filtered', () => {
  assert.match(overlay, /pillsEl\.insertAdjacentHTML\('beforeend', renderAgentBadge\(target\)\)/);
  assert.match(overlay, /function renderAgentBadge\(target\)/);
  assert.match(overlay, /Hand Agent:/);
  assert.match(overlay, /layerType:\s*''/);
  assert.doesNotMatch(overlay, /label:\s*'Hand Agent'[\s\S]{0,120}layerType:\s*'analysis'/);
});
