from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from loom.brain_harness.intent_harness import RewardedIntentHarness
from loom.brain_harness.intent_wiki import IntentActivation


def _activation() -> IntentActivation:
    return IntentActivation(
        ts="2026-06-13T00:00:00",
        run_id="run-test",
        question="market risk",
        domain="finance",
        active_intents=[
            {
                "intent_id": "content_requirements.market_brief",
                "zone": "content_requirements",
                "label": "market brief",
                "principle": "Cover market signals.",
            },
            {
                "intent_id": "risk_sensitivity.reversal",
                "zone": "risk_sensitivity",
                "label": "reversal",
                "principle": "Include reversal conditions.",
            },
        ],
        inactive_intents=[],
    )


class IntentHarnessTests(unittest.TestCase):
    def test_compile_rubric_maps_active_intents_to_evaluation_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RewardedIntentHarness(Path(tmp))
            rubric = harness.compile_rubric(_activation(), domain="finance", question="market risk")

            self.assertTrue(rubric.rubric_id.startswith("rubric_"))
            self.assertGreaterEqual(len(rubric.criteria), 2)
            criterion_ids = {c["criterion_id"] for c in rubric.criteria}
            self.assertIn("rubric.satisfy_content_requirements", criterion_ids)
            self.assertIn("rubric.add_risk_and_reversal_checks", criterion_ids)
            self.assertTrue(any(c["source_intent_ids"] for c in rubric.criteria))
            self.assertEqual("rubric_spec", harness.latest_rubric()["type"])

    def test_format_plan_for_prompt_is_disabled_for_generation_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RewardedIntentHarness(Path(tmp))
            plan = harness.plan(_activation(), domain="finance", question="market risk")

            self.assertEqual("", harness.format_plan_for_prompt(plan))

    def test_evaluate_and_update_accepts_rubric_and_records_reward(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RewardedIntentHarness(Path(tmp))
            activation = _activation()
            rubric = harness.compile_rubric(activation, domain="finance", question="market risk")
            report = harness.evaluate_and_update(
                question="market risk",
                domain="finance",
                activation=activation,
                plan=None,
                rubric=rubric,
                synthesis={
                    "stance": "hold",
                    "confidence": 0.7,
                    "key_drivers": [{"claim": "market brief includes risk"}],
                    "reversal_condition": "risk clears",
                },
                hand_artifacts={
                    "market": {
                        "narrative": "Recent market risk and reversal are covered.",
                        "metadata": {"resources_used": ["reuters-rss"], "key_claims": ["risk"]},
                    }
                },
            )

            self.assertIsNotNone(report)
            self.assertEqual(rubric.rubric_id, report.plan_id)
            self.assertIn("policy.add_risk_and_reversal_checks", report.policy_rewards)
            self.assertIsNotNone(harness.latest_reward())

    def test_compile_rubric_adds_resource_sidecar_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RewardedIntentHarness(Path(tmp))
            resource_context = {
                "resources": [{
                    "resource_id": "res-ai-capex",
                    "title": "AI capex note",
                    "trust_tier": "C",
                    "url": "https://example.com/ai-capex",
                }],
                "strategy_primitives": [{
                    "primitive_id": "sp-ai-capex",
                    "name": "AI capex digestion",
                    "variables": ["capex guidance", "GPU backlog"],
                    "invalidation": ["cloud capex accelerates"],
                    "source_resource_ids": ["res-ai-capex"],
                }],
            }

            rubric = harness.compile_rubric(
                _activation(),
                domain="loom-fin",
                question="AI capex risk",
                resource_context=resource_context,
            )

            criterion_ids = {c["criterion_id"] for c in rubric.criteria}
            self.assertIn("rubric.resource_source_fit", criterion_ids)
            self.assertIn("rubric.strategy_framework_fit", criterion_ids)
            self.assertEqual(resource_context, rubric.resource_context)

    def test_resource_sidecar_contributes_reward_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = RewardedIntentHarness(Path(tmp))
            activation = _activation()
            rubric = harness.compile_rubric(
                activation,
                domain="loom-fin",
                question="AI capex risk",
                resource_context={
                    "resources": [{
                        "resource_id": "res-ai-capex",
                        "title": "AI capex note",
                        "trust_tier": "C",
                    }],
                    "strategy_primitives": [{
                        "primitive_id": "sp-ai-capex",
                        "name": "AI capex digestion",
                        "variables": ["capex guidance", "GPU backlog"],
                        "invalidation": ["cloud capex accelerates"],
                    }],
                },
            )
            report = harness.evaluate_and_update(
                question="AI capex risk",
                domain="loom-fin",
                activation=activation,
                plan=None,
                rubric=rubric,
                synthesis={
                    "stance": "hold",
                    "confidence": 0.7,
                    "key_drivers": [{"claim": "Capex guidance and GPU backlog are balanced."}],
                    "reversal_condition": "cloud capex accelerates",
                },
                hand_artifacts={
                    "market": {
                        "narrative": "AI capex note source: res-ai-capex.",
                        "metadata": {"resources_used": ["res-ai-capex"]},
                    }
                },
            )

            self.assertIsNotNone(report)
            assert report is not None
            self.assertIn("source_fit", report.evaluator_scores)
            self.assertIn("framework_fit", report.evaluator_scores)
            self.assertIn("rubric.resource_source_fit", report.policy_rewards)


if __name__ == "__main__":
    unittest.main()
