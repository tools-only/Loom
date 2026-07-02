"""Bootstrap cloud adapters into an AgentAdapterRegistry.

Called once at Brain startup AFTER LoomCoreRuntime is ready.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_core.agent_adapters.cloud_config import load_cloud_agents
from loom_core.agent_adapters.factory import adapter_from_config


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
        adapter = adapter_from_config(
            {"adapter_id": adapter_id, **cfg},
            runtime=runtime,
            hands_root=hands_root,
        )
        try:
            registry.register(adapter)
            registered.append(adapter_id)
        except ValueError:
            pass

    return registered
