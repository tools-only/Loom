"""DataFlywheel 鈥?structured episode record persistence for BrainStateEngine (L5).

Write-only in P0; FlywheelAnalyzer (read + derive signals) is P4.

Each /analyze call produces one FlywheelRecord written to:
  brain/flywheel/records.jsonl   鈥?append-only master log
  brain/flywheel/<episode_id>.json 鈥?per-episode detail (for selective reads)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class BrainSelfEval:
    """Brain's own post-synthesis quality assessment."""
    episode_id: str
    confidence: float                  # synthesis.confidence
    stance: str                        # synthesis.stance
    key_driver_count: int = 0
    has_reversal_condition: bool = False
    cold_start: bool = False
    hand_count: int = 0
    overall_quality: float = 0.0       # placeholder; computed by FlywheelAnalyzer in P4


@dataclass
class HandEval:
    """Evaluation of a single hand's artifact quality."""
    hand_id: str
    artifact_present: bool
    claim_count: int = 0
    gap_count: int = 0
    source_tier: str = "unknown"       # A/B/C/E/F derived from resources_used


@dataclass
class PhaseTrace:
    phase: int
    hands_invoked: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class HumanFeedback:
    """Async human feedback injected after an episode completes."""
    episode_id: str
    ts: str
    signal: str                        # thumbs_up / thumbs_down / correction / ignore
    comment: str = ""
    corrected_stance: str = ""


