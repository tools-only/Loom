const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const webviewDir = __dirname;
const anchor = fs.readFileSync(path.join(webviewDir, 'anchor-client.js'), 'utf8');
const index = fs.readFileSync(path.join(webviewDir, 'index.html'), 'utf8');
const brain = fs.readFileSync(path.join(webviewDir, '..', '..', 'loom', 'brain.py'), 'utf8');
const server = fs.readFileSync(path.join(webviewDir, '..', '..', 'mcp', 'server.cjs'), 'utf8');
const shim = fs.readFileSync(path.join(webviewDir, '..', '..', 'mcp', 'shim.cjs'), 'utf8');
const loomCommand = fs.readFileSync(path.join(webviewDir, '..', '..', '.claude', 'commands', 'loom.md'), 'utf8');
const loomVisualCommand = fs.readFileSync(path.join(webviewDir, '..', '..', '.claude', 'commands', 'loom-visual.md'), 'utf8');

test('root home remains Loom Fin with fixed finance task controls', () => {
  assert.match(index, /id="anchor-task-domain"/);
  assert.match(index, /value="market"/);
  assert.match(index, /value="target"/);
  assert.match(index, /value="position"/);
  assert.match(index, /id="anchor-visualize-toggle"/);
  assert.match(index, /data-loom-entry="fin"/);
  assert.doesNotMatch(index, /value="general"/);
});

