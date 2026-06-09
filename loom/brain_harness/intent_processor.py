"""IntentProcessor + IntentStream — explicit intent extraction from human interactions.

Every human→Brain interaction produces an IntentEvent (structured intent data).
The intent-stream.jsonl is an append-only log and the source of truth for all
cognitive context: no hidden "user model", just a queryable event stream.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class IntentEvent:
    ts: str
    input_type: str        # query | resource_share | strategy_edit | feedback
    raw_input: str         # truncated to 300 chars
    intent: dict           # {goal, motivation, decision_frame, belief_signal, ...}
    anchor_context: dict | None = None
    resource_intent: dict | None = None   # only for resource_share
    session_id: str = ""


# ── IntentStream ───────────────────────────────────────────────────────────────

class IntentStream:
    """Append-only intent event log backed by a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, event: IntentEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def tail(self, n: int = 5) -> list[IntentEvent]:
        """Return the n most recent events, newest first."""
        lines = self.path.read_text("utf-8").splitlines() if self.path.exists() else []
        recent = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ri = d.pop("resource_intent", None)
                recent.append(IntentEvent(**d, resource_intent=ri))
            except (json.JSONDecodeError, TypeError):
                pass
            if len(recent) >= n:
                break
        return recent

    def all(self) -> list[IntentEvent]:
        """Return all events, oldest first."""
        lines = self.path.read_text("utf-8").splitlines() if self.path.exists() else []
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ri = d.pop("resource_intent", None)
                events.append(IntentEvent(**d, resource_intent=ri))
            except (json.JSONDecodeError, TypeError):
                pass
        return events

    def derive_context(self) -> dict:
        """Compute derived views from the full stream (no LLM — pure Python)."""
        events = self.all()
        if not events:
            return {"decision_context": None, "preferences": [], "counts": {}}

        # Decision context = most recent non-empty decision_frame
        decision_context = None
        for ev in reversed(events):
            frame = ev.intent.get("decision_frame", "").strip()
            if frame:
                decision_context = frame
                break

        # Preferences: count what_user_values from resource_share events
        value_counter: Counter = Counter()
        engagement_counter: Counter = Counter()
        author_counter: Counter = Counter()
        anchor_counter: Counter = Counter()
        behavior_counter: Counter = Counter()
        for ev in events:
            behavior = (ev.intent.get("behavior_intent") or "").strip()
            if behavior:
                behavior_counter[behavior] += 1
            if ev.anchor_context:
                anchor_id = (ev.anchor_context.get("anchor_id") or "").strip()
                if anchor_id:
                    anchor_counter[anchor_id] += 1
            if ev.input_type == "resource_share" and ev.resource_intent:
                ri = ev.resource_intent
                if ri.get("what_user_values"):
                    value_counter[ri["what_user_values"]] += 1
                if ri.get("engagement_type"):
                    engagement_counter[ri["engagement_type"]] += 1
                if ri.get("author_signal"):
                    author_counter[ri["author_signal"]] += 1

        total_resources = max(1, sum(value_counter.values()) or 1)
        preferences = [
            {
                "dimension": "analytical focus",
                "value": val,
                "count": cnt,
                "strength": round(cnt / total_resources, 2),
            }
            for val, cnt in value_counter.most_common(5)
        ]

        # Counts by type
        type_counter: Counter = Counter(ev.input_type for ev in events)

        return {
            "decision_context": decision_context,
            "preferences": preferences,
            "engagement_distribution": dict(engagement_counter.most_common()),
            "anchor_focus": dict(anchor_counter.most_common(10)),
            "behavior_distribution": dict(behavior_counter.most_common(10)),
            "counts": dict(type_counter),
            "total": len(events),
        }

    def format_for_prompt(self, n: int = 5) -> str:
        """Format recent events as text for LLM prompt injection."""
        events = self.tail(n)
        if not events:
            return ""
        lines: list[str] = []
        for ev in reversed(events):  # oldest first for context
            ts_short = ev.ts[:16]
            ri = ev.resource_intent
            intent_parts = [
                f"  goal: {ev.intent.get('goal', '')}",
                f"  motivation: {ev.intent.get('motivation', '')}",
                f"  decision_frame: {ev.intent.get('decision_frame', '')}",
                f"  behavior_intent: {ev.intent.get('behavior_intent', '')}",
                f"  analytical_direction: {ev.intent.get('analytical_direction', '')}",
                f"  content_signal: {ev.intent.get('content_signal', '')}",
            ]
            if ev.anchor_context:
                intent_parts.insert(
                    0,
                    "  anchor: "
                    + f"{ev.anchor_context.get('anchor_id', '')} "
                    + f"op={ev.anchor_context.get('anchor_op', '')}",
                )
            if ri:
                intent_parts.append(f"  engagement: {ri.get('engagement_type', '')} | values: {ri.get('what_user_values', '')}")
            lines.append(
                f"[{ts_short}] [{ev.input_type}] {ev.raw_input[:120]!r}\n"
                + "\n".join(intent_parts)
            )
        return "\n\n".join(lines)


