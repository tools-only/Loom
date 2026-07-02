"""Normalize social chat payloads into Brain analyze requests."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


_MENTION_RE = re.compile(r"<at\b[^>]*>.*?</at>|<@[!&]?\d+>")

_YES_ANSWERS = frozenset({"是", "好", "好的", "确认", "可以", "yes", "y"})
_NO_ANSWERS = frozenset({"否", "不", "不用", "取消", "no", "n"})


@dataclass(frozen=True)
class SocialIngressMessage:
    platform: str
    text: str
    user_id: str = ""
    channel_id: str = ""
    message_id: str = ""
    thread_id: str = ""
    event_id: str = ""
    timestamp: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SocialCommand:
    question: str
    domain_hint: str = ""
    hands: tuple[str, ...] = ()
    command: str = "analyze"


@dataclass(frozen=True)
class SocialAgentCommand:
    adapter_id: str
    task: str
    dangerous: bool = False


@dataclass(frozen=True)
class SessionCommand:
    """Parsed /agent command for session management."""
    action: str  # "start" | "list" | "select" | "close" | "status" | "help"
    adapter_id: str = ""       # for "start"
    label: str = ""            # for "start"
    session_id: str = ""       # for "select" / "close"
    raw: str = ""              # original text after /agent


def normalize_social_payload(
    payload: dict[str, Any],
    *,
    platform: str = "generic",
) -> SocialIngressMessage:
    """Normalize Feishu/Lark, Discord, or generic message payloads."""
    payload = payload or {}
    normalized_platform = str(payload.get("platform") or platform or "generic").lower()
    if normalized_platform in {"feishu", "lark"}:
        return _normalize_feishu(payload, normalized_platform)
    if normalized_platform == "discord":
        return _normalize_discord(payload)
    return _normalize_generic(payload, normalized_platform)


def parse_social_command(text: str, domain_registry=None) -> SocialCommand:
    """Parse an explicit Loom command into an analyze request shape."""
    clean = _clean_text(text)
    if not clean:
        return SocialCommand(question="")

    tokens = clean.split()
    explicit_command = bool(tokens and _is_loom_command_token(tokens[0]))
    if explicit_command:
        tokens = tokens[1:]
    else:
        return SocialCommand(question=clean)

    domain_hint = ""
    hands: list[str] = []
    if tokens:
        first = tokens[0].lower()
        if domain_registry:
            # Use registry keyword mapping
            domain_hint = domain_registry.keywords_to_domain(first) or ""
            if domain_hint:
                adapter = domain_registry.get(domain_hint)
                known_hands = set(adapter.default_hands.keys()) if adapter else set()
                if first in known_hands:
                    hands.append(first)
                tokens = tokens[1:]
        else:
            # Backward-compat: hardcoded finance/general mapping
            if first in {"fin", "finance", "market", "sentiment", "target", "position"}:
                domain_hint = "finance"
                if first in {"market", "sentiment", "target", "position"}:
                    hands.append(first)
                tokens = tokens[1:]
            elif first in {"general", "gen"}:
                domain_hint = "general"
                tokens = tokens[1:]

    question = " ".join(tokens).strip() if tokens else clean
    return SocialCommand(question=question, domain_hint=domain_hint, hands=tuple(hands))


def is_explicit_loom_command(text: str) -> bool:
    """Return true only for slash commands such as /loom or /loom-visual."""
    clean = _clean_text(text)
    if not clean:
        return False
    return _is_loom_command_token(clean.split()[0])


def parse_agent_command(text: str) -> SocialAgentCommand | None:
    """Parse direct full-agent commands without routing them through Brain."""
    clean = _clean_text(text)
    if not clean:
        return None
    tokens = clean.split()
    command = tokens[0].lower()
    if command == "/codex":
        return SocialAgentCommand("codex-app-server", " ".join(tokens[1:]).strip(), dangerous=True)
    if command in {"/claude", "/claude-code"}:
        return SocialAgentCommand("runtime-hand", " ".join(tokens[1:]).strip(), dangerous=True)
    if command != "/agent":
        return None
    if len(tokens) < 2:
        return SocialAgentCommand("", "")
    # /agent start|list|select|close|status → session management (handled elsewhere)
    action = tokens[1].lower()
    if action in {"start", "list", "select", "close", "status"}:
        return None  # session command, not a legacy one-shot
    # /agent <adapter_id> <task> — legacy one-shot
    return SocialAgentCommand(tokens[1], " ".join(tokens[2:]).strip())


def parse_session_command(text: str) -> SessionCommand | None:
    """Parse /agent and /brain commands for session management.

    /agent start|list|select|close|status — session lifecycle
    /brain — switch back to Brain mode (clear foreground session)
    """
    clean = _clean_text(text)
    if not clean:
        return None
    tokens = clean.split()
    first = tokens[0].lower()

    # /brain — explicit switch to Brain mode
    if first in {"/brain", "/loom-brain"}:
        return SessionCommand(action="brain", raw=clean)

    if first != "/agent":
        return None
    if len(tokens) < 2:
        return SessionCommand(action="help", raw="")

    action = tokens[1].lower()
    if action == "start":
        adapter = tokens[2] if len(tokens) > 2 else "runtime-hand"
        label = " ".join(tokens[3:]).strip() if len(tokens) > 3 else ""
        return SessionCommand(action="start", adapter_id=adapter, label=label, raw=clean)
    if action == "list":
        return SessionCommand(action="list", raw=clean)
    if action in ("select", "sel"):
        sid = tokens[2] if len(tokens) > 2 else ""
        return SessionCommand(action="select", session_id=sid, raw=clean)
    if action == "close":
        sid = tokens[2] if len(tokens) > 2 else ""
        return SessionCommand(action="close", session_id=sid, raw=clean)
    if action == "status":
        return SessionCommand(action="status", raw=clean)
    return SessionCommand(action="help", raw=clean)


def resolve_social_agent_request(
    *,
    text: str,
    user_id: str,
    context: dict[str, Any] | None,
    default_adapter_id: str,
) -> SocialAgentCommand | None:
    """Resolve explicit commands or a channel's default direct-agent mode."""
    context = context or {}
    settings = context.get("channel_settings")
    if not isinstance(settings, dict):
        settings = {}
    explicit = parse_agent_command(text)
    if explicit is None and is_explicit_loom_command(text):
        return None
    execution_mode = str(
        settings.get("executionMode") or settings.get("execution_mode") or "brain"
    ).strip().lower()
    if explicit is None and execution_mode != "agent":
        return None

    allowed = settings.get("agentAllowFrom", settings.get("agent_allow_from", []))
    if isinstance(allowed, str):
        allowed = [part.strip() for part in allowed.split(",") if part.strip()]
    if not isinstance(allowed, (list, tuple, set)) or user_id not in {str(item) for item in allowed}:
        raise PermissionError(
            "direct agent access requires the sender in channel setting agentAllowFrom"
        )

    adapter_id = (
        explicit.adapter_id if explicit is not None else ""
    ) or str(settings.get("agentAdapterId") or settings.get("agent_adapter_id") or "")
    adapter_id = adapter_id.strip() or str(default_adapter_id or "").strip()
    task = explicit.task if explicit is not None else _clean_text(text)
    dangerous = bool(explicit is not None and explicit.dangerous)
    if not adapter_id:
        raise ValueError("no direct agent adapter is configured")
    if not task:
        raise ValueError("direct agent task is required")
    return SocialAgentCommand(adapter_id=adapter_id, task=task, dangerous=dangerous)


