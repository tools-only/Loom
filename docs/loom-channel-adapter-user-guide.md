# Loom Channel Adapter User Guide

This guide explains how to connect a chat channel such as Feishu/Lark, Discord, or a custom bridge to Loom Brain.

## What A Channel Does

A channel adapter is the social entry and reply layer around Brain:

```text
mobile chat message
  -> channel webhook / bridge
  -> Loom /social ingress
  -> Brain analyze
  -> hand agents run
  -> Brain final reply
  -> channel sends reply to the user
```

The channel does not replace Brain or hand agents. It only handles:
- message normalization
- optional webhook verification
- sender allow-list checks
- reply transport configuration
- channel-specific defaults, such as `responseMode`, `allowFrom`, and `groupPolicy`

## Built-In Channels

Loom mirrors Nanobot's built-in channel catalog. Every channel type is configured as a bridge-mode adapter: it can be configured, selected, allow-listed, and routed through Loom, while platform-specific webhook polling, signing, SDK calls, and delivery should live in a small bridge service.

| Channel ID | Platform | Use case |
| --- | --- | --- |
| `generic` | `generic` | Your own bridge service posts normalized messages to Loom. |
| `discord` | `discord` | Discord webhook/bot ingress and replies. |
| `feishu` | `feishu` | Feishu/Lark event callbacks and IM replies. |
| `dingtalk` | `dingtalk` | DingTalk bridge-compatible channel. |
| `email` | `email` | Email bridge-compatible channel. |
| `matrix` | `matrix` | Matrix bridge-compatible channel. |
| `mochat` | `mochat` | MoChat bridge-compatible channel. |
| `msteams` | `msteams` | Microsoft Teams bridge-compatible channel. |
| `napcat` | `napcat` | NapCat/QQ bridge-compatible channel. |
| `qq` | `qq` | QQ bridge-compatible channel. |
| `signal` | `signal` | Signal bridge-compatible channel. |
| `slack` | `slack` | Slack bridge-compatible channel. |
| `telegram` | `telegram` | Telegram bridge-compatible channel. |
| `websocket` | `websocket` | WebSocket/Web UI bridge-compatible channel. |
| `wecom` | `wecom` | WeCom bridge-compatible channel. |
| `weixin` | `weixin` | Weixin/WeChat bridge-compatible channel. |
| `whatsapp` | `whatsapp` | WhatsApp bridge-compatible channel. |

Check configured channels:

```http
GET /social/channels
```

## Configuration File

The shared config file is:

```text
config/social-channels.json
```

Brain reads this file at startup. CLI, TUI, and webview channel settings all write the same file.

Minimal shape:

```json
{
  "version": 1,
  "default_channel": "generic",
  "channels": [
    {
      "channel_id": "discord",
      "platform": "discord",
      "label": "Discord",
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"],
      "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json",
      "allowChannels": [],
      "groupPolicy": "mention",
      "streaming": true,
      "proxy": null
    }
  ]
}
```

Loom accepts Nanobot's camelCase config shape and keeps snake_case aliases readable for older files.

## Startup Behavior

`scripts\start-anchor.bat` starts three local surfaces:

- Anchor web UI on `http://localhost:3000`
- Loom Brain on `http://localhost:3002`
- Channel bridge launcher on `http://localhost:3015`

The bridge launcher reads `config/social-channels.json`, starts bridge processes for enabled supported channels, and watches the config for changes. It does not make Feishu or Discord special inside Brain; each platform bridge is still an external bridge process.

Supported auto-start bridge processes:

| Platform | Behavior |
| --- | --- |
| `discord` | Connects to Discord Gateway with `token`, forwards allowed messages to Brain. |
| `feishu` / `lark` | Starts a local callback endpoint and forwards Feishu events to Brain. Configure Feishu's event URL or an external tunnel to reach that endpoint. |

Other enabled channels remain configured and selectable, but need their own bridge process until a platform bridge is added.

Discord uses the same outbound Gateway model as Nanobot: the bridge process opens a WebSocket to `gatewayUrl` (alias `gateway_url`), receives message events, filters them with `allowFrom` / `allowChannels` / `groupPolicy`, then forwards them to Brain. If the local machine cannot connect directly to Discord, set `proxy` on the Discord channel, for example `http://127.0.0.1:7890`. `proxyUsername` and `proxyPassword` are also supported.

When `responseMode` is `reply` or `auto_reply`, the Discord bridge also exposes Brain progress automatically:

