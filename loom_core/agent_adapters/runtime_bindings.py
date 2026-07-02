"""Persistent Hand-to-agent runtime bindings shared by Brain, CLI, and UI."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


DEFAULT_DOCUMENT: dict[str, Any] = {"version": 1, "bindings": {}}


def hand_runtime_config_path(root: str | Path, configured: str | Path | None = None) -> Path:
    """Return the runtime binding path, allowing an explicit CLI override."""
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(root).resolve() / "config" / "hand-runtimes.json"


def resolve_hand_runtime(
    *,
    explicit: str = "",
    bound: str = "",
    mounted: str = "",
    declared: str = "sdk",
) -> str:
    """Resolve runtime using the public and backwards-compatible precedence."""
    return explicit or bound or mounted or declared or "sdk"


class HandRuntimeBindingStore:
    """Small atomic JSON store for persistent Hand runtime selections."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def document(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"version": 1, "bindings": {}}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"version": 1, "bindings": {}}
            bindings = raw.get("bindings", {}) if isinstance(raw, dict) else {}
            if not isinstance(bindings, dict):
                bindings = {}
            return {
                "version": 1,
                "bindings": {
                    str(hand_id): str(adapter_id)
                    for hand_id, adapter_id in bindings.items()
                    if str(hand_id).strip() and str(adapter_id).strip()
                },
            }

    def list(self) -> dict[str, str]:
        return dict(self.document()["bindings"])

    def get(self, hand_id: str) -> str:
        return self.list().get(str(hand_id).strip(), "")

    def set(self, hand_id: str, adapter_id: str) -> None:
        hand_id = str(hand_id).strip()
        adapter_id = str(adapter_id).strip()
        if not hand_id:
            raise ValueError("hand_id is required")
        if not adapter_id:
            raise ValueError("adapter_id is required")
        with self._lock:
            document = self.document()
            document["bindings"][hand_id] = adapter_id
            self._write(document)

    def remove(self, hand_id: str) -> bool:
        hand_id = str(hand_id).strip()
        with self._lock:
            document = self.document()
            existed = hand_id in document["bindings"]
            if existed:
                document["bindings"].pop(hand_id, None)
                self._write(document)
            return existed

    def remove_adapter(self, adapter_id: str) -> list[str]:
        adapter_id = str(adapter_id).strip()
        with self._lock:
            document = self.document()
            removed = sorted(
                hand_id
                for hand_id, current in document["bindings"].items()
                if current == adapter_id
            )
            if removed:
                for hand_id in removed:
                    document["bindings"].pop(hand_id, None)
                self._write(document)
            return removed

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
