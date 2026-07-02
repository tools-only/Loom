from __future__ import annotations
from .base import BaseHand

class TargetHand(BaseHand):
    def __init__(self):
        super().__init__("target")

    async def run(self, task: str, context: dict, resource_menu: list[dict]) -> dict:
        return await super().run(task, context, resource_menu or [])
