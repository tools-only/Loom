// Trading Domain Event Layer — append-only trading events on top of
// existing Anchor session event log.
//
// Uses dependency injection: server.cjs calls initialize() with its
// recordEvent, generateEventId, createId, nowIso functions.
// Trading events coexist in the same logs/sessions/*/events.jsonl as
// existing Anchor events, differentiated by "trading.*" kind prefix.
//
// Every trading event carries:
//   trading_session_id  — the business-domain session
//   workspace_file_id   — the workspace file this session belongs to
//   actor               — "human" | "harness" | "subagent" | "system"
//   visibility          — always "private" for MVP
//   payload             — event-specific data

'use strict';

var _recordEvent = null;
var _generateEventId = null;
var _createId = null;
var _nowIso = null;
var _getCurrentSession = null;
var _initialized = false;

function log(msg) {
  process.stderr.write('[trading-events] ' + msg + '\n');
}

// ── Event kind constants ──────────────────────────────────────────────

var EVENT_KINDS = {
  SESSION_STARTED:     'trading.session_started',
  REASONING_DECLARED:  'trading.reasoning_declared',
  CLAIM_EXTRACTED:     'trading.claim_extracted',
  SUBAGENT_SPAWNED:    'trading.subagent_spawned',
  FINDING_ADDED:       'trading.finding_added',
  HUMAN_REACTION:      'trading.human_reaction',
  CLAIM_UPDATED:       'trading.claim_updated',
  TRADE_EXECUTED:      'trading.trade_executed',
  POSITION_UNWOUND:    'trading.position_unwound',
  POSTMORTEM_ADDED:    'trading.postmortem_added',
  POLICY_REJECTED:     'trading.policy_rejected'
};

var VALID_ACTORS = ['human', 'harness', 'subagent', 'system'];

// ── Initialize (called by server.cjs) ─────────────────────────────────

function initialize(deps) {
  if (_initialized) return;
  _recordEvent = deps.recordEvent;
  _generateEventId = deps.generateEventId;
  _createId = deps.createId;
  _nowIso = deps.nowIso;
  _getCurrentSession = deps.currentSession;  // getter for live reference
  _initialized = true;
  log('initialized');
}

// ── Trading session management ────────────────────────────────────────

function initTradingSession(workspaceFileId, anchorSessionId) {
  if (!_initialized) {
    log('WARNING: initTradingSession called before initialize()');
    return null;
  }

  var ts = typeof _nowIso === 'function' ? _nowIso() : new Date().toISOString();
  var generateId = typeof _generateEventId === 'function' ? _generateEventId : function() {
    return 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
  };
  var makeId = typeof _createId === 'function' ? _createId : function(prefix, seed) {
    return prefix + '_' + String(seed || 'item').replace(/[^a-z0-9_-]+/g, '-').slice(0, 24) + '_' + Date.now().toString(36);
  };

  var tradingSessionId = makeId('trd', workspaceFileId || 'session');
  var eventId = generateId();

  recordTradingEvent(EVENT_KINDS.SESSION_STARTED, {
    trading_session_id: tradingSessionId,
    workspace_file_id: workspaceFileId || null,
    anchor_session_id: anchorSessionId || null,
    started_at: ts
  });

  log('trading session started: ' + tradingSessionId);
  return tradingSessionId;
}

// ── Record a trading domain event ─────────────────────────────────────

function recordTradingEvent(kind, payload) {
  if (!_initialized || !_recordEvent) {
    log('WARNING: recordTradingEvent called before initialize()');
    return null;
  }

  var eventPayload = Object.assign({}, payload || {}, {
    _trading_event: true,
    recorded_at: typeof _nowIso === 'function' ? _nowIso() : new Date().toISOString()
  });

  // Ensure actor is valid
  if (eventPayload.actor && !VALID_ACTORS.includes(eventPayload.actor)) {
    eventPayload.actor = 'system';
  }

  // Enforce private visibility
  if (!eventPayload.visibility) {
    eventPayload.visibility = 'private';
  }

  var eventId = _recordEvent(kind, eventPayload);
  return eventId;
}

// ── Replay a trading session from the event log ───────────────────────

