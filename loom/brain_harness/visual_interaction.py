"""Visual query and interaction trace model.

Compiles epistemic bottlenecks into lightweight visual queries for human
checkpoint review, and records the interaction traces with inferred signals.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .bottleneck import EpistemicBottleneck


def _uid(prefix: str = "vq") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _iid(prefix: str = "vi") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class VisualQuery:
    """A small, local interaction compiled from a bottleneck."""

    query_id: str
    episode_id: str
    bottleneck_id: str
    query_type: str  # goal_fork, evidence_trust, gap_salience, drift_checkpoint
    anchor_type: str = ""
    anchor_id: str = ""
    cards: list[dict] = field(default_factory=list)
    allowed_interactions: list[str] = field(default_factory=list)
    expires_after_phase: str = "review"

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "episode_id": self.episode_id,
            "bottleneck_id": self.bottleneck_id,
            "query_type": self.query_type,
            "anchor_type": self.anchor_type,
            "anchor_id": self.anchor_id,
            "cards": list(self.cards),
            "allowed_interactions": list(self.allowed_interactions),
            "expires_after_phase": self.expires_after_phase,
        }


@dataclass
class VisualInteractionTrace:
    """Raw interaction plus inferred weak signal and downstream consumption."""

    interaction_id: str
    query_id: str
    episode_id: str
    anchor_type: str = ""
    anchor_id: str = ""
    gesture: str = ""
    visual_context: dict = field(default_factory=dict)
    inferred_signals: list[dict] = field(default_factory=list)
    consumed_by: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "interaction_id": self.interaction_id,
            "query_id": self.query_id,
            "episode_id": self.episode_id,
            "anchor_type": self.anchor_type,
            "anchor_id": self.anchor_id,
            "gesture": self.gesture,
            "visual_context": dict(self.visual_context),
            "inferred_signals": list(self.inferred_signals),
            "consumed_by": list(self.consumed_by),
        }

    def mark_consumed(self, consumer: str, effect: str) -> None:
        self.consumed_by.append({"consumer": consumer, "effect": effect})


class VisualQueryCompiler:
    """Compiles bottlenecks into visual queries for human review."""

    QUERY_TYPE_MAP = {
        "claim": "evidence_trust",
        "gap": "gap_salience",
        "assumption": "evidence_trust",
        "goal_frame": "goal_fork",
        "constraint": "drift_checkpoint",
    }

    @staticmethod
    def compile(
        episode_id: str,
        bottlenecks: list[EpistemicBottleneck],
    ) -> list[VisualQuery]:
        """Create visual queries only for 'ask'-routed bottlenecks."""
        queries: list[VisualQuery] = []
        for b in bottlenecks:
            if b.recommended_action != "ask":
                continue
            query_type = VisualQueryCompiler.QUERY_TYPE_MAP.get(b.anchor_type, "evidence_trust")
            q = VisualQuery(
                query_id=_uid("vq"),
                episode_id=episode_id,
                bottleneck_id=b.bottleneck_id,
                query_type=query_type,
                anchor_type=b.anchor_type,
                anchor_id=b.anchor_id,
                cards=[{"card_id": b.anchor_type, "label": b.rationale,
                        "state_ids": [b.anchor_id]}],
                allowed_interactions=["trust", "contest", "expand", "skip"],
            )
            queries.append(q)
        return queries


class VisualInteractionInterpreter:
    """Converts raw gestures into weak inferred signals."""

    GESTURE_SIGNAL_MAP = {
        "trust": "provisional_trust",
        "contest": "evidence_distrust",
        "expand": "evidence_need",
        "pin": "high_salience",
        "mute": "low_salience",
        "skip": "no_current_value",
    }

    @staticmethod
    def interpret(
        interaction_id: str,
        query_id: str,
        episode_id: str,
        gesture: str,
        anchor_type: str = "",
        anchor_id: str = "",
        visual_context: dict | None = None,
    ) -> VisualInteractionTrace:
        signal_type = VisualInteractionInterpreter.GESTURE_SIGNAL_MAP.get(
            gesture, "unknown"
        )
        target = anchor_id or query_id
        trace = VisualInteractionTrace(
            interaction_id=interaction_id or _iid("vi"),
            query_id=query_id,
            episode_id=episode_id,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            gesture=gesture,
            visual_context=visual_context or {},
            inferred_signals=[
                {
                    "type": signal_type,
                    "target": target,
                    "confidence": 0.7 if gesture in ("trust", "contest") else 0.5,
                }
            ],
        )
        return trace
