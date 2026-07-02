// Basic source-level tests for live-state-canvas.js
const fs = require('fs');
const path = require('path');
const assert = require('node:assert');
const { test } = require('node:test');

const src = fs.readFileSync(path.join(__dirname, 'live-state-canvas.js'), 'utf8');

test('live-state-canvas references /episodes/ and /workspace', () => {
  assert.match(src, /\/episodes\//);
  assert.match(src, /workspace/);
});

test('live-state-canvas uses data-state-id', () => {
  assert.match(src, /data-state-id/);
});

test('live-state-canvas references data-bottleneck-id or bottlenecks', () => {
  assert.match(src, /bottleneck/);
});

test('live-state-canvas references VisualInteraction or visual_queries', () => {
  assert.match(src, /visual_quer/);
});

test('live-state-canvas uses MutationObserver', () => {
  assert.match(src, /MutationObserver/);
});