- Discord's native typing indicator remains active while the ingress request is running.
- One reply Embed is created and edited in place, so progress does not spam the channel.
- The Embed shows the Brain phase, total dispatched hands, and which hands are running, complete, or failed.
- The final `Persisted` or `Failed` episode state is flushed before the typing indicator stops.

This uses the existing bot token and requires no additional Discord configuration. Channels with automatic replies disabled keep the previous fire-and-forget behavior.

## CLI Mode

List all Nanobot-compatible channel types:

```powershell
python -m loom_core channels available
```

List configured channels:

```powershell
python -m loom_core channels list
```

Enable a channel:

```powershell
python -m loom_core channels enable telegram `
  --channel-id telegram-work `
  --token YOUR_BOT_TOKEN `
  --set mode=polling `
  --allow-from * `
  --set-default
```

Use repeatable `--set KEY=VALUE` for platform-specific fields shown by `python -m loom_core channels available`, such as `homeserver` for Matrix, `appId` / `appSecret` for Feishu, or `allowChannels` / `groupPolicy` for Discord.

Disable, remove, or set default:

```powershell
python -m loom_core channels disable telegram-work
python -m loom_core channels remove telegram-work
python -m loom_core channels default generic
```

Use `--root D:\path\to\loom` or `--config path\to\social-channels.json` when running outside the project root.

## TUI Mode

Open the terminal menu:

```powershell
python -m loom_core channels tui
```

The TUI supports:
- viewing configured channels
- viewing available channel types
- enabling a channel
- editing platform-specific fields from the shared channel schema
- disabling a channel
- setting the default channel
- saving back to `config/social-channels.json`

## Webview Mode

Open the Loom webview and click the `Channels` button in the top toolbar. The panel calls Brain's channel APIs:

- `GET /social/channels`
- `POST /social/channels/register`
- `POST /social/channels/default`
- `DELETE /social/channels/{channel_id}`

Use the webview panel for quick local configuration. Use the config file or CLI for repeatable setup.

The platform selector and form fields are generated from the same channel catalog returned by `GET /social/channels`, so adding a new platform field in Loom Core makes it visible in CLI/TUI/Webview without duplicating form logic.

## Register A Channel

Registering a channel makes it selectable by `channel_adapter_id`.

```http
POST /social/channels/register
Content-Type: application/json

{
  "channel_id": "feishu-work",
  "platform": "feishu",
  "label": "Feishu Work Bot",
  "responseMode": "reply",
  "appId": "cli_xxx",
  "appSecret": "YOUR_APP_SECRET",
  "verificationToken": "YOUR_VERIFICATION_TOKEN",
  "allowFrom": ["ou_user_1", "ou_user_2"],
  "groupPolicy": "mention",
  "streaming": true
}
```

Important fields:

| Field | Meaning |
| --- | --- |
| `channel_id` | User-facing adapter ID. Use this in `channel_adapter_id`. |
| `platform` | Channel type from `python -m loom_core channels available`. All channel instances use the same bridge-mode contract. |
| `label` | Display name returned by `GET /social/channels`. |
| `responseMode` | Loom extension. Set to `reply` or `auto_reply` to send the Brain result back automatically. |
| `allowFrom` | Sender allow-list. `["*"]` allows everyone; `[]` denies all. |
| `requireVerification` | Loom extension. Force verification for this channel, overriding env defaults. |
| `set_default` | Make this the default channel when no `channel_adapter_id` is provided. |

Bridge-mode platforms store Nanobot-compatible transport settings, for example `token`, `appId`, `appSecret`, `allowChannels`, `groupPolicy`, `homeserver`, `botToken`, or `bridgeUrl`.

## Discord Example

Register the channel:

```http
POST /social/channels/register
Content-Type: application/json

{
  "channel_id": "discord-research",
  "platform": "discord",
  "label": "Discord Research",
  "enabled": true,
  "responseMode": "reply",
  "token": "YOUR_BOT_TOKEN",
  "allowFrom": ["YOUR_USER_ID"],
  "gatewayUrl": "wss://gateway.discord.gg/?v=10&encoding=json",
  "allowChannels": [],
  "groupPolicy": "mention",
  "streaming": true,
  "proxy": null
}
```

Send an ingress request:

```http
POST /social/discord/ingress
Content-Type: application/json

{
  "channel_adapter_id": "discord-research",
  "payload": {
    "id": "message_1",
    "channel_id": "channel_1",
    "author": { "id": "user_1" },
    "content": "/loom finance review NVDA capex risk"
  }
}
```

## Feishu/Lark Example

Register the channel:

```http
POST /social/channels/register
Content-Type: application/json

