"""BrainHarness — Brain agent harness with programmatic state selection.

Structural difference from hand harness:
  Hand harness: _assemble_prompt() bulk-loads .md files; LLM decides relevance.
  Brain harness: _assemble_prompt(domain, question) calls BrainState.query_rules()
                 first; only matched rules reach the LLM. The selection layer is
                 Python code in the Brain process, not context fed to the LLM.

Prompt layers:
  1. brain.md                  — static role contract (loaded wholesale, fine)
  2. brain-coordination SKILL  — static meta-skill index (loaded wholesale, fine)
  3. query_rules(domain)       — DYNAMIC: programmatic rule selection from BrainState
  4. query_frameworks(domain)  — DYNAMIC: distilled analytical frameworks
  5. intent_stream.tail(5)     — DYNAMIC: recent human intent signals (the WHY)
  6. query_notes(domain)       — DYNAMIC: recent domain-relevant learned notes
  7. last-synthesis.md (<24h)  — fresh context snapshot
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .intent_processor import IntentStream
    from .intent_wiki import IntentActivation
    from .intent_harness import PolicyPlan, RewardReport

from .state import BrainState
from .intent_wiki import IntentWiki
from .intent_harness import RewardedIntentHarness


def _parse_json(text: str) -> dict | None:
    """Extract a JSON object from text, handling optional markdown fences."""
    stripped = text.strip()
    for attempt in (stripped, None):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        break
    for fence in ("```json", "```"):
        try:
            if fence in stripped:
                start = stripped.index(fence) + len(fence)
                end = stripped.index("```", start)
                data = json.loads(stripped[start:end].strip())
                if isinstance(data, dict):
                    return data
        except (ValueError, json.JSONDecodeError):
            pass
    return None


class BrainHarness:
    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root)
        self.state = BrainState(self.root)  # structured queryable state
        self._intent_stream: IntentStream | None = None  # injected by brain.py at startup
        self.intent_wiki = IntentWiki(self.root)
        self._last_intent_activation: IntentActivation | None = None
        self.rewarded_intent_harness = RewardedIntentHarness(self.root)
        self._last_policy_plan: PolicyPlan | None = None
        self._last_reward_report: RewardReport | None = None

    # ── Prompt assembly ────────────────────────────────────────────────────────

    def _assemble_prompt_with_claims(
        self,
        domain: str,
        question: str,
        hand_claims: dict[str, list[str]],
    ) -> str:
        """Build prompt with full hand context for framework variable-overlap gate."""
        return self._assemble_prompt(domain=domain, question=question, hand_claims=hand_claims)

    def _assemble_prompt(
        self,
        domain: str = "general",
        question: str = "",
        hand_claims: dict[str, list[str]] | None = None,
    ) -> str:
        """Build synthesis system prompt.

        Static layers (role contract + skill index) are loaded wholesale.
        Dynamic layers (strategy rules, frameworks, learned notes) are selected
        programmatically by BrainState before reaching the LLM.
        """
        parts: list[str] = []

        # ── Static: role contract (identity, not data) ─────────────────────
        brain_md = self.root / "loom" / "brain_harness" / "prompts" / "brain.md"
        if brain_md.exists():
            parts.append(brain_md.read_text("utf-8"))

        # ── Static: meta-skill index (coordination rules, not user data) ───
        skill_md = self.root / "skills" / "brain-coordination" / "SKILL.md"
        if skill_md.exists():
            parts.append("\n\n---\n\n# Brain Coordination Skill\n\n")
            parts.append(skill_md.read_text("utf-8"))

        # ── Dynamic: strategy rules (programmatic selection, NOT bulk-load) ─
        self.state._reload()  # pick up any edits since last call
        relevant_rules = self.state.query_rules(domain, question)
        if relevant_rules:
            rules_text = self.state.format_rules(relevant_rules)
            weight_text = json.dumps(self.state.weighting, ensure_ascii=False) if self.state.weighting else "{}"
            parts.append(
                f"\n\n---\n\n## Strategy rules (domain={domain}, selected by Brain process)\n\n"
                f"{rules_text}\n\n"
                f"Weighting: {weight_text}\n"
                f"Style: {self.state.default_style}"
            )
        elif not self.state.is_empty():
            # State loaded but no domain-specific rules — include weighting only
            parts.append(
                f"\n\n---\n\n## Strategy (domain={domain}, no domain-specific rules)\n\n"
                f"Weighting: {json.dumps(self.state.weighting, ensure_ascii=False)}\n"
                f"Style: {self.state.default_style}"
            )

        # ── Dynamic: analytical frameworks (distilled from resources) ──────
        # hand_claims is None here (prompt built before synthesis) — uses domain+confidence
        # gates only. _assemble_prompt_with_claims() passes real claims for full filter.
        frameworks = self.state.query_frameworks(domain, hand_claims=hand_claims, min_confidence="medium")
        if frameworks:
            fw_text = self.state.format_frameworks(frameworks)
            parts.append(
                f"\n\n---\n\n## Analytical frameworks (domain={domain}, distilled)\n\n{fw_text}"
            )

        # ── Dynamic: recent intent stream (the WHY behind human interactions) ─
        if self._intent_stream is not None:
            intent_text = self._intent_stream.format_for_prompt(n=5)
            if intent_text:
                parts.append(
                    "\n\n---\n\n## Recent intent stream (what the user is actually working toward)\n\n"
                    "Use this to address the underlying motivation, not just the surface question.\n\n"
                    + intent_text
                )

        # ── Dynamic: durable intent wiki activation ────────────────────────
        activation = self.intent_wiki.activate(
            question=question,
            domain=domain,
            context={"hand_claims": hand_claims or {}},
        )
        self._last_intent_activation = activation
        activation_text = self.intent_wiki.format_activation_for_prompt(activation)
        if activation_text:
            parts.append(
                "\n\n---\n\n## Active long-lived user intents (Intent Wiki)\n\n"
                + activation_text
            )

        # ── Dynamic: rewarded policy plan over active intents ───────────────
        policy_plan = self.rewarded_intent_harness.plan(activation, domain=domain, question=question)
        self._last_policy_plan = policy_plan
        policy_text = self.rewarded_intent_harness.format_plan_for_prompt(policy_plan)
        if policy_text:
            parts.append(
                "\n\n---\n\n## Selected intent policies (Rewarded Intent Harness)\n\n"
                + policy_text
            )

        # ── Dynamic: learned notes (recent domain-relevant, not full file) ──
        notes = self.state.query_notes(domain, n=5)
        if notes:
            notes_text = self.state.format_notes(notes)
            parts.append(f"\n\n---\n\n## Learned notes (domain={domain}, recent)\n\n{notes_text}")

        # ── Context: last synthesis snapshot (< 24h) ────────────────────────
        ctx = self.root / "brain" / "context" / "last-synthesis.md"
        if ctx.exists() and (time.time() - ctx.stat().st_mtime) < 86400:
            parts.append(
                f"\n\n---\n\n## Last synthesis (< 24h)\n\n{ctx.read_text('utf-8')}"
            )

        return "".join(parts)

    # ── State helpers ──────────────────────────────────────────────────────────

    def cold_start(self) -> bool:
        """True when Brain.state has no strategy rules — drives UI cold-start notice."""
        self.state._reload()
        return self.state.is_empty()

    def select_state_context(
        self,
        domain: str,
        question: str,
        context: dict | None = None,
    ) -> dict:
        """Programmatically select Brain-side state before hand dispatch."""
        self.state._reload()
        rules = self.state.query_rules(domain, question)
        frameworks = self.state.query_frameworks(domain, hand_claims=None, min_confidence="medium")
        notes = self.state.query_notes(domain, n=5)
        intent_context = {}
        recent_intents: list[dict] = []
        if self._intent_stream is not None:
            intent_context = self._intent_stream.derive_context()
            recent_intents = [self._serialize(ev) for ev in self._intent_stream.tail(5)]
        return {
            "domain": domain,
            "strategy_rules": [self._serialize(rule) for rule in rules],
            "frameworks": [self._serialize(framework) for framework in frameworks],
            "learned_notes": [self._serialize(note) for note in notes],
            "intent_context": intent_context,
            "recent_intents": recent_intents,
            "request_context": context or {},
        }

    def compose_presentation(
        self,
        *,
        question: str,
        synthesis: dict,
        hand_artifacts: dict[str, dict],
        workflow_decision: dict,
        presentation_spec: dict,
    ) -> dict:
        """Brain-owned final content hierarchy for the user-facing UI."""
        cards: list[dict] = []
        detail_panels: dict[str, dict] = {}
        quality_gaps: list[str] = []

        for hand_id in workflow_decision.get("hands", list(hand_artifacts.keys())):
            artifact = hand_artifacts.get(hand_id, {})
            meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
            hand_spec = presentation_spec.get("hand_specs", {}).get(hand_id, {})
            claims = list(meta.get("key_claims", []) or [])
            gaps = list(meta.get("gaps", []) or [])
            sections = self._normalize_sections(artifact, claims, gaps)
            evidence = list(artifact.get("evidence", []) or []) if isinstance(artifact, dict) else []
            source_notes = list(meta.get("source_notes", []) or [])
            layers = self._compose_detail_layers(
                schema=presentation_spec.get("ui_contract", {})
                .get("detail_layer", {})
                .get("card_detail_schema", []),
                hand_id=hand_id,
                artifact=artifact,
                synthesis=synthesis,
                workflow_decision=workflow_decision,
                claims=claims,
                sections=sections,
                evidence=evidence,
                source_notes=source_notes,
                gaps=gaps,
            )

            if len(sections) < 4:
                quality_gaps.append(f"{hand_id}: fewer than 4 detail sections available")
            if not evidence and claims:
                quality_gaps.append(f"{hand_id}: claims exist but evidence rows are missing")

            cards.append({
                "hand_id": hand_id,
                "title": self._hand_title(hand_id),
                "visible_role": hand_spec.get("visible_role", ""),
                "visible_summary": artifact.get("narrative", "") if isinstance(artifact, dict) else "",
                "confidence": meta.get("confidence", 0.0),
                "detail_ref": hand_id,
            })
            detail_panels[hand_id] = {
                "hand_id": hand_id,
                "title": self._hand_title(hand_id),
                "sections": sections,
                "layers": layers,
                "evidence": evidence,
                "source_notes": source_notes,
                "gaps": gaps,
                "brain_requirements": hand_spec,
            }

        overview = {
            "question": question,
            "domain": workflow_decision.get("domain", "general"),
            "mode": workflow_decision.get("mode", "dynamic"),
            "stance": synthesis.get("stance", "n/a") if synthesis else "n/a",
            "confidence": synthesis.get("confidence", 0.0) if synthesis else 0.0,
            "key_drivers": synthesis.get("key_drivers", []) if synthesis else [],
            "reversal_condition": synthesis.get("reversal_condition", "") if synthesis else "",
            "clarifying_question": synthesis.get("clarifying_question") if synthesis else None,
        }
        return {
            "version": presentation_spec.get("version", "brain.presentation.v1"),
            "overview": overview,
            "cards": cards,
            "detail_panels": detail_panels,
            "quality_gaps": quality_gaps,
            "state_context": presentation_spec.get("state_context", {}),
            "ui_contract": presentation_spec.get("ui_contract", {}),
        }

    def write_last_synthesis(self, question: str, workflow: dict, synthesis: dict) -> None:
        path = self.root / "brain" / "context" / "last-synthesis.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        drivers = "\n".join(
            f"- [{d.get('hand', '?')}] {d.get('rule', '?')} → {d.get('claim', '?')}"
            for d in synthesis.get("key_drivers", [])
        )
        path.write_text(
            f"# Last synthesis — {datetime.now().isoformat()}\n\n"
            f"**Question:** {question}\n\n"
            f"**Domain:** {workflow.get('domain')}  **Mode:** {workflow.get('mode')}\n\n"
            f"**Stance:** {synthesis.get('stance')}  "
            f"**Confidence:** {synthesis.get('confidence')}\n\n"
            f"**Key drivers:**\n{drivers}\n\n"
            f"**Reversal:** {synthesis.get('reversal_condition')}\n",
            encoding="utf-8",
        )

    @staticmethod
    def _serialize(value):
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return [BrainHarness._serialize(item) for item in value]
        return value

    @staticmethod
    def _hand_title(hand_id: str) -> str:
        return {
            "market": "Market",
            "sentiment": "Sentiment",
            "target": "Targets",
            "position": "Position",
        }.get(hand_id, hand_id.title())

    @staticmethod
    def _normalize_sections(artifact: dict, claims: list[str], gaps: list[str]) -> list[dict]:
        sections = list(artifact.get("sections", []) or []) if isinstance(artifact, dict) else []
        normalized = [sec for sec in sections if isinstance(sec, dict)]
        existing_ids = {str(sec.get("id", "")) for sec in normalized}
        if claims and "evidence" not in existing_ids:
            normalized.append({
                "id": "evidence",
                "title": "Evidence and claims",
                "summary": "Brain promoted hand key claims into the detail layer.",
                "bullets": claims,
            })
        if gaps and "gaps" not in existing_ids:
            normalized.append({
                "id": "gaps",
                "title": "Coverage gaps",
                "summary": "Limits that should remain visible in drill-down.",
                "bullets": gaps,
            })
        if not normalized:
            narrative = artifact.get("narrative", "") if isinstance(artifact, dict) else ""
            normalized.append({
                "id": "summary",
                "title": "Summary",
                "summary": narrative or "No structured detail returned.",
                "bullets": claims or gaps or [narrative or "No expandable detail available."],
            })
        return normalized

    @staticmethod
    def _compose_detail_layers(
        *,
        schema: list[dict],
        hand_id: str,
        artifact: dict,
        synthesis: dict,
        workflow_decision: dict,
        claims: list[str],
        sections: list[dict],
        evidence: list[dict],
        source_notes: list[dict],
        gaps: list[str],
    ) -> list[dict]:
        if not schema:
            schema = [
                {"id": "judgment", "title": "Judgment"},
                {"id": "drivers", "title": "Drivers"},
                {"id": "evidence", "title": "Evidence"},
                {"id": "implications", "title": "Implications"},
                {"id": "gaps", "title": "Gaps"},
                {"id": "watchlist", "title": "Watchlist"},
            ]
        section_text = BrainHarness._section_lookup(sections)
        layers: list[dict] = []
        for item in schema:
            layer_id = item.get("id", "")
            title = item.get("title", layer_id.title())
            layers.append({
                "id": layer_id,
                "title": title,
                "summary": BrainHarness._layer_summary(
                    layer_id=layer_id,
                    hand_id=hand_id,
                    artifact=artifact,
                    synthesis=synthesis,
                    workflow_decision=workflow_decision,
                    section_text=section_text,
                    gaps=gaps,
                ),
                "items": BrainHarness._layer_items(
                    layer_id=layer_id,
                    claims=claims,
                    evidence=evidence,
                    source_notes=source_notes,
                    gaps=gaps,
                    sections=sections,
                    synthesis=synthesis,
                ),
                "provenance": BrainHarness._layer_provenance(
                    layer_id=layer_id,
                    evidence=evidence,
                    source_notes=source_notes,
                    claims=claims,
                    sections=sections,
                    synthesis=synthesis,
                    gaps=gaps,
                ),
                "schema": item,
            })
        return layers

    @staticmethod
    def _section_lookup(sections: list[dict]) -> dict[str, dict]:
        lookup: dict[str, dict] = {}
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_id = str(sec.get("id", "")).lower()
            title = str(sec.get("title", "")).lower()
            if sec_id:
                lookup[sec_id] = sec
            if title:
                lookup[title] = sec
        return lookup

    @staticmethod
    def _layer_summary(
        *,
        layer_id: str,
        hand_id: str,
        artifact: dict,
        synthesis: dict,
        workflow_decision: dict,
        section_text: dict[str, dict],
        gaps: list[str],
    ) -> str:
        narrative = artifact.get("narrative", "") if isinstance(artifact, dict) else ""
        if layer_id == "judgment":
            return narrative or f"{hand_id} did not return a visible judgment."
        if layer_id == "drivers":
            sec = section_text.get("drivers") or section_text.get("analysis") or section_text.get("summary")
            return sec.get("summary", "") if sec else "Brain grouped the strongest available claims as drivers."
        if layer_id == "evidence":
            return "Traceable support rows and source notes backing the card judgment."
        if layer_id == "implications":
            stance = synthesis.get("stance", "n/a") if synthesis else "n/a"
            domain = workflow_decision.get("domain", "general")
            return f"For {domain}, this card contributes to a {stance} stance and its next decision checks."
        if layer_id == "gaps":
            return "No explicit gaps were returned." if not gaps else "Known limits that weaken or qualify the judgment."
        if layer_id == "watchlist":
            return synthesis.get("reversal_condition", "") or "No reversal condition was provided."
        return ""

    @staticmethod
    def _layer_items(
        *,
        layer_id: str,
        claims: list[str],
        evidence: list[dict],
        source_notes: list[dict],
        gaps: list[str],
        sections: list[dict],
        synthesis: dict,
    ) -> list:
        if layer_id == "judgment":
            return claims[:3]
        if layer_id == "drivers":
            drivers = []
            for sec in sections:
                bullets = sec.get("bullets", []) if isinstance(sec, dict) else []
                drivers.extend(bullets or [])
            return (drivers or claims)[:6]
        if layer_id == "evidence":
            return evidence or source_notes
        if layer_id == "implications":
            implications = []
            for driver in synthesis.get("key_drivers", []) if synthesis else []:
                if isinstance(driver, dict) and driver.get("claim"):
                    implications.append(driver["claim"])
            return implications or claims[:3]
        if layer_id == "gaps":
            return gaps
        if layer_id == "watchlist":
            items = []
            reversal = synthesis.get("reversal_condition", "") if synthesis else ""
            if reversal:
                items.append(reversal)
            items.extend(gaps[:3])
            return items
        return []

    @staticmethod
    def _layer_provenance(
        *,
        layer_id: str,
        evidence: list[dict],
        source_notes: list[dict],
        claims: list[str],
        sections: list[dict],
        synthesis: dict,
        gaps: list[str],
    ) -> list[dict]:
        provenance: list[dict] = []
        if layer_id in ("judgment", "drivers") and claims:
            provenance.append({
                "source": "hand.metadata.key_claims",
                "source_tier": "derived",
                "freshness": "current run",
                "note": "Brain selected from hand claims for this layer.",
            })
        if layer_id == "drivers" and sections:
            provenance.append({
                "source": "hand.sections",
                "source_tier": "derived",
                "freshness": "current run",
                "note": "Brain grouped hand section bullets as causal drivers.",
            })
        if layer_id == "evidence":
            for row in evidence[:5]:
                if isinstance(row, dict):
                    provenance.append({
                        "source": row.get("source", "hand.evidence"),
                        "source_tier": row.get("source_tier", "unknown"),
                        "freshness": row.get("freshness", ""),
                        "note": row.get("support", row.get("claim", "")),
                    })
            for note in source_notes[:5]:
                if isinstance(note, dict):
                    provenance.append({
                        "source": note.get("source", "hand.metadata.source_notes"),
                        "source_tier": note.get("tier", note.get("source_tier", "unknown")),
                        "freshness": note.get("freshness", ""),
                        "note": note.get("note", ""),
                    })
        if layer_id == "implications":
            provenance.append({
                "source": "brain.synthesis",
                "source_tier": "derived",
                "freshness": "current run",
                "note": "Brain translated synthesis stance and key drivers into user-facing implications.",
            })
        if layer_id == "gaps" and gaps:
            provenance.append({
                "source": "hand.metadata.gaps",
                "source_tier": "gap",
                "freshness": "current run",
                "note": "Brain preserved missing, stale, or conflicting information.",
            })
        if layer_id == "watchlist":
            provenance.append({
                "source": "brain.synthesis.reversal_condition",
                "source_tier": "derived",
                "freshness": "current run",
                "note": "Brain used reversal condition and gaps as update signals.",
            })
        if not provenance:
            provenance.append({
                "source": "brain.presentation",
                "source_tier": "derived",
                "freshness": "current run",
                "note": "Brain generated this layer from available artifact structure; no external source was provided.",
            })
        return provenance

    # ── B-business synthesis ───────────────────────────────────────────────────

    async def synthesize(
        self,
        question: str,
        hand_artifacts: dict[str, dict],
        workflow_decision: dict,
        client,
        model: str,
    ) -> dict:
        """One LLM call: key_claims × pre-selected strategy rules → synthesis."""
        domain = workflow_decision.get("domain", "general")

        # Extract key_claims for framework variable-overlap gate
        hand_claims_map = {
            hid: art.get("metadata", {}).get("key_claims", [])
            for hid, art in hand_artifacts.items()
        }

        # Rebuild assemble_prompt with full hand context for framework selection
        # (framework variable-overlap gate now has real claim tokens to match against)
        system = self._assemble_prompt_with_claims(domain, question, hand_claims_map)

        # Hand summary: key_claims only (not full narrative)
        blocks: list[str] = []
        for hand_id, art in hand_artifacts.items():
            meta = art.get("metadata", {})
            error = meta.get("error")
            if error:
                blocks.append(f"### [{hand_id}] ERROR: {error}")
            else:
                claims = meta.get("key_claims", [])
                confidence = meta.get("confidence", "?")
                sources = meta.get("resources_used", [])
                def _claim_text(item):
                    if isinstance(item, str):
                        return item
                    if isinstance(item, dict):
                        claim = item.get("claim", item.get("text", str(item)))
                        source = item.get("source", "")
                        return f"{claim} ({source})" if source else claim
                    return str(item)
                claims_text = "\n".join(f"  - {_claim_text(c)}" for c in (claims or [])) or "  (no claims)"
                blocks.append(
                    f"### [{hand_id}] confidence={confidence}\n"
                    f"sources: {sources}\n"
                    f"key_claims:\n{claims_text}"
                )

        hands_text = "\n\n".join(blocks) if blocks else "(no hand outputs — cold run)"

        user_msg = (
            f"User question: {question}\n\n"
            f"Workflow decision: {json.dumps(workflow_decision, ensure_ascii=False)}\n\n"
            f"Hand summaries:\n\n{hands_text}\n\n"
            "Output ONLY a single JSON object (no other text):\n"
            '{"stance":"buy|hold|reduce|n/a",'
            '"confidence":0.0,'
            '"key_drivers":[{"rule":"<strategy rule id or text>","hand":"<hand_id>","claim":"<specific claim>"}],'
            '"reversal_condition":"...",'
            '"strategy_refs":["rule-id-1"],'
            '"clarifying_question":null,'
            '"regime_relevance":"当前 regime 为何使本次问题权重异常（≤80字符，无信号时填空字符串）",'
            '"watch_conditions":["需要持续监控的变量或事件，2-3条，无则空数组"],'
            '"priority_signal":"本次分析的最高优先级信号，一句话（无明确信号时填空字符串）"}'
        )

        resp = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

        parsed = _parse_json(text)
        if parsed is None:
            parsed = {
                "stance": "n/a",
                "confidence": 0.0,
                "key_drivers": [],
                "reversal_condition": "",
                "strategy_refs": [],
                "clarifying_question": "Brain could not parse a structured synthesis.",
                "_raw": text,
            }
        self._last_reward_report = self.rewarded_intent_harness.evaluate_and_update(
            question=question,
            domain=domain,
            activation=self._last_intent_activation,
            plan=self._last_policy_plan,
            synthesis=parsed,
            hand_artifacts=hand_artifacts,
        )
        return parsed
