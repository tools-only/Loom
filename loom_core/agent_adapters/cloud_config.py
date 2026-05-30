"""Load cloud agent configuration from config/cloud-agents.json + .env."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_cloud_agents(repo_root: Path) -> dict:
    """Return dict of {adapter_id: {endpoint, auth_token, capabilities, timeout_s}}.

    Skips adapters with require_auth=True (default) when the token env var is absent.
    """
    cfg_path = repo_root / "config" / "cloud-agents.json"
    if not cfg_path.exists():
        return {}

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    result = {}
    for adapter_id, info in raw.items():
        if adapter_id.startswith("_") or not isinstance(info, dict):
            continue  # skip metadata / comment keys
        token_var = info.get(
            "token_env",
            f"{adapter_id.upper().replace('-', '_')}_TOKEN",
        )
        token = os.environ.get(token_var)
        if not token and info.get("require_auth", True):
            continue
        result[adapter_id] = {
            "endpoint": info["endpoint"],
            "auth_token": token or None,
            "capabilities": info.get("capabilities", []),
            "timeout_s": float(info.get("timeout_s", 120)),
            "protocol": info.get("protocol", "loom"),
            "system_prompt": info.get("system_prompt"),
        }
    return result
