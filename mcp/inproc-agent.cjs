// Anchor in-process agent — provider-agnostic tool-use loop running inside
// the long-lived MCP Leader Node process. Replaces per-op `claude -p` subprocess.
// All deps (provider client, registry, loggers) are injected via create() so
// this module stays pure and testable.
// Supported providers via provider-adapter.cjs: Anthropic (default), OpenAI-compat.

'use strict';

const fs = require('fs');
const path = require('path');

// Content agent system prompt is defined in content-agent.md — separate from the
// management-agent CLAUDE.md so infrastructure knowledge never bleeds into content generation.
const CONTENT_AGENT_MD = path.join(__dirname, 'content-agent.md');
const SYSTEM_PROMPT = (() => {
  try { return fs.readFileSync(CONTENT_AGENT_MD, 'utf8'); }
  catch (e) { process.stderr.write(`[inproc] WARN: could not load content-agent.md: ${e.message}\n`); return ''; }
})();

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
  const opKind   = op?.intent?.op || '(unknown)';
  const target   = op?.intent?.target_ref || op?.target || '(unknown)';
  const instr    = op?.intent?.instruction || op?.args?.instruction || op?.args?.value || '';
  const subtree  = op?.render_state?.relevant_subtree;
  const html     = subtree?.target_html || subtree?.outerHTML || null;
  const needsFull = ['restructure', 'branch'].includes(opKind) && !html;

  const lines = [`Op: ${opKind} | Target: ${target}`];
  if (instr) lines.push(`Instruction: ${instr}`);

  if (html) {
    lines.push('', 'Current HTML of target node:', '```html', html, '```',
      '', 'Generate the modified outerHTML and call anchor_patch. Then call anchor_emit_event(complete).');
  } else if (needsFull) {
    lines.push('', 'This op needs full-page context. Call anchor_get_pending_op first, then patch.');
  } else {
    lines.push('', 'Call anchor_get_pending_op to receive target HTML, then call anchor_patch.');
  }

  return lines.join('\n');
}

function create(opts) {
  const {
    provider,
    model,
    toolRegistry,
    log,
    autoExecLog,
    concurrency,
  } = opts;

  if (!provider) throw new Error('inproc-agent: provider required (use provider-adapter)');
  if (!toolRegistry) throw new Error('inproc-agent: toolRegistry required');

  const client = provider;
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

    // If target HTML was embedded in the user message, pre-consume the op so
    // anchor_get_pending_op returns {pending:false} — the LLM has everything it needs.
    const subtree = op?.render_state?.relevant_subtree;
    if (subtree?.target_html || subtree?.outerHTML) ctx.opConsumed = true;

    let turn = 0;
    let lastError = null;
    let stopReason = null;

    try {
      while (turn < MAX_TURNS) {
        turn++;

        const stream = client.messages.stream({
          model,
          max_tokens: MAX_TOKENS,
          system: op?.systemPrompt || SYSTEM_PROMPT,
          tools: TOOL_DEFS,
          messages,
        });

        const resp = await stream.finalMessage();
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
