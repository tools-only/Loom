"""Human intent envelope normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_OPS = {
    "ask",
    "refine",
    "expand",
    "shorten",
    "longer",
    "edit",
    "annotate",
    "branch",
    "review",
    "restructure",
    "lock",
}


@dataclass(frozen=True)
class HumanIntentEnvelope:
    op: str
    event_id: str | None = None
    workspace_id: str | None = None
    file_id: str | None = None
    target_anchor: str | None = None
    instruction: str = ""
    selection: dict[str, Any] | None = None
    domain: str | None = None


def normalize_human_intent_envelope(raw: dict[str, Any]) -> HumanIntentEnvelope:
    op = raw.get("op")
    if not op:
        intent = raw.get("intent")
        if isinstance(intent, dict):
            op = intent.get("op")
    if not op:
        raise ValueError("human intent envelope requires op")
    if op not in SUPPORTED_OPS:
        raise ValueError(f"unsupported human intent op: {op}")

    return HumanIntentEnvelope(
        event_id=raw.get("eventId") or raw.get("event_id"),
        workspace_id=raw.get("workspaceId") or raw.get("workspace_id"),
        file_id=raw.get("fileId") or raw.get("file_id"),
        target_anchor=raw.get("targetAnchor") or raw.get("target_anchor"),
        op=op,
        instruction=raw.get("instruction") or "",
        selection=raw.get("selection"),
        domain=raw.get("domain"),
    )
