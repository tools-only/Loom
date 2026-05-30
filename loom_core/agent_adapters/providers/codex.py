"""Codex agent provider."""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_provider() -> dict[str, Any]:
    capabilities = [
        "market.regime.review",
        "ticker.thesis.review",
        "workspace.patch",
    ]
    adapter = ProcessAgentAdapter(
        adapter_id="codex",
        command=["codex", "run"],
        capabilities=capabilities,
    )
    return {
        "id": "codex",
        "label": "Codex Agent",
        "capabilities": capabilities,
        "instance": adapter,
    }
