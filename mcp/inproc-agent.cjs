// Anchor in-process agent — Anthropic SDK tool-use loop running inside the
// long-lived MCP Leader Node process. Replaces per-op `claude -p` subprocess.
// All deps (SDK constructor, registry, loggers) are injected via create() so
// this module stays pure and testable.

'use strict';

const SYSTEM_PROMPT = [
  'You are running an Anchor in-process auto-execute loop for ONE user op on an HTML document.',
  '',
  'Procedure:',
  '1. Call anchor_get_pending_op once to receive the user intent (with target_ref, op name, instruction) plus either relevant_subtree (preferred) or current_html.',
  '2. Call anchor_emit_event with type=thinking and payload {target_anchor: "<target>", summary: "<1-line plan>"}.',
  '3. Apply the op ONLY to the target anchor and its data-deps. Preserve every data-anc, data-handles, data-deps attribute and CSS class. Do not touch unrelated sections.',
  '4. Call anchor_patch with patches=[{anchor_id: "<target>", html_fragment: "<complete outerHTML for the target>"}]. If reverse-dependents must also change to stay consistent, include them as additional patch entries.',
  '5. Call anchor_emit_event with type=complete and payload {target_anchor: "<target>", summary: "<1-line>"}.',
  '',
  'Rules:',
  '- NEVER call anchor_render — whole-HTML replacement is disabled in this loop.',
  '- Always include target_anchor in every anchor_emit_event payload.',
  '- Output the patch via the tool call ONLY — do not echo the HTML in your text response.',
  '- Make best-judgment decisions; do not ask follow-up questions.',
].join('\n');

const TOOL_DEFS = [
  {
    name: 'anchor_get_pending_op',
    description: 'Get the user op assigned to this in-process loop. Returns {pending:true, op, relevant_subtree|current_html, ...} on the first call.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'anchor_get_html',
    description: 'Get the currently rendered full HTML from the webview. Use only if relevant_subtree from anchor_get_pending_op is insufficient.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'anchor_emit_event',
    description: 'Emit a progress event (thinking / tool_call / decision / complete / error / partial_render) to the webview timeline.',
    input_schema: {
      type: 'object',
      properties: {
        type: { type: 'string', enum: ['thinking', 'tool_call', 'partial_render', 'decision', 'complete', 'error'] },
        payload: { type: 'object' },
      },
      required: ['type'],
    },
  },
  {
    name: 'anchor_patch',
    description: 'Patch one or more anchor nodes by outerHTML replacement. Use this instead of anchor_render for all updates.',
    input_schema: {
      type: 'object',
      properties: {
        patches: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              anchor_id: { type: 'string', description: 'data-anc value of the target node' },
              html_fragment: { type: 'string', description: 'Complete outerHTML for the replacement (must include the same data-anc)' },
            },
            required: ['anchor_id', 'html_fragment'],
          },
        },
      },
      required: ['patches'],
    },
  },
];

function buildUserMessage(op) {
  const opKind = op?.intent?.op || '(unknown)';
  const target = op?.intent?.target_ref || op?.target || '(unknown)';
  const instruction = op?.intent?.instruction || op?.args?.instruction || op?.args?.value || '(no instruction)';
  return [
    `Process this user op now.`,
    `Op kind: ${opKind}`,
    `Target anchor: ${target}`,
    `Instruction: ${instruction}`,
    ``,
    `Call anchor_get_pending_op first to receive the full op context, then follow the system procedure.`,
  ].join('\n');
}

