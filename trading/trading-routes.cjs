// Trading Routes — Express route handlers for the trading.private domain.
//
// Mounted by server.cjs as a sub-router. Each route:
//   1. Validates the request body against trading domain requirements
//   2. Records a trading.* domain event via tradingEvents.recordTradingEvent()
//   3. Returns JSON with the resulting event_id and trading_session_id
//
// Uses dependency injection: receives tradingEvents and policyGate at mount time.

'use strict';

var _tradingEvents = null;
var _policyGate = null;
var _recordEvent = null;
var _getCurrentSession = null;

function log(msg) {
  process.stderr.write('[trading-routes] ' + msg + '\n');
}

// ── Mount all routes onto the Express app ─────────────────────────────

function mountTradingRoutes(app, deps) {
  _tradingEvents = deps.tradingEvents;
  _policyGate = deps.policyGate;
  _recordEvent = deps.recordEvent;
  _getCurrentSession = deps.currentSession;

  // POST /trading/session/start — create a new trading session
  app.post('/trading/session/start', function(req, res) {
    var workspaceFileId = req.body && req.body.workspace_file_id;
    var currentSession = typeof _getCurrentSession === 'function' ? _getCurrentSession() : null;
    var anchorSessionId = currentSession ? currentSession.id : null;

    var tradingSessionId = _tradingEvents.initTradingSession(workspaceFileId, anchorSessionId);
    if (!tradingSessionId) {
      return res.status(500).json({ ok: false, error: 'Failed to create trading session' });
    }

    res.json({
      ok: true,
      trading_session_id: tradingSessionId,
      anchor_session_id: anchorSessionId,
      workspace_file_id: workspaceFileId
    });
  });

  // GET /trading/session/:id/events — replay a trading session
  app.get('/trading/session/:id/events', function(req, res) {
    var tradingSessionId = req.params.id;
    var currentSession = typeof _getCurrentSession === 'function' ? _getCurrentSession() : null;

    if (!currentSession) {
      return res.json({ ok: true, state: _tradingEvents.buildEmptyState(tradingSessionId), events: [] });
    }

    // Read the anchor session event log and filter for trading events
    var fs = require('fs');
    var path = require('path');
    var eventsPath = currentSession.eventsPath;

    var events = [];
    try {
      var raw = fs.readFileSync(eventsPath, 'utf8');
      events = raw.trim() ? raw.trim().split('\n').map(JSON.parse) : [];
    } catch (e) {
      return res.status(500).json({ ok: false, error: 'Failed to read events: ' + e.message });
    }

    var tradingEvents = events.filter(function(e) {
      return e.kind && e.kind.startsWith('trading.') &&
        e.payload && e.payload.trading_session_id === tradingSessionId;
    });

    var state = _tradingEvents.replayTradingSession(events, tradingSessionId);

    res.json({
      ok: true,
      trading_session_id: tradingSessionId,
      event_count: tradingEvents.length,
      events: tradingEvents,
      state: state
    });
  });

  // POST /trading/reasoning — record reasoning declared
  app.post('/trading/reasoning', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id is required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.REASONING_DECLARED,
      {
        trading_session_id: body.trading_session_id,
        workspace_file_id: body.workspace_file_id || null,
        actor: 'human',
        ticker: body.ticker || null,
        intent: body.intent || null,
        time_window: body.time_window || null,
        position_context: body.position_context || null,
        reasoning_raw: body.reasoning_raw || '',
        emotion: body.emotion || null,
        sources: body.sources || []
      }
    );

    log('reasoning declared for session ' + body.trading_session_id);
    res.json({ ok: true, event_id: eventId, trading_session_id: body.trading_session_id });
  });

  // POST /trading/claim/extract — record claim extracted
  app.post('/trading/claim/extract', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id || !body.claim_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id and claim_id are required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.CLAIM_EXTRACTED,
      {
        trading_session_id: body.trading_session_id,
        workspace_file_id: body.workspace_file_id || null,
        actor: body.actor || 'system',
        claim_id: body.claim_id,
        source_event_id: body.source_event_id || null,
        text: body.text || '',
        original_text: body.original_text || body.text || '',
        source_type: body.source_type || 'other',
        direction: body.direction || 'unclear',
        time_horizon: body.time_horizon || null,
        expected_observable: body.expected_observable || null,
        status: 'active'
      }
    );

    log('claim extracted: ' + body.claim_id);
    res.json({ ok: true, event_id: eventId, claim_id: body.claim_id });
  });

  // POST /trading/claim/update — record claim updated
  app.post('/trading/claim/update', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id || !body.claim_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id and claim_id are required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.CLAIM_UPDATED,
      {
        trading_session_id: body.trading_session_id,
        claim_id: body.claim_id,
        actor: 'human',
        new_status: body.new_status || null,
        new_text: body.new_text || null,
        new_direction: body.new_direction || null,
        reason: body.reason || null
      }
    );

    log('claim updated: ' + body.claim_id);
    res.json({ ok: true, event_id: eventId, claim_id: body.claim_id });
  });

  // POST /trading/finding/add — record finding added (with policy gate)
  app.post('/trading/finding/add', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id is required' });
    }

    // Run policy gate
    var result = _policyGate.validateFinding(body);
    if (!result.ok) {
      var rejectEventId = _tradingEvents.recordTradingEvent(
        _tradingEvents.EVENT_KINDS.POLICY_REJECTED,
        {
          trading_session_id: body.trading_session_id,
          actor: body.actor || 'subagent',
          reason: 'Policy gate rejected finding',
          violations: result.violations,
          rejected_payload: body
        }
      );

      log('policy rejected finding: ' + result.violations.join('; '));
      return res.status(422).json({
        ok: false,
        error: 'Policy gate rejected finding',
        violations: result.violations,
        event_id: rejectEventId
      });
    }

    var findingId = body.finding_id || ('find_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6));

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.FINDING_ADDED,
      {
        trading_session_id: body.trading_session_id,
        workspace_file_id: body.workspace_file_id || null,
        actor: body.actor || 'subagent',
        finding_id: findingId,
        claim_id: body.claim_id,
        stance: body.stance,
        summary: body.summary || '',
        evidence: body.evidence || '',
        observed_at: body.observed_at || new Date().toISOString(),
        uncertainty: body.uncertainty || null,
        impact_on_claim: body.impact_on_claim || null,
        visibility: 'private'
      }
    );

    log('finding added: ' + findingId + ' -> claim ' + body.claim_id);
    res.json({ ok: true, event_id: eventId, finding_id: findingId });
  });

  // POST /trading/reaction — record human reaction
  app.post('/trading/reaction', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id || !body.action) {
      return res.status(400).json({ ok: false, error: 'trading_session_id and action are required' });
    }

    var validActions = ['ACCEPT', 'REBUT', 'IGNORE', 'UPDATE_CLAIM', 'ADD_CLAIM',
      'EXECUTE_TRADE', 'UNWIND', 'POSTMORTEM_NOTE', 'STOP_THREAD', 'RESTART_THREAD'];
    if (!validActions.includes(body.action)) {
      return res.status(400).json({
        ok: false,
        error: 'Invalid action. Must be one of: ' + validActions.join(', ')
      });
    }

    var reactionId = body.reaction_id || ('rxn_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6));

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.HUMAN_REACTION,
      {
        trading_session_id: body.trading_session_id,
        actor: 'human',
        reaction_id: reactionId,
        finding_id: body.finding_id || null,
        claim_id: body.claim_id || null,
        action: body.action,
        note: body.note || '',
        visibility: 'private'
      }
    );

    log('human reaction: ' + body.action);
    res.json({ ok: true, event_id: eventId, reaction_id: reactionId });
  });

  // POST /trading/trade/execute — record trade executed
  app.post('/trading/trade/execute', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id is required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.TRADE_EXECUTED,
      {
        trading_session_id: body.trading_session_id,
        actor: 'human',
        ticker: body.ticker || null,
        action: body.action || null,
        price: body.price || null,
        size: body.size || null,
        reason: body.reason || null,
        visibility: 'private'
      }
    );

    log('trade executed');
    res.json({ ok: true, event_id: eventId });
  });

  // POST /trading/position/unwind — record position unwound
  app.post('/trading/position/unwind', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id is required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.POSITION_UNWOUND,
      {
        trading_session_id: body.trading_session_id,
        actor: 'human',
        reason: body.reason || null,
        exit_price: body.exit_price || null,
        pnl: body.pnl || null,
        visibility: 'private'
      }
    );

    log('position unwound');
    res.json({ ok: true, event_id: eventId });
  });

  // POST /trading/postmortem — record postmortem added
  app.post('/trading/postmortem', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id) {
      return res.status(400).json({ ok: false, error: 'trading_session_id is required' });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.POSTMORTEM_ADDED,
      {
        trading_session_id: body.trading_session_id,
        actor: 'human',
        text: body.text || '',
        lessons: body.lessons || [],
        rating: body.rating || null,
        visibility: 'private'
      }
    );

    log('postmortem added');
    res.json({ ok: true, event_id: eventId });
  });

  // POST /trading/subagent/spawn — record subagent spawned
  app.post('/trading/subagent/spawn', function(req, res) {
    var body = req.body || {};
    if (!body.trading_session_id || !body.claim_id || !body.thread_type) {
      return res.status(400).json({ ok: false, error: 'trading_session_id, claim_id, and thread_type are required' });
    }

    var validThreads = ['bull', 'bear', 'perspective'];
    if (!validThreads.includes(body.thread_type)) {
      return res.status(400).json({
        ok: false,
        error: 'Invalid thread_type. Must be one of: ' + validThreads.join(', ')
      });
    }

    var eventId = _tradingEvents.recordTradingEvent(
      _tradingEvents.EVENT_KINDS.SUBAGENT_SPAWNED,
      {
        trading_session_id: body.trading_session_id,
        actor: 'harness',
        claim_id: body.claim_id,
        thread_type: body.thread_type,
        subagent_id: body.subagent_id || ('trading-' + body.thread_type),
        visibility: 'private'
      }
    );

    log('subagent spawned: ' + body.thread_type + ' for claim ' + body.claim_id);
    res.json({ ok: true, event_id: eventId });
  });

  log('routes mounted');
}

module.exports = { mountTradingRoutes: mountTradingRoutes };
