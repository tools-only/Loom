"""In-memory agent adapter registry."""

from __future__ import annotations

from .base import AgentAdapter


class AgentAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[AgentAdapter] = []
        self._default_runtime_adapter_id: str = "brain-inline"

    def set_default_runtime_adapter(self, adapter_id: str) -> None:
        self._default_runtime_adapter_id = adapter_id

    def resolve_runtime_adapter(self, executor_id: str) -> str:
        """If executor_id == 'brain-inline', substitute with the registered default."""
        if executor_id == "brain-inline":
            return self._default_runtime_adapter_id
        return executor_id

    def register(self, adapter: AgentAdapter) -> None:
        if any(existing.id == adapter.id for existing in self._adapters):
            raise ValueError(f"agent adapter already registered: {adapter.id}")
        self._adapters.append(adapter)

    def list(self) -> list[AgentAdapter]:
        return list(self._adapters)

    def find_by_capability(self, capability: str) -> AgentAdapter | None:
        for adapter in self._adapters:
            if capability in adapter.capabilities:
                return adapter
        return None

    def find_by_id(self, adapter_id: str) -> AgentAdapter | None:
        for adapter in self._adapters:
            if adapter.id == adapter_id:
                return adapter
        return None

    def upsert(self, adapter: AgentAdapter) -> None:
        """Register or replace an adapter with the same id."""
        self._adapters = [a for a in self._adapters if a.id != adapter.id]
        self._adapters.append(adapter)

    def unregister(self, adapter_id: str) -> bool:
        before = len(self._adapters)
        self._adapters = [a for a in self._adapters if a.id != adapter_id]
        return len(self._adapters) < before


def create_adapter_registry() -> AgentAdapterRegistry:
    return AgentAdapterRegistry()
