const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
  channelsFromDocument,
  detectLocalProxyUrl,
  isAllowed,
  proxyUrlFromConfig,
  shouldSendReply,
} = require('./common.cjs');

test('channelsFromDocument accepts Nanobot object shape', () => {
  const channels = channelsFromDocument({
    channels: {
      discord: {
        enabled: true,
        token: 'YOUR_BOT_TOKEN',
        allowFrom: ['YOUR_USER_ID'],
        allowChannels: [],
        groupPolicy: 'mention',
        streaming: true,
      },
    },
  });

  assert.equal(channels.length, 1);
  assert.equal(channels[0].channel_id, 'discord');
  assert.equal(channels[0].token, 'YOUR_BOT_TOKEN');
  assert.deepEqual(channels[0].allowFrom, ['YOUR_USER_ID']);
});

test('allowlist and reply mode helpers follow channel config', () => {
  assert.equal(isAllowed('u1', ['*']), true);
  assert.equal(isAllowed('u1', ['u1']), true);
  assert.equal(isAllowed('u2', ['u1']), false);
  assert.equal(isAllowed('u1', []), false);
  assert.equal(shouldSendReply({ responseMode: 'reply' }), true);
  assert.equal(shouldSendReply({ response_mode: 'auto_reply' }), true);
  assert.equal(shouldSendReply({ responseMode: '' }), false);
});

test('proxyUrlFromConfig accepts Nanobot-style proxy fields', () => {
  assert.equal(proxyUrlFromConfig({ proxy: '127.0.0.1:7890' }, { env: {} }), 'http://127.0.0.1:7890/');
  assert.equal(
    proxyUrlFromConfig({ proxy: 'http://proxy.local:8080', proxyUsername: 'u', proxyPassword: 'p' }, { env: {} }),
    'http://u:p@proxy.local:8080/',
  );
  assert.equal(proxyUrlFromConfig({ proxy: null }, { env: {} }), '');
});

test('detectLocalProxyUrl finds a proxy by probing local listening ports', async () => {
  const http = require('node:http');

  const origin = await new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      if (req.url === '/probe') {
        res.writeHead(200, { 'content-type': 'text/plain' });
        res.end('proxy-ok');
        return;
      }
      res.writeHead(404, { 'content-type': 'text/plain' });
      res.end('missing');
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });

  const proxy = await new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const target = new URL(req.url);
      const upstream = http.request({
        hostname: target.hostname,
        port: target.port || 80,
        path: `${target.pathname}${target.search}`,
        method: req.method,
        headers: req.headers,
      }, (upstreamRes) => {
        res.writeHead(upstreamRes.statusCode || 500, upstreamRes.headers);
        upstreamRes.pipe(res);
      });
      upstream.on('error', (err) => {
        res.writeHead(502, { 'content-type': 'text/plain' });
        res.end(String(err.message || err));
      });
      req.pipe(upstream);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });

  try {
    const proxyUrl = await detectLocalProxyUrl({
      candidatePorts: [proxy.address().port],
      env: {},
      scanCommonPorts: false,
      scanSystemPorts: false,
      probeUrl: `http://127.0.0.1:${origin.address().port}/probe`,
    });

    assert.equal(proxyUrl, `http://127.0.0.1:${proxy.address().port}/`);
  } finally {
    await Promise.all([
      new Promise((resolve) => origin.close(resolve)),
      new Promise((resolve) => proxy.close(resolve)),
    ]);
  }
});

test('discord bridge uses Discord Gateway identify property keys', () => {
  const source = fs.readFileSync(path.join(__dirname, 'discord-bridge.cjs'), 'utf8');
  assert.match(source, /os: 'loom'/);
  assert.match(source, /browser: 'loom-channel-bridge'/);
  assert.match(source, /device: 'loom-channel-bridge'/);
  assert.doesNotMatch(source, /\$os/);
});

test('discord bridge uses configurable long-running agent ingress timeout', () => {
  const source = fs.readFileSync(path.join(__dirname, 'discord-bridge.cjs'), 'utf8');
  assert.match(source, /ingressTimeoutMs/);
  assert.match(source, /postSocialIngress\(BRAIN_URL, 'discord', payload, \{ timeoutMs: ingressTimeoutMs \}\)/);
});
