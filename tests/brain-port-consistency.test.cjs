const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const uiFiles = [
  'loom/panel.html',
  'bridge/webview/hand-settings-panel.js',
  'bridge/webview/hand-feedback-widget.js',
];

test('browser UI targets the active Loom Brain port', () => {
  for (const rel of uiFiles) {
    const content = fs.readFileSync(path.join(root, rel), 'utf8');
    assert.equal(content.includes('localhost:3001'), false, `${rel} still targets the old Core port`);
    assert.equal(content.includes('127.0.0.1:3001'), false, `${rel} still targets the old Core port`);
  }
});
