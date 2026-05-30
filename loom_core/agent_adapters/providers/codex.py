"""Codex provider — process × loom."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = ["market.regime.review", "ticker.thesis.review", "workspace.patch"]
    adapter = AgentAdapter(
        adapter_id="codex",
        transport="process",
        protocol="loom",
        command=["codex", "run"],
        capabilities=capabilities,
    )
    return {"id": "codex", "label": "Codex Agent", "capabilities": capabilities, "instance": adapter}
