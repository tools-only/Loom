const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn } = require('child_process');

const {
  canonicalPlatform,
  channelId,
  channelsFromDocument,
  isEnabled,
  loadJsonFile,
  safeLog,
} = require('./common.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const CONFIG_PATH = process.env.LOOM_SOCIAL_CHANNEL_CONFIG || path.join(ROOT, 'config', 'social-channels.json');
const BRAIN_URL = process.env.LOOM_BRAIN_URL || 'http://127.0.0.1:3002';
const HEALTH_PORT = Number(process.env.LOOM_CHANNEL_BRIDGE_PORT || 3015);
const FEISHU_BASE_PORT = Number(process.env.LOOM_FEISHU_BRIDGE_BASE_PORT || 3020);

const BRIDGES = {
  discord: 'discord-bridge.cjs',
  feishu: 'feishu-bridge.cjs',
  lark: 'feishu-bridge.cjs',
};

const children = new Map();
let desiredKeys = new Set();
let reconcileTimer = null;
let shuttingDown = false;

function bridgeKey(config) {
  return channelId(config);
}

function bridgeScript(config) {
  return BRIDGES[canonicalPlatform(config)] || '';
}

function bridgeSignature(config) {
  return JSON.stringify(config);
}

function enabledChannels() {
  const document = loadJsonFile(CONFIG_PATH, {});
  return channelsFromDocument(document)
    .filter(isEnabled)
    .filter((channel) => bridgeScript(channel));
}

function reconcile() {
  const channels = enabledChannels();
  desiredKeys = new Set(channels.map(bridgeKey));
  const feishuChannels = channels.filter((item) => ['feishu', 'lark'].includes(canonicalPlatform(item)));
  const feishuPorts = new Map(feishuChannels.map((item, index) => [bridgeKey(item), FEISHU_BASE_PORT + index]));

  for (const config of channels) {
    const key = bridgeKey(config);
    const script = bridgeScript(config);
    const signature = bridgeSignature(config);
    const running = children.get(key);
    if (running && running.signature === signature && running.script === script) continue;
    if (running) stopChild(key, 'config changed');
    startChild(config, script, signature, feishuPorts.get(key));
  }

  for (const key of Array.from(children.keys())) {
    if (!desiredKeys.has(key)) stopChild(key, 'channel disabled or removed');
  }
}

function startChild(config, script, signature, feishuPort) {
  const key = bridgeKey(config);
  const platform = canonicalPlatform(config);
  const scriptPath = path.join(__dirname, script);
  const env = {
    ...process.env,
    LOOM_CHANNEL_CONFIG_PATH: CONFIG_PATH,
    LOOM_CHANNEL_ID: key,
    LOOM_BRAIN_URL: BRAIN_URL,
  };
  if (feishuPort) {
    env.LOOM_FEISHU_BRIDGE_PORT = String(feishuPort);
    env.LOOM_FEISHU_BRIDGE_PATH = `/feishu/${encodeURIComponent(key)}/events`;
  }

  const child = spawn(process.execPath, [scriptPath], {
    cwd: ROOT,
    env,
    stdio: 'inherit',
  });
  children.set(key, {
    child,
    platform,
    script,
    signature,
    startedAt: new Date().toISOString(),
  });
  safeLog('channel-launcher', `started ${platform} bridge for ${key}`);

  child.on('exit', (code, signal) => {
    const current = children.get(key);
    if (current && current.child === child) children.delete(key);
    safeLog('channel-launcher', `${platform} bridge ${key} exited code=${code} signal=${signal || ''}`);
    if (!shuttingDown && desiredKeys.has(key)) {
      setTimeout(() => {
        if (!children.has(key)) reconcile();
      }, 5000);
    }
  });
}

function stopChild(key, reason) {
  const running = children.get(key);
  if (!running) return;
  children.delete(key);
  safeLog('channel-launcher', `stopping ${running.platform} bridge for ${key}: ${reason}`);
  running.child.kill();
}

function scheduleReconcile() {
  if (reconcileTimer) clearTimeout(reconcileTimer);
  reconcileTimer = setTimeout(() => {
    reconcileTimer = null;
    reconcile();
  }, 500);
}

function startHealthServer() {
  const server = http.createServer((req, res) => {
    if (req.url === '/health') {
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({
        ok: true,
        config_path: CONFIG_PATH,
        brain_url: BRAIN_URL,
        bridges: Array.from(children.entries()).map(([id, info]) => ({
          channel_id: id,
          platform: info.platform,
          started_at: info.startedAt,
          pid: info.child.pid,
        })),
      }));
      return;
    }
    res.statusCode = 404;
    res.end('not found');
  });
  server.listen(HEALTH_PORT, '127.0.0.1', () => {
    safeLog('channel-launcher', `health on http://127.0.0.1:${HEALTH_PORT}/health`);
  });
  return server;
}

function shutdown() {
  shuttingDown = true;
  for (const key of Array.from(children.keys())) stopChild(key, 'launcher shutting down');
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

safeLog('channel-launcher', `using config ${CONFIG_PATH}`);
safeLog('channel-launcher', `using brain ${BRAIN_URL}`);
startHealthServer();
reconcile();

try {
  fs.watch(CONFIG_PATH, scheduleReconcile);
} catch (err) {
  safeLog('channel-launcher', `config watch unavailable: ${err.message}`);
}