function create(opts) {
  const {
    Anthropic,
    apiKey,
    model,
    toolRegistry,
    log,
    autoExecLog,
    concurrency,
  } = opts;

  if (!Anthropic) throw new Error('inproc-agent: Anthropic constructor required');
  if (!apiKey) throw new Error('inproc-agent: apiKey required');
  if (!toolRegistry) throw new Error('inproc-agent: toolRegistry required');

  const client = new Anthropic({ apiKey });
  const queue = [];
  let running = 0;

  const MAX_TURNS = 12;
  const MAX_TOKENS = parseInt(process.env.ANCHOR_INPROC_MAX_TOKENS) || 4096;

  async function runOne(op) {
    const opKind = op?.intent?.op || '(unknown)';
    if (opKind === 'debate' || opKind === 'debate_abort') {
      const target = op?.intent?.target_ref || op?.target || '__debate__';
      const opId = 'iop_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      const ctx = { opId, target, opKind, opPayload: op, opConsumed: false, completed: false, aborted: false,
        parentEventId: op?.provenance?.event_id || null };
      if (opKind === 'debate_abort') { ctx.aborted = true; return; }
      log(`in-process agent: routing to debate-orchestrator opId=${opId}`);
      autoExecLog({ event: 'inproc_debate_start', opId, target });
      const orch = require('./debate-orchestrator.cjs');
      return orch.runDebate(op, ctx, { client, model, toolRegistry, log, autoExecLog });
    }

    const opId = 'iop_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
    const target = op?.intent?.target_ref || op?.target || '(unknown)';
    const startedAt = Date.now();

    const ctx = {
      opId,
      target,
      opKind,
      opPayload: op,
      opConsumed: false,
      completed: false,
      parentEventId: op?.provenance?.event_id || null,
    };

    log(`in-process agent: start opId=${opId} op=${opKind} target=${target} (running ${running}/${concurrency})`);
    autoExecLog({ event: 'inproc_start', opId, opKind, target, model, running });

    const messages = [{ role: 'user', content: buildUserMessage(op) }];

    let turn = 0;
    let lastError = null;
    let stopReason = null;

    try {
      while (turn < MAX_TURNS) {
        turn++;
        const resp = await client.messages.create({
          model,
          max_tokens: MAX_TOKENS,
          system: SYSTEM_PROMPT,
          tools: TOOL_DEFS,
          messages,
        });
        stopReason = resp.stop_reason;

        const toolUses = (resp.content || []).filter(b => b.type === 'tool_use');
        if (toolUses.length === 0) break;

        const toolResults = [];
        for (const tu of toolUses) {
          const handler = toolRegistry[tu.name];
          if (!handler) {
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Unknown tool: ' + tu.name, is_error: true });
            continue;
          }
          try {
            const out = await handler(tu.input || {}, ctx);
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: String(out == null ? '' : out) });
          } catch (e) {
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Tool error: ' + (e && e.message || e), is_error: true });
          }
        }

        messages.push({ role: 'assistant', content: resp.content });
        messages.push({ role: 'user', content: toolResults });

        if (resp.stop_reason !== 'tool_use') break;
        if (ctx.completed) break;
      }
    } catch (e) {
      lastError = e;
      log(`in-process agent: error opId=${opId}: ${e && e.message || e}`);
      try {
        const errHandler = toolRegistry.anchor_emit_event;
        if (errHandler) {
          await errHandler({
            type: 'error',
            payload: { target_anchor: target, message: 'inproc-agent: ' + (e && e.message || 'unknown'), retriable: false },
          }, ctx);
        }
      } catch (_) { /* swallow secondary errors */ }
    }

    // Safety net: if the loop exits without an explicit complete/error event,
    // emit one so the webview's OpBars don't stay stuck in "processing".
    if (!ctx.completed && !lastError) {
      try {
        await toolRegistry.anchor_emit_event({
          type: 'complete',
          payload: { target_anchor: target, summary: 'op finished (auto-completed by runtime)' },
        }, ctx);
      } catch (_) { /* swallow */ }
    }

    const consumedMs = Date.now() - startedAt;
    log(`in-process agent: exit opId=${opId} turns=${turn} ms=${consumedMs} completed=${ctx.completed} stop=${stopReason} err=${lastError ? lastError.message : '-'}`);
    autoExecLog({
      event: 'inproc_complete',
      opId, opKind, target,
      turns: turn,
      consumedMs,
      completed: ctx.completed,
      stop_reason: stopReason,
      error: lastError ? (lastError.message || String(lastError)) : null,
    });
  }

  function pump() {
    while (running < concurrency && queue.length > 0) {
      const op = queue.shift();
      running++;
      runOne(op)
        .catch(e => log('in-process agent: unhandled: ' + (e && e.message || e)))
        .finally(() => {
          running--;
          setImmediate(pump);
        });
    }
  }

  return {
    enqueue(op) {
      queue.push(op);
      pump();
    },
    stats() {
      return { running, queued: queue.length, concurrency, model };
    },
  };
}

module.exports = { create, SYSTEM_PROMPT, TOOL_DEFS };
