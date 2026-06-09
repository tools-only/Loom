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

    def plan(self, activation: IntentActivation, domain: str, question: str, limit: int = 5) -> PolicyPlan:
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
        plan = PolicyPlan(
            ts=datetime.now().isoformat(),
            plan_id="plan_" + datetime.now().strftime("%Y%m%d%H%M%S%f"),
            domain=domain or "general",
            question=question,
            selected_policies=selected[:limit],
            suppressed_policies=suppressed,
        )
        self._append_jsonl(self.episodes_path, {"type": "policy_plan", **asdict(plan)})
        return plan

    def format_plan_for_prompt(self, plan: PolicyPlan) -> str:
        if not plan.selected_policies:
            return ""
        lines = [
            "The following intent policies were selected by the Brain process.",
            "Treat them as executable generation constraints, not background memory.",
        ]
        for policy in plan.selected_policies:
            lines.append(f"- {policy['label']} (id={policy['policy_id']}, score={policy['score']:.2f})")
            for action in policy.get("actions", []):
                lines.append(f"  - action: {action}")
        return "\n".join(lines)

    def evaluate_and_update(
        self,
        question: str,
        domain: str,
        activation: IntentActivation | None,
        plan: PolicyPlan | None,
        synthesis: dict[str, Any],
        hand_artifacts: dict[str, dict],
    ) -> RewardReport | None:
        if activation is None or plan is None:
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

        policy_rewards: dict[str, float] = {}
        for policy in plan.selected_policies:
            targets = policy.get("reward_targets", [])
            values = [evaluator_scores[t] for t in targets if t in evaluator_scores]
            policy_rewards[policy["policy_id"]] = round(sum(values) / len(values), 3) if values else 0.5

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
            plan_id=plan.plan_id,
            overall_reward=overall,
            evaluator_scores={k: round(v, 3) for k, v in evaluator_scores.items()},
            policy_rewards=policy_rewards,
            intent_rewards=intent_rewards,
            diagnosis=diagnosis,
        )

        self._append_jsonl(self.reward_ledger_path, asdict(report))
        self._update_policy_weights(policy_rewards)
        self._append_jsonl(self.credit_path, self._credit_assignment(report, plan))
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
            "latest_reward": self.latest_reward(),
        }

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
    def _credit_assignment(report: RewardReport, plan: PolicyPlan) -> dict[str, Any]:
        updates = []
        for policy in plan.selected_policies:
            reward = report.policy_rewards.get(policy["policy_id"], 0.5)
            updates.append({
                "policy_id": policy["policy_id"],
                "reward": reward,
                "credit": "positive" if reward >= 0.6 else "negative" if reward < 0.45 else "neutral",
                "reason": report.diagnosis,
            })
        return {
            "ts": datetime.now().isoformat(),
            "episode_id": report.episode_id,
            "plan_id": plan.plan_id,
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
