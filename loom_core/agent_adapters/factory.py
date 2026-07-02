"""Factory helpers for runtime-configured agent adapters."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from loom_core.agent_adapters.adapter import AgentAdapter


VALID_TRANSPORTS = {"process", "http", "websocket"}
VALID_PROTOCOLS = {"loom", "openai", "codex"}
VALID_CODEX_BACKENDS = {"sdk", "raw"}


def normalize_command(command: Any) -> list[str]:
    """Normalize a command config into an argv list.

    String commands are accepted for config ergonomics, but execution still uses
    ``create_subprocess_exec`` with argv, never a shell string.
    """
    if command is None or command == "":
        return []
    if isinstance(command, str):
        return shlex.split(command, posix=os.name != "nt")
    if isinstance(command, (list, tuple)):
        return [str(part) for part in command if str(part)]
    raise ValueError("command must be a string or list")


def normalize_adapter_config(raw: dict[str, Any]) -> dict[str, Any]:
    adapter_id = str(raw.get("adapter_id") or raw.get("id") or "").strip()
    if not adapter_id:
        raise ValueError("adapter_id is required")

    transport = str(raw.get("transport") or "process").strip().lower()
    if transport == "ws":
        transport = "websocket"
    protocol = str(raw.get("protocol") or "loom").strip().lower()
    codex_backend = str(raw.get("codex_backend") or "sdk").strip().lower()
    if transport not in VALID_TRANSPORTS:
        raise ValueError(f"unsupported adapter transport: {transport}")
    if protocol not in VALID_PROTOCOLS:
        raise ValueError(f"unsupported adapter protocol: {protocol}")
    if codex_backend not in VALID_CODEX_BACKENDS:
        raise ValueError(f"unsupported codex backend: {codex_backend}")

    command = normalize_command(raw.get("command", []))
    endpoint = str(raw.get("endpoint") or "").strip()
    sdk_managed_codex = (
        transport == "process" and protocol == "codex" and codex_backend == "sdk"
    )
    if transport == "process" and not command and not sdk_managed_codex:
        raise ValueError("process adapters require command")
    if transport in {"http", "websocket"} and not endpoint:
        raise ValueError(f"{transport} adapters require endpoint")

    capabilities = [
        str(item).strip()
        for item in (raw.get("capabilities") or [])
        if str(item).strip()
    ]
    hw_capabilities = raw.get("hw_capabilities") or {}
    if not isinstance(hw_capabilities, dict):
        hw_capabilities = {}

    timeout_s = raw.get("timeout_s", 120.0)
    try:
        timeout_value = float(timeout_s)
    except (TypeError, ValueError):
        timeout_value = 120.0
    auth_token_env = str(
        raw.get("auth_token_env")
        or raw.get("token_env")
        or raw.get("secret_env")
        or ""
    ).strip()
    auth_token = raw.get("auth_token") or raw.get("token") or None
    if not auth_token and auth_token_env:
        auth_token = os.environ.get(auth_token_env) or None
    codex_home = str(
        raw.get("codex_home")
        or raw.get("codexHome")
        or os.environ.get("LOOM_CODEX_HOME")
        or os.environ.get("CODEX_HOME")
        or ""
    ).strip()

    return {
        "adapter_id": adapter_id,
        "transport": transport,
        "protocol": protocol,
        "codex_backend": codex_backend,
        "command": command,
        "task_as_arg": bool(raw.get("task_as_arg", False)),
        "endpoint": endpoint,
        "auth_token": auth_token,
        "auth_token_env": auth_token_env,
        "codex_home": codex_home,
        "timeout_s": timeout_value,
        "capabilities": capabilities,
        "system_prompt": raw.get("system_prompt") or None,
        "hw_capabilities": hw_capabilities,
    }


def adapter_from_config(
    raw: dict[str, Any],
    *,
    runtime: Any = None,
    hands_root: str | Path | None = None,
    http_transport: Any = None,
) -> AgentAdapter:
    cfg = normalize_adapter_config(raw)
    hands_path = Path(hands_root) if hands_root is not None else None
    return AgentAdapter(
        adapter_id=cfg["adapter_id"],
        transport=cfg["transport"],
        protocol=cfg["protocol"],
        codex_backend=cfg["codex_backend"],
        command=cfg["command"],
        task_as_arg=cfg["task_as_arg"],
        endpoint=cfg["endpoint"],
        auth_token=cfg["auth_token"],
        auth_token_env=cfg["auth_token_env"],
        codex_home=cfg["codex_home"],
        timeout_s=cfg["timeout_s"],
        runtime=runtime if cfg["protocol"] in {"loom", "codex"} else None,
        hands_root=hands_path if cfg["protocol"] in {"loom", "codex"} else None,
        system_prompt=cfg["system_prompt"],
        capabilities=cfg["capabilities"],
        hw_capabilities=cfg["hw_capabilities"],
        _transport=http_transport,
    )


def persistable_adapter_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Return normalized adapter config safe for local persistence.

    Raw bearer tokens are intentionally omitted. Use ``auth_token_env`` /
    ``token_env`` / ``secret_env`` for adapters that must survive process
    restarts with authentication.
    """
    cfg = normalize_adapter_config(raw)
    cfg.pop("auth_token", None)
    has_secret_ref = bool(cfg.get("auth_token_env"))
    has_inline_secret = bool(raw.get("auth_token") or raw.get("token"))
    if has_secret_ref:
        cfg["secret_mode"] = "env"
    elif has_inline_secret:
        cfg["secret_mode"] = "memory_only"
    else:
        cfg["secret_mode"] = "none"
    return cfg


def adapter_public_info(adapter: Any) -> dict[str, Any]:
    """Return non-secret adapter metadata for control-plane APIs."""
    return {
        "id": adapter.id,
        "capabilities": list(getattr(adapter, "capabilities", []) or []),
        "hw_capabilities": dict(getattr(adapter, "hw_capabilities", {}) or {}),
        "transport": getattr(adapter, "_transport_kind", ""),
        "protocol": getattr(adapter, "_protocol", ""),
        "codex_backend": getattr(adapter, "_codex_backend", ""),
        "command": list(getattr(adapter, "_command", []) or []),
        "task_as_arg": bool(getattr(adapter, "_task_as_arg", False)),
        "endpoint": getattr(adapter, "_endpoint", ""),
        "auth_token_env": getattr(adapter, "_auth_token_env", ""),
        "codex_home": getattr(adapter, "_codex_home", ""),
        "auth_configured": bool(
            getattr(adapter, "_auth_token", None)
            or (
                getattr(adapter, "_auth_token_env", "")
                and os.environ.get(getattr(adapter, "_auth_token_env", ""))
            )
        ),
        "timeout_s": getattr(adapter, "_timeout_s", None),
    }
