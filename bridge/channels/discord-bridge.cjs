const path = require('path');
const WebSocket = require('ws');

const {
  configValue,
  createProxyAgent,
  findChannelConfig,
  isAllowed,
  listValue,
  postSocialIngress,
  requestJson,
  responseMode,
  safeLog,
  shouldSendReply,
} = require('./common.cjs');
const { createStatusMessage, replyAfterTypingStops, startTyping } = require('./discord-progress.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const CONFIG_PATH = process.env.LOOM_CHANNEL_CONFIG_PATH || path.join(ROOT, 'config', 'social-channels.json');
const CHANNEL_ID = process.env.LOOM_CHANNEL_ID || 'discord';
const BRAIN_URL = process.env.LOOM_BRAIN_URL || 'http://127.0.0.1:3002';
const DEFAULT_GATEWAY_URL = 'wss://gateway.discord.gg/?v=10&encoding=json';
const API_BASE = process.env.LOOM_DISCORD_API_BASE || 'https://discord.com/api/v10';

let config = null;
let botUserId = '';
let ws = null;
let heartbeatTimer = null;
let reconnectDelayMs = 1000;
let sequence = null;
let shuttingDown = false;
let proxyAgent = null;

function log(message) {
  safeLog(`discord:${CHANNEL_ID}`, message);
}

function errorSummary(err) {
  if (!err) return 'unknown error';
  const fields = [err.name, err.code, err.message].map((item) => String(item || '').trim()).filter(Boolean);
  return fields.length ? fields.join(' ') : String(err);
}

async function loadConfig() {
  const loaded = findChannelConfig(CONFIG_PATH, CHANNEL_ID);
  if (!loaded) throw new Error(`channel config not found: ${CHANNEL_ID}`);
  config = loaded;
  if (config.enabled !== true) throw new Error(`channel is disabled: ${CHANNEL_ID}`);
  config.token = configValue(config, 'token', 'reply_token', '');
  if (!config.token) throw new Error(`missing Discord token for channel: ${CHANNEL_ID}`);
  proxyAgent = await createProxyAgent(config);
  if (proxyAgent) log('using configured proxy');
}

function gatewayUrl() {
  return String(configValue(config, 'gatewayUrl', 'gateway_url', DEFAULT_GATEWAY_URL) || DEFAULT_GATEWAY_URL);
}

function identify() {
  ws.send(JSON.stringify({
    op: 2,
    d: {
      token: config.token,
      intents: Number(config.intents || 37377),
      properties: {
        os: 'loom',
        browser: 'loom-channel-bridge',
        device: 'loom-channel-bridge',
      },
    },
  }));
}

function startHeartbeat(intervalMs) {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ op: 1, d: sequence }));
    }
  }, Math.max(1000, Number(intervalMs || 45000)));
}

function messageMentionsBot(message) {
  const mentions = Array.isArray(message.mentions) ? message.mentions : [];
  if (botUserId && mentions.some((item) => String(item && item.id) === botUserId)) return true;
  if (botUserId && String(message.content || '').includes(`<@${botUserId}>`)) return true;
  if (botUserId && String(message.content || '').includes(`<@!${botUserId}>`)) return true;
  return false;
}

function messageSummary(message) {
  return `id=${message && message.id || ''} channel=${message && message.channel_id || ''} guild=${message && message.guild_id || 'dm'} author=${message && message.author && message.author.id || ''}`;
}

function shouldForwardMessage(message) {
  if (!message) {
    log('message ignored reason=empty');
    return false;
  }
  if (message.author && message.author.bot) return false;
  if (!isAllowed(message.author && message.author.id, configValue(config, 'allowFrom', 'allow_from', []))) {
    log(`message ignored reason=author_not_allowed ${messageSummary(message)}`);
    return false;
  }
  const allowedChannels = listValue(configValue(config, 'allowChannels', 'allow_channels', []));
  if (allowedChannels.length && !allowedChannels.includes(String(message.channel_id || ''))) {
    log(`message ignored reason=channel_not_allowed ${messageSummary(message)}`);
    return false;
  }
  const groupPolicy = String(configValue(config, 'groupPolicy', 'group_policy', 'mention')).toLowerCase();
  const isGroup = Boolean(message.guild_id);
  if (isGroup && groupPolicy === 'mention' && !messageMentionsBot(message)) {
    log(`message ignored reason=mention_required ${messageSummary(message)}`);
    return false;
  }
  return true;
}

