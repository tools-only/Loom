const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.join(__dirname, '..', '..');
const server = fs.readFileSync(path.join(root, 'mcp', 'server.cjs'), 'utf8');
const electronMain = fs.readFileSync(path.join(root, 'electron', 'main.js'), 'utf8');
const capturePagePath = path.join(root, 'bridge', 'webview', 'resource-capture.html');
const capturePage = fs.existsSync(capturePagePath) ? fs.readFileSync(capturePagePath, 'utf8') : '';
const captureRouteStart = server.indexOf("app.post('/channels/capture'");
const captureRouteEnd = captureRouteStart >= 0 ? server.indexOf("app.get('/pending-op'", captureRouteStart) : -1;
const captureRoute = captureRouteStart >= 0 && captureRouteEnd > captureRouteStart
  ? server.slice(captureRouteStart, captureRouteEnd)
  : '';

test('desktop resource capture is exposed as an Electron floating window', () => {
  assert.match(electronMain, /let captureWindow\s*=/);
  assert.match(electronMain, /function createResourceCaptureWindow\(/);
  assert.match(electronMain, /resource-capture\.html/);
  assert.match(electronMain, /label: 'Capture Resource'/);
  assert.match(electronMain, /globalShortcut\.register\('CommandOrControl\+Shift\+L'/);
});

test('capture endpoint persists channel resources and cultivates intent wiki', () => {
  assert.match(server, /CHANNEL_RESOURCES_FILE/);
  assert.match(server, /INTENT_STREAM_FILE/);
  assert.match(server, /INTENT_WIKI_INTENTS_FILE/);
  assert.match(server, /app\.post\('\/channels\/capture'/);
  assert.match(server, /registerChannelResource\(/);
  assert.match(server, /function cultivateIntentWikiFromChannelResource/);
  assert.match(server, /input_type: 'resource_share'/);
  assert.match(server, /source_preferences\./);
  assert.match(server, /channel_resource_entry: true/);
  assert.doesNotMatch(captureRoute, /\/analyze/);
});

test('capture page submits user resources without using agent slash commands', () => {
  assert.match(capturePage, /id="capture-form"/);
  assert.match(capturePage, /fetch\('\/channels\/capture'/);
  assert.match(capturePage, /name="intent_hint"/);
  assert.match(capturePage, /name="note"/);
  assert.match(capturePage, /name="tags"/);
  assert.doesNotMatch(capturePage, /loom_channel_connect/);
  assert.doesNotMatch(capturePage, /\/loom-channel/);
});