# ── IntentProcessor ────────────────────────────────────────────────────────────

class IntentProcessor:
    """Parse structured intent from any human→Brain interaction."""

    def __init__(self, project_root: Path, client, model: str) -> None:
        self.root = Path(project_root)
        self._client = client
        self._model = model
        self._system = self._load_system()

    def _load_system(self) -> str:
        p = self.root / "loom" / "brain_harness" / "prompts" / "intent.md"
        return p.read_text("utf-8") if p.exists() else "Extract structured intent. Output JSON only."

    async def parse(
        self,
        input_type: str,
        raw_input: str,
        extra_context: str = "",
        session_id: str = "",
        anchor_context: dict | None = None,
    ) -> IntentEvent:
        """Parse a human interaction into a structured IntentEvent.

        Runs concurrently with synthesis (fire-and-forget pattern).
        Uses a fast model + low token budget to keep latency minimal.
        """
        user_msg = f"input_type: {input_type}\nraw_input: {raw_input[:800]}"
        if extra_context:
            user_msg += f"\nextra_context: {extra_context[:400]}"
        if anchor_context:
            user_msg += "\n" + "\n".join(
                [
                    f"anchor_op: {str(anchor_context.get('anchor_op', ''))[:80]}",
                    f"anchor_id: {str(anchor_context.get('anchor_id', ''))[:160]}",
                    f"anchor_kind: {str(anchor_context.get('anchor_kind', ''))[:80]}",
                    f"anchor_content: {str(anchor_context.get('anchor_content', ''))[:1600]}",
                ]
            )

        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=500,
                system=self._system,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            intent_dict = self._parse_json(text) or {
                "goal": raw_input[:80],
                "motivation": "",
                "decision_frame": "",
                "belief_signal": "",
                "behavior_intent": "",
                "analytical_direction": "",
                "content_signal": "",
            }
        except Exception:
            intent_dict = {
                "goal": raw_input[:80],
                "motivation": "",
                "decision_frame": "",
                "belief_signal": "",
                "behavior_intent": "",
                "analytical_direction": "",
                "content_signal": "",
            }

        # Separate resource_intent fields
        resource_intent = None
        if input_type == "resource_share":
            resource_keys = {"engagement_type", "what_user_values", "author_signal"}
            resource_intent = {k: intent_dict.pop(k, "") for k in resource_keys}
        elif input_type == "strategy_edit":
            # change_signal stays in intent dict
            pass

        return IntentEvent(
            ts=datetime.now().isoformat(),
            input_type=input_type,
            raw_input=raw_input[:300],
            intent=intent_dict,
            anchor_context=anchor_context,
            resource_intent=resource_intent,
            session_id=session_id,
        )

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        stripped = text.strip()
        try:
            d = json.loads(stripped)
            if isinstance(d, dict):
                return d
        except (json.JSONDecodeError, ValueError):
            pass
        for fence in ("```json", "```"):
            if fence in stripped:
                try:
                    start = stripped.index(fence) + len(fence)
                    end = stripped.index("```", start)
                    d = json.loads(stripped[start:end].strip())
                    if isinstance(d, dict):
                        return d
                except (ValueError, json.JSONDecodeError):
                    pass
        return None
