const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, 'hand-settings-panel.js'), 'utf8');
const indexPage = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const anchorClient = fs.readFileSync(path.join(__dirname, 'anchor-client.js'), 'utf8');

test('Hand settings can select and persist a runtime adapter', () => {
  assert.match(source, /hsp-runtime-select/);
  assert.match(source, /\/hand\/\$\{handId\}\/runtime/);
  assert.match(source, /method: 'PUT'/);
  assert.match(source, /adapter_id: adapterId/);
  assert.match(source, /configured_runtime/);
});

test('Hand settings can register Codex App Server and HTTP agents', () => {
  assert.match(source, /Codex App Server · SDK/);
  assert.match(source, /codex_backend/);
  assert.match(source, /codex_home/);
  assert.match(source, /Codex Home/);
  assert.match(source, /\/adapters\/register/);
  assert.match(source, /http-openai/);
  assert.match(source, /auth_token_env/);
});

test('Hand settings can make an adapter the default executor for Brain-generated tasks', () => {
  assert.match(source, /hsp-brain-default/);
  assert.match(source, /\/adapters\/default-runtime/);
  assert.match(source, /set_default_runtime/);
  assert.match(source, /default_runtime_adapter/);
});

test('main Webview Settings exposes Codex and registered adapters per Hand', () => {
  assert.match(indexPage, /value="runtime">Agent Adapter/);
  assert.match(indexPage, /id="rt-market"/);
  assert.match(indexPage, /id="rt-sentiment"/);
  assert.match(indexPage, /id="rt-target"/);
  assert.match(indexPage, /id="rt-position"/);
  assert.match(anchorClient, /Codex App Server · SDK/);
  assert.match(anchorClient, /\/hands\/runtime-bindings/);
  assert.match(anchorClient, /\/adapters\/register/);
  assert.match(anchorClient, /\/runtime/);
});
