"""Load agent configuration from config/cloud-agents.json + .env."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_cloud_agents(repo_root: Path) -> dict:
    """Return dict of adapter configs keyed by adapter_id.

    Historically this file only described HTTP cloud agents. It now also
    accepts process-backed closed agents (for example Codex or Claude Code).
    Adapters with require_auth=True are skipped only when they declare a token
    env var and that env var is absent.
    """
    cfg_path = repo_root / "config" / "cloud-agents.json"
    if not cfg_path.exists():
        return {}

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    result = {}
    for adapter_id, info in raw.items():
        if adapter_id.startswith("_") or not isinstance(info, dict):
            continue  # skip metadata / comment keys
        transport = str(info.get("transport") or "http").lower()
        token_var = info.get(
            "token_env",
            f"{adapter_id.upper().replace('-', '_')}_TOKEN",
        )
        token = os.environ.get(token_var)
        requires_auth = bool(info.get("require_auth", transport == "http"))
        if not token and requires_auth and transport == "http":
            continue
        result[adapter_id] = {
            "adapter_id": adapter_id,
            "transport": transport,
            "protocol": info.get("protocol", "loom"),
            "codex_backend": info.get("codex_backend", "sdk"),
            "command": info.get("command", []),
            "task_as_arg": bool(info.get("task_as_arg", False)),
            "endpoint": info.get("endpoint", ""),
            "auth_token": token or None,
            "auth_token_env": token_var,
            "capabilities": info.get("capabilities", []),
            "timeout_s": float(info.get("timeout_s", 120)),
            "system_prompt": info.get("system_prompt"),
            "hw_capabilities": info.get("hw_capabilities", {}),
        }
    return result
