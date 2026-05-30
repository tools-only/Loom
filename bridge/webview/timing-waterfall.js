(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AnchorTimingWaterfall = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function finiteNumber(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0;
  }

  function validMs(value) {
    return finiteNumber(value) ? value : null;
  }

  function buildTimingStages(timing) {
    const t = timing || {};
    const server = t.server || {};
    const stages = [
      { name: 'Build Envelope', ms: validMs(t.t1_built ? t.t1_built - t.t0_click : null), color: '#5B8FF9' },
      { name: 'WS -> Server ACK', ms: validMs(t.t3_ack && t.t2_sent ? t.t3_ack - t.t2_sent : null), color: '#5B8FF9' },
      { name: 'ACK -> Thinking', ms: validMs(t.t4_thinking && t.t3_ack ? t.t4_thinking - t.t3_ack : null), color: '#5B8FF9' },
    ];

    const msHand = validMs(server.ms_hand_agent);
    const msLoom = validMs(server.ms_loom_agent);
    const bc = validMs(server.ms_broadcast);
    if (msHand != null || msLoom != null) {
      if (msHand != null) stages.push({ name: 'Hand Agent', ms: msHand, color: '#FFD700' });
      if (msLoom != null) stages.push({ name: 'Loom Agent -> Browser', ms: msLoom, color: '#F6AD55' });
      if (bc != null) stages.push({ name: 'broadcast patches', ms: bc, color: '#555' });
    } else if (validMs(server.ms_claude_gen) != null) {
      const resolve = validMs(server.ms_op_to_resolve);
      const gen = validMs(server.ms_claude_gen);
      if (resolve != null) stages.push({ name: 'op recv -> CC dispatched', ms: resolve, color: '#555' });
      if (gen != null) stages.push({ name: 'CC dispatch -> anchor_patch', ms: gen, color: '#F6AD55' });
      if (bc != null) stages.push({ name: 'broadcast patches', ms: bc, color: '#555' });
    }
    stages.push({ name: 'Patch -> DOM Done', ms: validMs(t.t6_dom && t.t5_patch ? t.t6_dom - t.t5_patch : null), color: '#5B8FF9' });

    return {
      stages: stages.filter((stage) => stage.ms != null && stage.ms >= 0),
      domDetail: [],
      serverTimings: [],
    };
  }

  return { buildTimingStages };
});
