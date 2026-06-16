"""Rewarded Intent Harness.

This layer turns durable intents into executable policies, evaluates whether a
generation satisfied them, and records reward/credit signals for future runs.
It is intentionally deterministic in v1: inspectable policy updates are more
valuable here than opaque optimization.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .intent_wiki import IntentActivation


@dataclass
class IntentPolicy:
    policy_id: str
    label: str
    when_zones: list[str]
    actions: list[str]
    reward_targets: list[str]
    weight: float = 0.5
    enabled: bool = True
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reward_count: int = 0
    average_reward: float = 0.0


@dataclass
class PolicyPlan:
    ts: str
    plan_id: str
    domain: str
    question: str
    selected_policies: list[dict[str, Any]]
    suppressed_policies: list[dict[str, Any]]


@dataclass
class RubricSpec:
    ts: str
    rubric_id: str
    domain: str
    question: str
    criteria: list[dict[str, Any]]
    suppressed_policies: list[dict[str, Any]]
    resource_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RewardReport:
    ts: str
    episode_id: str
    plan_id: str
    overall_reward: float
    evaluator_scores: dict[str, float]
    policy_rewards: dict[str, float]
    intent_rewards: dict[str, float]
    diagnosis: str


DEFAULT_POLICIES = [
    IntentPolicy(
        policy_id="policy.satisfy_content_requirements",
        label="Satisfy active content requirements",
        when_zones=["content_requirements", "domain_principles"],
        actions=[
            "translate active content intents into explicit output requirements",
            "add or revise sections so the generated page visibly satisfies the requirement",
        ],
        reward_targets=["intent_coverage", "relevance"],
        weight=0.62,
    ),
    IntentPolicy(
        policy_id="policy.retrieve_or_surface_fresh_context",
        label="Retrieve or surface fresh context when required",
        when_zones=["content_requirements", "source_preferences"],
        actions=[
            "identify whether the active intent requires recent context",
            "ask relevant hands/tools for fresh context or mark freshness gaps explicitly",
        ],
        reward_targets=["freshness", "decision_usefulness"],
        weight=0.58,
    ),
    IntentPolicy(
        policy_id="policy.respect_object_scoped_operations",
        label="Respect object-scoped user behavior",
        when_zones=["object_behavior", "workflow_preferences"],
        actions=[
            "ground the task in the target anchor/card/object before interpreting the instruction",
            "avoid applying local edits globally unless the user asks for global changes",
        ],
        reward_targets=["intent_coverage", "relevance"],
        weight=0.66,
    ),
    IntentPolicy(
        policy_id="policy.add_risk_and_reversal_checks",
        label="Add risk and reversal checks",
        when_zones=["risk_sensitivity", "decision_style"],
        actions=[
            "include counterarguments, uncertainty, downside triggers, or reversal conditions",
            "avoid generic risks; tie each risk to the current object or decision",
        ],
        reward_targets=["risk_coverage", "decision_usefulness"],
        weight=0.55,
    ),
    IntentPolicy(
        policy_id="policy.preserve_user_style",
        label="Preserve user style and granularity",
        when_zones=["personal_style"],
        actions=[
            "match the user's preferred density, language, and structure",
            "prefer reusable formatting choices that have received positive reward",
        ],
        reward_targets=["style_fit", "relevance"],
        weight=0.48,
    ),
]


class RewardedIntentHarness:
    """Policy planner + evaluator + reward ledger for intent-guided generation."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "brain" / "intent_harness"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.policies_path = self.dir / "policies.json"
        self.reward_ledger_path = self.dir / "reward_ledger.jsonl"
        self.episodes_path = self.dir / "episodes.jsonl"
        self.credit_path = self.dir / "credit_assignments.jsonl"
        if not self.policies_path.exists():
            self._write_policies(DEFAULT_POLICIES)

    def policies(self) -> list[IntentPolicy]:
        try:
            data = json.loads(self.policies_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"policies": [asdict(p) for p in DEFAULT_POLICIES]}
        out: list[IntentPolicy] = []
        for item in data.get("policies", []):
            try:
                out.append(IntentPolicy(**item))
            except TypeError:
                continue
        return out

    def _select_policy_candidates(
        self,
        activation: IntentActivation,
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        active_zones = {item.get("zone") for item in activation.active_intents}
        selected: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []

        for policy in self.policies():
            matching_zones = sorted(z for z in policy.when_zones if z in active_zones)
            score = policy.weight + 0.12 * len(matching_zones)
            item = {
                "policy_id": policy.policy_id,
                "label": policy.label,
                "actions": policy.actions,
                "reward_targets": policy.reward_targets,
                "score": round(score, 2),
                "matched_zones": matching_zones,
                "weight": policy.weight,
            }
            if policy.enabled and matching_zones:
                selected.append(item)
            else:
                item["reason"] = "no matching active intent zone" if policy.enabled else "disabled"
                suppressed.append(item)

        selected.sort(key=lambda p: p["score"], reverse=True)
        return selected[:limit], suppressed

    def plan(self, activation: IntentActivation, domain: str, question: str, limit: int = 5) -> PolicyPlan:
        selected, suppressed = self._select_policy_candidates(activation, limit=limit)
        plan = PolicyPlan(
            ts=datetime.now().isoformat(),
            plan_id="plan_" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            domain=domain or "general",
            question=question,
            selected_policies=selected,
            suppressed_policies=suppressed,
        )
        self._append_jsonl(self.episodes_path, {"type": "policy_plan", **asdict(plan)})
        return plan

    def format_plan_for_prompt(self, plan: PolicyPlan) -> str:
        """Deprecated: intent policies are evaluator-only, not prompt context."""
        return ""

    def compile_rubric(
        self,
        activation: IntentActivation,
        domain: str,
        question: str,
        limit: int = 5,
        resource_context: dict[str, Any] | None = None,
    ) -> RubricSpec:
        """Compile active intents into post-generation evaluation criteria.

        The rubric is deliberately not formatted for Brain prompts. It gives the
        evaluator a detailed checklist while keeping the generation context
        focused on the current goal and explicit state.
        """
        selected, suppressed = self._select_policy_candidates(activation, limit=limit)
        active_by_zone: dict[str, list[str]] = {}
        for intent in activation.active_intents:
            zone = str(intent.get("zone", ""))
            if not zone:
                continue
            active_by_zone.setdefault(zone, []).append(str(intent.get("intent_id", "")))

        criteria = []
        for policy in selected:
            matched_zones = list(policy.get("matched_zones", []) or [])
            source_intent_ids = [
                intent_id
                for zone in matched_zones
                for intent_id in active_by_zone.get(zone, [])
                if intent_id
            ]
            criteria.append({
                "criterion_id": policy["policy_id"].replace("policy.", "rubric.", 1),
                "label": policy["label"],
                "weight": policy["weight"],
                "score": policy["score"],
                "reward_targets": list(policy.get("reward_targets", []) or []),
                "matched_zones": matched_zones,
                "source_policy_id": policy["policy_id"],
                "source_intent_ids": source_intent_ids,
                "checks": [
                    f"Evaluate whether the result {action}."
                    for action in policy.get("actions", [])
                ],
            })

        resource_context = resource_context if isinstance(resource_context, dict) else {}
        criteria.extend(self._resource_criteria(resource_context))

        rubric = RubricSpec(
            ts=datetime.now().isoformat(),
            rubric_id="rubric_" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            domain=domain or "general",
            question=question,
            criteria=criteria,
            suppressed_policies=suppressed,
            resource_context=resource_context,
        )
        self._append_jsonl(self.episodes_path, {"type": "rubric_spec", **asdict(rubric)})
        return rubric

    @staticmethod
    def _resource_criteria(resource_context: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert resource sidecar context into evaluator-only criteria."""
        resources = [
            item for item in resource_context.get("resources", [])
            if isinstance(item, dict)
        ]
        primitives = [
            item for item in resource_context.get("strategy_primitives", [])
            if isinstance(item, dict)
        ]
        criteria: list[dict[str, Any]] = []
        if resources:
            criteria.append({
                "criterion_id": "rubric.resource_source_fit",
                "label": "Use relevant captured resources at the right confidence level",
                "weight": 0.16,
                "score": 0.7,
                "reward_targets": ["source_fit", "freshness"],
                "matched_zones": ["source_preferences"],
                "source_policy_id": "",
                "source_intent_ids": [],
                "source_refs": [
                    {
                        "type": "resource",
                        "id": item.get("resource_id", ""),
                        "title": item.get("title", ""),
                        "tier": item.get("trust_tier", "F"),
                        "url": item.get("url", ""),
                    }
                    for item in resources
                ],
                "checks": [
                    "Evaluate whether the result uses relevant captured resources without treating weak social signals as verified facts.",
                    "Evaluate whether source tier, freshness, and provenance are visible when they matter to the decision.",
                ],
            })
        if primitives:
            criteria.append({
                "criterion_id": "rubric.strategy_framework_fit",
                "label": "Apply distilled strategy frameworks as evaluation lenses",
                "weight": 0.18,
                "score": 0.72,
                "reward_targets": ["framework_fit", "risk_coverage", "decision_usefulness"],
                "matched_zones": ["source_preferences", "decision_style", "risk_sensitivity"],
                "source_policy_id": "",
                "source_intent_ids": [],
                "source_refs": [
                    {
                        "type": "strategy_primitive",
                        "id": item.get("primitive_id", ""),
                        "name": item.get("name", ""),
                        "source_resource_ids": item.get("source_resource_ids", []),
                    }
                    for item in primitives
                ],
                "checks": [
                    "Evaluate whether the result tests the primitive's core variables instead of only echoing its conclusion.",
                    "Evaluate whether trigger, evidence, and invalidation conditions are made explicit.",
                    "Evaluate whether conflicting or low-confidence frameworks are handled as hypotheses.",
                ],
            })
        return criteria

    def evaluate_and_update(
        self,
        question: str,
        domain: str,
        activation: IntentActivation | None,
        plan: PolicyPlan | RubricSpec | None,
        synthesis: dict[str, Any],
        hand_artifacts: dict[str, dict],
        rubric: RubricSpec | None = None,
    ) -> RewardReport | None:
        evaluation_plan = rubric or plan
        if activation is None or evaluation_plan is None:
            return None

        output_text = self._output_text(synthesis, hand_artifacts)
        evaluator_scores = {
            "intent_coverage": self._score_intent_coverage(activation, output_text),
            "relevance": self._score_relevance(question, activation, output_text),
            "freshness": self._score_freshness(activation, output_text, hand_artifacts),
            "risk_coverage": self._score_risk_coverage(activation, output_text),
            "decision_usefulness": self._score_decision_usefulness(synthesis, output_text),
            "style_fit": 0.55,
        }
        if isinstance(evaluation_plan, RubricSpec) and evaluation_plan.resource_context:
            evaluator_scores["source_fit"] = self._score_source_fit(
                evaluation_plan,
                output_text,
                hand_artifacts,
            )
            evaluator_scores["framework_fit"] = self._score_framework_fit(
                evaluation_plan,
                output_text,
            )

        policy_rewards: dict[str, float] = {}
        for item in self._reward_items(evaluation_plan):
            policy_id = item.get("source_policy_id") or item.get("policy_id") or item.get("criterion_id")
            targets = item.get("reward_targets", [])
            values = [evaluator_scores[t] for t in targets if t in evaluator_scores]
            policy_rewards[policy_id] = round(sum(values) / len(values), 3) if values else 0.5

        intent_rewards: dict[str, float] = {}
        for intent in activation.active_intents:
            zone = intent.get("zone", "")
            if zone == "risk_sensitivity":
                score = evaluator_scores["risk_coverage"]
            elif zone == "source_preferences":
                score = evaluator_scores["freshness"]
            else:
                score = evaluator_scores["intent_coverage"]
            intent_rewards[intent.get("intent_id", "")] = round(score, 3)

        overall = round(sum(evaluator_scores.values()) / len(evaluator_scores), 3)
        diagnosis = self._diagnosis(evaluator_scores)
        report = RewardReport(
            ts=datetime.now().isoformat(),
            episode_id="ep_" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            plan_id=self._plan_identifier(evaluation_plan),
            overall_reward=overall,
            evaluator_scores={k: round(v, 3) for k, v in evaluator_scores.items()},
            policy_rewards=policy_rewards,
            intent_rewards=intent_rewards,
            diagnosis=diagnosis,
        )

        self._append_jsonl(self.reward_ledger_path, asdict(report))
        self._update_policy_weights(policy_rewards)
        self._append_jsonl(self.credit_path, self._credit_assignment(report, evaluation_plan))
        return report

    def latest_reward(self) -> dict[str, Any] | None:
        if not self.reward_ledger_path.exists():
            return None
        lines = [ln for ln in self.reward_ledger_path.read_text("utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "policies": [asdict(p) for p in self.policies()],
            "latest_rubric": self.latest_rubric(),
            "latest_reward": self.latest_reward(),
        }

    def latest_rubric(self) -> dict[str, Any] | None:
        if not self.episodes_path.exists():
            return None
        lines = [ln for ln in self.episodes_path.read_text("utf-8").splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") == "rubric_spec":
                return item
        return None

    def _update_policy_weights(self, policy_rewards: dict[str, float]) -> None:
        policies = {p.policy_id: p for p in self.policies()}
        now = datetime.now().isoformat()
        for policy_id, reward in policy_rewards.items():
            policy = policies.get(policy_id)
            if not policy:
                continue
            old_count = policy.reward_count
            new_count = old_count + 1
            policy.average_reward = round(((policy.average_reward * old_count) + reward) / new_count, 3)
            policy.reward_count = new_count
            policy.weight = round(min(0.95, max(0.15, policy.weight + 0.08 * (reward - 0.5))), 3)
            policy.updated_at = now
        self._write_policies(sorted(policies.values(), key=lambda p: p.policy_id))

    @staticmethod
    def _output_text(synthesis: dict[str, Any], hand_artifacts: dict[str, dict]) -> str:
        parts = [json.dumps(synthesis, ensure_ascii=False)]
        for artifact in hand_artifacts.values():
            parts.append(str(artifact.get("narrative", "")))
            parts.append(json.dumps(artifact.get("metadata", {}), ensure_ascii=False))
        return "\n".join(parts).lower()

    @staticmethod
    def _score_intent_coverage(activation: IntentActivation, output_text: str) -> float:
        if not activation.active_intents:
            return 0.6
        hits = 0
        for intent in activation.active_intents:
            words = RewardedIntentHarness._keywords(intent.get("label", "") + " " + intent.get("principle", ""))
            if any(w in output_text for w in words):
                hits += 1
        return min(1.0, 0.25 + 0.75 * hits / max(1, len(activation.active_intents)))

    @staticmethod
    def _score_relevance(question: str, activation: IntentActivation, output_text: str) -> float:
        q_words = RewardedIntentHarness._keywords(question)
        if not q_words:
            return 0.55
        hits = sum(1 for word in q_words if word in output_text)
        base = min(0.9, 0.35 + 0.55 * hits / max(1, len(q_words)))
        if len(activation.active_intents) > 6:
            base -= 0.08
        return max(0.1, base)

    @staticmethod
    def _score_freshness(activation: IntentActivation, output_text: str, hand_artifacts: dict[str, dict]) -> float:
        needs_fresh = any(
            any(k in (intent.get("label", "") + intent.get("principle", "")).lower()
                for k in ("fresh", "recent", "latest", "news", "热点", "近期", "最新", "新闻"))
            for intent in activation.active_intents
        )
        if not needs_fresh:
            return 0.6
        resource_text = json.dumps(hand_artifacts, ensure_ascii=False).lower()
        has_fresh_signal = any(k in output_text + resource_text for k in (
            "recent", "latest", "news", "today", "2026", "近期", "最新", "新闻", "热点",
        ))
        return 0.82 if has_fresh_signal else 0.28

    @staticmethod
    def _score_risk_coverage(activation: IntentActivation, output_text: str) -> float:
        wants_risk = any(intent.get("zone") in ("risk_sensitivity", "decision_style")
                         for intent in activation.active_intents)
        if not wants_risk:
            return 0.58
        hits = sum(1 for k in ("risk", "downside", "reversal", "uncertain", "风险", "下行", "反转", "不确定")
                   if k in output_text)
        return min(0.9, 0.25 + hits * 0.16)

    @staticmethod
    def _score_decision_usefulness(synthesis: dict[str, Any], output_text: str) -> float:
        score = 0.35
        if synthesis.get("stance") and synthesis.get("stance") != "n/a":
            score += 0.18
        if synthesis.get("key_drivers"):
            score += 0.18
        if synthesis.get("reversal_condition") or any(k in output_text for k in ("reversal", "反转")):
            score += 0.14
        if synthesis.get("confidence"):
            score += 0.1
        return min(0.95, score)

    @staticmethod
    def _score_source_fit(rubric: RubricSpec, output_text: str, hand_artifacts: dict[str, dict]) -> float:
        resources = rubric.resource_context.get("resources", [])
        if not resources:
            return 0.6
        artifact_text = json.dumps(hand_artifacts, ensure_ascii=False).lower()
        combined = output_text + "\n" + artifact_text
        hits = 0
        strong_tier_hits = 0
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            probes = [
                str(resource.get("resource_id", "")),
                str(resource.get("title", "")),
                str(resource.get("url", "")),
                str(resource.get("source_author", "")),
            ]
            if any(probe and probe.lower() in combined for probe in probes):
                hits += 1
                if str(resource.get("trust_tier", "")).upper() in {"A", "B", "C"}:
                    strong_tier_hits += 1
        coverage = hits / max(1, len(resources))
        score = 0.32 + 0.48 * coverage + 0.1 * min(1, strong_tier_hits)
        if any(word in combined for word in ("source", "provenance", "tier", "来源", "出处", "引用")):
            score += 0.08
        return round(min(0.95, score), 3)

    @staticmethod
    def _score_framework_fit(rubric: RubricSpec, output_text: str) -> float:
        primitives = rubric.resource_context.get("strategy_primitives", [])
        if not primitives:
            return 0.6
        variables: list[str] = []
        invalidation_terms: list[str] = []
        for primitive in primitives:
            if not isinstance(primitive, dict):
                continue
            variables.extend(RewardedIntentHarness._keywords(" ".join(
                str(v) for v in primitive.get("variables", [])
            )))
            invalidation_terms.extend(RewardedIntentHarness._keywords(" ".join(
                str(v) for v in primitive.get("invalidation", [])
            )))
        variable_hits = sum(1 for word in set(variables) if word in output_text)
        invalidation_hits = sum(1 for word in set(invalidation_terms) if word in output_text)
        variable_score = variable_hits / max(1, min(8, len(set(variables))))
        invalidation_score = invalidation_hits / max(1, min(4, len(set(invalidation_terms))))
        explicit_risk = any(word in output_text for word in ("risk", "reversal", "invalid", "失效", "反证", "反转"))
        score = 0.3 + 0.38 * min(1.0, variable_score) + 0.18 * min(1.0, invalidation_score)
        if explicit_risk:
            score += 0.08
        return round(min(0.95, score), 3)

    @staticmethod
    def _diagnosis(scores: dict[str, float]) -> str:
        weak = sorted((k, v) for k, v in scores.items() if v < 0.45)
        strong = sorted((k, v) for k, v in scores.items() if v >= 0.75)
        parts = []
        if strong:
            parts.append("strong: " + ", ".join(k for k, _ in strong[:3]))
        if weak:
            parts.append("needs work: " + ", ".join(k for k, _ in weak[:3]))
        return "; ".join(parts) or "balanced reward profile"

    @staticmethod
    @staticmethod
    def _reward_items(plan: PolicyPlan | RubricSpec) -> list[dict[str, Any]]:
        if isinstance(plan, RubricSpec):
            return plan.criteria
        return plan.selected_policies

    @staticmethod
    def _plan_identifier(plan: PolicyPlan | RubricSpec) -> str:
        if isinstance(plan, RubricSpec):
            return plan.rubric_id
        return plan.plan_id

    @staticmethod
    def _credit_assignment(report: RewardReport, plan: PolicyPlan | RubricSpec) -> dict[str, Any]:
        updates = []
        for item in RewardedIntentHarness._reward_items(plan):
            policy_id = item.get("source_policy_id") or item.get("policy_id") or item.get("criterion_id")
            reward = report.policy_rewards.get(policy_id, 0.5)
            updates.append({
                "policy_id": policy_id,
                "reward": reward,
                "credit": "positive" if reward >= 0.6 else "negative" if reward < 0.45 else "neutral",
                "reason": report.diagnosis,
            })
        return {
            "ts": datetime.now().isoformat(),
            "episode_id": report.episode_id,
            "plan_id": RewardedIntentHarness._plan_identifier(plan),
            "policy_updates": updates,
        }

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]{2,}", str(text).lower())
        stop = {"the", "and", "for", "with", "this", "that", "user", "intent", "policy"}
        out: list[str] = []
        for word in words:
            if word in stop or word in out:
                continue
            out.append(word)
            if len(out) >= 16:
                break
        return out

    def _write_policies(self, policies: list[IntentPolicy]) -> None:
        self.policies_path.write_text(
            json.dumps({"version": 1, "policies": [asdict(p) for p in policies]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
