"""Bootstrap cloud adapters into an AgentAdapterRegistry.

Called once at Brain startup AFTER LoomCoreRuntime is ready.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_core.agent_adapters.adapter import AgentAdapter
from loom_core.agent_adapters.cloud_config import load_cloud_agents


def register_cloud_adapters(
    registry: Any,
    runtime: Any,
    repo_root: Path | None = None,
) -> list[str]:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    hands_root = repo_root / "hands"
    cfgs = load_cloud_agents(repo_root)
    registered: list[str] = []

    for adapter_id, cfg in cfgs.items():
        protocol = cfg.get("protocol", "loom")
        adapter = AgentAdapter(
            adapter_id=adapter_id,
            transport="http",
            protocol=protocol,
            endpoint=cfg["endpoint"],
            auth_token=cfg["auth_token"],
            timeout_s=cfg["timeout_s"],
            runtime=runtime if protocol == "loom" else None,
            hands_root=hands_root if protocol == "loom" else None,
            capabilities=cfg["capabilities"],
            system_prompt=cfg.get("system_prompt"),
        )
        try:
            registry.register(adapter)
            registered.append(adapter_id)
        except ValueError:
            pass

    return registered
