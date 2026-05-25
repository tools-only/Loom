'use strict';

const fs = require('fs');
const path = require('path');
const transcript = require('./lib/debate-transcript.cjs');
const specWriter = require('./lib/debate-spec-writer.cjs');
const codexBridge = require('./lib/codex-bridge.cjs');

const HOST_MODEL = process.env.DEBATE_HOST_MODEL || 'claude-opus-4-7';
const PROPOSER_MODEL = process.env.DEBATE_PROPOSER_MODEL || 'claude-sonnet-4-6';
const MAX_ROUNDS = 14;
const MAX_MINUTES = 60;
const MAX_TOKENS = 4096;

const DEBATES_DIR = path.join(__dirname, '../output/debates');
const TEMPLATE_PATH = path.join(__dirname, '../.claude/skills/anchor-debate/references/four-layer-template.md');

function loadAgentPrompt(name) {
  const p = path.join(__dirname, '../.claude/agents', `${name}.md`);
  try {
    const raw = fs.readFileSync(p, 'utf8');
    const bodyStart = raw.indexOf('\n---\n', raw.indexOf('---') + 3);
    return bodyStart !== -1 ? raw.slice(bodyStart + 5).trim() : raw.trim();
  } catch (_) {
    return `You are the ${name}. Follow your role.`;
  }
}

function extractJson(text) {
  try { return JSON.parse(text.trim()); } catch (_) {}
  const m = text.match(/```(?:json)?\s*([\s\S]+?)```/);
  if (m) { try { return JSON.parse(m[1].trim()); } catch (_) {} }
  const s = text.indexOf('{'), e = text.lastIndexOf('}');
  if (s !== -1 && e > s) { try { return JSON.parse(text.slice(s, e + 1)); } catch (_) {} }
  return null;
}

function condensedContext(t, lastN = 2) {
  const recent = t.rounds.slice(-lastN).map(r => ({
    round: r.round,
    scope: r.scope,
    verdict: r.host_close?.verdict,
    summary: r.host_close?.summary,
  }));
  return JSON.stringify({ topic: t.topic, commitments: t.commitments, recent_rounds: recent }, null, 2);
}

async function llmCall(client, model, systemPrompt, userMessage) {
  const resp = await client.messages.create({
    model,
    max_tokens: MAX_TOKENS,
    system: systemPrompt,
    messages: [{ role: 'user', content: userMessage }],
  });
  const text = (resp.content || [])
    .filter(b => b.type === 'text')
    .map(b => b.text)
    .join('');
  return text;
}

async function emitDebate(toolRegistry, ctx, kind, payload) {
  try {
    await toolRegistry.anchor_emit_event(
      { type: 'decision', payload: { kind: `debate.${kind}`, ...payload } },
      ctx
    );
  } catch (_) {}
}

