"""Append-only JSONL event log."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


class EventLog:
    """Append-only event log backed by a JSONL file."""

    def __init__(self, path: str) -> None:
        self._path = path

    def append(self, event: dict) -> str:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event.get("type", "unknown")

    def reload(self) -> list[dict]:
        if not os.path.exists(self._path):
            return []
        events: list[dict] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
