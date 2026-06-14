"""Opencode provider — process × loom, task injected as CLI arg."""
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
    capabilities = ["thesis.debate", "workspace.patch"]
    adapter = AgentAdapter(
        adapter_id="opencode",
        transport="process",
        protocol="loom",
        command=["opencode", "run"],
        task_as_arg=True,   # opencode run "<task>" — prompt is a CLI argument
        capabilities=capabilities,
        hw_capabilities=_HW,
    )
    return {"id": "opencode", "label": "Opencode Agent", "capabilities": capabilities, "hw_capabilities": _HW, "instance": adapter}
