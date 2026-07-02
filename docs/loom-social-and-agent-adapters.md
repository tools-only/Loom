# Loom Brain Social Ingress and Agent Adapter Control

## Current Flow Audit

Implemented today:
- Brain already owns the core loop: `/analyze` resolves workflow, builds state projection, writes analysis plan, decomposes runtime hand tasks, dispatches hands through adapters, repairs invalid artifacts once, reviews coverage, synthesizes, writes flywheel/goal/intent reward records, and patches the webview.
- Brain review follow-ups now act as bounded redo requests: a follow-up can target an existing `task_id`/artifact, mark that artifact rejected, rerun the selected hand/executor, and replace the rejected artifact before synthesis.
- Brain can now receive external chat commands through `POST /social/ingress` or `POST /social/{platform}/ingress`.
- Social entry is now adapter-driven: `GET /social/channels` lists selectable channel adapters, `POST /social/channels/register` adds a Feishu/Discord/generic-compatible channel, and `channel_adapter_id` on ingress chooses the adapter for that request.
- Channel configuration now follows a Nanobot-style catalog/registry split: built-in channel types expose shared field schemas, enabled channel instances persist to `config/social-channels.json`, and CLI/TUI/Webview all render from the same schema.
- Social ingress can verify trusted bridge HMAC signatures, Feishu/Lark verification tokens and URL challenges, Feishu custom-bot style signatures, and Discord Ed25519 interaction signatures.
- Social ingress now returns `reply_text` for bridge-controlled replies and can optionally POST replies through Discord/Feishu/Lark webhooks, Discord bot REST, or Feishu/Lark IM message API. Feishu/Lark IM replies can use a provided tenant token or acquire/cache one from app credentials.
- User corrections can now trigger `POST /feedback/repair` or `POST /flywheel/repair`, which selects target hand agents from the feedback and episode hand evaluations, reruns those hands, patches repaired cards, resynthesizes Brain output over original plus repaired artifacts when available, and appends `repair_history` to the flywheel episode detail.
- Brain can now register runtime agent backends through `POST /adapters/register`, list them with `GET /adapters`, and choose the default backend for generated hands through `POST /adapters/default-runtime`.

Still incomplete for a production mobile/social loop:
- Older flywheel episodes created before `hand_artifacts` persistence can only resynthesize over repaired artifacts, because the original full artifacts were not stored.
- Adapter tokens are env-backed or memory-only; there is still no external secret-manager integration.

## Social Ingress

Social channels are selectable adapters rather than hard-coded routes. The built-in catalog mirrors Nanobot's channel names, and every configured channel uses the same bridge-mode contract. Generic, Discord, Feishu/Lark, Telegram, Slack, Matrix, QQ, WeCom, Weixin, WhatsApp, Email, and the other catalog entries all become enabled only through channel configuration.

List configured channels:

```http
GET /social/channels
```

Register a user-selectable Feishu channel:

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
  "streaming": true,
  "set_default": false
}
```

Register a Discord channel:

```http
POST /social/channels/register
Content-Type: application/json

