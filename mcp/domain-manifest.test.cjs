const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  buildDomainManifestResponse,
  loadDomainManifests,
} = require('./lib/domain-registry.cjs');

const ROOT = path.join(__dirname, '..');
const manifestPath = path.join(ROOT, 'domains', 'loom-fin', 'manifest.json');

test('loom-fin domain manifest declares current finance routes and capabilities', () => {
  assert.equal(fs.existsSync(manifestPath), true);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

  assert.equal(manifest.id, 'loom-fin');
  assert.equal(manifest.runtime, 'local-desktop-single-user');
  assert.deepEqual(manifest.compatibility.preserveExistingExperience, true);

  for (const route of ['overview', 'market', 'target', 'sentiment', 'position', 'trading.private']) {
    assert.ok(manifest.routes.includes(route), `missing route ${route}`);
  }

  for (const capability of [
    'market.regime.review',
    'ticker.thesis.review',
    'sentiment.scan',
    'position.review',
    'thesis.debate',
  ]) {
    assert.ok(manifest.capabilities.includes(capability), `missing capability ${capability}`);
  }
});

test('domain registry loads loom-fin manifest with compatibility flags', () => {
  const manifests = loadDomainManifests(ROOT);
  const loomFin = manifests.find(manifest => manifest.id === 'loom-fin');

  assert.ok(loomFin, 'loom-fin manifest should be loaded');
  assert.equal(loomFin.compatibility.preserveExistingExperience, true);
  assert.equal(loomFin.compatibility.preserveCssTemplates, true);
  assert.equal(loomFin.paths.legacyConnectors, '../../mcp/connectors');
});

test('domain registry builds public manifest response', () => {
  const response = buildDomainManifestResponse(loadDomainManifests(ROOT));
  const loomFin = response.domains.find(manifest => manifest.id === 'loom-fin');

  assert.equal(response.ok, true);
  assert.ok(loomFin, 'loom-fin manifest should be exposed');
  assert.equal(loomFin.manifestPath, undefined);
  assert.equal(loomFin.compatibility.preserveExistingExperience, true);
});
