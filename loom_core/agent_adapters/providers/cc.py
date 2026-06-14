"""Claude Code (cc) provider — process × loom."""
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
    capabilities = ["market.analysis", "sentiment.scan", "target.thesis", "position.review"]
    adapter = AgentAdapter(
        adapter_id="cc",
        transport="process",
        protocol="loom",
        command=["claude", "-p"],
        capabilities=capabilities,
        hw_capabilities=_HW,
    )
    return {"id": "cc", "label": "Claude Code Agent", "capabilities": capabilities, "hw_capabilities": _HW, "instance": adapter}
