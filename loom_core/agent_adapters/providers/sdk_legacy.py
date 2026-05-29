"""SDK Legacy in-process adapter.

Wraps a domain-provided async invoke function so that existing SDK-based
hand implementations can be registered as AgentAdapters without subprocess
overhead. The trading domain creates these adapters at startup and registers
them; this module has no knowledge of domain business logic.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, Callable, Awaitable


class InProcessAdapter:
    """Generic in-process adapter — domain provides the invoke callable.

    The domain passes an async callable with signature:
        async def invoke_fn(task: dict) -> dict  (returns artifact)
    """

    def __init__(
        self,
        adapter_id: str,
        invoke_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        capabilities: list[str] | None = None,
    ) -> None:
        if not adapter_id:
            raise ValueError("adapter_id must be non-empty")
        self.id = adapter_id
        self._invoke_fn = invoke_fn
        self.capabilities = capabilities or []

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        if not task:
            raise ValueError("task envelope must not be empty")

        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}

        try:
            artifact = await self._invoke_fn(task)
            yield {"type": "run.artifact", "run_id": run_id, "artifact": artifact}
            yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}
        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def cancel(self, run_id: str) -> None:
        pass


def create_provider(
    adapter_id: str,
    invoke_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    capabilities: list[str] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Factory used by trading domain to register a legacy SDK hand."""
    caps = capabilities or []
    adapter = InProcessAdapter(
        adapter_id=adapter_id,
        invoke_fn=invoke_fn,
        capabilities=caps,
    )
    return {
        "id": adapter_id,
        "label": label or f"SDK Legacy — {adapter_id}",
        "capabilities": caps,
        "instance": adapter,
    }
