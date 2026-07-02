const fs = require('fs');
const http = require('http');
const https = require('https');
const { execFileSync } = require('child_process');
const path = require('path');
const { URL } = require('url');

function loadJsonFile(file, fallback = {}) {
  try {
    if (!fs.existsSync(file)) return fallback;
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    return data && typeof data === 'object' ? data : fallback;
  } catch {
    return fallback;
  }
}

function channelsFromDocument(document) {
  const channels = document && document.channels;
  if (Array.isArray(channels)) {
    return channels.filter((item) => item && typeof item === 'object');
  }
  if (channels && typeof channels === 'object') {
    return Object.entries(channels)
      .filter(([, value]) => value && typeof value === 'object')
      .map(([channelId, value]) => ({ channel_id: channelId, ...value }));
  }
  return [];
}

function findChannelConfig(configPath, channelId) {
  const document = loadJsonFile(configPath, {});
  return channelsFromDocument(document).find((channel) => {
    return String(channel.channel_id || channel.id || '') === String(channelId || '');
  }) || null;
}

function canonicalPlatform(config) {
  return String(config.platform || config.channel_id || '').trim().toLowerCase();
}

function channelId(config) {
  return String(config.channel_id || config.id || canonicalPlatform(config)).trim();
}

function isEnabled(config) {
  return config && config.enabled === true;
}

function responseMode(config) {
  return String(config.responseMode || config.response_mode || '').trim().toLowerCase();
}

function shouldSendReply(config) {
  return ['reply', 'auto_reply'].includes(responseMode(config));
}

function listValue(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === 'string') return value.split(',').map((item) => item.trim()).filter(Boolean);
  return [];
}

function configValue(config, camelKey, snakeKey, fallback = undefined) {
  if (config && Object.prototype.hasOwnProperty.call(config, camelKey)) return config[camelKey];
  if (snakeKey && config && Object.prototype.hasOwnProperty.call(config, snakeKey)) return config[snakeKey];
  return fallback;
}

function normalizeProxyUrl(proxy, { username = '', password = '' } = {}) {
  let raw = String(proxy || '').trim();
  if (!raw) return '';
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) raw = `http://${raw}`;
  const parsed = new URL(raw);
  if (username && !parsed.username) parsed.username = username;
  if (password && !parsed.password) parsed.password = password;
  return parsed.toString();
}

function envProxyUrl(env = process.env) {
  const names = [
    'HTTPS_PROXY',
    'https_proxy',
    'HTTP_PROXY',
    'http_proxy',
    'ALL_PROXY',
    'all_proxy',
  ];
  for (const name of names) {
    const value = normalizeProxyUrl(env && env[name] ? env[name] : '');
    if (value) return value;
  }
  return '';
}

function discoverListeningPorts() {
  if (process.platform !== 'win32') return [];
  try {
    const output = execFileSync('netstat', ['-ano', '-p', 'TCP'], {
      encoding: 'utf8',
      windowsHide: true,
      maxBuffer: 1024 * 1024,
    });
    const ports = new Set();
    for (const line of output.split(/\r?\n/)) {
      const match = line.match(/^\s*TCP\s+([^\s:]+):(\d+)\s+[^\s:]+:\d+\s+LISTENING\s+\d+\s*$/i);
      if (!match) continue;
      const host = String(match[1] || '').toLowerCase();
      const port = Number(match[2]);
      if (!Number.isFinite(port) || port <= 0) continue;
      if (host === '127.0.0.1' || host === '0.0.0.0' || host === 'localhost' || host === '::1' || host === '[::]') {
        ports.add(port);
      }
    }
    return [...ports];
  } catch {
    return [];
  }
}

function commonProxyPorts() {
  return [
    7890, 7891, 7892, 7893,
    1080, 1081, 1087, 2080, 2081, 2082, 2083, 2086, 2087,
    3128, 3129, 4444, 5000, 6666, 6667,
    8080, 8081, 8088, 8888, 8889, 9999,
    10080, 11451, 11588, 12222, 15236, 20170, 20171, 20172,
    25555, 27888, 28080, 30080, 50080,
  ];
}

function portsToProbe({
  candidatePorts = [],
  env = process.env,
  scanCommonPorts = true,
  scanSystemPorts = true,
} = {}) {
  const ports = new Set();
  for (const port of candidatePorts || []) {
    const value = Number(port);
    if (Number.isFinite(value) && value > 0) ports.add(value);
  }
  if (scanSystemPorts) {
    for (const port of discoverListeningPorts()) ports.add(port);
  }
  if (scanCommonPorts) {
    for (const port of commonProxyPorts()) ports.add(port);
  }
  const envProxy = envProxyUrl(env);
  if (envProxy) return [];
  return [...ports];
}

function probeProxyUrl(proxyUrl, probeUrl, { timeoutMs = 1500 } = {}) {
  const { HttpProxyAgent } = require('http-proxy-agent');
  const agent = new HttpProxyAgent(proxyUrl);
  return requestJson('GET', probeUrl, { timeoutMs, agent })
    .then((response) => response && response.statusCode === 200 && response.body === 'proxy-ok')
    .catch(() => false);
}

