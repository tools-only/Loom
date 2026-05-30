"""Opencode agent provider."""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["thesis.debate", "workspace.patch"]
    adapter = ProcessAgentAdapter(
        adapter_id="opencode",
        command=["opencode", "run"],
        capabilities=capabilities,
    )
    return {
        "id": "opencode",
        "label": "Opencode Agent",
        "capabilities": capabilities,
        "instance": adapter,
    }
