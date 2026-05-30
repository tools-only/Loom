"""Herms provider — process × loom."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["workspace.patch", "sentiment.scan"]
    adapter = AgentAdapter(
        adapter_id="herms",
        transport="process",
        protocol="loom",
        command=["herms", "run"],
        capabilities=capabilities,
    )
    return {"id": "herms", "label": "Herms Agent", "capabilities": capabilities, "instance": adapter}
