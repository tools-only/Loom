// Trading Canvas Renderer — generates and patches Trading Analysis HTML.
//
// Uses Bloom Design System classes and data-anc protocol.
// All trading anchors carry domain metadata: data-domain="trading.private",
// data-trading-session-id, data-claim-id, data-finding-id.

'use strict';

// ── Helpers ───────────────────────────────────────────────────────────

function escAttr(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function nowIso() {
  return new Date().toISOString();
}

// ── Anchor ID factories ───────────────────────────────────────────────

function claimAnchorId(claimId) {
  return 'claim.' + claimId;
}

function threadAnchorId(claimId, threadType) {
  return 'thread.' + claimId + '.' + threadType;
}

function findingAnchorId(findingId) {
  return 'finding.' + findingId;
}

function reactionAnchorId(reactionId) {
  return 'reaction.' + reactionId;
}

// ── Template generation ───────────────────────────────────────────────

function generateTradingCanvasHTML(options) {
  const opts = options || {};
  const tradingSessionId = escAttr(opts.trading_session_id || '');
  const title = escAttr(opts.title || 'Trading Analysis');
  const ts = opts.timestamp || nowIso();

  return [
    '<div class="trading-canvas" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '',
    '  <!-- Trade Intent -->',
    '  <section class="anc-section anc-section--gc" data-anc="trade.intent" data-handles="edit,refine,annotate" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Trade Intent</h2>',
    '      <span class="anc-pill anc-pill--draft">Draft</span>',
    '    </div>',
    '    <div class="trading-intent-form">',
    '      <div class="trading-field">',
    '        <label>Ticker</label>',
    '        <span class="trading-field-value" data-anc="trade.intent.ticker" data-handles="edit">—</span>',
    '      </div>',
    '      <div class="trading-field">',
    '        <label>Intent</label>',
    '        <span class="trading-field-value" data-anc="trade.intent.action" data-handles="edit">—</span>',
    '      </div>',
    '      <div class="trading-field">',
    '        <label>Time Horizon</label>',
    '        <span class="trading-field-value" data-anc="trade.intent.horizon" data-handles="edit">—</span>',
    '      </div>',
    '      <div class="trading-field trading-field--wide">',
    '        <label>Position Context</label>',
    '        <span class="trading-field-value" data-anc="trade.intent.context" data-handles="edit">—</span>',
    '      </div>',
    '    </div>',
    '  </section>',
    '',
    '  <!-- Raw Reasoning -->',
    '  <section class="anc-section anc-section--gc" data-anc="reasoning.raw" data-handles="edit,expand,annotate" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Raw Reasoning</h2>',
    '      <span class="anc-pill anc-pill--draft">Draft</span>',
    '    </div>',
    '    <p class="trading-placeholder">Write your free-text reasoning, emotional state, sources, and any private channel information here.</p>',
    '  </section>',
    '',
    '  <!-- Claims -->',
    '  <section class="anc-section anc-section--gc" data-anc="claims" data-handles="expand,restructure" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Claims</h2>',
    '      <span class="anc-pill anc-pill--gen">AI Extracted</span>',
    '    </div>',
    '    <div class="trading-placeholder" data-anc="claims.empty" data-handles="">',
    '      <p>Claims will be extracted from your reasoning above. Each reason becomes a trackable claim with bull, bear, and perspective threads.</p>',
    '    </div>',
    '  </section>',
    '',
    '  <!-- Tracking Threads -->',
    '  <section class="anc-section anc-section--gc" data-anc="tracking" data-handles="expand,restructure" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Tracking Threads</h2>',
    '      <span class="anc-pill anc-pill--active">Live</span>',
    '    </div>',
    '    <div class="trading-placeholder" data-anc="tracking.empty" data-handles="">',
    '      <p>Tracking threads appear here after claims are created. Each claim gets bull, bear, and perspective tracking threads.</p>',
    '    </div>',
    '  </section>',
    '',
    '  <!-- Reactions -->',
    '  <section class="anc-section anc-section--gc" data-anc="reactions" data-handles="expand,annotate" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Reactions</h2>',
    '    </div>',
    '    <p class="trading-placeholder">Your reactions to findings will appear here.</p>',
    '  </section>',
    '',
    '  <!-- Position / Outcome -->',
    '  <section class="anc-section anc-section--gc anc-section--ocean" data-anc="position.outcome" data-handles="edit,annotate" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Position / Outcome</h2>',
    '      <span class="anc-pill anc-pill--review">Pending</span>',
    '    </div>',
    '    <div class="trading-field">',
    '      <label>Status</label>',
    '      <span class="trading-field-value" data-anc="position.outcome.status" data-handles="edit">Not entered</span>',
    '    </div>',
    '    <div class="trading-field">',
    '      <label>Entry</label>',
    '      <span class="trading-field-value" data-anc="position.outcome.entry" data-handles="edit">—</span>',
    '    </div>',
    '    <div class="trading-field">',
    '      <label>Exit</label>',
    '      <span class="trading-field-value" data-anc="position.outcome.exit" data-handles="edit">—</span>',
    '    </div>',
    '    <div class="trading-field">',
    '      <label>P&L</label>',
    '      <span class="trading-field-value" data-anc="position.outcome.pnl" data-handles="edit">—</span>',
    '    </div>',
    '  </section>',
    '',
    '  <!-- Postmortem -->',
    '  <section class="anc-section anc-section--gc anc-section--berry" data-anc="postmortem" data-handles="edit,expand" data-domain="trading.private" data-trading-session-id="' + tradingSessionId + '">',
    '    <div class="anc-section__header">',
    '      <h2>Postmortem</h2>',
    '    </div>',
    '    <p class="trading-placeholder">After the trade concludes, record what was learned.</p>',
    '  </section>',
    '',
    '</div>'
  ].join('\n');
}

// ── Claim anchor builder ──────────────────────────────────────────────

function buildClaimHTML(claim) {
  var id = escAttr(claim.claim_id || '');
  var sessionId = escAttr(claim.trading_session_id || '');
  var text = escAttr(claim.text || '');
  var direction = claim.direction || 'unclear';
  var sourceType = claim.source_type || 'other';
  var status = claim.status || 'active';

  var directionPill = '';
  if (direction === 'bullish') directionPill = '<span class="anc-pill anc-pill--active">Bullish</span>';
  else if (direction === 'bearish') directionPill = '<span class="anc-pill anc-pill--warn">Bearish</span>';
  else if (direction === 'neutral') directionPill = '<span class="anc-pill anc-pill--review">Neutral</span>';
  else directionPill = '<span class="anc-pill anc-pill--draft">Unclear</span>';

  return [
    '<article class="anc-section anc-section--gc trading-claim"',
    '  data-anc="' + claimAnchorId(id) + '"',
    '  data-handles="refine,annotate,branch,ask"',
    '  data-domain="trading.private"',
    '  data-trading-session-id="' + sessionId + '"',
    '  data-claim-id="' + id + '">',
    '  <div class="anc-section__header">',
    '    <div class="anc-pill-row">',
    '      <span class="anc-pill anc-pill--lock">Claim</span>',
    '      ' + directionPill,
    '      <span class="anc-pill anc-pill--gen">' + escAttr(sourceType) + '</span>',
    '    </div>',
    '  </div>',
    '  <p>' + text + '</p>',
    '  <div class="trading-claim-meta">',
    '    <span data-anc="' + claimAnchorId(id) + '.status" data-handles="edit">Status: ' + escAttr(status) + '</span>',
    '  </div>',
    '</article>'
  ].join('\n');
}

// ── Thread anchor builder ─────────────────────────────────────────────

function buildThreadHTML(claimId, threadType, sessionId) {
  var id = escAttr(claimId || '');
  var type = escAttr(threadType || '');
  var sid = escAttr(sessionId || '');
  var label = threadType === 'bull' ? 'Bull Case'
    : threadType === 'bear' ? 'Bear Case'
    : threadType === 'perspective' ? 'Perspective' : 'Thread';

  var themeClass = threadType === 'bull' ? 'anc-section--aurora'
    : threadType === 'bear' ? 'anc-section--flame'
    : 'anc-section--arctic';

  var iconSvg = '';
  if (threadType === 'bull') {
    iconSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 22h20L12 2z"/></svg>';
  } else if (threadType === 'bear') {
    iconSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22L2 2h20L12 22z"/></svg>';
  } else {
    iconSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>';
  }

  return [
    '<section class="anc-section anc-section--gc ' + themeClass + ' trading-thread"',
    '  data-anc="' + threadAnchorId(id, type) + '"',
    '  data-handles="expand,annotate,branch"',
    '  data-domain="trading.private"',
    '  data-trading-session-id="' + sid + '"',
    '  data-claim-id="' + id + '">',
    '  <div class="anc-section__header">',
    '    <span class="trading-thread-icon">' + iconSvg + '</span>',
    '    <h3>' + label + '</h3>',
    '    <span class="anc-pill anc-pill--active">Tracking</span>',
    '  </div>',
    '  <div class="trading-thread-findings" data-anc="' + threadAnchorId(id, type) + '.findings" data-handles="expand">',
    '    <p class="trading-placeholder">No findings yet.</p>',
    '  </div>',
    '</section>'
  ].join('\n');
}

// ── Finding HTML builder ──────────────────────────────────────────────

function buildFindingHTML(finding) {
  var id = escAttr(finding.finding_id || '');
  var claimId = escAttr(finding.claim_id || '');
  var sessionId = escAttr(finding.trading_session_id || '');
  var stance = finding.stance || 'complicates';
  var summary = escAttr(finding.summary || '');
  var evidence = escAttr(finding.evidence || '');
  var uncertainty = finding.uncertainty != null ? finding.uncertainty : '';
  var observedAt = finding.observed_at || '';

  var stancePill = '';
  if (stance === 'supports') stancePill = '<span class="anc-pill anc-pill--active">Supports</span>';
  else if (stance === 'rebuts') stancePill = '<span class="anc-pill anc-pill--warn">Rebuts</span>';
  else stancePill = '<span class="anc-pill anc-pill--review">Complicates</span>';

  return [
    '<div class="trading-finding"',
    '  data-anc="' + findingAnchorId(id) + '"',
    '  data-handles="annotate,branch"',
    '  data-domain="trading.private"',
    '  data-trading-session-id="' + sessionId + '"',
    '  data-claim-id="' + claimId + '"',
    '  data-finding-id="' + id + '">',
    '  <div class="anc-pill-row">',
    '    <span class="anc-pill anc-pill--lock">Finding</span>',
    '    ' + stancePill,
    (uncertainty ? '    <span class="anc-pill anc-pill--draft">Uncertainty: ' + escAttr(uncertainty) + '</span>' : ''),
    '  </div>',
    '  <p class="trading-finding-summary"><strong>' + summary + '</strong></p>',
    (evidence ? '  <p class="trading-finding-evidence">' + evidence + '</p>' : ''),
    (observedAt ? '  <div class="trading-finding-meta">Observed: ' + escAttr(observedAt) + '</div>' : ''),
    '</div>'
  ].join('\n');
}

// ── Reaction HTML builder ──────────────────────────────────────────────

function buildReactionHTML(reaction) {
  var id = escAttr(reaction.reaction_id || '');
  var sessionId = escAttr(reaction.trading_session_id || '');
  var action = reaction.action || 'ACCEPT';
  var note = escAttr(reaction.note || '');
  var ts = reaction.timestamp || nowIso();

  var actionPill = '';
  if (action === 'ACCEPT') actionPill = '<span class="anc-pill anc-pill--active">Accepted</span>';
  else if (action === 'REBUT') actionPill = '<span class="anc-pill anc-pill--warn">Rebutted</span>';
  else if (action === 'IGNORE') actionPill = '<span class="anc-pill anc-pill--draft">Ignored</span>';
  else if (action === 'UPDATE_CLAIM') actionPill = '<span class="anc-pill anc-pill--gen">Updated Claim</span>';
  else if (action === 'EXECUTE_TRADE') actionPill = '<span class="anc-pill anc-pill--lock">Trade Executed</span>';
  else actionPill = '<span class="anc-pill anc-pill--review">' + escAttr(action) + '</span>';

  return [
    '<div class="trading-reaction"',
    '  data-anc="' + reactionAnchorId(id) + '"',
    '  data-handles="annotate"',
    '  data-domain="trading.private"',
    '  data-trading-session-id="' + sessionId + '">',
    '  <div class="anc-pill-row">',
    '    ' + actionPill,
    '    <span class="anc-pill anc-pill--draft">' + escAttr(ts) + '</span>',
    '  </div>',
    (note ? '  <p class="trading-reaction-note">' + note + '</p>' : ''),
    '</div>'
  ].join('\n');
}

// ── Position summary updater ──────────────────────────────────────────

function buildPositionSummaryHTML(position) {
  var sessionId = escAttr(position.trading_session_id || '');
  var status = escAttr(position.status || 'Not entered');
  var entry = escAttr(position.entry || '—');
  var exit = escAttr(position.exit || '—');
  var pnl = escAttr(position.pnl || '—');

  return [
    '<section class="anc-section anc-section--gc anc-section--ocean"',
    '  data-anc="position.outcome"',
    '  data-handles="edit,annotate"',
    '  data-domain="trading.private"',
    '  data-trading-session-id="' + sessionId + '">',
    '  <div class="anc-section__header">',
    '    <h2>Position / Outcome</h2>',
    '    <span class="anc-pill anc-pill--review">' + escAttr(status) + '</span>',
    '  </div>',
    '  <div class="trading-field"><label>Status</label><span class="trading-field-value" data-anc="position.outcome.status" data-handles="edit">' + status + '</span></div>',
    '  <div class="trading-field"><label>Entry</label><span class="trading-field-value" data-anc="position.outcome.entry" data-handles="edit">' + entry + '</span></div>',
    '  <div class="trading-field"><label>Exit</label><span class="trading-field-value" data-anc="position.outcome.exit" data-handles="edit">' + exit + '</span></div>',
    '  <div class="trading-field"><label>P&amp;L</label><span class="trading-field-value" data-anc="position.outcome.pnl" data-handles="edit">' + pnl + '</span></div>',
    '</section>'
  ].join('\n');
}

// ── Exports ───────────────────────────────────────────────────────────

module.exports = {
  generateTradingCanvasHTML: generateTradingCanvasHTML,
  buildClaimHTML: buildClaimHTML,
  buildThreadHTML: buildThreadHTML,
  buildFindingHTML: buildFindingHTML,
  buildReactionHTML: buildReactionHTML,
  buildPositionSummaryHTML: buildPositionSummaryHTML,
  claimAnchorId: claimAnchorId,
  threadAnchorId: threadAnchorId,
  findingAnchorId: findingAnchorId,
  reactionAnchorId: reactionAnchorId
};
