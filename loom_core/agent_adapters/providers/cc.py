"""Claude Code (cc) agent provider."""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = [
        "market.analysis",
        "sentiment.scan",
        "target.thesis",
        "position.review",
    ]
    adapter = ProcessAgentAdapter(
        adapter_id="cc",
        command=["claude", "-p"],
        capabilities=capabilities,
    )
    return {
        "id": "cc",
        "label": "Claude Code Agent",
        "capabilities": capabilities,
        "instance": adapter,
    }
