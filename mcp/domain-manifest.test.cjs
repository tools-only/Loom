const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const manifestPath = path.join(ROOT, 'domains', 'loom-fin', 'manifest.json');

test('loom-fin domain manifest declares current finance routes and capabilities', () => {
  assert.equal(fs.existsSync(manifestPath), true);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

  assert.equal(manifest.id, 'loom-fin');
  assert.equal(manifest.runtime, 'local-desktop-single-user');
  assert.equal(manifest.interface, 'loom-agent-adapter');
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
    assert.ok(
      manifest.agentTasks.some(task => task.id === capability && task.agent && task.adapter),
      `missing agent task mapping for ${capability}`,
    );
  }
  assert.equal(manifest.paths.legacyPythonBrain, undefined);
});
