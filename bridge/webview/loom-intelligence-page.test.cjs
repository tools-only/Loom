const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('loom intelligence page is wired into main webview routing', () => {
  const index = read('bridge/webview/index.html');
  const client = read('bridge/webview/anchor-client.js');

  assert.match(index, /id="anchor-intent-wiki-btn"/);
  assert.match(index, /href="#intent-wiki"/);
  assert.match(index, /loom-intelligence-page\.js/);
  assert.match(client, /route === 'intent-wiki'/);
  assert.match(client, /LoomIntelligencePage\.renderInto\(this\)/);
});

test('loom intelligence page fetches only read-only Brain data sources', () => {
  const page = read('bridge/webview/loom-intelligence-page.js');

  assert.match(page, /window\.LoomIntelligencePage/);
  assert.match(page, /http:\/\/localhost:3002\/intent-stream\/data/);
  assert.match(page, /http:\/\/localhost:3002\/feedback/);
  assert.match(page, /http:\/\/localhost:3002\/flywheel\?limit=100/);
  assert.match(page, /http:\/\/localhost:3002\/goals\?status=all/);
  assert.match(page, /flywheelRecords/);
  assert.match(page, /lii-episode-links/);
  assert.doesNotMatch(page, /method:\s*['"]POST['"]/);
  assert.doesNotMatch(page, /method:\s*['"]PUT['"]/);
  assert.doesNotMatch(page, /method:\s*['"]PATCH['"]/);
  assert.doesNotMatch(page, /method:\s*['"]DELETE['"]/);
});
