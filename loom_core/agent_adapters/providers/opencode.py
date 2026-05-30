"""Opencode provider — process × loom, task injected as CLI arg."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["thesis.debate", "workspace.patch"]
    adapter = AgentAdapter(
        adapter_id="opencode",
        transport="process",
        protocol="loom",
        command=["opencode", "run"],
        task_as_arg=True,   # opencode run "<task>" — prompt is a CLI argument
        capabilities=capabilities,
    )
    return {"id": "opencode", "label": "Opencode Agent", "capabilities": capabilities, "instance": adapter}
