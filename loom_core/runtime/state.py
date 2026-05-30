"""Runtime state management for Loom Core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
    """Mutable state of the Loom Core runtime."""

    booted: bool = False
    manifests: list[dict[str, Any]] = field(default_factory=list)
    active_adapter_ids: list[str] = field(default_factory=list)

    def mark_booted(self) -> None:
        self.booted = True

    def set_manifests(self, manifests: list[dict[str, Any]]) -> None:
        self.manifests = list(manifests)
