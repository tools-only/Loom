from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loom.brain_harness.flywheel import FlywheelRecord, FlywheelWriter


class FlywheelRecordTests(unittest.TestCase):
    def test_record_captures_intent_rubric_and_reward_detail(self):
        record = FlywheelRecord.new(
            goal_id="goal-1",
            question="market risk",
            domain="finance",
            synthesis={
                "stance": "hold",
                "confidence": 0.7,
                "key_drivers": [{"claim": "risk is balanced"}],
                "reversal_condition": "liquidity breaks",
            },
            hand_artifacts={
                "market": {
                    "metadata": {
                        "key_claims": ["risk claim"],
                        "gaps": ["missing positioning"],
                        "resources_used": ["reuters-rss"],
                    }
                }
            },
            cold_start=False,
            intent_activation={
                "run_id": "run-1",
                "active_intents": [{"intent_id": "risk_sensitivity.reversal"}],
            },
            intent_rubric={
                "rubric_id": "rubric-1",
                "criteria": [
                    {"criterion_id": "rubric.add_risk_and_reversal_checks"},
                    {"criterion_id": "rubric.satisfy_content_requirements"},
                ],
                "resource_context": {
                    "resources": [{"resource_id": "res-1"}],
                    "strategy_primitives": [{"primitive_id": "sp-1"}],
                },
            },
            intent_reward_report={
                "overall_reward": 0.82,
                "evaluator_scores": {"risk_coverage": 0.9},
                "policy_rewards": {"policy.add_risk_and_reversal_checks": 0.86},
            },
        )

        data = record.to_dict()
        self.assertEqual("rubric-1", data["intent_rubric"]["rubric_id"])
        self.assertEqual(0.82, data["intent_reward_report"]["overall_reward"])
        self.assertEqual(0.82, data["brain_self_eval"]["overall_quality"])

        summary = record.summary_line()
        self.assertEqual(0.82, summary["reward_score"])
        self.assertEqual("rubric-1", summary["rubric_id"])
        self.assertEqual(2, summary["rubric_criteria_count"])
        self.assertEqual(1, summary["rubric_resource_count"])
        self.assertEqual(1, summary["rubric_strategy_primitive_count"])

    def test_writer_persists_reward_detail_to_episode_file_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = FlywheelWriter(Path(tmp))
            record = FlywheelRecord.new(
                goal_id="goal-2",
                question="market risk",
                domain="finance",
                synthesis={"stance": "hold", "confidence": 0.6},
                hand_artifacts={},
                intent_rubric={"rubric_id": "rubric-2", "criteria": []},
                intent_reward_report={"overall_reward": 0.64},
            )

            writer.append_record(record)

            detail_path = Path(tmp) / "brain" / "flywheel" / f"{record.episode_id}.json"
            detail = json.loads(detail_path.read_text("utf-8"))
            self.assertEqual("rubric-2", detail["intent_rubric"]["rubric_id"])
            self.assertEqual(0.64, detail["intent_reward_report"]["overall_reward"])

            summaries = writer.read_summary_log(limit=1)
            self.assertEqual(1, len(summaries))
            self.assertEqual("rubric-2", summaries[0]["rubric_id"])
            self.assertEqual(0.64, summaries[0]["reward_score"])


if __name__ == "__main__":
    unittest.main()