function discordReplyText(response) {
  const json = response && response.json;
  if (!json || typeof json !== 'object') return '';
  return String(json.reply_text || json.replyText || '');
}

function discordReplyFile(response) {
  const json = response && response.json;
  if (!json || typeof json !== 'object') return '';
  return String(json.visual_html_file || '');
}

function boundedDiscordContent(text) {
  const content = String(text || '').trim();
  if (!content) return '';
  return content.length > 1900 ? `${content.slice(0, 1897)}...` : content;
}

async function sendDiscordReply(message, text, filePath) {
  const content = boundedDiscordContent(text);
  const hasFile = filePath && require('fs').existsSync(filePath);
  if (!content && !hasFile) {
    log(`reply skipped reason=empty_reply_text ${messageSummary(message)}`);
    return;
  }
  const channelId = String(message && message.channel_id || '');
  if (!channelId) {
    log(`reply skipped reason=missing_channel_id ${messageSummary(message)}`);
    return;
  }
  const body = {
    content: content || 'Loom analysis result',
    allowed_mentions: { parse: [] },
  };
  if (message && message.id) {
    body.message_reference = {
      message_id: String(message.id),
      channel_id: channelId,
      fail_if_not_exists: false,
    };
  }

  let formData;
  let headers;
  if (hasFile) {
    // Multipart form upload with file attachment
    const FormData = require('form-data');
    const fs = require('fs');
    formData = new FormData();
    formData.append('payload_json', JSON.stringify(body));
    formData.append('files[0]', fs.createReadStream(filePath), {
      filename: 'loom-analysis.html',
      contentType: 'text/html',
    });
    headers = Object.assign(
      { authorization: `Bot ${config.token}` },
      formData.getHeaders()
    );
  } else {
    headers = {
      'content-type': 'application/json',
      authorization: `Bot ${config.token}`,
    };
  }

  const requestOpts = {
    method: 'POST',
    hostname: new URL(API_BASE).hostname,
    port: 443,
    path: `/api/v10/channels/${encodeURIComponent(channelId)}/messages`,
    headers,
    agent: proxyAgent,
    timeout: 30000,
  };

  try {
    const result = await new Promise((resolve, reject) => {
      const https = require('https');
      const req = https.request(requestOpts, (res) => {
        let text = '';
        res.setEncoding('utf8');
        res.on('data', (c) => text += c);
        res.on('end', () => {
          let json = null;
          try { json = JSON.parse(text); } catch {}
          resolve({ statusCode: res.statusCode, body: text, json });
        });
      });
      req.on('error', reject);
      req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
      if (formData) {
        formData.pipe(req);
      } else {
        req.write(JSON.stringify(body));
        req.end();
      }
    });
    if (result.statusCode >= 400) {
      log(`reply failed status=${result.statusCode} body=${String(result.body || '').slice(0, 300)} ${messageSummary(message)}`);
      return;
    }
    log(`reply sent status=${result.statusCode} hasFile=${hasFile} ${messageSummary(message)}`);
  } catch (err) {
    log(`reply error: ${err.message} ${messageSummary(message)}`);
  }
}

