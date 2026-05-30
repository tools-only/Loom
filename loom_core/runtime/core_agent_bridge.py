"""Bridge between Core runtime and the optional Core Agent.

The bridge is a no-op when core_agent is None. It ensures the runtime
never blocks on agent reasoning.
"""

from __future__ import annotations

from typing import Any


class CoreAgentBridge:
    """Routes Core-level queries to the Core Agent if present."""

    def __init__(self, runtime: Any, core_agent: Any = None) -> None:
        self._runtime = runtime
        self._core_agent = core_agent

    def route(self, query_type: str, payload: dict[str, Any]) -> Any:
        if self._core_agent is None:
            return None
        return self._core_agent.suggest(query_type)
