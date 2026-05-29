"""Callback registry for domain resource fetchers.

Trading domain registers fetchers at startup; Core routes /resources/:id
calls here without knowing what resources exist.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class ResourceProviderRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fetchers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, resource_id: str, fetcher: Callable[[dict[str, Any]], Any]) -> None:
        with self._lock:
            self._fetchers[resource_id] = fetcher

    def fetch(self, resource_id: str, params: dict[str, Any]) -> Any:
        with self._lock:
            fetcher = self._fetchers.get(resource_id)
        if fetcher is None:
            raise KeyError(resource_id)
        return fetcher(params)

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._fetchers.keys())
