"""Backward-compatible alias for ProcessAgentAdapter.

New code should use AgentAdapter(transport="process", protocol="loom", ...) directly.
"""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.adapter import AgentAdapter


class ProcessAgentAdapter(AgentAdapter):
    """Subprocess adapter: stdin JSON envelope → stdout NDJSON events."""

    def __init__(
        self,
        adapter_id: str,
        command: list[str],
        capabilities: list[str] | None = None,
    ) -> None:
        super().__init__(
            adapter_id=adapter_id,
            transport="process",
            protocol="loom",
            command=command,
            capabilities=capabilities,
        )
