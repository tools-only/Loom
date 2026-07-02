function authHeaders(token) {
  return { authorization: `Bot ${token}` };
}

function startTyping({ apiBase, channelId, token, request, agent = null, intervalMs = 8000 }) {
  let stopped = false;
  const send = async () => {
    if (stopped) return;
    try {
      await request(
        'POST',
        `${String(apiBase).replace(/\/+$/, '')}/channels/${encodeURIComponent(channelId)}/typing`,
        { headers: authHeaders(token), agent },
      );
    } catch {}
  };
  void send();
  const timer = setInterval(send, intervalMs);
  if (typeof timer.unref === 'function') timer.unref();
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}

async function replyAfterTypingStops(stopTyping, sendReply) {
  stopTyping();
  await sendReply();
}

async function createStatusMessage({ apiBase, channelId, sourceMessageId, token, request, agent = null }) {
  const body = {
    embeds: [{
      title: 'Loom 已接收任务',
      description: '正在转发给 Brain…',
      color: 0xF59E0B,
      fields: [{ name: '状态', value: '等待 Brain 规划和派发 hand agents', inline: false }],
      footer: { text: 'Loom Brain' },
    }],
    allowed_mentions: { parse: [] },
  };
  if (sourceMessageId) {
    body.message_reference = {
      message_id: String(sourceMessageId),
      channel_id: String(channelId),
      fail_if_not_exists: false,
    };
  }
  const response = await request(
    'POST',
    `${String(apiBase).replace(/\/+$/, '')}/channels/${encodeURIComponent(channelId)}/messages`,
    { body, headers: authHeaders(token), agent },
  );
  if (response.statusCode >= 400) return '';
  return String(response.json && response.json.id || '');
}

module.exports = { createStatusMessage, replyAfterTypingStops, startTyping };
