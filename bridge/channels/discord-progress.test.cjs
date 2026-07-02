const assert = require('node:assert/strict');
const test = require('node:test');

const {
  createStatusMessage,
  replyAfterTypingStops,
  startTyping,
} = require('./discord-progress.cjs');

test('replyAfterTypingStops clears typing before waiting for the reply request', async () => {
  const events = [];
  let releaseReply;
  const replyDone = new Promise((resolve) => { releaseReply = resolve; });

  const completion = replyAfterTypingStops(
    () => events.push('typing-stopped'),
    async () => {
      events.push('reply-started');
      await replyDone;
      events.push('reply-finished');
    },
  );

  await Promise.resolve();
  assert.deepEqual(events, ['typing-stopped', 'reply-started']);
  releaseReply();
  await completion;
  assert.deepEqual(events, ['typing-stopped', 'reply-started', 'reply-finished']);
});

test('startTyping sends immediately and renews until stopped', async () => {
  const calls = [];
  const request = async (method, url) => {
    calls.push({ method, url });
    return { statusCode: 204 };
  };

  const stop = startTyping({
    apiBase: 'https://discord.example/api/v10',
    channelId: 'channel_1',
    token: 'bot-token',
    intervalMs: 10,
    request,
  });
  await new Promise((resolve) => setTimeout(resolve, 26));
  stop();
  const countAfterStop = calls.length;
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.ok(countAfterStop >= 2);
  assert.equal(calls.length, countAfterStop);
  assert.ok(calls.every((call) => call.method === 'POST'));
  assert.ok(calls.every((call) => call.url.endsWith('/channels/channel_1/typing')));
});

test('createStatusMessage replies with an initial Embed and returns its id', async () => {
  let captured;
  const request = async (method, url, options) => {
    captured = { method, url, options };
    return { statusCode: 200, json: { id: 'status_1' } };
  };

  const statusId = await createStatusMessage({
    apiBase: 'https://discord.example/api/v10',
    channelId: 'channel_1',
    sourceMessageId: 'source_1',
    token: 'bot-token',
    request,
  });

  assert.equal(statusId, 'status_1');
  assert.equal(captured.method, 'POST');
  assert.ok(captured.url.endsWith('/channels/channel_1/messages'));
  assert.equal(captured.options.body.message_reference.message_id, 'source_1');
  assert.match(captured.options.body.embeds[0].title, /已接收/);
  assert.deepEqual(captured.options.body.allowed_mentions.parse, []);
});
