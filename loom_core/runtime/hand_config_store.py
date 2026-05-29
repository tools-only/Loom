"""Per-hand config store backed by hands/<id>/config.json.

Raw JSON passthrough — no schema validation or strategy.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class HandConfigStore:
    def __init__(self, hands_root: Path) -> None:
        self._root = Path(hands_root)
        self._lock = threading.Lock()

    def _config_path(self, hand_id: str) -> Path:
        return self._root / hand_id / "config.json"

    def read(self, hand_id: str) -> dict:
        path = self._config_path(hand_id)
        with self._lock:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))

    def write(self, hand_id: str, config: dict) -> None:
        path = self._config_path(hand_id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