function replayTradingSession(events, tradingSessionId) {
  if (!tradingSessionId || !Array.isArray(events)) {
    return buildEmptyState(tradingSessionId);
  }

  var state = buildEmptyState(tradingSessionId);

  events.forEach(function(event) {
    if (!event || !event.kind || !event.kind.startsWith('trading.')) return;

    var payload = event.payload || {};
    if (payload.trading_session_id !== tradingSessionId) return;

    switch (event.kind) {
      case EVENT_KINDS.SESSION_STARTED:
        state.session_started_at = event.timestamp;
        state.workspace_file_id = payload.workspace_file_id;
        break;

      case EVENT_KINDS.REASONING_DECLARED:
        state.reasoning_events.push({
          event_id: event.event_id,
          timestamp: event.timestamp,
          actor: payload.actor,
          ticker: payload.ticker,
          intent: payload.intent,
          raw_text: payload.reasoning_raw,
          emotion: payload.emotion,
          sources: payload.sources || []
        });
        break;

      case EVENT_KINDS.CLAIM_EXTRACTED:
        var claim = {
          claim_id: payload.claim_id,
          source_event_id: payload.source_event_id,
          text: payload.text,
          original_text: payload.original_text,
          source_type: payload.source_type,
          direction: payload.direction,
          time_horizon: payload.time_horizon,
          status: payload.status || 'active',
          updated_at: event.timestamp
        };
        state.claims.push(claim);
        break;

      case EVENT_KINDS.CLAIM_UPDATED:
        for (var ci = 0; ci < state.claims.length; ci++) {
          if (state.claims[ci].claim_id === payload.claim_id) {
            state.claims[ci].status = payload.new_status || state.claims[ci].status;
            state.claims[ci].text = payload.new_text || state.claims[ci].text;
            state.claims[ci].updated_at = event.timestamp;
          }
        }
        break;

      case EVENT_KINDS.SUBAGENT_SPAWNED:
        state.tracking_threads.push({
          claim_id: payload.claim_id,
          thread_type: payload.thread_type,
          subagent_id: payload.subagent_id,
          spawned_at: event.timestamp
        });
        break;

      case EVENT_KINDS.FINDING_ADDED:
        state.findings.push({
          finding_id: payload.finding_id,
          claim_id: payload.claim_id,
          stance: payload.stance,
          summary: payload.summary,
          evidence: payload.evidence,
          observed_at: payload.observed_at,
          uncertainty: payload.uncertainty,
          impact_on_claim: payload.impact_on_claim,
          added_at: event.timestamp
        });
        break;

      case EVENT_KINDS.HUMAN_REACTION:
        state.reactions.push({
          reaction_id: payload.reaction_id,
          finding_id: payload.finding_id,
          claim_id: payload.claim_id,
          action: payload.action,
          note: payload.note,
          timestamp: event.timestamp
        });
        break;

      case EVENT_KINDS.TRADE_EXECUTED:
        state.trades.push({
          event_id: event.event_id,
          ticker: payload.ticker,
          action: payload.action,
          price: payload.price,
          size: payload.size,
          timestamp: event.timestamp
        });
        break;

      case EVENT_KINDS.POSITION_UNWOUND:
        state.position_unwound_at = event.timestamp;
        state.unwind_reason = payload.reason;
        break;

      case EVENT_KINDS.POSTMORTEM_ADDED:
        state.postmortems.push({
          event_id: event.event_id,
          text: payload.text,
          lessons: payload.lessons,
          timestamp: event.timestamp
        });
        break;

      case EVENT_KINDS.POLICY_REJECTED:
        state.policy_rejections.push({
          event_id: event.event_id,
          reason: payload.reason,
          violations: payload.violations,
          timestamp: event.timestamp
        });
        break;
    }
  });

  return state;
}

function buildEmptyState(tradingSessionId) {
  return {
    trading_session_id: tradingSessionId || null,
    session_started_at: null,
    workspace_file_id: null,
    reasoning_events: [],
    claims: [],
    tracking_threads: [],
    findings: [],
    reactions: [],
    trades: [],
    position_unwound_at: null,
    unwind_reason: null,
    postmortems: [],
    policy_rejections: []
  };
}

// ── Exports ───────────────────────────────────────────────────────────

module.exports = {
  EVENT_KINDS: EVENT_KINDS,
  initialize: initialize,
  initTradingSession: initTradingSession,
  recordTradingEvent: recordTradingEvent,
  replayTradingSession: replayTradingSession,
  buildEmptyState: buildEmptyState
};
