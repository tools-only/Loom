"""Contextual feedback compilation for the minimal agent harness loop.

This module intentionally stays deterministic in v1. It does not infer a
user's "true intent"; it maps scoped feedback to auditable hypotheses and a
repair-oriented IntentDelta that downstream Brain repair can consume.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScopedFeedback:
    episode_id: str
    raw_signal: str = "feedback"
    comment: str = ""
    object_ref: str = ""
    object_type: str = ""
    ui_selection: str = ""
    anchor_id: str = ""
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ScopedFeedback":
        ui_scope = event.get("ui_scope") if isinstance(event.get("ui_scope"), dict) else {}
        object_ref = str(
            event.get("object_ref")
            or event.get("orchestration_ref")
            or ui_scope.get("object_ref")
            or ""
        )
        object_type = str(event.get("object_type") or _type_from_ref(object_ref))
        return cls(
            episode_id=str(event.get("episode_id", "")),
            raw_signal=str(event.get("raw_signal") or event.get("signal") or event.get("vote") or "feedback"),
            comment=str(event.get("comment") or event.get("note") or ""),
            object_ref=object_ref,
            object_type=object_type,
            ui_selection=str(event.get("ui_selection") or ui_scope.get("selection") or ""),
            anchor_id=str(event.get("anchor_id") or ui_scope.get("anchor_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["feedback_id"] = feedback_id(self)
        return data


@dataclass(frozen=True)
class IntentDelta:
    target: str
    instruction: str
    affected_objects: list[str] = field(default_factory=list)
    required_constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextualIntentAnalysis:
    analysis_id: str
    feedback_id: str
    human_readable_summary: str
    intent_hypotheses: list[dict[str, Any]]
    agent_readable_intent_delta: IntentDelta
    affected_objects: list[str]
    ambiguities: list[str] = field(default_factory=list)
    confidence: str = "low"
    persistence_level: str = "episode_only"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["agent_readable_intent_delta"] = self.agent_readable_intent_delta.to_dict()
        return data


class ContextualIntentCompiler:
    """Compile scoped human feedback into repair-oriented intent deltas."""

    def compile(
        self,
        feedback: ScopedFeedback | dict[str, Any],
        *,
        episode: dict[str, Any] | None = None,
    ) -> ContextualIntentAnalysis:
        fb = feedback if isinstance(feedback, ScopedFeedback) else ScopedFeedback.from_event(feedback)
        episode = episode or {}
        obj_type = fb.object_type or _type_from_ref(fb.object_ref)
        affected = _affected_objects(fb, episode)
        target, instruction, hypotheses, constraints, confidence, ambiguities = _compile_by_scope(
            fb,
            obj_type,
            affected,
        )
        delta = IntentDelta(
            target=target,
            instruction=instruction,
            affected_objects=affected,
            required_constraints=constraints,
        )
        return ContextualIntentAnalysis(
            analysis_id="cia-" + uuid.uuid4().hex[:12],
            feedback_id=feedback_id(fb),
            human_readable_summary=_summary_for(target, obj_type),
            intent_hypotheses=hypotheses,
            agent_readable_intent_delta=delta,
            affected_objects=affected,
            ambiguities=ambiguities,
            confidence=confidence,
            persistence_level="episode_only",
        )


def feedback_id(feedback: ScopedFeedback) -> str:
    seed = "|".join([
        feedback.episode_id,
        feedback.object_ref,
        feedback.raw_signal,
        feedback.comment,
        str(round(feedback.created_at, 3)),
    ])
    return "fb-" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:12]


def _type_from_ref(object_ref: str) -> str:
    if ":" not in object_ref:
        return ""
    return object_ref.split(":", 1)[0]


def _affected_objects(feedback: ScopedFeedback, episode: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if feedback.object_ref:
        refs.append(feedback.object_ref)
    if feedback.anchor_id:
        refs.append(f"anchor:{feedback.anchor_id}")

    hand_artifacts = episode.get("hand_artifacts", {})
    if isinstance(hand_artifacts, dict):
        for artifact_key, artifact in hand_artifacts.items():
            if not isinstance(artifact, dict):
                continue
            meta = artifact.get("metadata", {}) if isinstance(artifact.get("metadata"), dict) else {}
            task_id = str(meta.get("task_id") or artifact_key or "")
            hand_id = str(meta.get("hand_id") or "")
            executor_id = str(meta.get("executor_id") or "")
            key_claims = " ".join(str(item) for item in meta.get("key_claims", []) or [])
            if feedback.object_ref and feedback.object_ref.split(":", 1)[-1] in key_claims:
                if task_id:
                    refs.append(f"task:{task_id}")
                if hand_id:
                    refs.append(f"hand:{hand_id}")
                if executor_id and executor_id != hand_id:
                    refs.append(f"executor:{executor_id}")

    return _dedupe(refs)


def _compile_by_scope(
    feedback: ScopedFeedback,
    object_type: str,
    affected: list[str],
) -> tuple[str, str, list[dict[str, Any]], list[str], str, list[str]]:
    comment = feedback.comment.strip() or "No free-form feedback was provided."
    if object_type == "claim":
        return (
            "claim_revision",
            f"Re-check the scoped claim using the user's feedback: {comment}",
            [
                {"target": "claim_revision", "reason": "feedback is attached to a claim object"},
                {"target": "evidence_check", "reason": "claim-level corrections usually require support verification"},
            ],
            ["verify_supporting_evidence", "preserve_feedback_provenance"],
            "medium",
            [],
        )
    if object_type == "source":
        return (
            "source_preference",
            f"Re-evaluate source fitness for the scoped source and use stronger source support: {comment}",
            [
                {"target": "source_preference", "reason": "feedback is attached to a source object"},
                {"target": "freshness_check", "reason": "source concerns may be trust or recency concerns"},
            ],
            ["cite_source_tier_or_gap", "avoid_unverified_source_upgrade"],
            "medium",
            [],
        )
    if object_type in {"hand", "artifact", "task"}:
        return (
            "task_repair",
            f"Repair only the scoped task or hand contribution using the user's feedback: {comment}",
            [
                {"target": "task_repair", "reason": f"feedback is attached to a {object_type} object"},
                {"target": "rubric_gap", "reason": "hand-level feedback may indicate missing rubric coverage"},
            ],
            ["repair_scoped_artifact_only", "make_changed_assumptions_explicit"],
            "medium",
            [],
        )
    return (
        "episode_diagnosis",
        f"Localize this episode-level feedback before changing any harness state: {comment}",
        [
            {"target": "claim_revision", "reason": "final-answer feedback may point to a bad claim"},
            {"target": "source_preference", "reason": "final-answer feedback may point to weak evidence"},
            {"target": "task_repair", "reason": "final-answer feedback may point to a wrong hand/task"},
        ],
        ["localize_feedback_before_repair"],
        "low",
        ["needs_localization"],
    )


def _summary_for(target: str, object_type: str) -> str:
    labels = {
        "claim_revision": "Feedback is interpreted as a scoped claim correction.",
        "source_preference": "Feedback is interpreted as a scoped source quality concern.",
        "task_repair": "Feedback is interpreted as a scoped task or hand repair request.",
        "episode_diagnosis": "Feedback is broad and should be localized before repair.",
    }
    suffix = f" Scope: {object_type}." if object_type else ""
    return labels.get(target, "Feedback was compiled into a repair constraint.") + suffix


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
