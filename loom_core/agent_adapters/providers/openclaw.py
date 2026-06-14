"""Openclaw provider — http × openai (local gateway at :18789)."""
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
    capabilities = ["workspace.patch", "analysis.review"]
    adapter = AgentAdapter(
        adapter_id="openclaw",
        transport="http",
        protocol="openai",
        endpoint="http://localhost:18789/v1/chat/completions",
        capabilities=capabilities,
        hw_capabilities=_HW,
    )
    return {"id": "openclaw", "label": "OpenClaw Agent", "capabilities": capabilities, "hw_capabilities": _HW, "instance": adapter}
