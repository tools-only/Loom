const test = require('node:test');
const assert = require('node:assert/strict');

const { buildAgentTimingPayload } = require('../mcp/lib/agent-timing.cjs');

test('computes hand agent and loom agent timing from timeline events', () => {
  const payload = buildAgentTimingPayload({
    user_click_received: { ms: 1000 },
    hand_agent_invoke: { ms: 1020 },
    hand_agent_done: { ms: 1120 },
    agent_content_generated: { ms: 1300 },
    webview_patch_broadcast: { ms: 1325 },
  });

  assert.equal(payload.ms_hand_agent, 100);
  assert.equal(payload.ms_loom_agent, 205);
  assert.equal(payload.ms_broadcast, 25);
  assert.equal(payload.timing_source, 'patch');
});

test('omits hand timing when no hand agent participated', () => {
  const payload = buildAgentTimingPayload({
    user_click_received: { ms: 200 },
    agent_content_generated: { ms: 420 },
    webview_patch_broadcast: { ms: 450 },
  });

  assert.equal(payload.ms_hand_agent, null);
  assert.equal(payload.ms_loom_agent, 250);
  assert.equal(payload.ms_broadcast, 30);
});
