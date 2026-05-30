const test = require('node:test');
const assert = require('node:assert/strict');

const { buildTimingStages } = require('./timing-waterfall.js');

test('flattens server timings alongside the main waterfall', () => {
  const result = buildTimingStages({
    t0_click: 0,
    t1_built: 2,
    t2_sent: 3,
    t3_ack: 8,
    t4_thinking: 10,
    t5_patch: 120,
    t6_dom: 125,
    server: {
      ms_hand_agent: 40,
      ms_loom_agent: 70,
      ms_broadcast: 1,
    },
  });

  assert.deepEqual(
    result.stages.map((stage) => stage.name),
    ['Build Envelope', 'WS -> Server ACK', 'ACK -> Thinking', 'Hand Agent', 'Loom Agent -> Browser', 'broadcast patches', 'Patch -> DOM Done']
  );
  assert.deepEqual(result.serverTimings, []);
});

test('keeps legacy server timings when no hand-agent split exists', () => {
  const result = buildTimingStages({
    t0_click: 0,
    t1_built: 2,
    t2_sent: 3,
    t3_ack: 8,
    t4_thinking: 10,
    t5_patch: 120,
    t6_dom: 125,
    server: {
      ms_claude_gen: 55,
      ms_op_to_resolve: 7,
      ms_broadcast: 2,
    },
  });

  assert.deepEqual(
    result.stages.map((stage) => stage.name),
    ['Build Envelope', 'WS -> Server ACK', 'ACK -> Thinking', 'op recv -> CC dispatched', 'CC dispatch -> anchor_patch', 'broadcast patches', 'Patch -> DOM Done']
  );
  assert.deepEqual(result.serverTimings, []);
});
