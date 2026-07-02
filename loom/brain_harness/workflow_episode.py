"""WorkflowEpisode 鈥?per-run typed event log for BrainOrchestrator.

One episode = one analyze() call. Events are appended incrementally to:
  brain/episodes/<episode_id>.jsonl

The file is append-only and acts as a crash-recovery checkpoint. Phase views
(phase_trace, rubric_coverage) are derived from the event log, not stored as
separate fields.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

TerminationReason = Literal[
    "synthesis_success",
    "budget_exceeded",
    "repair_budget_exceeded",
    "user_interrupt",
    "adapter_error",
    "gap_unresolved",
    "schema_violation_unrecoverable",
]

EpisodeState = Literal[
    "Planning",
    "Dispatching",
    "Reviewing",
    "Repairing",
    "Synthesizing",
    "Persisted",
    "Interrupted",
    "Failed",
]

_EPISODE_DIR = "brain/episodes"

# ── Event name constants (plan: Task 4) ──
EVENT_STATE_PROPOSED = "state.proposed"
EVENT_CLAIM_CREATED = "claim.created"
EVENT_GAP_DETECTED = "gap.detected"
EVENT_BOTTLENECK_DETECTED = "bottleneck.detected"
EVENT_VISUAL_QUERY_CREATED = "visual.query_created"
EVENT_VISUAL_INTERACTION = "visual.interaction"
EVENT_STATE_USED_BY_SYNTHESIS = "state.used_by_synthesis"
EVENT_INTERACTION_CONSUMED = "interaction.consumed"


@dataclass
class WorkflowEpisode:
    episode_id: str
    goal: str
    domain: str = "general"
    goal_type: str = "ad_hoc"

    state: EpisodeState = "Planning"
    termination_reason: TerminationReason | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    # Budget tracking 鈥?filled by BudgetGovernor
    budget_token_used: int = 0
    budget_cost_used_usd: float = 0.0

    # Cached phase summaries (derived from events for quick access)
    hands_dispatched: list[str] = field(default_factory=list)
    quality_gaps: list[str] = field(default_factory=list)

    # Append-only in-memory event buffer (not included in to_summary)
    _events: list[dict] = field(default_factory=list, repr=False)
    _event_sink: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)

    # 鈹€鈹€ Factory 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    @classmethod
    def new(
        cls,
        goal: str,
        domain: str = "general",
        goal_type: str = "ad_hoc",
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> "WorkflowEpisode":
        return cls(
            episode_id=str(uuid.uuid4()),
            goal=goal,
            domain=domain,
            goal_type=goal_type,
            _event_sink=event_sink,
        )

    # 鈹€鈹€ Event API 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def write_event(
        self,
        root: Path,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append event to in-memory buffer and flush to JSONL immediately."""
        event: dict[str, Any] = {
            "ts": time.time(),
            "type": event_type,
            "episode_id": self.episode_id,
        }
        if payload:
            event.update(payload)
        self._events.append(event)

        ep_dir = root / _EPISODE_DIR
        ep_dir.mkdir(parents=True, exist_ok=True)
        log_path = ep_dir / f"{self.episode_id}.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        if self._event_sink is not None:
            try:
                self._event_sink(dict(event))
            except Exception:
                pass

    # 鈹€鈹€ State transitions 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def transition(
        self,
        root: Path,
        new_state: EpisodeState,
        payload: dict | None = None,
    ) -> None:
        old = self.state
        self.state = new_state
        self.write_event(root, "state.transition", {"from": old, "to": new_state, **(payload or {})})

    def finish(
        self,
        root: Path,
        termination_reason: TerminationReason,
        payload: dict | None = None,
    ) -> None:
        self.finished_at = time.time()
        self.termination_reason = termination_reason
        target: EpisodeState = "Persisted" if termination_reason == "synthesis_success" else "Failed"
        self.transition(root, target, payload)

    # 鈹€鈹€ Summary (safe to serialize, no Path objects) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def to_summary(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "goal": self.goal,
            "domain": self.domain,
            "goal_type": self.goal_type,
            "state": self.state,
            "termination_reason": self.termination_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": (
                round((self.finished_at - self.started_at) * 1000)
                if self.finished_at
                else None
            ),
            "hands_dispatched": self.hands_dispatched,
            "quality_gaps": self.quality_gaps,
            "budget_token_used": self.budget_token_used,
            "budget_cost_used_usd": self.budget_cost_used_usd,
            "event_count": len(self._events),
        }
