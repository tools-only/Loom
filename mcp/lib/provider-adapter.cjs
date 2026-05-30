'use strict';

// ── Anthropic passthrough ──────────────────────────────────────────
function createAnthropicClient(opts) {
  const { apiKey, baseUrl } = opts;
  let Anthropic;
  try {
    const sdk = require('@anthropic-ai/sdk');
    Anthropic = sdk.default || sdk;
  } catch (e) {
    throw new Error('provider-adapter: @anthropic-ai/sdk not found: ' + e.message);
  }
  const init = { apiKey };
  if (baseUrl) init.baseURL = baseUrl;
  return new Anthropic(init);
}

// ── OpenAI-compat adapter ───────────────────────────────────────────
const OPENAI_TO_ANTHROPIC_STOP = {
  'tool_calls': 'tool_use',
  'stop': 'end_turn',
  'length': 'max_tokens',
  'content_filter': 'end_turn',
};

function anthropicToolsToOpenAI(tools) {
  if (!tools || tools.length === 0) return undefined;
  return tools.map(t => ({
    type: 'function',
    function: {
      name: t.name,
      description: t.description,
      parameters: t.input_schema || { type: 'object', properties: {} },
    },
  }));
}

function messagesToOpenAI(messages) {
  const out = [];
  for (const m of messages) {
    if (m.role === 'system') {
      out.push({ role: 'system', content: m.content });
    } else if (m.role === 'user') {
      if (typeof m.content === 'string') {
        out.push({ role: 'user', content: m.content });
      } else if (Array.isArray(m.content)) {
        const textParts = [];
        const toolResults = [];
        for (const block of m.content) {
          if (block.type === 'tool_result') {
            toolResults.push({ role: 'tool', tool_call_id: block.tool_use_id, content: block.content });
          } else if (block.type === 'text') {
            textParts.push(block.text);
          } else if (typeof block === 'string') {
            textParts.push(block);
          }
        }
        if (textParts.length > 0) out.push({ role: 'user', content: textParts.join('\n') });
        out.push(...toolResults);
      }
    } else if (m.role === 'assistant') {
      if (typeof m.content === 'string') {
        out.push({ role: 'assistant', content: m.content });
      } else if (Array.isArray(m.content)) {
        const text = [];
        const toolCalls = [];
        for (const block of m.content) {
          if (block.type === 'text') text.push(block.text);
          if (block.type === 'tool_use') {
            toolCalls.push({
              id: block.id,
              type: 'function',
              function: { name: block.name, arguments: JSON.stringify(block.input) },
            });
          }
        }
        const obj = { role: 'assistant' };
        if (text.length > 0) obj.content = text.join('\n');
        if (toolCalls.length > 0) obj.tool_calls = toolCalls;
        out.push(obj);
      }
    }
  }
  return out;
}

class OpenAIStreamWrapper {
  constructor(rawStream) {
    this._stream = rawStream;
    this._accText = '';
    this._toolCalls = {};
    this._finishReason = null;
    this._textListeners = [];
  }

  on(event, cb) {
    if (event === 'text') this._textListeners.push(cb);
    return this;
  }

  async finalMessage() {
    for await (const chunk of this._stream) {
      const delta = chunk.choices?.[0]?.delta;
      const finish = chunk.choices?.[0]?.finish_reason;

      if (delta?.content) {
        this._accText += delta.content;
        for (const cb of this._textListeners) {
          try { cb(delta.content); } catch (_) {}
        }
      }

      if (delta?.tool_calls) {
        for (const tc of delta.tool_calls) {
          if (!this._toolCalls[tc.index]) {
            this._toolCalls[tc.index] = { id: tc.id || '', name: '', arguments: '' };
          }
          if (tc.id) this._toolCalls[tc.index].id = tc.id;
          if (tc.function?.name) this._toolCalls[tc.index].name += tc.function.name;
          if (tc.function?.arguments) this._toolCalls[tc.index].arguments += tc.function.arguments;
        }
      }

      if (finish) this._finishReason = finish;
    }

    const content = [];
    if (this._accText) content.push({ type: 'text', text: this._accText });

    const tcList = Object.values(this._toolCalls).filter(tc => tc.name);
    for (const tc of tcList) {
      let input = {};
      try { input = JSON.parse(tc.arguments || '{}'); } catch (_) {}
      content.push({
        type: 'tool_use',
        id: tc.id || ('tc_' + Math.random().toString(36).slice(2)),
        name: tc.name,
        input,
      });
    }

    return {
      stop_reason: OPENAI_TO_ANTHROPIC_STOP[this._finishReason] || 'end_turn',
      content,
      role: 'assistant',
    };
  }
}

