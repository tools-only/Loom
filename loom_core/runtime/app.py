"""Loom Core runtime daemon — local-first human-agent interaction framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_core.domain_sdk.registry import load_domain_manifests
from loom_core.runtime.state import RuntimeState
from loom_core.runtime.resource_provider import ResourceProviderRegistry
from loom_core.runtime.feedback_store import FeedbackStore
from loom_core.runtime.hand_config_store import HandConfigStore


class LoomCoreRuntime:
    """Local Core runtime that owns bootstrap, state, manifests, and lifecycle.

    The runtime stays deterministic and low-latency. It does not import or
    execute domain-specific (e.g. finance) business logic.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir)
        self._state = RuntimeState()
        self.core_agent: Any = None  # optional non-blocking Core Agent
        self.resource_provider = ResourceProviderRegistry()
        self.feedback_store = FeedbackStore(self._root / "logs" / "feedback.jsonl")
        self.hand_config_store = HandConfigStore(self._root / "hands")

    def bootstrap(self) -> None:
        manifests = load_domain_manifests(self._root)
        self._state.set_manifests(manifests)
        self._state.mark_booted()

    @property
    def is_booted(self) -> bool:
        return self._state.booted

    @property
    def manifests(self) -> list[dict[str, Any]]:
        return self._state.manifests

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "booted": self._state.booted,
            "manifests_loaded": len(self._state.manifests),
            "core_agent_present": self.core_agent is not None,
            "resources_registered": len(self.resource_provider.list_ids()),
        }
