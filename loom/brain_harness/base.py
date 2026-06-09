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
                claims_text = "\n".join(f"  - {c}" for c in claims) or "  (no claims)"
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
            '"clarifying_question":null}'
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
