"""Append-only feedback event store backed by JSONL.

Raw events only — no aggregation, no ranking, no analysis.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class FeedbackStore:
    def __init__(self, log_path: Path) -> None:
        self._path = Path(log_path)
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> None:
        record = dict(event)
        if "ts" not in record:
            record["ts"] = time.time()
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(
        self,
        *,
        hand_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if not self._path.exists():
                return []
            lines = self._path.read_text(encoding="utf-8").splitlines()

        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if hand_id is not None and event.get("hand_id") != hand_id:
                continue
            if since is not None and event.get("ts", 0) < since:
                continue
            results.append(event)
        return results