{
  "channel_id": "discord-research",
  "platform": "discord",
  "label": "Discord Research",
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

`allowFrom: ["*"]` allows any sender on that channel. An explicit user ID list restricts ingress, and an empty list denies all senders until updated.
Discord uses an outbound Gateway WebSocket, matching Nanobot's channel model. When the local machine cannot connect directly to Discord, set `proxy` on the Discord channel. `proxyUsername` and `proxyPassword` are supported when the proxy requires authentication.

Verification is optional for local calls. Set `LOOM_SOCIAL_REQUIRE_VERIFICATION=1` in production. Supported verification inputs:
- trusted bridge HMAC: `LOOM_SOCIAL_INGRESS_SECRET` plus header `X-Loom-Signature: sha256=<hex>`
- Feishu/Lark event token: `LOOM_FEISHU_VERIFICATION_TOKEN` or `FEISHU_VERIFICATION_TOKEN`
- Feishu/Lark URL verification: returns `{ "challenge": "..." }` without running Brain
- Feishu custom-bot style signature: `LOOM_FEISHU_BOT_SECRET` or `FEISHU_BOT_SECRET`
- Discord interactions: `LOOM_DISCORD_PUBLIC_KEY` or `DISCORD_PUBLIC_KEY` plus `X-Signature-Ed25519` and `X-Signature-Timestamp`

Outbound replies use this order:
- explicit `reply_webhook_url`
- env webhook: `LOOM_SOCIAL_REPLY_DISCORD_WEBHOOK`, `LOOM_SOCIAL_REPLY_FEISHU_WEBHOOK`, `DISCORD_WEBHOOK_URL`, or `FEISHU_WEBHOOK_URL`
- Discord bot REST when `LOOM_DISCORD_BOT_TOKEN` or `DISCORD_BOT_TOKEN` is set and the message has `channel_id`
- Feishu/Lark IM API when a tenant token is available or app credentials can acquire one, and the message has `channel_id` / chat ID

Optional outbound env:
- `LOOM_DISCORD_API_BASE` defaults to `https://discord.com/api/v10`
- `LOOM_FEISHU_API_BASE` defaults to `https://open.feishu.cn/open-apis`
- `LOOM_FEISHU_RECEIVE_ID_TYPE` defaults to `chat_id`
- `LOOM_FEISHU_TENANT_ACCESS_TOKEN` or `FEISHU_TENANT_ACCESS_TOKEN` can provide a static tenant token
- `LOOM_FEISHU_APP_ID` / `LOOM_FEISHU_APP_SECRET` or `FEISHU_APP_ID` / `FEISHU_APP_SECRET` let Brain acquire and in-memory cache a tenant token

Generic direct call:

```http
POST /social/ingress
Content-Type: application/json

{
  "channel_adapter_id": "discord-research",
  "platform": "discord",
  "text": "/loom finance review NVDA AI capex risk",
  "user_id": "user_1",
  "channel_id": "channel_1",
  "message_id": "message_1",
  "send_reply": true,
  "context": { "responseMode": "reply" }
}
```

Feishu/Lark webhook-style call:

```http
POST /social/feishu/ingress
Content-Type: application/json

{
  "channel_adapter_id": "feishu-work",
  "payload": {
    "header": { "event_id": "evt_1" },
    "event": {
      "sender": { "sender_id": { "open_id": "ou_1" } },
      "message": {
        "message_id": "om_1",
        "chat_id": "oc_1",
        "content": "{\"text\":\"<at user_id=\\\"bot\\\">Loom</at> /loom finance review AI capex\"}"
      }
    }
  }
}
```

Command parsing is intentionally small:
- `/loom finance ...`, `/loom fin ...`, `/loom market ...`, `/loom target ...`, `/loom position ...` set `domain_hint=finance`.
- `/loom general ...` sets `domain_hint=general`.
- `market`, `sentiment`, `target`, and `position` also pass a hand hint into the existing `hands` request field.

## Feedback Repair

After a user replies with a correction, the bridge should pass the original `episode_id` plus the correction:

```http
POST /feedback/repair
Content-Type: application/json

{
  "episode_id": "ep-1781440000000-abcd1234",
  "signal": "correction",
  "comment": "sentiment missed the crowding risk; rerun that card",
  "hand_id": "sentiment",
  "corrected_stance": "reduce",
  "send_reply": true,
  "reply_webhook_url": "https://discord.com/api/webhooks/..."
}
```

If `hand_id` or `target_hands` is omitted, Brain selects repair targets in this order:
- explicit `hand_id` / `target_hands`
- hand names mentioned in `comment`
- weakest hand evaluations from the episode detail, prioritizing missing artifacts, high gap count, then low claim count

The route appends:
- raw feedback to `logs/feedback.jsonl`
- human feedback to `brain/flywheel/<episode_id>.json`
- repair attempts to the `repair_history` field inside `brain/flywheel/<episode_id>.json`
- for new episodes, original hand artifacts are persisted in `hand_artifacts`, so repair resynthesis can combine original unchanged cards with repaired cards

## Brain Quality Gate Redo

During `/analyze`, `BrainHarness.review()` can emit:

```json
{
  "follow_up_needed": true,
  "follow_up_tasks": [
    {
      "target_task_id": "t1",
      "hand_id": "runtime-evidence-agent",
      "executor_id": "brain-inline",
      "reason": "missing source support",
      "task": "Redo t1 with cited evidence"
    }
  ]
}
```

The orchestrator resolves the target artifact by `target_task_id`, `target_artifact_key`, `artifact_key`, `task_id`, `hand_id`, or `executor_id`. If a target is found, the repaired artifact replaces the rejected artifact under the same key before synthesis. Artifact metadata records `quality_status`, `review_repair_reason`, `repair_attempt`, and `replaces_artifact_key`.

Repair budget defaults to one review-driven redo per `/analyze` call. Override it with request context:

```json
{
  "quality_gate": { "max_repair_attempts": 0 }
}
```

`review_result.repair_budget` reports attempts used, remaining budget, and whether the gate was exceeded. Skipped repairs are appended to `review_result.repair_history`, and the episode quality gaps note repair budget exhaustion.

## Runtime Agent Adapters

Register a local Codex process backend:

```http
POST /adapters/register
Content-Type: application/json

{
  "adapter_id": "codex-runtime",
  "transport": "process",
  "protocol": "loom",
  "command": ["codex", "run"],
  "capabilities": ["runtime.hand", "workspace.patch"],
  "set_default_runtime": true
}
```

Register Claude Code as the runtime hand backend:

```http
POST /adapters/register
Content-Type: application/json

{
  "adapter_id": "claude-code-runtime",
  "transport": "process",
  "protocol": "loom",
  "command": ["claude", "-p"],
  "capabilities": ["runtime.hand"],
  "set_default_runtime": true
}
```

Register Codex app-server through OpenAI's official Python SDK. The SDK starts
its version-matched app-server runtime, performs the JSON-RPC lifecycle, and
routes typed turn notifications. No separate `codex` executable command is
required:

```http
POST /adapters/register
Content-Type: application/json

{
  "adapter_id": "codex-app-service",
  "transport": "process",
  "protocol": "codex",
  "codex_backend": "sdk",
  "capabilities": ["runtime.hand", "workspace.patch"],
  "set_default_runtime": true
}
```

Install `loom/requirements.txt` before using this adapter. It includes
`openai-codex==0.1.0b3`, whose `openai-codex-cli-bin` dependency pins a compatible Codex
runtime. Existing Codex authentication is reused. Runtime hand threads are
ephemeral by default, use `workspace-write`, and deny permission escalation by
default. Per-task overrides can be supplied in `task.codex` or
`task.context.codex`, for example:

```json
{
  "codex": {
    "model": "gpt-5.4",
    "sandbox": "read-only",
    "approvalMode": "auto_review",
    "ephemeral": true
  }
}
```

For compatibility testing or a custom app-server build, select the raw JSON-RPC
backend explicitly and provide the full launch command:

```json
{
  "adapter_id": "codex-app-service-raw",
  "transport": "process",
  "protocol": "codex",
  "codex_backend": "raw",
  "command": ["codex", "app-server", "--listen", "stdio://"],
  "capabilities": ["runtime.hand", "workspace.patch"]
}
```

The raw backend waits for the `initialize` response before sending `initialized`
and starting a thread, as required by the app-server protocol. It is a
compatibility path; the SDK backend should be the production default.

App-server also exposes an experimental, unsupported WebSocket listener. Loom
can connect to it for development, but it should not be used for production:

```http
POST /adapters/register
Content-Type: application/json

{
  "adapter_id": "codex-app-service-ws",
  "transport": "websocket",
  "protocol": "codex",
  "codex_backend": "raw",
  "endpoint": "ws://127.0.0.1:4222",
  "capabilities": ["runtime.hand", "workspace.patch"],
  "set_default_runtime": true
}
```

OpenAI-compatible HTTP agents are still supported with `protocol: "openai"` and
a Chat Completions style endpoint, but that is not the Codex app-server
protocol.

Dynamic adapter config is persisted to `loom/agent-adapters.json`. Raw `auth_token` / `token` values are never written there. If a registration supplies only an inline token and no `auth_token_env`, the token is usable for the current Brain process but the persisted config is marked `secret_mode=memory_only`, so authenticated reload requires registering again or setting an env-backed token reference.

Brain-generated hands default to `brain-inline` unless the registry default is changed. `POST /adapters/default-runtime` can point that default at any registered adapter:

```http
POST /adapters/default-runtime
Content-Type: application/json

{ "adapter_id": "codex-runtime" }
```

### Select an agent for each Hand

Hand runtime selection is persistent and independent per Hand. All configuration
surfaces write the same `config/hand-runtimes.json` binding document. Runtime
resolution uses this order:

1. the one-shot `runtime` field on `POST /run`
2. the persistent Hand binding
3. a legacy mounted HTTP agent
4. the Hand's declared runtime, normally `sdk`

The CLI can register Codex App Server and bind one or more Hands in one command:

```powershell
python -m loom_core agents register codex-app-server `
  --protocol codex `
  --transport process `
  --codex-backend sdk `
  --bind-hand market `
  --bind-hand sentiment
```

Other useful CLI operations:

```powershell
python -m loom_core agents list
python -m loom_core agents adapters
python -m loom_core agents bind target codex-app-server
python -m loom_core agents bind position sdk
python -m loom_core agents unbind target
python -m loom_core agents remove codex-app-server
```

For the raw app-server protocol use `--codex-backend raw --command "codex
app-server --listen stdio://"`. For an HTTP agent use `--transport http --protocol openai
--endpoint https://agent.example/v1/chat/completions --auth-token-env
MY_AGENT_TOKEN`. Inline secrets are not accepted by this CLI; environment
variable references remain safe to persist.

Launch the terminal UI with:

```powershell
python -m loom_core agents tui
```

It provides guided flows for SDK/raw Codex App Server registration, generic
process/HTTP agents, Hand binding, unbinding, and removal.

In the Loom Webview toolbar, open **Settings**. For each Hand, select **Agent
Adapter**, then choose **Codex App Server · SDK** or another registered adapter.
Choosing Codex auto-registers the SDK-backed adapter when Settings is saved.
The same binding is also available from a Hand card's gear menu through the
**运行 Agent** selector. **接入新的 Agent** can register SDK/raw Codex App Server
or an HTTP Loom/OpenAI-compatible agent. Webview registration calls the Brain
control-plane API, so it takes effect without a restart. CLI-written adapters
are lazy-loaded by Brain the first time they are used.

Equivalent control-plane requests are:

```http
GET /hands/runtime-bindings
GET /hand/sentiment/runtime
PUT /hand/sentiment/runtime
Content-Type: application/json

{ "adapter_id": "codex-app-server" }
```

Use `{ "adapter_id": "default" }` or `DELETE /hand/sentiment/runtime` to
remove the explicit binding. Removing a dynamic adapter also clears every Hand
binding that referenced it.