def parse_yes_no(text: str) -> bool | None:
    """Parse only a direct answer to a Brain-issued binary confirmation."""
    normalized = _clean_text(text).casefold().strip(" .,!，。！？?")
    if normalized in _YES_ANSWERS:
        return True
    if normalized in _NO_ANSWERS:
        return False
    return None


def build_analyze_request_from_social(
    message: SocialIngressMessage,
    *,
    extra_context: dict[str, Any] | None = None,
    domain_hint: str = "",
    domain_registry=None,
) -> dict[str, Any]:
    command = parse_social_command(message.text, domain_registry=domain_registry)
    selected_domain = domain_hint or command.domain_hint
    session_parts = [message.platform, message.channel_id, message.user_id]
    session_id = ":".join(part for part in session_parts if part)
    context = {
        "source": "social",
        "entrypoint": "social",
        "task_family": "general",
        "session_id": session_id,
        "social": asdict(message) | {"raw": _redact_raw(message.raw)},
    }
    if extra_context:
        context.update(extra_context)
    return {
        "question": command.question,
        "context": context,
        "domain_hint": selected_domain,
        "hands": list(command.hands),
    }


def _is_loom_command_token(token: str) -> bool:
    token = str(token or "").strip().lower()
    return token == "/loom" or token.startswith("/loom-")


def _normalize_feishu(payload: dict[str, Any], platform: str) -> SocialIngressMessage:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    message = event.get("message") if isinstance(event.get("message"), dict) else event
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    content = message.get("content", payload.get("text", ""))
    text = _extract_text_content(content)
    return SocialIngressMessage(
        platform=platform,
        text=_clean_text(text),
        user_id=str(sender_id.get("open_id") or sender_id.get("user_id") or payload.get("user_id") or ""),
        channel_id=str(message.get("chat_id") or payload.get("channel_id") or ""),
        message_id=str(message.get("message_id") or payload.get("message_id") or ""),
        thread_id=str(message.get("thread_id") or ""),
        event_id=str(header.get("event_id") or payload.get("event_id") or ""),
        timestamp=str(header.get("create_time") or message.get("create_time") or payload.get("timestamp") or ""),
        raw=payload,
    )


def _normalize_discord(payload: dict[str, Any]) -> SocialIngressMessage:
    author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
    return SocialIngressMessage(
        platform="discord",
        text=_clean_text(str(payload.get("content") or payload.get("text") or "")),
        user_id=str(author.get("id") or payload.get("user_id") or ""),
        channel_id=str(payload.get("channel_id") or payload.get("channelId") or ""),
        message_id=str(payload.get("id") or payload.get("message_id") or ""),
        thread_id=str(payload.get("thread_id") or payload.get("threadId") or ""),
        event_id=str(payload.get("event_id") or payload.get("id") or ""),
        timestamp=str(payload.get("timestamp") or ""),
        raw=payload,
    )


def _normalize_generic(payload: dict[str, Any], platform: str) -> SocialIngressMessage:
    return SocialIngressMessage(
        platform=platform,
        text=_clean_text(str(payload.get("text") or payload.get("content") or payload.get("message") or "")),
        user_id=str(payload.get("user_id") or payload.get("userId") or ""),
        channel_id=str(payload.get("channel_id") or payload.get("channelId") or ""),
        message_id=str(payload.get("message_id") or payload.get("messageId") or payload.get("id") or ""),
        thread_id=str(payload.get("thread_id") or payload.get("threadId") or ""),
        event_id=str(payload.get("event_id") or payload.get("eventId") or ""),
        timestamp=str(payload.get("timestamp") or ""),
        raw=payload,
    )


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict):
            return str(parsed.get("text") or parsed.get("content") or content)
        return content
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "")


def _clean_text(text: str) -> str:
    text = _MENTION_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _redact_raw(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    redacted = dict(raw)
    for key in ("token", "challenge", "encrypt", "authorization", "auth_token"):
        if key in redacted:
            redacted[key] = "[redacted]"
    return redacted
