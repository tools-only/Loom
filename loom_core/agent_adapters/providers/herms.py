"""Herms provider — process × loom."""
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
    capabilities = ["workspace.patch", "sentiment.scan"]
    adapter = AgentAdapter(
        adapter_id="herms",
        transport="process",
        protocol="loom",
        command=["herms", "run"],
        capabilities=capabilities,
        hw_capabilities=_HW,
    )
    return {"id": "herms", "label": "Herms Agent", "capabilities": capabilities, "hw_capabilities": _HW, "instance": adapter}
