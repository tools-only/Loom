// Trading Policy Gate — validates findings before they are written.
//
// Checks:
//   - Must bind to a claim_id
//   - Must declare stance (supports / rebuts / complicates)
//   - Must include evidence or observed_at
//   - visibility must be "private"
//   - Must NOT contain direct buy/sell advice
//
// Returns { ok: boolean, violations: string[] }

'use strict';

var VALID_STANCES = ['supports', 'rebuts', 'complicates'];

var BUY_SELL_PATTERNS = [
  /\bbuy\s+(the\s+)?(stock|dip|now|more|shares|call|put)\b/i,
  /\bsell\s+(the\s+)?(stock|now|all|shares|call|put)\b/i,
  /\b(strong\s+)?buy\s+rating\b/i,
  /\b(strong\s+)?sell\s+rating\b/i,
  /\bload\s+up\s+on\b/i,
  /\bdump\s+(your|the)\b/i,
  /\ball\s+in\b/i,
  /\bget\s+out\s+now\b/i,
  /\byou\s+should\s+(buy|sell)\b/i
];

function validateFinding(finding) {
  var violations = [];

  if (!finding) {
    violations.push('Finding is null or undefined');
    return { ok: false, violations: violations };
  }

  // Must bind to claim_id
  if (!finding.claim_id || typeof finding.claim_id !== 'string' || !finding.claim_id.trim()) {
    violations.push('Finding must bind to a claim_id');
  }

  // Must declare stance
  if (!finding.stance || !VALID_STANCES.includes(finding.stance)) {
    violations.push('Finding must declare stance: one of ' + VALID_STANCES.join(', '));
  }

  // Must include evidence or observed_at
  var hasEvidence = finding.evidence && typeof finding.evidence === 'string' && finding.evidence.trim();
  var hasObservedAt = finding.observed_at && typeof finding.observed_at === 'string' && finding.observed_at.trim();
  if (!hasEvidence && !hasObservedAt) {
    violations.push('Finding must include evidence or observed_at');
  }

  // visibility must be private
  if (finding.visibility && finding.visibility !== 'private') {
    violations.push('Finding visibility must be "private", got: ' + finding.visibility);
  }

  // No direct buy/sell advice
  var textToCheck = [
    finding.summary || '',
    finding.evidence || '',
    finding.impact_on_claim || ''
  ].join(' ');

  for (var i = 0; i < BUY_SELL_PATTERNS.length; i++) {
    if (BUY_SELL_PATTERNS[i].test(textToCheck)) {
      violations.push('Finding must not contain direct buy/sell advice');
      break;
    }
  }

  return {
    ok: violations.length === 0,
    violations: violations
  };
}

// Validate a complete trading event envelope
function validateTradingEnvelope(envelope) {
  if (!envelope) {
    return { ok: false, violations: ['Envelope is null or undefined'] };
  }

  var domain = envelope.domain;
  if (!domain) {
    return { ok: false, violations: ['Missing domain field in envelope'] };
  }

  if (domain.namespace !== 'trading.private') {
    return { ok: false, violations: ['Invalid domain namespace: ' + domain.namespace] };
  }

  var violations = [];

  if (!domain.action) {
    violations.push('Missing domain.action');
  }

  if (!domain.trading_session_id) {
    violations.push('Missing domain.trading_session_id');
  }

  return {
    ok: violations.length === 0,
    violations: violations
  };
}

module.exports = {
  validateFinding: validateFinding,
  validateTradingEnvelope: validateTradingEnvelope,
  VALID_STANCES: VALID_STANCES
};
