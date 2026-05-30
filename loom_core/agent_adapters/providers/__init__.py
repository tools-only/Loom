"""Provider definitions for concrete agent adapters."""

from __future__ import annotations
from typing import Any


def create_providers() -> dict[str, dict[str, Any]]:
    from . import codex, cc, openclaw, herms, opencode

    result: dict[str, dict[str, Any]] = {}
    for mod in [codex, cc, openclaw, herms, opencode]:
        try:
            info = mod.create_provider()
            result[info["id"]] = info
        except Exception:
            pass
    return result
