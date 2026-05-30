"""Herms agent provider."""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["workspace.patch", "sentiment.scan"]
    adapter = ProcessAgentAdapter(
        adapter_id="herms",
        command=["herms", "run"],
        capabilities=capabilities,
    )
    return {
        "id": "herms",
        "label": "Herms Agent",
        "capabilities": capabilities,
        "instance": adapter,
    }
