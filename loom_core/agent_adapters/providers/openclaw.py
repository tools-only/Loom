"""Openclaw provider — http × openai (local gateway at :18789)."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["workspace.patch", "analysis.review"]
    adapter = AgentAdapter(
        adapter_id="openclaw",
        transport="http",
        protocol="openai",
        endpoint="http://localhost:18789/v1/chat/completions",
        capabilities=capabilities,
    )
    return {"id": "openclaw", "label": "OpenClaw Agent", "capabilities": capabilities, "instance": adapter}
