"""Base agent adapter protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class AgentAdapter(Protocol):
    id: str
    capabilities: list[str]

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        ...

    async def cancel(self, run_id: str) -> None:
        ...

