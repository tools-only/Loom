"""Brain state projection — single source of truth for assembled Brain state.

Both `plan()` and `decompose()` should build from the same projection so they
reason about the same state view. Historically `_assemble_prompt()` (used by
`plan()`) covered 10/10 sections while `select_state_context()` (used by
`decompose()`) covered only 6/10. This module makes the full 10-section
projection a first-class, content-addressed artifact.

Sections (all 10):
  1.  brain_md            — static role contract text
  2.  strategy_rules      — domain-matched strategy rules
  3.  frameworks          — distilled analytical frameworks
  4.  intent_stream       — recent intent stream formatted for prompt
  5.  intent_wiki         — Intent Wiki activation, formatted for prompt
  6.  policy_plan         — Rewarded Intent Harness policy plan, formatted
  7.  learned_notes       — recent domain-relevant learned notes
  8.  last_synthesis      — last synthesis snapshot (<24h)
  9.  intent_context      — derived intent context (decision frame, etc.)
  10. recent_intents      — tail of recent intent events (structured)

The projection is content-addressed via SHA256 of canonical JSON so callers
can compare projections across plan/decompose without re-running selection.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Projection dataclass ───────────────────────────────────────────────────────

@dataclass
class Projection:
    """A point-in-time, content-addressed Brain state projection."""
    content_id: str          # "sha256:<hex[:16]>"
    state_version: int       # snapshot of BrainState.state_version at build time
    schema_version: str      # "1.0" for now
    sections: dict           # all 10/10 sections by name
    materialized_at: str     # ISO8601 UTC timestamp


# ── Canonical serialization ────────────────────────────────────────────────────

_ISO_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def _normalize_ts_string(s: str) -> str:
    """Normalize an ISO-8601-ish timestamp string for content addressing.

    - Replace 'T' separator with a space
    - Drop trailing 'Z' or timezone offset
    - Strip microseconds
    Non-timestamp strings are returned unchanged.
    """
    m = _ISO_TS_RE.match(s)
    if not m:
        return s
    return f"{m.group(1)} {m.group(2)}"


def _normalize_for_hash(value: Any) -> Any:
    """Recursively normalize string values that look like ISO timestamps."""
    if isinstance(value, str):
        return _normalize_ts_string(value)
    if isinstance(value, dict):
        return {k: _normalize_for_hash(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_for_hash(v) for v in value]
    return value


def canonical_serialize(data: dict) -> bytes:
    """Return deterministic JSON bytes for a dict.

    - sort_keys + tight separators + ASCII-safe escapes
    - Normalizes top-level string values that look like ISO timestamps
      (drops microseconds, normalizes T/Z) so otherwise-equivalent states
      hash to the same content id.
    """
    normalized = _normalize_for_hash(data)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def content_id(data: dict) -> str:
    """Return 'sha256:<first 16 hex chars>' content id for a dict."""
    digest = hashlib.sha256(canonical_serialize(data)).hexdigest()[:16]
    return f"sha256:{digest}"


# ── Serialization helper ───────────────────────────────────────────────────────

def _serialize(value: Any) -> Any:
    """Convert dataclasses to plain dicts; pass-through otherwise.

    Mirrors BrainHarness._serialize so projections stay JSON-friendly.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


# ── Builder ────────────────────────────────────────────────────────────────────

def build_projection(
    harness,
    domain: str,
    question: str,
    *,
    hand_claims: dict[str, list[str]] | None = None,
) -> Projection:
    """Assemble all 10 Brain state sections into a content-addressed Projection.

    Side effects (kept to match existing _assemble_prompt behavior):
      - calls harness.state._reload()
      - sets harness._last_intent_activation
      - sets harness._last_policy_plan
    """
    # Pick up any state edits since last call.
    harness.state._reload()

    root = Path(getattr(harness, "root", "."))

    # ── Section 1: brain.md (role contract) ────────────────────────────────
    brain_md_path = root / "loom" / "brain_harness" / "prompts" / "brain.md"
    brain_md_text = brain_md_path.read_text("utf-8") if brain_md_path.exists() else ""

    # ── Section 2: strategy_rules ──────────────────────────────────────────
    rules = harness.state.query_rules(domain, question)
    strategy_rules = [_serialize(r) for r in rules]

    # ── Section 3: frameworks ──────────────────────────────────────────────
    frameworks = harness.state.query_frameworks(
        domain,
        hand_claims=hand_claims,
        min_confidence="medium",
    )
    frameworks_list = [_serialize(fw) for fw in frameworks]

    # ── Section 4: intent_stream (formatted text tail) ─────────────────────
    intent_stream_text = ""
    if getattr(harness, "_intent_stream", None) is not None:
        intent_stream_text = harness._intent_stream.format_for_prompt(n=5)

    # ── Section 5: intent_wiki activation (formatted text) ─────────────────
    activation = harness.intent_wiki.activate(
        question=question,
        domain=domain,
        context={"hand_claims": hand_claims or {}},
    )
    harness._last_intent_activation = activation
    intent_wiki_text = harness.intent_wiki.format_activation_for_prompt(activation)

    # ── Section 6: policy_plan (Rewarded Intent Harness) ───────────────────
    policy_plan = harness.rewarded_intent_harness.plan(
        activation, domain=domain, question=question
    )
    harness._last_policy_plan = policy_plan
    policy_plan_text = harness.rewarded_intent_harness.format_plan_for_prompt(policy_plan)

    # ── Section 7: learned_notes ───────────────────────────────────────────
    notes = harness.state.query_notes(domain, n=5)
    learned_notes = [_serialize(n) for n in notes]

    # ── Section 8: last_synthesis (<24h) ───────────────────────────────────
    last_synth_text = ""
    ctx_path = root / "brain" / "context" / "last-synthesis.md"
    if ctx_path.exists():
        try:
            if (time.time() - ctx_path.stat().st_mtime) < 86400:
                last_synth_text = ctx_path.read_text("utf-8")
        except OSError:
            last_synth_text = ""

    # ── Section 9: intent_context (derived) ────────────────────────────────
    intent_context: dict = {}
    if getattr(harness, "_intent_stream", None) is not None:
        intent_context = harness._intent_stream.derive_context()

    # ── Section 10: recent_intents (structured tail) ───────────────────────
    recent_intents: list = []
    if getattr(harness, "_intent_stream", None) is not None:
        recent_intents = [_serialize(ev) for ev in harness._intent_stream.tail(5)]

    sections = {
        "brain_md": brain_md_text,
        "strategy_rules": strategy_rules,
        "frameworks": frameworks_list,
        "intent_stream": intent_stream_text,
        "intent_wiki": intent_wiki_text,
        "policy_plan": policy_plan_text,
        "learned_notes": learned_notes,
        "last_synthesis": last_synth_text,
        "intent_context": intent_context,
        "recent_intents": recent_intents,
    }

    # state_version: BrainState may not yet expose a counter (P2 work).
    state_version = int(getattr(harness.state, "get_state_version", lambda: 0)())

    # ISO8601 UTC timestamp with trailing 'Z' (matches contract).
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return Projection(
        content_id=content_id(sections),
        state_version=state_version,
        schema_version="1.0",
        sections=sections,
        materialized_at=now_utc + "Z",
    )


__all__ = [
    "Projection",
    "canonical_serialize",
    "content_id",
    "build_projection",
]