class OpenAICompatClient {
  constructor(rawClient) {
    this._raw = rawClient;
  }

  get messages() {
    return {
      stream: (params) => {
        const { model, max_tokens, system, tools, messages } = params;
        const openaiMessages = [];
        if (system) openaiMessages.push({ role: 'system', content: system });
        openaiMessages.push(...messagesToOpenAI(messages));

        const oaiParams = {
          model,
          max_completion_tokens: max_tokens,
          messages: openaiMessages,
          stream: true,
        };
        if (tools && tools.length > 0) {
          oaiParams.tools = anthropicToolsToOpenAI(tools);
        }

        return new OpenAIStreamWrapper(this._raw.chat.completions.create(oaiParams));
      },

      create: async (params) => {
        const { model, max_tokens, system, tools, messages } = params;
        const openaiMessages = [];
        if (system) openaiMessages.push({ role: 'system', content: system });
        openaiMessages.push(...messagesToOpenAI(messages));

        const oaiParams = {
          model,
          max_completion_tokens: max_tokens,
          messages: openaiMessages,
        };
        if (tools && tools.length > 0) {
          oaiParams.tools = anthropicToolsToOpenAI(tools);
        }

        const resp = await this._raw.chat.completions.create(oaiParams);
        const choice = resp.choices?.[0];
        if (!choice) throw new Error('provider-adapter: empty response from OpenAI-compat API');

        // Build Anthropic-compatible content
        const content = [];
        const msg = choice.message;
        if (msg.content) {
          const text = typeof msg.content === 'string' ? msg.content
            : (Array.isArray(msg.content) ? msg.content.filter(c => c.type === 'text').map(c => c.text).join('') : '');
          if (text) content.push({ type: 'text', text });
        }
        if (msg.tool_calls) {
          for (const tc of msg.tool_calls) {
            let input = {};
            try { input = JSON.parse(tc.function.arguments || '{}'); } catch (_) {}
            content.push({ type: 'tool_use', id: tc.id, name: tc.function.name, input });
          }
        }

        return {
          stop_reason: OPENAI_TO_ANTHROPIC_STOP[choice.finish_reason] || 'end_turn',
          content,
          role: 'assistant',
        };
      },
    };
  }
}

// ── Factory ─────────────────────────────────────────────────────────
function createFromEnv(opts) {
  // Accept explicit config object (from config-store), or fall back to env vars
  const _opts = opts || {};
  const provider = (_opts.provider || process.env.ANCHOR_PROVIDER || 'anthropic').toLowerCase();
  const apiKey = _opts.apiKey || process.env.ANCHOR_API_KEY || process.env.ANTHROPIC_API_KEY;
  const baseUrl = _opts.baseUrl || process.env.ANCHOR_BASE_URL || null;
  const model = _opts.model || process.env.ANCHOR_INPROC_MODEL
    || (provider === 'anthropic' ? 'claude-haiku-4-5-20251001' : 'gpt-4o');

  if (!apiKey) return null;

  try {
    let client;
    if (provider === 'anthropic') {
      client = createAnthropicClient({ apiKey, baseUrl });
    } else {
      let OpenAI;
      try {
        const oai = require('openai');
        OpenAI = oai.default || oai;
      } catch (e) {
        throw new Error(
          'provider-adapter: openai package required for non-Anthropic providers. ' +
          'Run: npm install openai --prefix bridge'
        );
      }
      const rawClient = new OpenAI({ apiKey, baseURL: baseUrl || 'https://api.openai.com/v1' });
      client = new OpenAICompatClient(rawClient);
    }

    return { client, provider, model };
  } catch (e) {
    console.error('[provider-adapter] createFromEnv failed:', e.message);
    return null;
  }
}

module.exports = { createFromEnv, createAnthropicClient, OpenAICompatClient, anthropicToolsToOpenAI, messagesToOpenAI };
