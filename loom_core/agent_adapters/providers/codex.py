"""Codex provider — process × loom."""
from __future__ import annotations
from typing import Any
from loom_core.agent_adapters.adapter import AgentAdapter


_HW: dict[str, bool] = {
    "supports_streaming": False,
    "supports_tool_call_loop": False,
    "supports_partial_events": False,
    "supports_seed": False,
    "supports_logprobs": False,
    "supports_constrained_decoding": False,
}


def create_provider() -> dict[str, Any]:
    capabilities = ["market.regime.review", "ticker.thesis.review", "workspace.patch"]
    adapter = AgentAdapter(
        adapter_id="codex",
        transport="process",
        protocol="loom",
        command=["codex", "run"],
        capabilities=capabilities,
        hw_capabilities=_HW,
    )
    return {"id": "codex", "label": "Codex Agent", "capabilities": capabilities, "hw_capabilities": _HW, "instance": adapter}
