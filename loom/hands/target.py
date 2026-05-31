from __future__ import annotations

from .base import BaseHand
from bridge import get_thesis, append_thesis


class TargetHand(BaseHand):
    def __init__(self):
        super().__init__("target")

    async def run(self, task: str, context: dict, resource_menu: list[dict]) -> dict:
        ticker = context.get("ticker", "").upper()

        # Inject prior thesis into context for incremental updates
        if ticker:
            prior = await get_thesis(ticker)
            if prior:
                context = {**context, "prior_thesis": prior}

        artifact = await super().run(task, context, resource_menu)

        # Persist updated thesis (Python-owned write)
        if ticker:
            append_thesis(ticker, artifact)

        return artifact
