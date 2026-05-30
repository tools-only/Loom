"""OpenClaw agent provider."""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["workspace.patch", "analysis.review"]
    adapter = ProcessAgentAdapter(
        adapter_id="openclaw",
        command=["openclaw", "run"],
        capabilities=capabilities,
    )
    return {
        "id": "openclaw",
        "label": "OpenClaw Agent",
        "capabilities": capabilities,
        "instance": adapter,
    }
