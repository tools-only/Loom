"""Intent Wiki: long-lived user intent memory and activation graph.

The event stream is evidence. The wiki is the durable, domain-agnostic layer
that turns repeated behavior into reusable intent logic.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .intent_processor import IntentEvent


INTENT_ZONES = {
    "content_requirements": "What generated content should include or emphasize.",
    "decision_style": "How the user weighs tradeoffs, uncertainty, and decisions.",
    "workflow_preferences": "How the user wants work organized across steps.",
    "source_preferences": "What evidence, resources, or authors the user tends to value.",
    "object_behavior": "How the user acts on anchors, cards, sections, or other objects.",
    "risk_sensitivity": "How the user wants counterarguments, failure modes, and uncertainty handled.",
    "personal_style": "Preferred style, granularity, and presentation shape.",
    "domain_principles": "Domain-specific long-lived principles supplied by a domain pack or inferred from usage.",
}


@dataclass
class IntentNode:
    intent_id: str
    zone: str
    label: str
    principle: str
    status: str = "active"
    confidence: float = 0.35
    evidence_count: int = 0
    activation_hints: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_evidence_ts: str = ""


@dataclass
class IntentActivation:
    ts: str
    run_id: str
    question: str
    domain: str
    active_intents: list[dict[str, Any]]
    inactive_intents: list[dict[str, Any]]


class IntentWiki:
    """Structured user intent library with deterministic activation.

    The first version intentionally uses explicit rules over hidden state. LLM
    extraction can improve labels later, but the maintenance loop remains local
    and inspectable.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "brain" / "intent_wiki"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.intents_path = self.dir / "intents.json"
        self.evidence_path = self.dir / "evidence.jsonl"
        self.activations_path = self.dir / "activations.jsonl"
        if not self.intents_path.exists():
            self._write_nodes([])

    def all_nodes(self) -> list[IntentNode]:
        try:
            data = json.loads(self.intents_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"intents": []}
        nodes: list[IntentNode] = []
        for item in data.get("intents", []):
            try:
                nodes.append(IntentNode(**item))
            except TypeError:
                continue
        return nodes

    def ingest_event(self, event: IntentEvent) -> list[IntentNode]:
        """Update long-lived intents from one analyzed behavior event."""
        candidates = self._candidates_from_event(event)
        if not candidates:
            return []

        nodes_by_id = {node.intent_id: node for node in self.all_nodes()}
        changed: list[IntentNode] = []
        now = datetime.now().isoformat()

        for candidate in candidates:
            intent_id = candidate["intent_id"]
            node = nodes_by_id.get(intent_id)
            if node is None:
                node = IntentNode(
                    intent_id=intent_id,
                    zone=candidate["zone"],
                    label=candidate["label"],
                    principle=candidate["principle"],
                    activation_hints=candidate.get("activation_hints", {}),
                )
                nodes_by_id[intent_id] = node
            else:
                node.label = candidate["label"] or node.label
                node.principle = candidate["principle"] or node.principle
                node.activation_hints = self._merge_hints(node.activation_hints, candidate.get("activation_hints", {}))

            node.evidence_count += 1
            node.confidence = min(0.95, round(node.confidence + 0.08, 2))
            node.updated_at = now
            node.last_evidence_ts = event.ts
            changed.append(node)

            self._append_jsonl(self.evidence_path, {
                "ts": now,
                "intent_id": node.intent_id,
                "event_ts": event.ts,
                "input_type": event.input_type,
                "raw_input": event.raw_input,
                "anchor_context": event.anchor_context,
                "intent": event.intent,
                "reason": candidate.get("reason", ""),
            })

        self._write_nodes(sorted(nodes_by_id.values(), key=lambda n: (n.zone, n.intent_id)))
        return changed

    def activate(self, question: str, domain: str, context: dict | None = None, limit: int = 8) -> IntentActivation:
        """Select durable intents that should influence this generation."""
        context = context or {}
        q = question.lower()
        domain_l = (domain or "general").lower()
        active: list[dict[str, Any]] = []
        inactive: list[dict[str, Any]] = []

        for node in self.all_nodes():
            if node.status != "active":
                inactive.append(self._activation_item(node, 0.0, "disabled"))
                continue
            score, reason = self._activation_score(node, q, domain_l, context)
            item = self._activation_item(node, score, reason)
            if score >= 0.25:
                active.append(item)
            else:
                inactive.append(item)

        active.sort(key=lambda item: item["score"], reverse=True)
        inactive.sort(key=lambda item: item["score"], reverse=True)
        activation = IntentActivation(
            ts=datetime.now().isoformat(),
            run_id="run_" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            question=question,
            domain=domain or "general",
            active_intents=active[:limit],
            inactive_intents=inactive,
        )
        self._append_jsonl(self.activations_path, asdict(activation))
        return activation

    def latest_activation(self) -> dict[str, Any] | None:
        if not self.activations_path.exists():
            return None
        lines = [ln for ln in self.activations_path.read_text("utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return None

    def graph(self) -> dict[str, Any]:
        latest = self.latest_activation()
        active_ids = {item.get("intent_id") for item in (latest or {}).get("active_intents", [])}
        nodes = []
        for node in self.all_nodes():
            item = asdict(node)
            item["is_active"] = node.intent_id in active_ids
            nodes.append(item)
        return {
            "zones": [{"id": zone, "label": zone.replace("_", " ").title(), "description": desc}
                      for zone, desc in INTENT_ZONES.items()],
            "nodes": nodes,
            "latest_activation": latest,
        }

    def format_activation_for_prompt(self, activation: IntentActivation) -> str:
        if not activation.active_intents:
            return ""
        lines = [
            "The following long-lived user intents are active for this generation.",
            "Satisfy them unless they conflict with the explicit user request.",
        ]
        for item in activation.active_intents:
            lines.append(
                f"- [{item['zone']}] {item['label']} "
                f"(id={item['intent_id']}, score={item['score']:.2f}): {item['principle']}"
            )
        return "\n".join(lines)

    def _candidates_from_event(self, event: IntentEvent) -> list[dict[str, Any]]:
        intent = event.intent or {}
        anchor = event.anchor_context or {}
        candidates: list[dict[str, Any]] = []
        text = " ".join(str(intent.get(k, "")) for k in (
            "goal", "motivation", "decision_frame", "belief_signal",
            "behavior_intent", "analytical_direction", "content_signal",
        ))
        raw = event.raw_input or ""

        if intent.get("content_signal") or self._mentions_freshness(text + " " + raw):
            label = self._compact_label(intent.get("content_signal") or intent.get("analytical_direction") or raw)
            candidates.append(self._candidate(
                "content_requirements", label,
                "Generated outputs should preserve this recurring content requirement when relevant.",
                event, reason="content signal or freshness requirement",
            ))

        behavior = (intent.get("behavior_intent") or "").strip()
        if behavior:
            candidates.append(self._candidate(
                "object_behavior", f"User often intends to {behavior}",
                "When the user acts on an object, infer the operation-level intent instead of treating it as a one-off edit.",
                event, reason="behavior intent",
            ))

        if event.resource_intent:
            value = event.resource_intent.get("what_user_values") or event.resource_intent.get("author_signal") or raw
            candidates.append(self._candidate(
                "source_preferences", self._compact_label(value),
                "Prefer evidence and resources matching this recurring source/value preference when relevant.",
                event, reason="resource intent",
            ))

        direction = intent.get("analytical_direction") or ""
        if self._mentions_risk(direction + " " + text):
            candidates.append(self._candidate(
                "risk_sensitivity", self._compact_label(direction or raw),
                "Surface uncertainty, counterarguments, reversal conditions, and downside cases when this intent is relevant.",
                event, reason="risk-sensitive analytical direction",
            ))

        if anchor.get("anchor_id") or anchor.get("anchor_op"):
            candidates.append(self._candidate(
                "workflow_preferences",
                f"Respect object-scoped intent for {anchor.get('anchor_op') or 'operations'}",
                "Use the target object and operation as part of task interpretation, not merely the user's text.",
                event, reason="anchor-bound behavior",
            ))

        return candidates

    def _candidate(self, zone: str, label: str, principle: str, event: IntentEvent, reason: str) -> dict[str, Any]:
        label = self._compact_label(label)
        intent_id = f"{zone}.{self._slug(label)}"
        anchor = event.anchor_context or {}
        return {
            "intent_id": intent_id,
            "zone": zone,
            "label": label,
            "principle": principle,
            "reason": reason,
            "activation_hints": {
                "keywords": self._keywords(" ".join([
                    label,
                    event.raw_input,
                    json.dumps(event.intent, ensure_ascii=False),
                    str(anchor.get("anchor_content", ""))[:500],
                ])),
                "anchor_ops": [anchor.get("anchor_op")] if anchor.get("anchor_op") else [],
                "object_kinds": [anchor.get("anchor_kind")] if anchor.get("anchor_kind") else [],
                "requires_fresh_context": self._mentions_freshness(label + " " + event.raw_input),
            },
        }

    def _activation_score(self, node: IntentNode, question: str, domain: str, context: dict) -> tuple[float, str]:
        hints = node.activation_hints or {}
        keywords = set(hints.get("keywords", []))
        score = 0.0
        reasons: list[str] = []

        if node.status == "active":
            score += 0.1
        if node.evidence_count >= 2:
            score += 0.1
            reasons.append("repeated evidence")
        if node.confidence >= 0.55:
            score += 0.1
            reasons.append("high confidence")

        matched = sorted(k for k in keywords if k and k in question)
        if matched:
            score += min(0.45, 0.12 * len(matched))
            reasons.append("keyword match: " + ", ".join(matched[:4]))

        if hints.get("requires_fresh_context") and self._context_has_freshness(question, context):
            score += 0.25
            reasons.append("fresh context needed")

        if domain and domain != "general":
            score += 0.05
        return min(score, 1.0), "; ".join(reasons) or "background preference"

    @staticmethod
    def _activation_item(node: IntentNode, score: float, reason: str) -> dict[str, Any]:
        return {
            "intent_id": node.intent_id,
            "zone": node.zone,
            "label": node.label,
            "principle": node.principle,
            "score": round(score, 2),
            "reason": reason,
            "confidence": node.confidence,
            "evidence_count": node.evidence_count,
        }

    @staticmethod
    def _compact_label(text: str, max_len: int = 80) -> str:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return "Capture recurring user intent"
        return text[:max_len].rstrip()

    @staticmethod
    def _slug(text: str) -> str:
        words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
        slug = "_".join(words[:8]) or "intent"
        return slug[:80]

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]{2,}", text.lower())
        stop = {"the", "and", "for", "with", "this", "that", "user", "intent", "analysis"}
        out: list[str] = []
        for word in words:
            if word in stop or word in out:
                continue
            out.append(word)
            if len(out) >= 12:
                break
        return out

    @staticmethod
    def _mentions_freshness(text: str) -> bool:
        t = text.lower()
        return any(k in t for k in (
            "recent", "latest", "news", "hot", "event", "catalyst", "today",
            "近期", "最新", "新闻", "热点", "事件", "催化",
        ))

    @staticmethod
    def _mentions_risk(text: str) -> bool:
        t = text.lower()
        return any(k in t for k in (
            "risk", "downside", "uncertain", "reversal", "bearish", "challenge",
            "风险", "下行", "不确定", "反转", "反例", "挑战",
        ))

    @staticmethod
    def _context_has_freshness(question: str, context: dict) -> bool:
        joined = question + " " + json.dumps(context, ensure_ascii=False)
        return IntentWiki._mentions_freshness(joined)

    @staticmethod
    def _merge_hints(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        merged = dict(old or {})
        for key, value in (new or {}).items():
            if isinstance(value, list):
                existing = merged.get(key, [])
                merged[key] = list(dict.fromkeys([*existing, *value]))
            elif isinstance(value, bool):
                merged[key] = bool(merged.get(key)) or value
            else:
                merged[key] = value
        return merged

    def _write_nodes(self, nodes: list[IntentNode]) -> None:
        self.intents_path.write_text(
            json.dumps({"version": 1, "zones": INTENT_ZONES, "intents": [asdict(n) for n in nodes]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
