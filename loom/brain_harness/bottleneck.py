"""Epistemic bottleneck detection and routing.

Detects states, claims, gaps, or decisions whose uncertainty may materially
affect downstream work, then routes them to ask/verify/defer/use actions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .environment_state import EnvironmentState, EnvironmentStateFrame


def _uid(prefix: str = "B") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class EpistemicBottleneck:
    """A state/claim/gap whose uncertainty may materially affect downstream work."""

    bottleneck_id: str
    anchor_type: str  # state, claim, gap
    anchor_id: str
    uncertainty: float = 0.5
    impact: float = 0.5
    human_answerability: float = 0.5
    agent_verifiability: float = 0.5
    interaction_cost: float = 0.5
    repair_cost_if_wrong: float = 0.5
    recommended_action: str = "defer"  # ask, verify, defer, use
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "bottleneck_id": self.bottleneck_id,
            "anchor_type": self.anchor_type,
            "anchor_id": self.anchor_id,
            "uncertainty": self.uncertainty,
            "impact": self.impact,
            "human_answerability": self.human_answerability,
            "agent_verifiability": self.agent_verifiability,
            "interaction_cost": self.interaction_cost,
            "repair_cost_if_wrong": self.repair_cost_if_wrong,
            "recommended_action": self.recommended_action,
            "rationale": self.rationale,
        }


def route_bottleneck(b: EpistemicBottleneck) -> str:
    """Deterministic router: scores -> action."""
    if b.impact < 0.3 or b.uncertainty < 0.2:
        return "use"

    if b.human_answerability > 0.5 and b.interaction_cost < 0.4:
        return "ask"

    if b.agent_verifiability > 0.4:
        return "verify"

    if b.repair_cost_if_wrong > 0.7:
        return "ask"

    return "defer"


class BottleneckDetector:
    """Detects epistemic bottlenecks from environment state frames."""

    @staticmethod
    def detect(
        frame: EnvironmentStateFrame,
        hand_artifacts: dict | None = None,
        review_result: dict | None = None,
    ) -> list[EpistemicBottleneck]:
        bottlenecks: list[EpistemicBottleneck] = []

        for state in frame.active_states:
            uncertainty = 1.0 - state.confidence
            impact = state.salience
            is_gap = state.type == "gap"

            b = EpistemicBottleneck(
                bottleneck_id=_uid("B"),
                anchor_type=state.type,
                anchor_id=state.state_id,
                uncertainty=uncertainty,
                impact=impact if not is_gap else max(impact, 0.6),
                human_answerability=_estimate_human_answerability(state),
                agent_verifiability=_estimate_agent_verifiability(state),
                interaction_cost=0.18 if state.type in ("claim", "gap") else 0.5,
                repair_cost_if_wrong=impact * 1.2 if state.type == "claim" else 0.3,
            )
            b.recommended_action = route_bottleneck(b)
            if b.recommended_action == "ask":
                b.rationale = _rationale_for(state, b)
            bottlenecks.append(b)

        if review_result and isinstance(review_result, dict):
            gaps = review_result.get("confidence_gaps", []) or []
            for gap in gaps:
                b = EpistemicBottleneck(
                    bottleneck_id=_uid("B"),
                    anchor_type="gap",
                    anchor_id="review",
                    uncertainty=0.6,
                    impact=0.7,
                    human_answerability=0.6,
                    agent_verifiability=0.5,
                    interaction_cost=0.2,
                    repair_cost_if_wrong=0.75,
                )
                b.recommended_action = route_bottleneck(b)
                bottlenecks.append(b)

        return bottlenecks


def _estimate_human_answerability(state: EnvironmentState) -> float:
    if state.type == "goal_frame":
        return 0.9
    if state.type in ("claim", "assumption"):
        return 0.65
    if state.type == "gap":
        return 0.55
    return 0.4


def _estimate_agent_verifiability(state: EnvironmentState) -> float:
    if state.type == "claim":
        return 0.55
    if state.type == "gap":
        return 0.45
    return 0.35


def _rationale_for(state: EnvironmentState, b: EpistemicBottleneck) -> str:
    if state.type == "claim":
        return f"Claim with low confidence ({state.confidence:.0%}) can be calibrated cheaply."
    if state.type == "gap":
        return "High-impact gap can benefit from human salience judgment."
    return "State would benefit from human calibration."
