"""Claude Code (cc) provider — process × loom."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["market.analysis", "sentiment.scan", "target.thesis", "position.review"]
    adapter = AgentAdapter(
        adapter_id="cc",
        transport="process",
        protocol="loom",
        command=["claude", "-p"],
        capabilities=capabilities,
    )
    return {"id": "cc", "label": "Claude Code Agent", "capabilities": capabilities, "instance": adapter}
