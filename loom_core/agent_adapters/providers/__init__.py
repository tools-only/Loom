"""Provider definitions for concrete agent adapters.

Each provider wraps ProcessAgentAdapter with domain-appropriate
capabilities and command defaults.
"""

from __future__ import annotations

from typing import Any

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter


def create_providers() -> dict[str, dict[str, Any]]:
    """Return a dict of provider info keyed by adapter id.

    Each entry: {id, label, capabilities, instance (ProcessAgentAdapter)}.
    """
    from . import codex, cc, openclaw, herms, opencode

    provider_modules = [codex, cc, openclaw, herms, opencode]
    result: dict[str, dict[str, Any]] = {}
    for mod in provider_modules:
        info = mod.create_provider()
        result[info["id"]] = info
    return result
