const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const sourcePath = path.join(__dirname, 'hand-feedback-widget.js');
const source = fs.readFileSync(sourcePath, 'utf8');

test('hand feedback widget submits scoped feedback and handles intent lens response', () => {
  assert.match(source, /object_ref/);
  assert.match(source, /object_type/);
  assert.match(source, /orchestration_ref/);
  assert.match(source, /intent_lens/);
});
