const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'canvas-client.js'), 'utf8');

test('canvas card feedback posts scoped feedback to Brain feedback endpoint', () => {
  assert.match(source, /\/feedback/);
  assert.match(source, /object_ref/);
  assert.match(source, /orchestration_ref/);
});
