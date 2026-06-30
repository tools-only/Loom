"""Deterministic helpers for feedback-driven episode repair."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RepairPlan:
    episode_id: str
    question: str
    domain: str
    target_hands: list[str]
    reason: str


def choose_repair_hands(
    episode: dict[str, Any],
    *,
    comment: str = "",
    explicit_hand_id: str = "",
    target_hands: list[str] | None = None,
    max_hands: int = 2,
) -> tuple[list[str], str]:
    """Choose which hand(s) should repair an episode after human feedback."""
    hand_evals = [
        item for item in episode.get("hand_evaluations", [])
        if isinstance(item, dict) and item.get("hand_id")
    ]
    known_hands = [str(item["hand_id"]) for item in hand_evals]

    requested = [h for h in (target_hands or []) if h]
    if explicit_hand_id:
        requested.insert(0, explicit_hand_id)
    requested = _dedupe([h for h in requested if not known_hands or h in known_hands])
    if requested:
        return requested[:max_hands], "explicit feedback target"

    mentioned = _hands_mentioned(comment, known_hands)
    if mentioned:
        return mentioned[:max_hands], "hand mentioned in correction"

    ranked = sorted(
        hand_evals,
        key=lambda item: (
            0 if not item.get("artifact_present", False) else 1,
            -int(item.get("gap_count", 0) or 0),
            int(item.get("claim_count", 0) or 0),
            str(item.get("source_tier", "unknown")),
        ),
    )
    fallback = [str(item["hand_id"]) for item in ranked[:max_hands]]
    if fallback:
        return fallback, "lowest-confidence hand evaluation"
    return [], "no hand evaluations available"


def build_repair_plan(
    episode: dict[str, Any],
    *,
    comment: str,
    explicit_hand_id: str = "",
    target_hands: list[str] | None = None,
    max_hands: int = 2,
) -> RepairPlan:
    target, reason = choose_repair_hands(
        episode,
        comment=comment,
        explicit_hand_id=explicit_hand_id,
        target_hands=target_hands,
        max_hands=max_hands,
    )
    return RepairPlan(
        episode_id=str(episode.get("episode_id", "")),
        question=str(episode.get("question", "")),
        domain=str(episode.get("domain", "general") or "general"),
        target_hands=target,
        reason=reason,
    )


def build_repair_task(
    episode: dict[str, Any],
    *,
    hand_id: str,
    comment: str,
    corrected_stance: str = "",
    intent_delta: dict[str, Any] | None = None,
) -> str:
    """Create the task string sent to the selected hand for correction."""
    brain_eval = episode.get("brain_self_eval", {})
    hand_eval = next(
        (
            item for item in episode.get("hand_evaluations", [])
            if isinstance(item, dict) and item.get("hand_id") == hand_id
        ),
        {},
    )
    lines = [
        "Repair a previous Loom Brain episode using the user's correction.",
        "",
        f"Original question: {episode.get('question', '')}",
        f"Domain: {episode.get('domain', 'general')}",
        f"Previous stance: {brain_eval.get('stance', 'n/a')}",
        f"Previous confidence: {brain_eval.get('confidence', 0.0)}",
        f"Target hand: {hand_id}",
        f"Previous hand evaluation: {hand_eval}",
        "",
        "User correction:",
        comment or "(no free-form correction provided)",
    ]
    if corrected_stance:
        lines.extend(["", f"Corrected stance requested by user: {corrected_stance}"])
    if intent_delta:
        lines.extend([
            "",
            "Structured repair intent:",
            f"Target: {intent_delta.get('target', '')}",
            f"Instruction: {intent_delta.get('instruction', '')}",
            "Affected objects: " + ", ".join(str(item) for item in intent_delta.get("affected_objects", []) or []),
            "Required constraints: " + ", ".join(str(item) for item in intent_delta.get("required_constraints", []) or []),
        ])
    lines.extend([
        "",
        "Return a corrected Loom hand artifact as JSON. Preserve the standard fields:",
        "metadata.confidence, metadata.key_claims, metadata.gaps, narrative, sections, evidence.",
        "Focus only on the target hand's contribution and make changed assumptions explicit.",
    ])
    return "\n".join(lines)


def summarize_repair_for_reply(repair_result: dict[str, Any]) -> str:
    plan = repair_result.get("repair_plan", {})
    artifacts = repair_result.get("artifacts", {})
    hands = ", ".join(plan.get("target_hands", []) or artifacts.keys())
    status = "completed" if repair_result.get("ok") else "failed"
    pieces = [f"Repair {status}"]
    if hands:
        pieces.append(f"hands: {hands}")
    episode_id = repair_result.get("episode_id") or plan.get("episode_id")
    if episode_id:
        pieces.append(f"episode: {episode_id}")
    return " | ".join(pieces)


def _hands_mentioned(comment: str, known_hands: list[str]) -> list[str]:
    text = comment.lower()
    found = []
    for hand in known_hands:
        pattern = r"(?<![a-z0-9_-])" + re.escape(hand.lower()) + r"(?![a-z0-9_-])"
        if re.search(pattern, text):
            found.append(hand)
    return _dedupe(found)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