async function runDebate(op, ctx, deps) {
  const { client, toolRegistry, log, autoExecLog } = deps;
  const topic = op?.intent?.instruction || op?.intent?.topic || 'Untitled Debate';
  const debateId = 'dbt_' + Date.now().toString(36);
  const startedAt = Date.now();

  const hostSystem = loadAgentPrompt('debate-host');
  const proposerSystem = loadAgentPrompt('debate-proposer');

  const t = transcript.create(debateId, topic, {
    max_rounds: MAX_ROUNDS,
    max_minutes: MAX_MINUTES,
    models: { host: HOST_MODEL, proposer: PROPOSER_MODEL, reviewer: 'gpt-5-via-codex' },
  });

  log(`debate-orchestrator: start debateId=${debateId} topic="${topic}"`);
  autoExecLog({ event: 'debate_start', debateId, topic });

  await emitDebate(toolRegistry, ctx, 'start', {
    debate_id: debateId,
    topic,
    target_anchor: ctx.target,
  });

  const codexAvailable = await codexBridge.selfTest().then(r => r.ok).catch(() => false);
  if (!codexAvailable) {
    log('debate-orchestrator: codex not available, reviewer will use fallback');
    await emitDebate(toolRegistry, ctx, 'reviewer_fallback', {
      debate_id: debateId,
      error: 'codex CLI not available — reviewer will use Claude sonnet as fallback',
    });
  }

  let convergedCount = 0;
  const LAYERS = ['problem', 'ideal', 'gap', 'strategy'];

  for (let round = 1; round <= MAX_ROUNDS; round++) {
    if (Date.now() - startedAt > MAX_MINUTES * 60 * 1000) {
      log(`debate-orchestrator: wall-clock limit reached at round ${round}`);
      break;
    }
    if (ctx.aborted) {
      log(`debate-orchestrator: aborted by user at round ${round}`);
      break;
    }

    log(`debate-orchestrator: round ${round} start`);

    // ── A. Host setup ────────────────────────────────────────────────────────
    let hostSetup;
    try {
      const prevLayer = t.rounds.length > 0 ? t.rounds[t.rounds.length - 1]?.scope?.layer : null;
      const needsRetro = round > 1;
      const hostUserMsg = [
        `Topic: ${topic}`,
        `Round: ${round} of ${MAX_ROUNDS}`,
        `Context:\n${condensedContext(t)}`,
        needsRetro ? `Previous scope layer: ${prevLayer}` : '',
        `Output host_setup JSON for this round. If scope layer changes, include mapping_table.`,
      ].filter(Boolean).join('\n\n');

      const hostText = await llmCall(client, HOST_MODEL, hostSystem, hostUserMsg);
      hostSetup = extractJson(hostText) || {
        step: 'host_setup', round,
        scope: { layer: LAYERS[Math.min(round - 1, 3)], focus: 'continue debate', mapped_anchors: [] },
        briefing_proposer: `Argue for the scope: ${topic}`,
        briefing_reviewer: `Critique the scope: ${topic}`,
      };
    } catch (e) {
      log(`debate-orchestrator: host_setup error round ${round}: ${e.message}`);
      hostSetup = {
        step: 'host_setup', round,
        scope: { layer: LAYERS[Math.min(round - 1, 3)], focus: topic, mapped_anchors: [] },
        briefing_proposer: topic,
        briefing_reviewer: topic,
      };
    }

    await emitDebate(toolRegistry, ctx, 'round_open', {
      debate_id: debateId,
      round,
      scope: hostSetup.scope,
      mapped_anchors: hostSetup.scope?.mapped_anchors || [],
    });

    // ── B. Proposer ──────────────────────────────────────────────────────────
    let proposerOutput;
    try {
      const propMsg = [
        `Round ${round} scope: ${JSON.stringify(hostSetup.scope)}`,
        `Host briefing: ${hostSetup.briefing_proposer}`,
        `Commitments so far: ${JSON.stringify(t.commitments.slice(-6))}`,
        `Output your proposal as proposer JSON.`,
      ].join('\n\n');

      const propText = await llmCall(client, PROPOSER_MODEL, proposerSystem, propMsg);
      proposerOutput = extractJson(propText) || { role: 'proposer', round, position: propText.slice(0, 500) };
    } catch (e) {
      log(`debate-orchestrator: proposer error round ${round}: ${e.message}`);
      proposerOutput = { role: 'proposer', round, position: 'ERROR: ' + e.message };
    }

    await emitDebate(toolRegistry, ctx, 'proposer_turn', {
      debate_id: debateId,
      round,
      role: 'proposer',
      text: proposerOutput.position || JSON.stringify(proposerOutput).slice(0, 300),
    });

    // ── C. Reviewer ──────────────────────────────────────────────────────────
    let reviewerOutput;
    const reviewerPrompt = [
      `Round ${round} scope: ${JSON.stringify(hostSetup.scope)}`,
      `Host briefing: ${hostSetup.briefing_reviewer}`,
      `Proposer argument: ${JSON.stringify(proposerOutput)}`,
      `Commitments so far: ${JSON.stringify(t.commitments.slice(-6))}`,
      `Output your critique as reviewer JSON with fields: role, round, scope_layer, verdict (agree/partial/reject), gaps, counter_evidence, alternative_framing, confidence.`,
    ].join('\n\n');

    try {
      if (codexAvailable) {
        const r = await codexBridge.callGpt5(reviewerPrompt, { timeout: 60000 });
        reviewerOutput = extractJson(r.raw || r.text) || { role: 'reviewer', round, verdict: 'partial', gaps: [], text: r.text?.slice(0, 500) };
        reviewerOutput.model = r.model;
      } else {
        const revText = await llmCall(client, PROPOSER_MODEL,
          loadAgentPrompt('debate-reviewer'), reviewerPrompt);
        reviewerOutput = extractJson(revText) || { role: 'reviewer', round, verdict: 'partial', text: revText.slice(0, 500) };
        reviewerOutput.model = 'claude-sonnet-fallback';
      }
    } catch (e) {
      log(`debate-orchestrator: reviewer error round ${round}: ${e.message}`);
      reviewerOutput = { role: 'reviewer', round, verdict: 'partial', error: e.message };
    }

    await emitDebate(toolRegistry, ctx, 'reviewer_turn', {
      debate_id: debateId,
      round,
      role: 'reviewer',
      model: reviewerOutput.model || 'unknown',
      text: reviewerOutput.alternative_framing || JSON.stringify(reviewerOutput).slice(0, 300),
      verdict: reviewerOutput.verdict,
    });

    // ── D. Host judge ────────────────────────────────────────────────────────
    let hostClose;
    try {
      const judgeMsg = [
        `Round ${round} — judge the debate.`,
        `Scope: ${JSON.stringify(hostSetup.scope)}`,
        `Proposer: ${JSON.stringify(proposerOutput)}`,
        `Reviewer: ${JSON.stringify(reviewerOutput)}`,
        `Output host_judge JSON with: step="host_judge", round, verdict (converged/continue/escalate), commitments_delta (array of {layer, statement}), summary.`,
      ].join('\n\n');

      const judgeText = await llmCall(client, HOST_MODEL, hostSystem, judgeMsg);
      hostClose = extractJson(judgeText) || { step: 'host_judge', round, verdict: 'continue', commitments_delta: [], summary: '' };
    } catch (e) {
      log(`debate-orchestrator: host_judge error round ${round}: ${e.message}`);
      hostClose = { step: 'host_judge', round, verdict: 'continue', commitments_delta: [], summary: '' };
    }

    if (hostClose.commitments_delta?.length) {
      transcript.addCommitments(t, hostClose.commitments_delta.map(c => ({ round, ...c })));
    }

    transcript.addRound(t, {
      round,
      scope: hostSetup.scope,
      host_open: hostSetup,
      proposer: proposerOutput,
      reviewer: reviewerOutput,
      host_close: hostClose,
      mapping_table: hostSetup.mapping_table || null,
    });

    transcript.save(t, DEBATES_DIR);

    await emitDebate(toolRegistry, ctx, 'round_close', {
      debate_id: debateId,
      round,
      verdict: hostClose.verdict,
      commitments_delta: hostClose.commitments_delta || [],
      summary: hostClose.summary,
    });

    if (hostClose.verdict === 'converged') {
      convergedCount++;
      if (convergedCount >= 2) {
        const layersCovered = new Set(t.commitments.map(c => c.layer));
        if (LAYERS.every(l => layersCovered.has(l))) {
          log(`debate-orchestrator: converged after round ${round}`);
          break;
        }
      }
    } else {
      convergedCount = 0;
    }
  }

  // ── Finalize ──────────────────────────────────────────────────────────────
  let specPath;
  try {
    specPath = specWriter.write(t, TEMPLATE_PATH, DEBATES_DIR);
  } catch (e) {
    log(`debate-orchestrator: spec write error: ${e.message}`);
  }

  const status = ctx.aborted ? 'aborted' : 'complete';
  transcript.finalize(t, status, { specPath, patchTarget: ctx.target });
  transcript.save(t, DEBATES_DIR);

  await emitDebate(toolRegistry, ctx, 'complete', {
    debate_id: debateId,
    spec_path: specPath,
    transcript_path: path.join(DEBATES_DIR, debateId, 'transcript.json'),
    rounds_used: t.rounds.length,
    status,
    target_anchor: ctx.target,
  });

  try {
    await toolRegistry.anchor_emit_event({
      type: 'complete',
      payload: {
        target_anchor: ctx.target || '__debate__',
        summary: `Debate "${topic}" finished in ${t.rounds.length} rounds. Spec: ${specPath || 'not saved'}`,
      },
    }, ctx);
    ctx.completed = true;
  } catch (_) {}

  log(`debate-orchestrator: done debateId=${debateId} rounds=${t.rounds.length} status=${status}`);
  autoExecLog({ event: 'debate_complete', debateId, rounds: t.rounds.length, status });
}

module.exports = { runDebate };