async function forwardMessage(message) {
  try {
    const wantsReply = shouldSendReply(config);
    const channelId = String(message && message.channel_id || '');
    const stopTyping = wantsReply && channelId
      ? startTyping({
        apiBase: API_BASE,
        channelId,
        token: config.token,
        request: requestJson,
        agent: proxyAgent,
      })
      : () => {};
    let statusMessageId = '';
    if (wantsReply && channelId) {
      try {
        statusMessageId = await createStatusMessage({
          apiBase: API_BASE,
          channelId,
          sourceMessageId: message.id,
          token: config.token,
          request: requestJson,
          agent: proxyAgent,
        });
      } catch (err) {
        log(`status message error: ${err.message} ${messageSummary(message)}`);
      }
    }
    const payload = {
      channel_adapter_id: CHANNEL_ID,
      platform: 'discord',
      send_reply: false,
      context: {
        bridgeManagedReply: true,
        responseMode: responseMode(config),
        statusMessageId,
      },
      payload: {
        id: message.id,
        channel_id: message.channel_id,
        guild_id: message.guild_id || '',
        author: {
          id: message.author && message.author.id,
          username: message.author && message.author.username,
          bot: Boolean(message.author && message.author.bot),
        },
        content: message.content || '',
        timestamp: message.timestamp || '',
        mentions: Array.isArray(message.mentions) ? message.mentions : [],
        message_reference: message.message_reference || null,
        thread_id: message.thread_id || '',
        raw: message,
      },
    };
    try {
      log(`forwarding message to brain bridge_reply=${wantsReply} ${messageSummary(message)}`);
      const ingressTimeoutMs = Math.max(
        300000,
        Number(configValue(config, 'ingressTimeoutMs', 'ingress_timeout_ms', 1800000)) || 1800000,
      );
      const response = await postSocialIngress(BRAIN_URL, 'discord', payload, { timeoutMs: ingressTimeoutMs });
      if (response.statusCode >= 400) {
        log(`brain ingress failed status=${response.statusCode} body=${String(response.body || '').slice(0, 300)} ${messageSummary(message)}`);
      } else {
        log(`brain ingress completed status=${response.statusCode} ${messageSummary(message)}`);
        if (wantsReply) {
          await replyAfterTypingStops(
            stopTyping,
            () => sendDiscordReply(message, discordReplyText(response), discordReplyFile(response)),
          );
        }
      }
    } catch (err) {
      log(`brain ingress error: ${err.message} ${messageSummary(message)}`);
    } finally {
      stopTyping();
    }
  } catch (outerErr) {
    log(`forwardMessage fatal error: ${String(outerErr && outerErr.message || outerErr)} ${messageSummary(message)}`);
  }
}

function handleDispatch(type, data) {
  if (type === 'READY') {
    botUserId = String(data && data.user && data.user.id || '');
    log(`connected as ${data && data.user && data.user.username || botUserId || 'bot'}`);
    return;
  }
  if (type === 'MESSAGE_CREATE') {
    log(`message received ${messageSummary(data)} content_chars=${String(data && data.content || '').length}`);
    if (shouldForwardMessage(data)) {
      forwardMessage(data);
    }
  }
}

async function connect() {
  await loadConfig();
  const url = gatewayUrl();
  log('connecting gateway');
  ws = new WebSocket(url, proxyAgent ? { agent: proxyAgent } : undefined);

  ws.on('open', () => {
    reconnectDelayMs = 1000;
    log('gateway websocket opened');
  });

  ws.on('message', (data) => {
    let packet = null;
    try {
      packet = JSON.parse(data.toString());
    } catch {
      return;
    }
    if (packet.s != null) sequence = packet.s;
    if (packet.op === 10) {
      startHeartbeat(packet.d && packet.d.heartbeat_interval);
      identify();
      return;
    }
    if (packet.op === 0) handleDispatch(packet.t, packet.d);
    if (packet.op === 7) {
      log('gateway requested reconnect');
      try {
        ws.close();
      } catch {}
    }
    if (packet.op === 9) {
      log(`gateway invalid session resumable=${Boolean(packet.d)}`);
      try {
        ws.close();
      } catch {}
    }
  });

  ws.on('close', (code, reason) => {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    const reasonText = Buffer.isBuffer(reason) ? reason.toString('utf8') : String(reason || '');
    log(`gateway closed code=${code}${reasonText ? ` reason=${reasonText.slice(0, 200)}` : ''}`);
    if (!shuttingDown) scheduleReconnect();
  });

  ws.on('error', (err) => {
    log(`gateway error: ${errorSummary(err)}`);
  });
}

function scheduleReconnect() {
  const delay = reconnectDelayMs;
  reconnectDelayMs = Math.min(60000, Math.floor(reconnectDelayMs * 1.8));
  log(`reconnecting in ${delay}ms`);
  setTimeout(() => {
    if (!shuttingDown) connect().catch((err) => {
      log(`connect failed: ${err.message}`);
      scheduleReconnect();
    });
  }, delay);
}

function shutdown() {
  shuttingDown = true;
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  if (ws) {
    try {
      ws.close(1000, 'shutdown');
    } catch {}
  }
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

connect().catch((err) => {
  log(`startup failed: ${err.message}`);
  process.exit(1);
});