{
  "channel_id": "feishu-work",
  "platform": "feishu",
  "label": "Feishu Work Bot",
  "enabled": true,
  "responseMode": "reply",
  "appId": "cli_xxx",
  "appSecret": "YOUR_APP_SECRET",
  "verificationToken": "YOUR_VERIFICATION_TOKEN",
  "allowFrom": ["ou_user_1"],
  "groupPolicy": "mention",
  "streaming": true
}
```

Send a Feishu event payload:

```http
POST /social/feishu/ingress
Content-Type: application/json

{
  "channel_adapter_id": "feishu-work",
  "payload": {
    "header": { "event_id": "evt_1" },
    "event": {
      "sender": { "sender_id": { "open_id": "ou_user_1" } },
      "message": {
        "message_id": "om_1",
        "chat_id": "oc_1",
        "content": "{\"text\":\"/loom finance review AI capex\"}"
      }
    }
  }
}
```

## Custom Channel Bridge

For a new chat app, the fastest integration is a small bridge service:

1. Receive the chat app webhook.
2. Verify it in your bridge.
3. Convert it into Loom's generic payload.
4. POST it to `/social/ingress`.
5. Let Loom return `reply_text`, or set `responseMode: reply` if your channel can be handled by Loom's reply helpers.

Generic payload shape:

```http
POST /social/ingress
Content-Type: application/json

{
  "channel_adapter_id": "generic",
  "platform": "generic",
  "text": "/loom general summarize this thread",
  "user_id": "user_1",
  "channel_id": "chat_1",
  "message_id": "message_1",
  "send_reply": false
}
```

If `send_reply` is false, the bridge should read `reply_text` from Loom's response and send it back through the chat app itself.

## Direct Agent Service Mode

Channels can invoke a configured Codex or Claude Code runtime directly, without
running Brain planning, review, or Loom's `run.artifact` output contract. The
channel remains the transport; `AgentSessionService` is the execution boundary.

Use explicit commands while keeping normal messages on Brain:

```text
/codex inspect the workspace and implement the requested change
/claude investigate the failing tests and report the root cause
/agent codex-app-server review the current branch
```

Or set `executionMode` to `agent` so plain messages use the configured adapter.
An explicit `/loom` or `/loom-visual` command always keeps the Brain workflow.

```json
{
  "executionMode": "agent",
  "agentAdapterId": "codex-app-server",
  "agentAllowFrom": ["YOUR_USER_ID"],
  "agentWorkspace": "D:/workspace",
  "ingressTimeoutMs": 1800000
}
```

`agentAllowFrom` is mandatory for direct agent execution and does not accept
`*`. This is intentionally separate from the channel's general `allowFrom`
because a full agent may read, edit, and execute commands inside its workspace.

The same service is available independently of social transport:

```http
POST /agent-sessions/run
Content-Type: application/json

{
  "adapter_id": "codex-app-server",
  "task": "Inspect the workspace and run the relevant tests",
  "cwd": "D:/workspace",
  "context": {}
}
```

Codex uses the registered app-server adapter without a forced output schema.
Claude Code uses the configured CLI process as a full tool-capable agent and
returns its final assistant message. Brain remains available as a separate
orchestration path rather than being embedded in the direct-agent protocol.

## Security Checklist

- Keep bot tokens in local config or environment variables you control.
- Set `allowFrom` to specific user IDs for private bots.
- Set `LOOM_SOCIAL_REQUIRE_VERIFICATION=1` in production.
- Configure platform verification keys:
  - `LOOM_FEISHU_VERIFICATION_TOKEN` or `FEISHU_VERIFICATION_TOKEN`
  - `LOOM_FEISHU_BOT_SECRET` or `FEISHU_BOT_SECRET`
  - `LOOM_DISCORD_PUBLIC_KEY` or `DISCORD_PUBLIC_KEY`
  - `LOOM_SOCIAL_INGRESS_SECRET` for trusted bridge HMAC
- Keep channel IDs stable; clients use them as adapter selectors.

## When To Add Code

Use the generic bridge when possible. Add dedicated Loom helper code only when the platform needs first-class payload parsing, verification, or reply formatting.

Bridge support usually requires changes in:
- `loom_core/interaction_protocol/social.py` for payload normalization
- `loom_core/interaction_protocol/social_verify.py` for webhook verification
- `loom_core/interaction_protocol/social_reply.py` for outbound replies
- `loom_core/interaction_protocol/social_channel.py` for default channel config
- tests under `tests/test_social_*.py`