async function detectLocalProxyUrl(options = {}) {
  const {
    candidatePorts,
    env = process.env,
    probeUrl = '',
    timeoutMs = 1500,
    scanCommonPorts = true,
    scanSystemPorts = true,
  } = options;

  const envUrl = envProxyUrl(env);
  if (envUrl) return envUrl;

  const ports = portsToProbe({ candidatePorts, env, scanCommonPorts, scanSystemPorts });
  if (!ports.length) return '';

  let probeServer = null;
  let probeOrigin = probeUrl;
  if (!probeOrigin) {
    probeOrigin = await new Promise((resolve, reject) => {
      const server = http.createServer((req, res) => {
        if (req.url === '/probe') {
          res.writeHead(200, { 'content-type': 'text/plain' });
          res.end('proxy-ok');
          return;
        }
        res.writeHead(404, { 'content-type': 'text/plain' });
        res.end('missing');
      });
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        probeServer = server;
        resolve(`http://127.0.0.1:${server.address().port}/probe`);
      });
    });
  }

  try {
    for (const port of ports) {
      const proxyUrl = normalizeProxyUrl(`127.0.0.1:${port}`);
      if (!proxyUrl) continue;
      if (await probeProxyUrl(proxyUrl, probeOrigin, { timeoutMs })) return proxyUrl;
    }
    return '';
  } finally {
    if (probeServer) {
      await new Promise((resolve) => probeServer.close(resolve));
    }
  }
}

function proxyUrlFromConfig(config, options = {}) {
  const explicitProxy = normalizeProxyUrl(
    configValue(config, 'proxy', 'proxy', ''),
    {
      username: String(configValue(config, 'proxyUsername', 'proxy_username', '') || ''),
      password: String(configValue(config, 'proxyPassword', 'proxy_password', '') || ''),
    },
  );
  if (explicitProxy) return explicitProxy;

  const envProxy = envProxyUrl(options.env || process.env);
  if (envProxy) return envProxy;
  return '';
}

let cachedDetectedProxyUrl = '';
let cachedDetectedProxySource = '';

async function createProxyAgent(config) {
  let proxyUrl = proxyUrlFromConfig(config);
  if (!proxyUrl) {
    const source = JSON.stringify({
      proxy: String(configValue(config, 'proxy', 'proxy', '') || ''),
      proxyUsername: String(configValue(config, 'proxyUsername', 'proxy_username', '') || ''),
      proxyPassword: String(configValue(config, 'proxyPassword', 'proxy_password', '') || ''),
      httpProxy: String(process.env.HTTP_PROXY || process.env.http_proxy || ''),
      httpsProxy: String(process.env.HTTPS_PROXY || process.env.https_proxy || ''),
      allProxy: String(process.env.ALL_PROXY || process.env.all_proxy || ''),
    });
    if (cachedDetectedProxyUrl && cachedDetectedProxySource === source) {
      proxyUrl = cachedDetectedProxyUrl;
    } else {
      proxyUrl = await detectLocalProxyUrl({ env: process.env });
      if (proxyUrl) {
        cachedDetectedProxyUrl = proxyUrl;
        cachedDetectedProxySource = source;
      }
    }
  }
  if (!proxyUrl) return null;
  const { HttpsProxyAgent } = require('https-proxy-agent');
  return new HttpsProxyAgent(proxyUrl);
}

function isAllowed(value, allowed) {
  const allow = listValue(allowed);
  if (allow.includes('*')) return true;
  if (!allow.length) return false;
  return allow.includes(String(value || ''));
}

function readJsonBody(req, { limitBytes = 1024 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', (chunk) => {
      body += chunk;
      if (Buffer.byteLength(body, 'utf8') > limitBytes) {
        reject(new Error('request body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!body.trim()) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

function requestJson(method, url, { body, headers = {}, timeoutMs = 15000, agent = null } = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const transport = parsed.protocol === 'https:' ? https : http;
    const payload = body == null ? null : Buffer.from(JSON.stringify(body));
    const req = transport.request({
      method,
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path: `${parsed.pathname}${parsed.search}`,
      ...(agent ? { agent } : {}),
      headers: {
        ...(payload ? {
          'content-type': 'application/json',
          'content-length': payload.length,
        } : {}),
        ...headers,
      },
      timeout: timeoutMs,
    }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        text += chunk;
      });
      res.on('end', () => {
        let json = null;
        if (text.trim()) {
          try {
            json = JSON.parse(text);
          } catch {
            json = null;
          }
        }
        resolve({ statusCode: res.statusCode || 0, body: text, json });
      });
    });
    req.on('timeout', () => {
      req.destroy(new Error(`request timed out: ${url}`));
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function postSocialIngress(brainUrl, platform, payload, { timeoutMs = 300000 } = {}) {
  const base = String(brainUrl || 'http://127.0.0.1:3002').replace(/\/+$/, '');
  return requestJson('POST', `${base}/social/${encodeURIComponent(platform)}/ingress`, { body: payload, timeoutMs });
}

function safeLog(prefix, message) {
  const line = `[${prefix}] ${message}\n`;
  process.stderr.write(line);
  try {
    const logDir = process.env.LOOM_CHANNEL_BRIDGE_LOG_DIR || path.join(__dirname, '..', '..', 'logs', 'channel-bridges');
    const logName = String(prefix || 'bridge')
      .replace(/[^a-z0-9_.-]+/gi, '_')
      .slice(0, 80) || 'bridge';
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(path.join(logDir, `${logName}.log`), `${new Date().toISOString()} ${line}`, 'utf8');
  } catch {}
}

module.exports = {
  canonicalPlatform,
  channelId,
  channelsFromDocument,
  configValue,
  createProxyAgent,
  detectLocalProxyUrl,
  findChannelConfig,
  isAllowed,
  isEnabled,
  listValue,
  loadJsonFile,
  normalizeProxyUrl,
  postSocialIngress,
  proxyUrlFromConfig,
  readJsonBody,
  requestJson,
  envProxyUrl,
  responseMode,
  safeLog,
  shouldSendReply,
};