@dataclass
class FlywheelRecord:
    """One entry in the data flywheel 鈥?one per /analyze call."""
    episode_id: str
    goal_id: str
    ts: str
    question: str
    domain: str
    brain_self_eval: BrainSelfEval
    hand_evaluations: list[HandEval] = field(default_factory=list)
    hand_artifacts: dict[str, Any] = field(default_factory=dict)
    orchestration_trace: list[PhaseTrace] = field(default_factory=list)
    orchestration_snapshot: dict[str, Any] = field(default_factory=dict)
    human_feedback: list[HumanFeedback] = field(default_factory=list)
    intent_activation: dict[str, Any] | None = None
    intent_rubric: dict[str, Any] | None = None
    intent_reward_report: dict[str, Any] | None = None
    # Derived in P4 by FlywheelAnalyzer:
    profile_signals: list[dict] = field(default_factory=list)
    strategy_signals: list[dict] = field(default_factory=list)
    # State-aware harness fields (MVP):
    state_transitions: list[dict] = field(default_factory=list)
    bottlenecks: list[dict] = field(default_factory=list)
    visual_queries: list[dict] = field(default_factory=list)
    visual_interactions: list[dict] = field(default_factory=list)
    interaction_consumption: list[dict] = field(default_factory=list)

    @staticmethod
    def new(
        goal_id: str,
        question: str,
        domain: str,
        synthesis: dict,
        hand_artifacts: dict,
        cold_start: bool = False,
        intent_activation: dict[str, Any] | None = None,
        intent_rubric: dict[str, Any] | None = None,
        intent_reward_report: dict[str, Any] | None = None,
    ) -> "FlywheelRecord":
        episode_id = _new_episode_id()
        intent_activation = _plain_dict(intent_activation)
        intent_rubric = _plain_dict(intent_rubric)
        intent_reward_report = _plain_dict(intent_reward_report)
        reward_score = _reward_score(intent_reward_report)
        hand_evals = []
        for hand_id, art in (hand_artifacts or {}).items():
            meta = art.get("metadata", {}) if isinstance(art, dict) else {}
            claim_count = len(meta.get("key_claims", []))
            gap_count = len(meta.get("gaps", []))
            sources = meta.get("resources_used", [])
            hand_evals.append(HandEval(
                hand_id=hand_id,
                artifact_present=bool(art),
                claim_count=claim_count,
                gap_count=gap_count,
                source_tier=_infer_tier(sources),
            ))

        brain_eval = BrainSelfEval(
            episode_id=episode_id,
            confidence=synthesis.get("confidence", 0.0) if synthesis else 0.0,
            stance=synthesis.get("stance", "n/a") if synthesis else "n/a",
            key_driver_count=len(synthesis.get("key_drivers", [])) if synthesis else 0,
            has_reversal_condition=bool(synthesis.get("reversal_condition")) if synthesis else False,
            cold_start=cold_start,
            hand_count=len(hand_artifacts or {}),
            overall_quality=reward_score or 0.0,
        )

        return FlywheelRecord(
            episode_id=episode_id,
            goal_id=goal_id,
            ts=_now(),
            question=question,
            domain=domain,
            brain_self_eval=brain_eval,
            hand_evaluations=hand_evals,
            hand_artifacts=hand_artifacts or {},
            intent_activation=intent_activation,
            intent_rubric=intent_rubric,
            intent_reward_report=intent_reward_report,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> dict:
        """Compact dict for the JSONL master log (no per-hand detail)."""
        return {
            "episode_id": self.episode_id,
            "goal_id": self.goal_id,
            "ts": self.ts,
            "domain": self.domain,
            "stance": self.brain_self_eval.stance,
            "confidence": self.brain_self_eval.confidence,
            "reward_score": _reward_score(self.intent_reward_report),
            "rubric_id": _rubric_id(self.intent_rubric),
            "rubric_criteria_count": _rubric_criteria_count(self.intent_rubric),
            "rubric_resource_count": _rubric_resource_count(self.intent_rubric),
            "rubric_strategy_primitive_count": _rubric_strategy_primitive_count(self.intent_rubric),
            "hand_count": self.brain_self_eval.hand_count,
            "cold_start": self.brain_self_eval.cold_start,
        }


class FlywheelWriter:
    """Append-only writer for FlywheelRecord objects."""

    def __init__(self, root: Path) -> None:
        self._dir = root / "brain" / "flywheel"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log = self._dir / "records.jsonl"

    def append_record(self, record: FlywheelRecord) -> None:
        # Compact summary line to master JSONL
        line = json.dumps(record.summary_line(), ensure_ascii=False)
        with self._log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        # Full detail JSON for per-episode reads
        detail_path = self._dir / f"{record.episode_id}.json"
        detail_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_human_feedback(self, episode_id: str, feedback: HumanFeedback) -> bool:
        """Inject human feedback into an existing episode detail file."""
        detail_path = self._dir / f"{episode_id}.json"
        if not detail_path.exists():
            return False
        try:
            d = json.loads(detail_path.read_text("utf-8"))
            d.setdefault("human_feedback", []).append(asdict(feedback))
            detail_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
            return True
        except Exception:
            return False

    def load_detail(self, episode_id: str) -> dict[str, Any] | None:
        """Load the full per-episode detail record."""
        detail_path = self._dir / f"{episode_id}.json"
        if not detail_path.exists():
            return None
        try:
            data = json.loads(detail_path.read_text("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def append_repair_result(self, episode_id: str, repair: dict[str, Any]) -> bool:
        """Append a Brain-triggered repair attempt to an episode detail file."""
        return self._append_to_detail_list(episode_id, "repair_history", repair)

    def append_feedback_event(self, episode_id: str, event: dict[str, Any]) -> bool:
        """Append a scoped raw feedback event to an episode detail file."""
        return self._append_to_detail_list(episode_id, "feedback_events", event)

    def append_intent_analysis(self, episode_id: str, analysis: dict[str, Any]) -> bool:
        """Append a contextual intent analysis to an episode detail file."""
        return self._append_to_detail_list(episode_id, "intent_analyses", analysis)

    def append_confirmed_correction(self, episode_id: str, correction: dict[str, Any]) -> bool:
        """Append a user-confirmed correction to an episode detail file."""
        return self._append_to_detail_list(episode_id, "confirmed_corrections", correction)

    def append_state_transition(self, episode_id: str, transition: dict[str, Any]) -> bool:
        return self._append_to_detail_list(episode_id, "state_transitions", transition)

    def append_bottleneck(self, episode_id: str, bottleneck: dict[str, Any]) -> bool:
        return self._append_to_detail_list(episode_id, "bottlenecks", bottleneck)

    def append_visual_query(self, episode_id: str, query: dict[str, Any]) -> bool:
        return self._append_to_detail_list(episode_id, "visual_queries", query)

    def append_visual_interaction(self, episode_id: str, trace: dict[str, Any]) -> bool:
        return self._append_to_detail_list(episode_id, "visual_interactions", trace)

    def append_interaction_consumption(self, episode_id: str, interaction_id: str, consumption: dict[str, Any]) -> bool:
        return self._append_to_detail_list(episode_id, "interaction_consumption",
                                           {"interaction_id": interaction_id, **consumption})

    def read_summary_log(self, limit: int = 100) -> list[dict]:
        if not self._log.exists():
            return []
        lines = self._log.read_text("utf-8").splitlines()
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    def _append_to_detail_list(self, episode_id: str, key: str, item: dict[str, Any]) -> bool:
        detail_path = self._dir / f"{episode_id}.json"
        if not detail_path.exists():
            return False
        try:
            data = json.loads(detail_path.read_text("utf-8"))
            data.setdefault(key, []).append(item)
            detail_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

# 鈹€鈹€ helpers

_TIER_A_B = {"fred", "sec-edgar", "finnhub", "yahoo-finance", "cftc-cot", "investing-calendar"}
_TIER_C = {"reuters-rss", "marketwatch-rss", "cnbc-rss"}
_TIER_E_F = {"fear-greed", "aaii", "naaim", "stocktwits", "reddit", "kol-rss"}


def _infer_tier(sources: list) -> str:
    s = set(sources)
    if s & _TIER_A_B:
        return "A/B"
    if s & _TIER_C:
        return "C"
    if s & _TIER_E_F:
        return "E/F"
    return "unknown"


def _plain_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return data if isinstance(data, dict) else None
    return None


def _reward_score(reward_report: dict[str, Any] | None) -> float | None:
    if not isinstance(reward_report, dict):
        return None
    score = reward_report.get("overall_reward")
    return score if isinstance(score, (int, float)) else None


def _rubric_id(intent_rubric: dict[str, Any] | None) -> str:
    if not isinstance(intent_rubric, dict):
        return ""
    return str(intent_rubric.get("rubric_id", "") or "")


def _rubric_criteria_count(intent_rubric: dict[str, Any] | None) -> int:
    if not isinstance(intent_rubric, dict):
        return 0
    criteria = intent_rubric.get("criteria")
    return len(criteria) if isinstance(criteria, list) else 0


def _rubric_resource_count(intent_rubric: dict[str, Any] | None) -> int:
    context = _rubric_resource_context(intent_rubric)
    resources = context.get("resources")
    return len(resources) if isinstance(resources, list) else 0


def _rubric_strategy_primitive_count(intent_rubric: dict[str, Any] | None) -> int:
    context = _rubric_resource_context(intent_rubric)
    primitives = context.get("strategy_primitives")
    return len(primitives) if isinstance(primitives, list) else 0


def _rubric_resource_context(intent_rubric: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent_rubric, dict):
        return {}
    context = intent_rubric.get("resource_context")
    return context if isinstance(context, dict) else {}


def _new_episode_id() -> str:
    return f"ep-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")



