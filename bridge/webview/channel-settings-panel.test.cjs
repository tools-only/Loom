const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..', '..');
const indexPage = fs.readFileSync(path.join(root, 'bridge', 'webview', 'index.html'), 'utf8');
const channelPanel = fs.readFileSync(path.join(root, 'bridge', 'webview', 'channel-settings-panel.js'), 'utf8');
const styles = fs.readFileSync(path.join(root, 'bridge', 'webview', 'styles.css'), 'utf8');

test('webview exposes channel adapter settings panel', () => {
  assert.match(indexPage, /id="anchor-channels-config-btn"/);
  assert.match(indexPage, /channel-settings-panel\.js/);
  assert.match(channelPanel, /\/social\/channels/);
  assert.match(channelPanel, /\/social\/channels\/config/);
  assert.match(channelPanel, /\/social\/channels\/register/);
  assert.match(channelPanel, /\/social\/channels\/default/);
  assert.match(channelPanel, /\/social\/channels\/\$\{encodeURIComponent\(channelId\)\}/);
  assert.match(channelPanel, /data-channel-fields/);
  assert.match(channelPanel, /fieldSpecsFor/);
  assert.match(channelPanel, /data-channel-toggle/);
  assert.match(channelPanel, /closest\('#anchor-channels-config-btn'\)/);
  assert.match(styles, /#anchor-channel-panel\s*\{/);
  assert.match(styles, /top:\s*68px/);
  assert.match(styles, /bottom:\s*18px/);
});
