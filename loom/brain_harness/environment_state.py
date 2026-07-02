"""Environment state data model — structured representation of the task world.

States represent facts, claims, assumptions, gaps, risks, and goal frames
that emerge during agent execution. They are NOT user intent and NOT UI cards.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


def _uid(prefix: str = "S") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class EnvironmentState:
    """A single structured observation about the task world."""

    state_id: str
    episode_id: str
    type: str  # claim, gap, assumption, risk, goal_frame, constraint
    status: str = "proposed"  # proposed -> active -> contested -> verifying -> resolved | stale | retired
    summary: str = ""
    scope: str = "current_episode"
    salience: float = 0.5
    freshness: float = 1.0
    confidence: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    created_by: str = ""
    updated_by: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "state_id": self.state_id,
            "episode_id": self.episode_id,
            "type": self.type,
            "status": self.status,
            "summary": self.summary,
            "scope": self.scope,
            "salience": self.salience,
            "freshness": self.freshness,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "conflicts_with": list(self.conflicts_with),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class StateTransition:
    """Evidence-backed movement of a state between statuses."""

    state_id: str
    from_status: str
    to_status: str
    episode_id: str
    phase: str = ""
    evidence: list[dict] = field(default_factory=list)
    decided_by: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "state_id": self.state_id,
            "from": self.from_status,
            "to": self.to_status,
            "episode_id": self.episode_id,
            "phase": self.phase,
            "evidence": list(self.evidence),
            "decided_by": self.decided_by,
            "confidence": self.confidence,
        }


@dataclass
class EnvironmentStateFrame:
    """A point-in-time snapshot of active environment states for a given episode."""

    episode_id: str
    states: list[EnvironmentState] = field(default_factory=list)
    active_state_ids: list[str] = field(default_factory=list)

    @property
    def active_states(self) -> list[EnvironmentState]:
        return [s for s in self.states if s.state_id in set(self.active_state_ids)]

    @property
    def stale_states(self) -> list[EnvironmentState]:
        return [s for s in self.states if s.status == "stale"]

    @property
    def contested_states(self) -> list[EnvironmentState]:
        return [s for s in self.states if s.status == "contested"]

    def summary(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "total_states": len(self.states),
            "active_count": len(self.active_states),
            "stale_count": len(self.stale_states),
            "contested_count": len(self.contested_states),
            "state_ids": [s.state_id for s in self.active_states],
        }


class EnvironmentStateManager:
    """Extracts and manages environment states from agent execution artifacts."""

    @staticmethod
    def extract_from_artifacts(
        episode_id: str,
        hand_artifacts: dict,
        review_result: dict | None = None,
    ) -> list[EnvironmentState]:
        """Extract claim and gap states from hand artifact metadata."""
        states: list[EnvironmentState] = []
        now = time.time()

        for hand_id, artifact in (hand_artifacts or {}).items():
            meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
            claims = meta.get("key_claims", []) or []
            gaps = meta.get("gaps", []) or []

            for claim in claims:
                if isinstance(claim, dict):
                    state = EnvironmentState(
                        state_id=_uid("S"),
                        episode_id=episode_id,
                        type="claim",
                        status="active",
                        summary=str(claim.get("claim", claim.get("text", ""))),
                        confidence=float(claim.get("confidence", 0.5)),
                        evidence_refs=[f"artifact:{hand_id}"],
                        created_by="artifact_extraction",
                        created_at=now,
                        updated_at=now,
                    )
                    states.append(state)

            for gap in gaps:
                if isinstance(gap, dict):
                    state = EnvironmentState(
                        state_id=_uid("S"),
                        episode_id=episode_id,
                        type="gap",
                        status="active",
                        summary=str(gap.get("description", gap.get("gap", ""))),
                        salience=float(gap.get("impact", 0.5)),
                        freshness=float(gap.get("freshness", 0.5)),
                        confidence=0.3,
                        evidence_refs=[f"artifact:{hand_id}"],
                        created_by="gap_extraction",
                        created_at=now,
                        updated_at=now,
                    )
                    states.append(state)

        if review_result and isinstance(review_result, dict):
            gaps = review_result.get("confidence_gaps", []) or []
            for gap in gaps:
                states.append(EnvironmentState(
                    state_id=_uid("S"),
                    episode_id=episode_id,
                    type="gap",
                    status="active",
                    summary=str(gap.get("gap", str(gap))),
                    salience=0.6,
                    confidence=0.3,
                    evidence_refs=["review"],
                    created_by="review_gap",
                    created_at=now,
                    updated_at=now,
                ))

        return states

    @staticmethod
    def build_frame(
        episode_id: str,
        states: list[EnvironmentState],
    ) -> EnvironmentStateFrame:
        """Select active states, excluding stale and retired."""
        active_ids = [
            s.state_id
            for s in states
            if s.status not in ("stale", "retired")
        ]
        return EnvironmentStateFrame(
            episode_id=episode_id,
            states=states,
            active_state_ids=active_ids,
        )

    @staticmethod
    def transition(
        state: EnvironmentState,
        to_status: str,
        episode_id: str,
        phase: str = "",
        evidence: list[dict] | None = None,
        decided_by: str = "",
    ) -> StateTransition:
        """Create a StateTransition and update the state's status."""
        now = time.time()
        old_status = state.status
        state.status = to_status
        state.updated_at = now
        state.updated_by = decided_by

        return StateTransition(
            state_id=state.state_id,
            from_status=old_status,
            to_status=to_status,
            episode_id=episode_id,
            phase=phase,
            evidence=evidence or [],
            decided_by=decided_by,
            confidence=state.confidence,
        )
