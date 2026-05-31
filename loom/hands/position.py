from __future__ import annotations

from .base import BaseHand


class PositionHand(BaseHand):
    def __init__(self):
        super().__init__("position")

    async def run(self, task: str, context: dict, resource_menu: list[dict]) -> dict:
        # Position data is user-supplied — no external connector fetching needed.
        # Pass empty resource_menu so the Hand won't try to fetch anything.
        return await super().run(task, context, [])
