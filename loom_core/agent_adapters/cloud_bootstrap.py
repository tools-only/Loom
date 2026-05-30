"""Bootstrap cloud adapters into an AgentAdapterRegistry.

Called once at Brain startup AFTER LoomCoreRuntime is ready, so
HttpAgentAdapter can receive the runtime reference it needs for
snapshot construction and writeback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_core.agent_adapters.cloud_config import load_cloud_agents
from loom_core.agent_adapters.http_adapter import HttpAgentAdapter


def register_cloud_adapters(
    registry: Any,
    runtime: Any,
    repo_root: Path | None = None,
) -> list[str]:
    """Load config/cloud-agents.json + env, register HttpAgentAdapters.

    Returns the list of adapter IDs that were successfully registered.
    Skips adapters missing required auth tokens (already filtered by load_cloud_agents).
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    hands_root = repo_root / "hands"
    cfgs = load_cloud_agents(repo_root)
    registered: list[str] = []

    for adapter_id, cfg in cfgs.items():
        adapter = HttpAgentAdapter(
            adapter_id=adapter_id,
            endpoint=cfg["endpoint"],
            runtime=runtime,
            hands_root=hands_root,
            auth_token=cfg["auth_token"],
            capabilities=cfg["capabilities"],
            timeout_s=cfg["timeout_s"],
        )
        try:
            registry.register(adapter)
            registered.append(adapter_id)
        except ValueError:
            pass  # duplicate id — already registered

    return registered
