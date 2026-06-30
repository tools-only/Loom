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
        self.assertIn("market", data["hand_artifacts"])

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
            self.assertEqual({}, detail["hand_artifacts"])

            summaries = writer.read_summary_log(limit=1)
            self.assertEqual(1, len(summaries))
            self.assertEqual("rubric-2", summaries[0]["rubric_id"])
            self.assertEqual(0.64, summaries[0]["reward_score"])

    def test_writer_loads_detail_and_appends_repair_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = FlywheelWriter(Path(tmp))
            record = FlywheelRecord.new(
                goal_id="goal-3",
                question="repair this",
                domain="general",
                synthesis={"stance": "n/a", "confidence": 0.4},
                hand_artifacts={"market": {"metadata": {"key_claims": [], "gaps": ["missing"]}}},
            )
            writer.append_record(record)

            detail = writer.load_detail(record.episode_id)
            self.assertIsNotNone(detail)
            self.assertEqual("repair this", detail["question"])
            self.assertIn("market", detail["hand_artifacts"])

            ok = writer.append_repair_result(record.episode_id, {
                "ok": True,
                "repair_plan": {"target_hands": ["market"]},
            })
            self.assertTrue(ok)
            updated = writer.load_detail(record.episode_id)
            self.assertEqual(1, len(updated["repair_history"]))
            self.assertEqual(["market"], updated["repair_history"][0]["repair_plan"]["target_hands"])


    def test_writer_appends_feedback_analysis_and_confirmed_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = FlywheelWriter(Path(tmp))
            record = FlywheelRecord.new(
                goal_id="goal-4",
                question="fix a claim",
                domain="general",
                synthesis={"stance": "n/a", "confidence": 0.4},
                hand_artifacts={},
            )
            writer.append_record(record)

            self.assertTrue(writer.append_feedback_event(record.episode_id, {
                "feedback_id": "fb-1",
                "object_ref": "claim:c1",
                "comment": "wrong",
            }))
            self.assertTrue(writer.append_intent_analysis(record.episode_id, {
                "analysis_id": "cia-1",
                "feedback_id": "fb-1",
                "affected_objects": ["claim:c1"],
            }))
            self.assertTrue(writer.append_confirmed_correction(record.episode_id, {
                "correction_id": "cc-1",
                "analysis_id": "cia-1",
                "reuse_scope": "task_pattern",
            }))

            updated = writer.load_detail(record.episode_id)
            self.assertEqual("fb-1", updated["feedback_events"][0]["feedback_id"])
            self.assertEqual("cia-1", updated["intent_analyses"][0]["analysis_id"])
            self.assertEqual("cc-1", updated["confirmed_corrections"][0]["correction_id"])

if __name__ == "__main__":
    unittest.main()

