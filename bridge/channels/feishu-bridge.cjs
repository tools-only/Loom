const http = require('http');
const path = require('path');

const {
  configValue,
  findChannelConfig,
  postSocialIngress,
  readJsonBody,
  safeLog,
  shouldSendReply,
} = require('./common.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const CONFIG_PATH = process.env.LOOM_CHANNEL_CONFIG_PATH || path.join(ROOT, 'config', 'social-channels.json');
const CHANNEL_ID = process.env.LOOM_CHANNEL_ID || 'feishu';
const BRAIN_URL = process.env.LOOM_BRAIN_URL || 'http://127.0.0.1:3002';
const HOST = process.env.LOOM_FEISHU_BRIDGE_HOST || '127.0.0.1';
const PORT = Number(process.env.LOOM_FEISHU_BRIDGE_PORT || 3020);
const EVENT_PATH = process.env.LOOM_FEISHU_BRIDGE_PATH || `/feishu/${encodeURIComponent(CHANNEL_ID)}/events`;

let config = null;

function log(message) {
  safeLog(`feishu:${CHANNEL_ID}`, message);
}

function loadConfig() {
  const loaded = findChannelConfig(CONFIG_PATH, CHANNEL_ID);
  if (!loaded) throw new Error(`channel config not found: ${CHANNEL_ID}`);
  config = loaded;
  if (config.enabled !== true) throw new Error(`channel is disabled: ${CHANNEL_ID}`);
}

function eventPayload(payload) {
  return payload && typeof payload.payload === 'object' ? payload.payload : payload;
}

function verificationChallenge(payload) {
  const event = eventPayload(payload) || {};
  return event.challenge || payload.challenge || '';
}

function verifyToken(payload) {
  const expected = String(configValue(config, 'verificationToken', 'verification_token', '') || '').trim();
  if (!expected) return true;
  const event = eventPayload(payload) || {};
  return String(event.token || payload.token || '') === expected;
}

function hasMention(message) {
  if (!message || typeof message !== 'object') return false;
  if (Array.isArray(message.mentions) && message.mentions.length) return true;
  const content = message.content;
  if (typeof content === 'string' && content.includes('<at')) return true;
  if (content && typeof content === 'object' && String(content.text || '').includes('<at')) return true;
  return false;
}

function shouldForward(payload) {
  const event = payload.event && typeof payload.event === 'object' ? payload.event : payload;
  const message = event.message && typeof event.message === 'object' ? event.message : {};
  const groupPolicy = String(configValue(config, 'groupPolicy', 'group_policy', 'mention') || 'mention').toLowerCase();
  const chatType = String(message.chat_type || message.chatType || '').toLowerCase();
  if (groupPolicy === 'mention' && ['group', 'chat'].includes(chatType) && !hasMention(message)) {
    return false;
  }
  return true;
}

async function forward(payload) {
  const body = {
    channel_adapter_id: CHANNEL_ID,
    platform: 'feishu',
    send_reply: shouldSendReply(config),
    payload,
  };
  const response = await postSocialIngress(BRAIN_URL, 'feishu', body);
  return response;
}

function sendJson(res, statusCode, body) {
  const text = JSON.stringify(body);
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(text),
  });
  res.end(text);
}

async function handleEvent(req, res) {
  let payload;
  try {
    payload = await readJsonBody(req, { limitBytes: 5 * 1024 * 1024 });
  } catch (err) {
    sendJson(res, 400, { ok: false, error: err.message });
    return;
  }

  const challenge = verificationChallenge(payload);
  if (challenge) {
    sendJson(res, 200, { challenge });
    return;
  }

  if (!verifyToken(payload)) {
    sendJson(res, 401, { ok: false, error: 'invalid verification token' });
    return;
  }

  if (!shouldForward(payload)) {
    sendJson(res, 200, { ok: true, skipped: true, reason: 'groupPolicy mention not satisfied' });
    return;
  }

  try {
    const response = await forward(payload);
    if (response.statusCode >= 400) {
      sendJson(res, 502, {
        ok: false,
        error: 'brain ingress failed',
        status_code: response.statusCode,
      });
      return;
    }
    sendJson(res, 200, { ok: true, brain: response.json || null });
  } catch (err) {
    sendJson(res, 502, { ok: false, error: err.message });
  }
}

function start() {
  loadConfig();
  const server = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/health') {
      sendJson(res, 200, {
        ok: true,
        channel_id: CHANNEL_ID,
        platform: 'feishu',
        event_url: `http://${HOST}:${PORT}${EVENT_PATH}`,
      });
      return;
    }
    if (req.method === 'POST' && req.url === EVENT_PATH) {
      handleEvent(req, res);
      return;
    }
    sendJson(res, 404, { ok: false, error: 'not found', event_path: EVENT_PATH });
  });
  server.listen(PORT, HOST, () => {
    log(`listening on http://${HOST}:${PORT}${EVENT_PATH}`);
  });
}

try {
  start();
} catch (err) {
  log(`startup failed: ${err.message}`);
  process.exit(1);
}
