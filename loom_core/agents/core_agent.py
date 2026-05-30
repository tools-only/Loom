"""Loom Core Agent — optional high-level reasoning layer.

The Core Agent is allowed to be slower and inference-heavy, and must never
block the base UI loop or task dispatch path. When absent, all methods
return None.
"""

from __future__ import annotations

from typing import Any


class LoomCoreAgent:
    """Optional Core Agent for higher-order reasoning about Loom itself.

    Currently a reserve — returns None for all operations when idle.
    """

    def __init__(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def suggest(self, query: str) -> Any:
        return None
