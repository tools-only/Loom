"""Loom Core Agent — Brain-level reasoning and multi-hand orchestration.

Responsibilities:
  - Resolve workflow (which hands to fire, for which domain)
  - Parallel hand execution via injected hand_runner callable
  - B-business synthesis: apply user strategy to multi-hand key_claims
  - Sediment last-synthesis to brain/context/
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Awaitable


class LoomCoreAgent:
    """Brain agent: orchestrates hands and synthesizes under user strategy."""

    def __init__(
        self,
        brain_harness,
        dispatcher,
        hand_runner: Callable[[str, str, dict], Awaitable[dict]],
        client,
        model: str,
    ) -> None:
        self._harness = brain_harness
        self._dispatcher = dispatcher
        self._hand_runner = hand_runner
        self._client = client
        self._model = model
        self._running = True

    @property
    def is_running(self) -> bool:
        return self._running

    async def analyze(self, question: str, context: dict) -> dict[str, Any]:
        """Full Brain pipeline: workflow → parallel hands → synthesis → sediment."""
        cold = self._harness.cold_start()
        wf = await self._dispatcher.resolve(question, context)

        async def _run_one(hand_id: str) -> tuple[str, dict]:
            try:
                artifact = await self._hand_runner(hand_id, question, context)
                return hand_id, artifact
            except Exception as exc:
                return hand_id, {
                    "metadata": {"key_claims": [], "error": str(exc), "confidence": 0.0},
                    "narrative": "",
                }

        results = await asyncio.gather(*[_run_one(h) for h in wf["hands"]])
        hand_artifacts = dict(results)

        synthesis = await self._harness.synthesize(
            question, hand_artifacts, wf, self._client, self._model
        )
        intent_activation = getattr(self._harness, "_last_intent_activation", None)
        policy_plan = getattr(self._harness, "_last_policy_plan", None)
        reward_report = getattr(self._harness, "_last_reward_report", None)
        self._harness.write_last_synthesis(question, wf, synthesis)

        return {
            "synthesis": synthesis,
            "hand_artifacts": hand_artifacts,
            "workflow_decision": wf,
            "cold_start": cold,
            "intent_activation": self._asdict_or_none(intent_activation),
            "intent_policy_plan": self._asdict_or_none(policy_plan),
            "intent_reward_report": self._asdict_or_none(reward_report),
        }

    def suggest(self, query: str) -> Any:
        """Legacy stub — prefer analyze() for new callers."""
        return None

    @staticmethod
    def _asdict_or_none(value: Any) -> dict | None:
        if value is None:
            return None
        if is_dataclass(value):
            return asdict(value)
        return value if isinstance(value, dict) else None
