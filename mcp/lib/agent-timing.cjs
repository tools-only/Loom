function eventMs(events, name) {
  const value = events && events[name] && events[name].ms;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function diffMs(end, start) {
  if (typeof end !== 'number' || typeof start !== 'number') return null;
  const value = end - start;
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function buildAgentTimingPayload(events, options = {}) {
  const handStart = eventMs(events, 'hand_agent_invoke');
  const handDone = eventMs(events, 'hand_agent_done');
  const patchBroadcast = eventMs(events, 'webview_patch_broadcast');
  const renderBroadcast = eventMs(events, 'ui_render_broadcast');
  const browserBroadcast = patchBroadcast ?? renderBroadcast;
  const userClick = eventMs(events, 'user_click_received');
  const loomStart = handDone ?? userClick ?? eventMs(events, 'ui_render_start');

  return {
    agent_context: options.agentContext || null,
    ms_hand_agent: diffMs(handDone, handStart),
    ms_loom_agent: diffMs(browserBroadcast, loomStart),
    ms_broadcast: diffMs(browserBroadcast, eventMs(events, 'agent_content_generated')),
    timing_source: patchBroadcast != null ? 'patch' : renderBroadcast != null ? 'render' : 'unknown',
  };
}

module.exports = { buildAgentTimingPayload };
