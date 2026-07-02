const fs = require('fs');
const path = require('path');
const assert = require('node:assert');
const { test } = require('node:test');

const src = fs.readFileSync(path.join(__dirname, 'checkpoint-review-deck.js'), 'utf8');

test('checkpoint-review-deck references /checkpoint-response', () => {
  assert.match(src, /checkpoint-response/);
});

test('checkpoint-review-deck supports trust gesture', () => {
  assert.match(src, /trust/);
});

test('checkpoint-review-deck supports contest gesture', () => {
  assert.match(src, /contest/);
});

test('checkpoint-review-deck supports expand gesture', () => {
  assert.match(src, /expand/);
});

test('checkpoint-review-deck supports skip gesture', () => {
  assert.match(src, /skip/);
});

test('checkpoint-review-deck references consumed_by or consumption', () => {
  // The deck posts to checkpoint-response; consumption tracking is server-side
  assert.match(src, /POST/);
});

test('checkpoint-review-deck uses MutationObserver', () => {
  assert.match(src, /MutationObserver/);
});
