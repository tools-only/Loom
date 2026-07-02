"""Selectable social channel adapters for Brain ingress and replies."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from loom_core.interaction_protocol.social import (
    SocialIngressMessage,
    normalize_social_payload,
)
from loom_core.interaction_protocol.social_reply import (
    SocialReplyResult,
    edit_discord_message,
    send_social_reply,
)
from loom_core.interaction_protocol.social_verify import (
    SocialVerificationResult,
    verify_social_request,
)

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MISSING = object()


def _field(
    name: str,
    label: str,
    *,
    kind: str = "text",
    placeholder: str = "",
    description: str = "",
    required: bool = False,
    default: Any = _MISSING,
    options: list[dict[str, str]] | None = None,
    aliases: tuple[str, ...] = (),
    secret: bool = False,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "name": name,
        "label": label,
        "kind": kind,
        "placeholder": placeholder,
        "description": description,
        "required": required,
    }
    if default is not _MISSING:
        field["default"] = default
    if options is not None:
        field["options"] = options
    if aliases:
        field["aliases"] = list(aliases)
    if secret:
        field["secret"] = True
    return field


def _select(*values: str) -> list[dict[str, str]]:
    return [{"value": value, "label": value or "default"} for value in values]


_COMMON_CHANNEL_FIELDS: tuple[dict[str, Any], ...] = (
    _field("channel_id", "Channel ID", placeholder="telegram-work", required=True),
    _field("label", "Label", placeholder="Telegram Work"),
    _field("enabled", "Enabled", kind="boolean", default=True),
    _field(
        "response_mode",
        "Response Mode",
        kind="select",
        options=[
            {"value": "", "label": "manual"},
            {"value": "reply", "label": "reply"},
            {"value": "auto_reply", "label": "auto_reply"},
        ],
    ),
    _field(
        "executionMode",
        "Execution Mode",
        kind="select",
        default="brain",
        aliases=("execution_mode",),
        options=[
            {"value": "brain", "label": "Brain orchestration"},
            {"value": "agent", "label": "Direct agent service"},
        ],
        description="Route plain channel messages through Brain or directly to a configured full agent runtime.",
    ),
    _field(
        "agentAdapterId",
        "Agent Adapter ID",
        placeholder="codex-app-server",
        aliases=("agent_adapter_id",),
        description="Registered adapter used by direct agent mode; /agent can override it per message.",
    ),
    _field(
        "agentAllowFrom",
        "Agent Allow From",
        kind="list",
        default=[],
        aliases=("agent_allow_from",),
        description="Explicit sender allowlist for workspace-capable direct agent sessions. Wildcards are not accepted.",
    ),
    _field(
        "agentWorkspace",
        "Agent Workspace",
        placeholder="D:/workspace",
        aliases=("agent_workspace",),
        description="Working directory exposed to the selected agent runtime.",
    ),
    _field(
        "ingressTimeoutMs",
        "Ingress Timeout (ms)",
        kind="number",
        default=1800000,
        aliases=("ingress_timeout_ms",),
        description="Bridge deadline for long-running Brain or agent sessions.",
    ),
    _field("replyTokenEnv", "Reply Token Env", kind="env", placeholder="LOOM_TELEGRAM_BOT_TOKEN", aliases=("reply_token_env",)),
    _field("replyWebhookEnv", "Reply Webhook Env", kind="env", placeholder="LOOM_SOCIAL_REPLY_TELEGRAM_WEBHOOK", aliases=("reply_webhook_env",)),
    _field("requireVerification", "Require Verification", kind="tri_state_boolean", aliases=("require_verification",)),
)

_PLATFORM_CHANNEL_FIELDS: dict[str, tuple[dict[str, Any], ...]] = {
    "generic": (
        _field("allowFrom", "Allow From", kind="list", placeholder="* or user_1,user_2", default=["*"], aliases=("allow_from",)),
    ),
    "discord": (
        _field("token", "Token", kind="password", placeholder="YOUR_BOT_TOKEN", default="", secret=True),
        _field("allowFrom", "Allow From", kind="list", placeholder="YOUR_USER_ID", default=[], aliases=("allow_from",)),
        _field("gatewayUrl", "Gateway URL", kind="url", default="wss://gateway.discord.gg/?v=10&encoding=json", aliases=("gateway_url",)),
        _field("allowChannels", "Allow Channels", kind="list", default=[], aliases=("allow_channels",)),
        _field("intents", "Intents", kind="number", default=37377),
        _field("groupPolicy", "Group Policy", kind="select", default="mention", aliases=("group_policy",), options=_select("mention", "open")),
        _field("readReceiptEmoji", "Read Receipt Emoji", default="👀", aliases=("read_receipt_emoji",)),
        _field("workingEmoji", "Working Emoji", default="🔧", aliases=("working_emoji",)),
        _field("workingEmojiDelay", "Working Emoji Delay", kind="number", default=2.0, aliases=("working_emoji_delay",)),
        _field("streaming", "Streaming", kind="boolean", default=True),
        _field("proxy", "Proxy", default=None),
        _field("proxyUsername", "Proxy Username", default=None, aliases=("proxy_username",)),
        _field("proxyPassword", "Proxy Password", kind="password", default=None, aliases=("proxy_password",), secret=True),
    ),
    "dingtalk": (
        _field("clientId", "Client ID", default="", aliases=("client_id",)),
        _field("clientSecret", "Client Secret", kind="password", default="", aliases=("client_secret",), secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("allowRemoteMediaRedirects", "Allow Remote Media Redirects", kind="boolean", default=False, aliases=("allow_remote_media_redirects",)),
        _field("remoteMediaRedirectAllowedHosts", "Remote Media Redirect Allowed Hosts", kind="list", default=[], aliases=("remote_media_redirect_allowed_hosts",)),
        _field("groupUserIsolation", "Group User Isolation", kind="boolean", default=False, aliases=("group_user_isolation",)),
    ),
    "email": (
        _field("consentGranted", "Consent Granted", kind="boolean", default=False, aliases=("consent_granted",)),
        _field("imapHost", "IMAP Host", placeholder="imap.example.com", default="", aliases=("imap_host",)),
        _field("imapPort", "IMAP Port", kind="number", default=993, aliases=("imap_port",)),
        _field("imapUsername", "IMAP Username", default="", aliases=("imap_username", "username")),
        _field("imapPassword", "IMAP Password", kind="password", aliases=("imap_password", "password"), secret=True),
        _field("imapMailbox", "IMAP Mailbox", default="INBOX", aliases=("imap_mailbox",)),
        _field("imapUseSsl", "IMAP Use SSL", kind="boolean", default=True, aliases=("imap_use_ssl",)),
        _field("smtpHost", "SMTP Host", placeholder="smtp.example.com", default="", aliases=("smtp_host",)),
        _field("smtpPort", "SMTP Port", kind="number", default=587, aliases=("smtp_port",)),
        _field("smtpUsername", "SMTP Username", default="", aliases=("smtp_username",)),
        _field("smtpPassword", "SMTP Password", kind="password", aliases=("smtp_password",), secret=True),
        _field("smtpUseTls", "SMTP Use TLS", kind="boolean", default=True, aliases=("smtp_use_tls",)),
        _field("smtpUseSsl", "SMTP Use SSL", kind="boolean", aliases=("smtp_use_ssl",)),
        _field("fromAddress", "From Address", default="", aliases=("from_address",)),
        _field("autoReplyEnabled", "Auto Reply Enabled", kind="boolean", default=True, aliases=("auto_reply_enabled",)),
        _field("pollIntervalSeconds", "Poll Interval Seconds", kind="number", default=30, aliases=("poll_interval_seconds",)),
        _field("markSeen", "Mark Seen", kind="boolean", default=True, aliases=("mark_seen",)),
        _field("postAction", "Post Action", kind="select", default=None, aliases=("post_action",), options=_select("", "delete", "move")),
        _field("postActionMoveMailbox", "Post Action Move Mailbox", default="", aliases=("post_action_move_mailbox",)),
        _field("postActionExpunge", "Post Action Expunge", kind="boolean", default=False, aliases=("post_action_expunge",)),
        _field("postActionIgnoreSkipped", "Post Action Ignore Skipped", kind="boolean", default=True, aliases=("post_action_ignore_skipped",)),
        _field("maxBodyChars", "Max Body Chars", kind="number", default=12000, aliases=("max_body_chars",)),
        _field("subjectPrefix", "Subject Prefix", default="Re: ", aliases=("subject_prefix",)),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("verifyDkim", "Verify DKIM", kind="boolean", default=True, aliases=("verify_dkim",)),
        _field("verifySpf", "Verify SPF", kind="boolean", default=True, aliases=("verify_spf",)),
        _field("allowedAttachmentTypes", "Allowed Attachment Types", kind="list", default=[], aliases=("allowed_attachment_types",)),
        _field("maxAttachmentSize", "Max Attachment Size", kind="number", default=2000000, aliases=("max_attachment_size",)),
        _field("maxAttachmentsPerEmail", "Max Attachments Per Email", kind="number", default=5, aliases=("max_attachments_per_email",)),
    ),
    "feishu": (
        _field("appId", "App ID", default="", aliases=("app_id",)),
        _field("appSecret", "App Secret", kind="password", default="", aliases=("app_secret",), secret=True),
        _field("encryptKey", "Encrypt Key", kind="password", default="", aliases=("encrypt_key",), secret=True),
        _field("verificationToken", "Verification Token", kind="password", default="", aliases=("verification_token",), secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("reactEmoji", "React Emoji", default="THUMBSUP", aliases=("react_emoji",)),
        _field("doneEmoji", "Done Emoji", default=None, aliases=("done_emoji",)),
        _field("toolHintPrefix", "Tool Hint Prefix", default="🔧", aliases=("tool_hint_prefix",)),
        _field("groupPolicy", "Group Policy", kind="select", default="mention", aliases=("group_policy",), options=_select("open", "mention")),
        _field("replyToMessage", "Reply To Message", kind="boolean", default=False, aliases=("reply_to_message",)),
        _field("streaming", "Streaming", kind="boolean", default=True),
        _field("domain", "Domain", kind="select", default="feishu", options=_select("feishu", "lark")),
        _field("topicIsolation", "Topic Isolation", kind="boolean", default=True, aliases=("topic_isolation",)),
    ),
    "matrix": (
        _field("homeserver", "Homeserver", default="https://matrix.org", placeholder="https://matrix.example.com"),
        _field("userId", "User ID", default="", aliases=("user_id",)),
        _field("password", "Password", kind="password", default="", secret=True),
        _field("accessToken", "Access Token", kind="password", default="", aliases=("access_token",), secret=True),
        _field("deviceId", "Device ID", default="", aliases=("device_id",)),
        _field("e2eeEnabled", "E2EE Enabled", kind="boolean", default=True, aliases=("e2ee_enabled",)),
        _field("sasVerification", "SAS Verification", kind="boolean", default=False, aliases=("sas_verification",)),
        _field("syncStopGraceSeconds", "Sync Stop Grace Seconds", kind="number", default=2, aliases=("sync_stop_grace_seconds",)),
        _field("maxMediaBytes", "Max Media Bytes", kind="number", default=20971520, aliases=("max_media_bytes",)),
        _field("maxConcurrentMediaDownloads", "Max Concurrent Media Downloads", kind="number", default=2, aliases=("max_concurrent_media_downloads",)),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("groupPolicy", "Group Policy", kind="select", default="open", aliases=("group_policy",), options=_select("open", "mention", "allowlist")),
        _field("groupAllowFrom", "Group Allow From", kind="list", default=[], aliases=("group_allow_from",)),
        _field("allowRoomMentions", "Allow Room Mentions", kind="boolean", default=False, aliases=("allow_room_mentions",)),
        _field("streaming", "Streaming", kind="boolean", default=False),
    ),
    "mochat": (
        _field("baseUrl", "Base URL", kind="url", default="https://mochat.io", aliases=("base_url",)),
        _field("socketUrl", "Socket URL", kind="url", default="", aliases=("socket_url",)),
        _field("socketPath", "Socket Path", default="/socket.io", aliases=("socket_path",)),
        _field("socketDisableMsgpack", "Socket Disable Msgpack", kind="boolean", default=False, aliases=("socket_disable_msgpack",)),
        _field("socketReconnectDelayMs", "Socket Reconnect Delay Ms", kind="number", default=1000, aliases=("socket_reconnect_delay_ms",)),
        _field("socketMaxReconnectDelayMs", "Socket Max Reconnect Delay Ms", kind="number", default=10000, aliases=("socket_max_reconnect_delay_ms",)),
        _field("socketConnectTimeoutMs", "Socket Connect Timeout Ms", kind="number", default=10000, aliases=("socket_connect_timeout_ms",)),
        _field("refreshIntervalMs", "Refresh Interval Ms", kind="number", default=30000, aliases=("refresh_interval_ms",)),
        _field("watchTimeoutMs", "Watch Timeout Ms", kind="number", default=25000, aliases=("watch_timeout_ms",)),
        _field("watchLimit", "Watch Limit", kind="number", default=100, aliases=("watch_limit",)),
        _field("retryDelayMs", "Retry Delay Ms", kind="number", default=500, aliases=("retry_delay_ms",)),
        _field("maxRetryAttempts", "Max Retry Attempts", kind="number", default=0, aliases=("max_retry_attempts",)),
        _field("clawToken", "Claw Token", kind="password", aliases=("claw_token",), secret=True),
        _field("agentUserId", "Agent User ID", default="", aliases=("agent_user_id",)),
        _field("sessions", "Sessions", kind="list", default=[]),
        _field("panels", "Panels", kind="list", default=[]),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("mention", "Mention", kind="json", default={"requireInGroups": False}),
        _field("groups", "Groups", kind="json", default={}),
        _field("replyDelayMode", "Reply Delay Mode", default="non-mention", aliases=("reply_delay_mode",)),
        _field("replyDelayMs", "Reply Delay Ms", kind="number", default=120000, aliases=("reply_delay_ms",)),
    ),
    "msteams": (
        _field("appId", "App ID", default="", aliases=("app_id",)),
        _field("appPassword", "App Password", kind="password", default="", aliases=("app_password",), secret=True),
        _field("tenantId", "Tenant ID", default="", aliases=("tenant_id",)),
        _field("host", "Host", default="0.0.0.0"),
        _field("port", "Port", kind="number", default=3978),
        _field("path", "Path", default="/api/messages"),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("replyInThread", "Reply In Thread", kind="boolean", default=True, aliases=("reply_in_thread",)),
        _field("mentionOnlyResponse", "Mention Only Response", default="Hi — what can I help with?", aliases=("mention_only_response",)),
        _field("validateInboundAuth", "Validate Inbound Auth", kind="boolean", default=True, aliases=("validate_inbound_auth",)),
        _field("refTtlDays", "Ref TTL Days", kind="number", default=30, aliases=("ref_ttl_days",)),
        _field("pruneWebChatRefs", "Prune Web Chat Refs", kind="boolean", default=True, aliases=("prune_web_chat_refs",)),
        _field("pruneNonPersonalRefs", "Prune Non Personal Refs", kind="boolean", default=True, aliases=("prune_non_personal_refs",)),
        _field("refTouchIntervalS", "Ref Touch Interval S", kind="number", default=300, aliases=("ref_touch_interval_s",)),
        _field("trustedServiceUrlHosts", "Trusted Service URL Hosts", kind="list", default=[
            "smba.trafficmanager.net",
            "smba.infra.gcc.teams.microsoft.com",
            "smba.infra.gov.teams.microsoft.us",
            "smba.infra.dod.teams.microsoft.us",
        ], aliases=("trusted_service_url_hosts",)),
    ),
    "napcat": (
        _field("wsUrl", "WebSocket URL", kind="url", default="ws://127.0.0.1:3001", aliases=("ws_url",)),
        _field("accessToken", "Access Token", kind="password", default="", aliases=("access_token",), secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("groupPolicy", "Group Policy", kind="select", default="mention", aliases=("group_policy",), options=_select("open", "mention")),
        _field("groupPolicyOverrides", "Group Policy Overrides", kind="json", default={}, aliases=("group_policy_overrides",)),
        _field("welcomeNewMembers", "Welcome New Members", kind="boolean", default=True, aliases=("welcome_new_members",)),
        _field("maxImageBytes", "Max Image Bytes", kind="number", default=20971520, aliases=("max_image_bytes",)),
    ),
    "qq": (
        _field("appId", "App ID", default="", aliases=("app_id",)),
        _field("secret", "Secret", kind="password", default="", secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("msgFormat", "Message Format", kind="select", default="plain", aliases=("msg_format",), options=_select("plain", "markdown")),
        _field("ackMessage", "Ack Message", default="⏳ Processing...", aliases=("ack_message",)),
        _field("mediaDir", "Media Dir", default="", aliases=("media_dir",)),
        _field("downloadChunkSize", "Download Chunk Size", kind="number", default=262144, aliases=("download_chunk_size",)),
        _field("downloadMaxBytes", "Download Max Bytes", kind="number", default=209715200, aliases=("download_max_bytes",)),
    ),
    "signal": (
        _field("phoneNumber", "Phone Number", placeholder="+15555550123", default="", aliases=("phone_number",)),
        _field("daemonHost", "Daemon Host", default="localhost", aliases=("daemon_host",)),
        _field("daemonPort", "Daemon Port", kind="number", default=8080, aliases=("daemon_port",)),
        _field("groupMessageBufferSize", "Group Message Buffer Size", kind="number", default=20, aliases=("group_message_buffer_size",)),
        _field("attachmentsDir", "Attachments Dir", default=None, aliases=("attachments_dir",)),
        _field("dm", "DM Policy", kind="json", default={"enabled": False, "policy": "allowlist", "allowFrom": []}),
        _field("group", "Group Policy", kind="json", default={"enabled": False, "policy": "allowlist", "allowFrom": [], "requireMention": True}),
    ),
    "slack": (
        _field("mode", "Mode", kind="select", default="socket", options=_select("socket")),
        _field("webhookPath", "Webhook Path", default="/slack/events", aliases=("webhook_path",)),
        _field("botToken", "Bot Token", kind="password", default="", aliases=("bot_token",), secret=True),
        _field("appToken", "App Token", kind="password", default="", aliases=("app_token",), secret=True),
        _field("userTokenReadOnly", "User Token Read Only", kind="boolean", default=True, aliases=("user_token_read_only",)),
        _field("replyInThread", "Reply In Thread", kind="boolean", default=True, aliases=("reply_in_thread",)),
        _field("reactEmoji", "React Emoji", default="eyes", aliases=("react_emoji",)),
        _field("doneEmoji", "Done Emoji", default="white_check_mark", aliases=("done_emoji",)),
        _field("includeThreadContext", "Include Thread Context", kind="boolean", default=True, aliases=("include_thread_context",)),
        _field("threadContextLimit", "Thread Context Limit", kind="number", default=20, aliases=("thread_context_limit",)),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("groupPolicy", "Group Policy", kind="select", default="mention", aliases=("group_policy",), options=_select("open", "mention")),
        _field("groupAllowFrom", "Group Allow From", kind="list", default=[], aliases=("group_allow_from",)),
        _field("groupRequireMention", "Group Require Mention", kind="boolean", default=False, aliases=("group_require_mention",)),
        _field("dm", "DM Policy", kind="json", default={"enabled": True, "policy": "open", "allowFrom": []}),
    ),
    "telegram": (
        _field("token", "Token", kind="password", placeholder="YOUR_BOT_TOKEN", default="", secret=True),
        _field("mode", "Mode", kind="select", default="polling", options=_select("polling", "webhook")),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("proxy", "Proxy", default=None),
        _field("replyToMessage", "Reply To Message", kind="boolean", default=False, aliases=("reply_to_message",)),
        _field("reactEmoji", "React Emoji", default="👀", aliases=("react_emoji",)),
        _field("groupPolicy", "Group Policy", kind="select", default="mention", aliases=("group_policy",), options=_select("open", "mention")),
        _field("connectionPoolSize", "Connection Pool Size", kind="number", default=32, aliases=("connection_pool_size",)),
        _field("poolTimeout", "Pool Timeout", kind="number", default=5.0, aliases=("pool_timeout",)),
        _field("streaming", "Streaming", kind="boolean", default=True),
        _field("inlineKeyboards", "Inline Keyboards", kind="boolean", default=False, aliases=("inline_keyboards",)),
        _field("streamEditInterval", "Stream Edit Interval", kind="number", default=0.6, aliases=("stream_edit_interval",)),
        _field("webhookUrl", "Webhook URL", kind="url", default="", aliases=("webhook_url",)),
        _field("webhookListenHost", "Webhook Listen Host", default="127.0.0.1", aliases=("webhook_listen_host",)),
        _field("webhookListenPort", "Webhook Listen Port", kind="number", default=8081, aliases=("webhook_listen_port",)),
        _field("webhookPath", "Webhook Path", default="/telegram", aliases=("webhook_path",)),
        _field("webhookSecretToken", "Webhook Secret Token", kind="password", default="", aliases=("webhook_secret_token",), secret=True),
        _field("webhookMaxConnections", "Webhook Max Connections", kind="number", default=4, aliases=("webhook_max_connections",)),
    ),
    "websocket": (
        _field("host", "Host", default="127.0.0.1"),
        _field("port", "Port", kind="number", default=8765),
        _field("unixSocketPath", "Unix Socket Path", default="", aliases=("unix_socket_path",)),
        _field("path", "Path", default="/"),
        _field("token", "Token", kind="password", default="", secret=True),
        _field("tokenIssuePath", "Token Issue Path", default="", aliases=("token_issue_path",)),
        _field("tokenIssueSecret", "Token Issue Secret", kind="password", default="", aliases=("token_issue_secret",), secret=True),
        _field("tokenTtlS", "Token TTL Seconds", kind="number", default=300, aliases=("token_ttl_s",)),
        _field("websocketRequiresToken", "WebSocket Requires Token", kind="boolean", default=True, aliases=("websocket_requires_token",)),
        _field("allowFrom", "Allow From", kind="list", default=["*"], aliases=("allow_from",)),
        _field("streaming", "Streaming", kind="boolean", default=True),
        _field("maxMessageBytes", "Max Message Bytes", kind="number", default=37748736, aliases=("max_message_bytes",)),
        _field("pingIntervalS", "Ping Interval Seconds", kind="number", default=20.0, aliases=("ping_interval_s",)),
        _field("pingTimeoutS", "Ping Timeout Seconds", kind="number", default=20.0, aliases=("ping_timeout_s",)),
        _field("sslCertfile", "SSL Certfile", default="", aliases=("ssl_certfile",)),
        _field("sslKeyfile", "SSL Keyfile", kind="password", default="", aliases=("ssl_keyfile",), secret=True),
    ),
    "wecom": (
        _field("botId", "Bot ID", default="", aliases=("bot_id",)),
        _field("secret", "Secret", kind="password", default="", secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("welcomeMessage", "Welcome Message", default="", aliases=("welcome_message",)),
    ),
    "weixin": (
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("baseUrl", "Base URL", kind="url", default="https://ilinkai.weixin.qq.com", aliases=("base_url",)),
        _field("cdnBaseUrl", "CDN Base URL", kind="url", default="https://novac2c.cdn.weixin.qq.com/c2c", aliases=("cdn_base_url",)),
        _field("routeTag", "Route Tag", default=None, aliases=("route_tag",)),
        _field("token", "Token", kind="password", default="", secret=True),
        _field("stateDir", "State Dir", default="", aliases=("state_dir",)),
        _field("pollTimeout", "Poll Timeout", kind="number", default=35, aliases=("poll_timeout",)),
    ),
    "whatsapp": (
        _field("bridgeUrl", "Bridge URL", kind="url", default="ws://localhost:3001", aliases=("bridge_url",)),
        _field("bridgeToken", "Bridge Token", kind="password", default="", aliases=("bridge_token",), secret=True),
        _field("allowFrom", "Allow From", kind="list", default=[], aliases=("allow_from",)),
        _field("groupPolicy", "Group Policy", kind="select", default="open", aliases=("group_policy",), options=_select("open", "mention")),
    ),
}


NANOBOT_CHANNEL_TYPES: tuple[dict[str, Any], ...] = (
    {
        "platform": "generic",
        "label": "Generic Bridge",
        "status": "bridge",
        "description": "Loom-normalized bridge payloads posted to /social/ingress.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "discord",
        "label": "Discord",
        "status": "bridge",
        "description": "Discord message payloads through a bridge-managed webhook or bot transport.",
        "capabilities": ["social.ingress", "social.reply", "social.verify", "bot_api"],
    },
    {
        "platform": "feishu",
        "label": "Feishu/Lark",
        "status": "bridge",
        "aliases": ["lark"],
        "description": "Feishu/Lark event callbacks and replies through a bridge-managed app transport.",
        "capabilities": ["social.ingress", "social.reply", "social.verify", "bot_api"],
    },
    {
        "platform": "dingtalk",
        "label": "DingTalk",
        "status": "bridge",
        "description": "Nanobot-compatible DingTalk channel type; use a bridge until dedicated transport support is added.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "email",
        "label": "Email",
        "status": "bridge",
        "description": "Nanobot-compatible IMAP/SMTP channel type; use a bridge for polling and delivery.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "matrix",
        "label": "Matrix",
        "status": "bridge",
        "description": "Nanobot-compatible Matrix channel type; use a bridge for homeserver sync and replies.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "mochat",
        "label": "MoChat",
        "status": "bridge",
        "description": "Nanobot-compatible MoChat channel type; use a bridge for platform-specific transport.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "msteams",
        "label": "Microsoft Teams",
        "status": "bridge",
        "description": "Nanobot-compatible Microsoft Teams channel type; use a bridge or webhook relay.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "napcat",
        "label": "NapCat",
        "status": "bridge",
        "description": "Nanobot-compatible NapCat/QQ channel type; use a bridge for OneBot transport.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "qq",
        "label": "QQ",
        "status": "bridge",
        "description": "Nanobot-compatible QQ channel type; use a bridge for official or OneBot delivery.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "signal",
        "label": "Signal",
        "status": "bridge",
        "description": "Nanobot-compatible Signal channel type; use signal-cli or another bridge.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "slack",
        "label": "Slack",
        "status": "bridge",
        "description": "Nanobot-compatible Slack channel type; use bridge payloads until dedicated Slack signing support is added.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "telegram",
        "label": "Telegram",
        "status": "bridge",
        "description": "Nanobot-compatible Telegram channel type; use a bot webhook bridge.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "websocket",
        "label": "WebSocket/Web UI",
        "status": "bridge",
        "description": "Nanobot-compatible websocket channel type for local web clients.",
        "capabilities": ["social.ingress", "social.reply", "streaming", "bridge"],
    },
    {
        "platform": "wecom",
        "label": "WeCom",
        "status": "bridge",
        "description": "Nanobot-compatible WeCom channel type; use a bridge for enterprise WeChat transport.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "weixin",
        "label": "Weixin/WeChat",
        "status": "bridge",
        "description": "Nanobot-compatible Weixin channel type; use a bridge for official-account callbacks.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
    {
        "platform": "whatsapp",
        "label": "WhatsApp",
        "status": "bridge",
        "description": "Nanobot-compatible WhatsApp channel type; use a bridge for Cloud API callbacks.",
        "capabilities": ["social.ingress", "social.reply", "bridge"],
    },
)

_CHANNEL_TYPES_BY_PLATFORM = {item["platform"]: item for item in NANOBOT_CHANNEL_TYPES}
for _item in NANOBOT_CHANNEL_TYPES:
    for _alias in _item.get("aliases", []):
        _CHANNEL_TYPES_BY_PLATFORM[str(_alias)] = _item

_ADMIN_ONLY_KEYS = {"set_default", "secret_mode"}
_CORE_CONFIG_KEYS = {
    "id",
    "channel_id",
    "platform",
    "label",
    "enabled",
    "capabilities",
    "default_context",
    "defaultContext",
    "response_mode",
    "responseMode",
    "reply_webhook_url",
    "replyWebhookUrl",
    "reply_webhook_env",
    "replyWebhookEnv",
    "reply_token",
    "replyToken",
    "reply_token_env",
    "replyTokenEnv",
    "receive_id_type",
    "receiveIdType",
    "require_verification",
    "requireVerification",
    "allow_from",
    "allowFrom",
    "mode",
    "status",
    "settings",
    *_ADMIN_ONLY_KEYS,
}
_LEGACY_INLINE_SECRET_KEYS = {
    "reply_token",
    "auth_token",
    "refresh_token",
}
_URL_SECRET_KEYS = {"reply_webhook_url", "replyWebhookUrl"}


def _is_env_var_name(value: str) -> bool:
    return bool(value and _ENV_VAR_RE.match(value))


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _optional_bool_value(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return _bool_value(value)


def _string_list(value: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple, set)):
        return default
    return tuple(str(item).strip() for item in value if str(item).strip())


def _to_snake(name: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name or ""))
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.replace("-", "_").lower()


def _get_any(raw: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return default


def _field_alias_map(platform: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for field_spec in channel_config_fields(platform):
        canonical = str(field_spec.get("name") or "")
        if not canonical:
            continue
        aliases = {canonical, _to_snake(canonical), *(str(item) for item in field_spec.get("aliases", []))}
        for alias in aliases:
            if alias:
                alias_map.setdefault(alias, canonical)
    return alias_map


def _canonical_config_key(platform: str, key: str) -> str:
    return _field_alias_map(platform).get(str(key), str(key))


def _field_spec_by_name(platform: str) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field_spec in channel_config_fields(platform):
        name = str(field_spec.get("name") or "")
        if name:
            fields[name] = dict(field_spec)
    return fields


def _platform_field_names(platform: str) -> set[str]:
    canonical = _canonical_platform(platform)
    return {
        str(field_spec.get("name") or "")
        for field_spec in _PLATFORM_CHANNEL_FIELDS.get(canonical, ())
        if str(field_spec.get("name") or "")
    }


def _default_allow_from(platform: str) -> tuple[str, ...]:
    spec = _field_spec_by_name(platform).get("allowFrom")
    if spec is not None:
        return _string_list(spec.get("default", []), default=())
    return ()


def _canonical_platform(platform: str) -> str:
    info = channel_type_info(platform)
    return str(info.get("platform") or platform or "generic").lower()


def channel_config_fields(platform: str) -> list[dict[str, Any]]:
    canonical = _canonical_platform(platform)
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field_spec in (*_COMMON_CHANNEL_FIELDS, *_PLATFORM_CHANNEL_FIELDS.get(canonical, ())):
        name = str(field_spec.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        fields.append(dict(field_spec))
    return fields


def canonical_channel_field_name(platform: str, key: str) -> str:
    """Return the Nanobot-style field name for a UI/CLI config key."""
    return _canonical_config_key(platform, key)


def _field_names(platform: str) -> set[str]:
    return set(_field_alias_map(platform))


def _setting_values(raw: dict[str, Any], platform: str) -> dict[str, Any]:
    settings = raw.get("settings")
    merged: dict[str, Any] = {}
    if isinstance(settings, dict):
        for key, value in settings.items():
            merged[_canonical_config_key(platform, str(key))] = value
    field_names = _field_names(platform)
    platform_fields = _platform_field_names(platform)
    for key, value in raw.items():
        canonical = _canonical_config_key(platform, str(key))
        if key in _CORE_CONFIG_KEYS and not (canonical == "mode" and canonical in platform_fields):
            continue
        if key in field_names or canonical in field_names or key not in _ADMIN_ONLY_KEYS:
            merged[canonical] = value
    return {
        str(key): value
        for key, value in merged.items()
        if str(key).strip() and key not in _ADMIN_ONLY_KEYS
    }


def _public_settings(settings: dict[str, Any], platform: str) -> dict[str, Any]:
    public: dict[str, Any] = {}
    field_specs = _field_spec_by_name(platform)
    for key, value in settings.items():
        key = str(key)
        field_spec = field_specs.get(key, {})
        if key.endswith("Env") or key.endswith("_env"):
            public[key] = value if _is_env_var_name(str(value or "")) else ""
        elif field_spec.get("secret") or _looks_sensitive_key(key) or key in _URL_SECRET_KEYS:
            public[f"{key}_configured"] = bool(value)
        else:
            public[key] = value
    return public


def _is_legacy_inline_secret_key(key: str) -> bool:
    normalized = key.lower()
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    return normalized in _LEGACY_INLINE_SECRET_KEYS or compact in {"replytoken", "authtoken", "refreshtoken"}


def _looks_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    if normalized in {"websocketrequirestoken", "tokenttls", "tokenissuepath"}:
        return False
    return normalized.endswith(("token", "secret", "password", "key"))


def _safe_env_ref(raw: Any) -> str:
    value = str(raw or "").strip()
    return value if _is_env_var_name(value) else ""


def _extract_env_backed_secret(raw: dict[str, Any], secret_key: str, env_key: str) -> tuple[str, str]:
    secret_value = str(raw.get(secret_key) or "").strip()
    env_value = str(raw.get(env_key) or "").strip()
    if env_value and not _is_env_var_name(env_value):
        secret_value = secret_value or env_value
        env_value = ""
    return secret_value, env_value


def _extract_env_backed_url(raw: dict[str, Any], url_key: str, env_key: str) -> tuple[str, str]:
    url_value = str(raw.get(url_key) or "").strip()
    env_value = str(raw.get(env_key) or "").strip()
    if env_value and not _is_env_var_name(env_value):
        url_value = url_value or env_value
        env_value = ""
    return url_value, env_value


@dataclass(frozen=True)
class SocialChannelConfig:
    channel_id: str
    platform: str
    label: str = ""
    enabled: bool = True
    capabilities: tuple[str, ...] = ()
    default_context: dict[str, Any] = field(default_factory=dict)
    response_mode: str = ""
    reply_webhook_url: str = ""
    reply_webhook_env: str = ""
    reply_token: str = ""
    reply_token_env: str = ""
    receive_id_type: str = ""
    require_verification: bool | None = None
    allow_from: tuple[str, ...] = ("*",)
    mode: str = "bridge"
    status: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


class SocialChannelAdapter:
    """One selectable social channel.

    The adapter owns platform-specific normalize/verify/reply defaults, while
    Brain keeps orchestration generic.
    """

    def __init__(self, config: SocialChannelConfig) -> None:
        if not config.channel_id:
            raise ValueError("channel_id is required")
        self.id = config.channel_id
        self.platform = config.platform
        self.label = config.label or config.channel_id
        self.enabled = config.enabled
        self.capabilities = list(config.capabilities)
        self.mode = config.mode
        self.status = config.status
        self.settings = dict(config.settings or {})
        self._config = config

    def normalize_payload(self, payload: dict[str, Any]) -> SocialIngressMessage:
        normalized = dict(payload or {})
        normalized.setdefault("platform", self.platform)
        return normalize_social_payload(normalized, platform=self.platform)

    def is_allowed(self, sender_id: str) -> bool:
        allow_from = set(self._config.allow_from or ())
        if "*" in allow_from:
            return True
        if not allow_from:
            return False
        return sender_id in allow_from

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        payload: dict[str, Any],
    ) -> SocialVerificationResult:
        return verify_social_request(
            platform=self.platform,
            headers=headers,
            body=body,
            payload=payload,
            require_verification=self._config.require_verification,
        )

    def context(self, extra_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = dict(self._config.default_context or {})
        if self._config.response_mode:
            context.setdefault("response_mode", self._config.response_mode)
        if self._config.receive_id_type:
            context.setdefault("receive_id_type", self._config.receive_id_type)
        if self._config.settings:
            context.setdefault("channel_settings", dict(self._config.settings))
        if extra_context:
            context.update(extra_context)
        context.setdefault("social_channel", self.public_info())
        return context

    async def send_reply(
        self,
        *,
        text: str,
        message: SocialIngressMessage,
        webhook_url: str = "",
        token: str = "",
        context: dict[str, Any] | None = None,
        http_transport: Any = None,
        file_path: str = "",
    ) -> SocialReplyResult:
        context = context or {}
        return await send_social_reply(
            platform=self.platform,
            text=text,
            webhook_url=(
                webhook_url
                or str(context.get("reply_webhook_url", ""))
                or self._reply_webhook_url()
            ),
            token=(
                token
                or str(context.get("reply_token", ""))
                or self._reply_token()
            ),
            app_id=str(
                context.get("appId")
                or context.get("app_id")
                or self._config.settings.get("appId")
                or ""
            ),
            app_secret=str(
                context.get("appSecret")
                or context.get("app_secret")
                or self._config.settings.get("appSecret")
                or ""
            ),
            channel_id=message.channel_id or str(context.get("reply_channel_id", "")),
            message_id=message.message_id or str(context.get("reply_message_id", "")),
            receive_id_type=str(
                context.get("receive_id_type")
                or context.get("reply_receive_id_type")
                or self._config.receive_id_type
                or ""
            ),
            file_path=file_path,
            proxy_url=self._proxy_url(context),
            http_transport=http_transport,
        )

    async def edit_progress(
        self,
        *,
        message: SocialIngressMessage,
        status_message_id: str,
        embed: dict[str, Any],
        context: dict[str, Any] | None = None,
        http_transport: Any = None,
    ) -> SocialReplyResult:
        context = context or {}
        if self.platform != "discord":
            return SocialReplyResult(ok=True, skipped=True, platform=self.platform, transport="none")
        return await edit_discord_message(
            token=str(context.get("reply_token") or self._reply_token()),
            channel_id=message.channel_id,
            message_id=status_message_id,
            embed=embed,
            proxy_url=self._proxy_url(context),
            http_transport=http_transport,
        )

    def public_info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "platform": self.platform,
            "label": self.label,
            "enabled": self.enabled,
            "capabilities": list(self.capabilities),
            "mode": self.mode,
            "status": self.status,
            "response_mode": self._config.response_mode,
            "replyWebhookEnv": self._config.reply_webhook_env,
            "replyTokenEnv": self._config.reply_token_env,
            "receiveIdType": self._config.receive_id_type,
            "settings": _public_settings(self._config.settings, self.platform),
            "webhook_configured": bool(self._reply_webhook_url()),
            "token_configured": bool(self._reply_token()),
            "requireVerification": self._config.require_verification,
            "allow_policy": self._allow_policy(),
            "config_fields": [field["name"] for field in channel_config_fields(self.platform)],
        }

    def config_dict(self, *, redact_secrets: bool = False) -> dict[str, Any]:
        data = {
            "channel_id": self.id,
            "platform": self.platform,
            "label": self.label,
            "enabled": self.enabled,
            "allowFrom": list(self._config.allow_from),
        }
        if self.capabilities:
            data["capabilities"] = list(self.capabilities)
        if self._config.default_context:
            data["defaultContext"] = dict(self._config.default_context or {})
        if self._config.response_mode:
            data["responseMode"] = self._config.response_mode
        if self._config.reply_webhook_url:
            data["replyWebhookUrl"] = self._config.reply_webhook_url
        if self._config.reply_webhook_env:
            data["replyWebhookEnv"] = self._config.reply_webhook_env
        if self._config.reply_token:
            data["replyToken"] = self._config.reply_token
        if self._config.reply_token_env:
            data["replyTokenEnv"] = self._config.reply_token_env
        if self._config.receive_id_type:
            data["receiveIdType"] = self._config.receive_id_type
        if self._config.require_verification is not None:
            data["requireVerification"] = self._config.require_verification
        data.update(self._config.settings)
        if redact_secrets:
            return persistable_social_channel_config(data)
        return data

    def _allow_policy(self) -> str:
        allow_from = set(self._config.allow_from or ())
        if "*" in allow_from:
            return "open"
        if allow_from:
            return "restricted"
        return "deny_all"

    def _reply_webhook_url(self) -> str:
        if self._config.reply_webhook_url:
            return self._config.reply_webhook_url
        if self._config.reply_webhook_env:
            return os.environ.get(self._config.reply_webhook_env, "")
        for key in ("replyWebhookUrl", "webhookUrl", "bridgeUrl"):
            value = str(self._config.settings.get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                return value
        return ""

    def _reply_token(self) -> str:
        if self._config.reply_token:
            return self._config.reply_token
        if self._config.reply_token_env:
            return os.environ.get(self._config.reply_token_env, "")
        for key in ("token", "botToken", "appToken", "accessToken", "bridgeToken"):
            value = str(self._config.settings.get(key) or "").strip()
            if value:
                return value
        return ""

    def _proxy_url(self, context: dict[str, Any]) -> str:
        channel_settings = context.get("channel_settings")
        if not isinstance(channel_settings, dict):
            channel_settings = {}
        return str(
            context.get("proxy")
            or channel_settings.get("proxy")
            or self._config.settings.get("proxy")
            or ""
        ).strip()


class SocialChannelRegistry:
    def __init__(self, default_channel_id: str = "generic") -> None:
        self._channels: dict[str, SocialChannelAdapter] = {}
        self._default_channel_id = default_channel_id

    def upsert(self, channel: SocialChannelAdapter) -> None:
        self._channels[channel.id] = channel

    def list(self) -> list[SocialChannelAdapter]:
        return list(self._channels.values())

    def find_by_id(self, channel_id: str) -> SocialChannelAdapter | None:
        return self._channels.get(channel_id)

    def unregister(self, channel_id: str) -> bool:
        return self._channels.pop(channel_id, None) is not None

    def set_default(self, channel_id: str) -> None:
        channel = self._channels.get(channel_id)
        if channel is None:
            raise ValueError(f"unknown social channel: {channel_id}")
        if not channel.enabled:
            raise ValueError(f"social channel is disabled: {channel_id}")
        self._default_channel_id = channel_id

    def get_default(self) -> str:
        return self._default_channel_id

    def resolve(
        self,
        *,
        channel_id: str = "",
        platform: str = "",
    ) -> SocialChannelAdapter:
        if channel_id:
            channel = self.find_by_id(channel_id)
            if channel is None:
                raise ValueError(f"unknown social channel: {channel_id}")
            if not channel.enabled:
                raise ValueError(f"social channel is disabled: {channel_id}")
            return channel
        platform = (platform or "").lower()
        if platform:
            for channel in self._channels.values():
                if channel.platform == platform and channel.enabled:
                    return channel
        default = self.find_by_id(self._default_channel_id)
        if default is not None and default.enabled:
            return default
        generic = self.find_by_id("generic")
        if generic is not None and generic.enabled:
            return generic
        raise ValueError("no social channels are registered")


def normalize_social_channel_config(raw: dict[str, Any]) -> SocialChannelConfig:
    raw = dict(raw or {})
    channel_id = str(raw.get("channel_id") or raw.get("id") or "").strip()
    if not channel_id:
        raise ValueError("channel_id is required")
    platform = str(raw.get("platform") or channel_id or "generic").strip().lower()
    if not platform:
        platform = "generic"
    platform = _canonical_platform(platform)
    channel_type = channel_type_info(platform)
    capabilities = tuple(
        str(item).strip()
        for item in raw.get("capabilities", [])
        if str(item).strip()
    )
    if not capabilities:
        capabilities = tuple(channel_type.get("capabilities", ()))
    default_context = _get_any(raw, "defaultContext", "default_context", default={}) or {}
    if not isinstance(default_context, dict):
        default_context = {}
    require_verification = _optional_bool_value(_get_any(raw, "requireVerification", "require_verification"))
    allow_from = _string_list(
        _get_any(raw, "allowFrom", "allow_from", default=_default_allow_from(platform)),
        default=_default_allow_from(platform),
    )
    reply_secret_raw = {
        "replyToken": _get_any(raw, "replyToken", "reply_token", default=""),
        "replyTokenEnv": _get_any(raw, "replyTokenEnv", "reply_token_env", default=""),
    }
    reply_token, reply_token_env = _extract_env_backed_secret(reply_secret_raw, "replyToken", "replyTokenEnv")
    reply_url_raw = {
        "replyWebhookUrl": _get_any(raw, "replyWebhookUrl", "reply_webhook_url", default=""),
        "replyWebhookEnv": _get_any(raw, "replyWebhookEnv", "reply_webhook_env", default=""),
    }
    reply_webhook_url, reply_webhook_env = _extract_env_backed_url(reply_url_raw, "replyWebhookUrl", "replyWebhookEnv")
    return SocialChannelConfig(
        channel_id=channel_id,
        platform=platform,
        label=str(raw.get("label") or channel_type.get("label") or channel_id),
        enabled=_bool_value(raw.get("enabled"), default=True),
        capabilities=capabilities,
        default_context=default_context,
        response_mode=str(_get_any(raw, "responseMode", "response_mode", default="") or ""),
        reply_webhook_url=reply_webhook_url,
        reply_webhook_env=reply_webhook_env,
        reply_token=reply_token,
        reply_token_env=reply_token_env,
        receive_id_type=str(_get_any(raw, "receiveIdType", "receive_id_type", default="") or ""),
        require_verification=require_verification,
        allow_from=allow_from,
        mode="bridge",
        status="bridge",
        settings=_setting_values(raw, platform),
    )


def social_channel_from_config(raw: dict[str, Any]) -> SocialChannelAdapter:
    return SocialChannelAdapter(normalize_social_channel_config(raw))


def available_social_channel_types() -> list[dict[str, Any]]:
    available = []
    for item in NANOBOT_CHANNEL_TYPES:
        platform = str(item["platform"])
        fields = channel_config_fields(platform)
        available.append({
            **dict(item),
            "config_fields": [field["name"] for field in fields],
            "fields": fields,
            "default_config": default_social_channel_config(platform),
        })
    return available


def channel_type_info(platform: str) -> dict[str, Any]:
    platform = (platform or "generic").lower()
    return dict(_CHANNEL_TYPES_BY_PLATFORM.get(platform) or _CHANNEL_TYPES_BY_PLATFORM["generic"])


def default_social_channel_config(
    platform: str,
    *,
    channel_id: str = "",
    enabled: bool = False,
) -> dict[str, Any]:
    channel_type = channel_type_info(platform)
    canonical = str(channel_type.get("platform") or platform or "generic")
    config = {
        "channel_id": channel_id or canonical,
        "platform": canonical,
        "label": channel_type.get("label", canonical),
        "enabled": enabled,
        "capabilities": list(channel_type.get("capabilities", [])),
    }
    for field_spec in channel_config_fields(canonical):
        name = field_spec["name"]
        if name in config:
            continue
        if "default" in field_spec:
            config[name] = field_spec["default"]
    return config


def persistable_social_channel_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = dict(raw or {})
    settings = config.pop("settings", None)
    if isinstance(settings, dict):
        for key, value in settings.items():
            config.setdefault(str(key), value)
    for key, value in list(config.items()):
        if key in _URL_SECRET_KEYS and value:
            config.pop(key, None)
            config["secret_mode"] = "memory_only"
            continue
        if key.endswith("_env") and value and not _is_env_var_name(str(value)):
            config.pop(key, None)
            config["secret_mode"] = "memory_only"
            continue
        canonical = _canonical_config_key(str(config.get("platform") or "generic"), str(key))
        if canonical != key:
            config.pop(key, None)
            config.setdefault(canonical, value)
            continue
        if _is_legacy_inline_secret_key(key) and value:
            config.pop(key, None)
            config["secret_mode"] = "memory_only"
    config.pop("set_default", None)
    return config


def default_social_channel_configs() -> list[dict[str, Any]]:
    enabled_defaults = [
        default_social_channel_config("generic", enabled=True),
    ]
    configured = {item["platform"] for item in enabled_defaults}
    for channel_type in NANOBOT_CHANNEL_TYPES:
        platform = channel_type["platform"]
        if platform in configured:
            continue
        enabled_defaults.append(default_social_channel_config(platform, enabled=False))
    return enabled_defaults


def create_default_social_channel_registry() -> SocialChannelRegistry:
    registry = SocialChannelRegistry(default_channel_id="generic")
    for config in default_social_channel_configs():
        registry.upsert(social_channel_from_config(config))
    return registry