test('loom visual tasks create dynamic webview sessions instead of a fixed page', () => {
  assert.doesNotMatch(server, /sendFile\(path\.join\(WEBVIEW_DIR, 'general\.html'\)\)/);
  assert.match(server, /app\.get\('\/loom-visual\/:visualId'/);
  assert.match(server, /function renderDynamicVisualPage\(visualId\)/);
  assert.match(server, /data-loom-entry="dynamic-visual"/);
  assert.match(server, /data-loom-visual-id="\$\{escapeHtmlAttr\(visualId\)\}"/);
  assert.match(server, /\/ws\/visual\//);
});

test('dynamic visual surfaces are isolated from Loom Fin broadcasts', () => {
  assert.match(anchor, /_loomVisualId\(\)/);
  assert.match(anchor, /return visualId \? 'visual:' \+ visualId :/);
  assert.match(anchor, /'\/ws\/visual\/' \+ encodeURIComponent\(visualId\)/);
  assert.match(anchor, /visual_id: visualId \|\| undefined/);
  assert.match(server, /ws\.loomSurface = normalizeSurface/);
  assert.match(server, /function surfaceFromVisualId\(visualId\)/);
  assert.match(server, /function broadcast\(html, surface = 'fin'\)/);
  assert.match(server, /normalizeSurface\(ws\.loomSurface\) === target/);
  assert.match(server, /processorPool\.set\(procId, \{ ws: null, partition: partitionId, ops, surface: opSurface\(op\) \}\)/);
});

test('home prompt defaults to general instead of market inference', () => {
  assert.match(anchor, /return 'general';/);
  assert.doesNotMatch(anchor, /return 'market';\s*\n\s*},\s*\n\s*submitPrompt/);
});

test('prompt submit forwards visualize and source context without changing brain-hand routing', () => {
  assert.match(anchor, /let visualize = this\._readVisualizeChoice\(\);/);
  assert.match(anchor, /type: 'prompt', text: promptText, route: effectiveRoute, visualize, context: routeContext/);
  assert.match(anchor, /source: 'ui'/);
  assert.match(anchor, /task_family: effectiveRoute === 'general' \? 'general' : 'monitor'/);
});

test('slash commands select Loom entry and visualization mode explicitly', () => {
  assert.match(anchor, /_parseLoomSlashCommand\(text\)/);
  assert.match(anchor, /command === 'loom-visual'/);
  assert.match(anchor, /slash\.visualize/);
  assert.match(anchor, /const promptText = slash \? slash\.text : text;/);
  assert.match(anchor, /const effectiveRoute = String\(route \|\| slash\?\.route \|\|/);
});

test('host agent slash commands document visual and non-visual Loom entry points', () => {
  assert.match(loomCommand, /current Claude Code or Codex main agent is the Brain/);
  assert.match(loomCommand, /Do not call `loom_prompt`/);
  assert.match(loomCommand, /Do not call Brain HTTP APIs/);
  assert.match(loomVisualCommand, /current Claude Code or Codex main agent is the Brain/);
  assert.match(loomVisualCommand, /Call `loom_prompt` only to prepare/);
  assert.match(loomVisualCommand, /anchor_render/);
  assert.match(loomVisualCommand, /"visual_id": "<returned visual_id>"/);
  assert.match(loomVisualCommand, /\/loom-visual\/<visual_id>/);
});

test('mcp shim prepares Loom entry without running a separate Brain', () => {
  assert.match(shim, /function ensureLoomServices/);
  assert.match(shim, /function hasDynamicVisualCapability/);
  assert.match(shim, /function restartAnchorService/);
  assert.match(shim, /await ensureAnchorServiceFreshForVisual\(options\)/);
  assert.match(shim, /startDetached\('Anchor service'/);
  assert.match(shim, /name: 'loom_prompt'/);
  assert.match(shim, /mode: visualize \? 'visual_prepare' : 'text_prepare'/);
  assert.match(shim, /route: 'general'/);
  assert.match(shim, /brain: 'host_agent'/);
  assert.match(shim, /const visualId = visualize \? createVisualId\(\) : '';/);
  assert.match(shim, /visual_id: visualId/);
  assert.match(shim, /url: visualUrl/);
  assert.match(shim, /visual_id: \{ type: 'string'/);
  assert.doesNotMatch(shim, /POST', '\/analyze'/);
  assert.doesNotMatch(shim, /sendVisualPrompt/);
  assert.doesNotMatch(shim, /surface: \{ type: 'string', enum: \['fin', 'general'\]/);
});

test('loom visual entry refreshes stale anchor service without restarting the host agent', () => {
  assert.match(server, /capabilities:/);
  assert.match(server, /dynamic_visual_webview: true/);
  assert.match(server, /service_version: 'dynamic-visual-v2'/);
  assert.match(shim, /const REQUIRED_ANCHOR_CAPABILITY = 'dynamic-visual-v2'/);
  assert.match(shim, /\/loom-visual\/__loom_capability_probe__/);
  assert.match(shim, /POST', '\/shutdown'/);
  assert.match(shim, /restartAnchorService\('dynamic visual webview capability mismatch', options\)/);
});

test('loom visual prepare opens the dynamic visual URL instead of the root home page', () => {
  assert.match(shim, /const visualId = visualize \? createVisualId\(\) : '';/);
  assert.match(shim, /await ensureLoomServices\(\{ visualize, visual_id: visualId \}\)/);
  assert.match(shim, /ANCHOR_OPEN_URL: `http:\/\/localhost:\$\{PORT\}\/loom-visual\/\$\{options\.visual_id\}`/);
  assert.match(shim, /await post\('\/runtime\/open-url', \{ url: visualUrl \}/);
  assert.match(server, /const url = process\.env\.ANCHOR_OPEN_URL \|\| `http:\/\/localhost:\$\{PORT\}`;/);
  assert.match(server, /app\.post\('\/runtime\/open-url'/);
  assert.match(server, /broadcastBrowserMessage\(\{ type: 'navigate', url \}\)/);
  assert.match(anchor, /case 'navigate':/);
});

test('host-agent entry does not modify Python Brain core analyze flow', () => {
  assert.doesNotMatch(brain, /visualize: bool \| None = None/);
  assert.doesNotMatch(brain, /def _should_patch_webview/);
  assert.doesNotMatch(brain, /if not should_patch:/);
});

test('server prompt entry does not bypass the mounted host-agent Brain', () => {
  assert.match(server, /function parseLoomSlashCommand\(text\)/);
  assert.match(server, /if \(requestedVisualize === false\)/);
  assert.match(server, /host-agent Brain/);
  assert.doesNotMatch(server, /function _callBrainAnalyze/);
  assert.doesNotMatch(server, /_callBrainAnalyze\(cleanPrompt/);
  assert.match(server, /type: 'prompt_result'/);
  assert.match(server, /const surface = msg\.visual_id \? surfaceFromVisualId\(msg\.visual_id\) : normalizeSurface\(msg\.surface \|\| agentSurface\(agentId\)\)/);
});
