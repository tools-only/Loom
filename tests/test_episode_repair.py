import unittest

from loom_core.repair.episode_repair import (
    build_repair_plan,
    build_repair_task,
    choose_repair_hands,
    summarize_repair_for_reply,
)


def _episode():
    return {
        "episode_id": "ep-1",
        "question": "Assess market risk",
        "domain": "finance",
        "brain_self_eval": {"stance": "hold", "confidence": 0.6},
        "hand_evaluations": [
            {"hand_id": "market", "artifact_present": True, "claim_count": 3, "gap_count": 1},
            {"hand_id": "sentiment", "artifact_present": True, "claim_count": 1, "gap_count": 4},
            {"hand_id": "target", "artifact_present": False, "claim_count": 0, "gap_count": 3},
        ],
    }


class EpisodeRepairTests(unittest.TestCase):
    def test_explicit_target_wins(self):
        hands, reason = choose_repair_hands(_episode(), explicit_hand_id="market")

        self.assertEqual(["market"], hands)
        self.assertEqual("explicit feedback target", reason)

    def test_comment_mention_selects_hand(self):
        hands, reason = choose_repair_hands(_episode(), comment="sentiment missed the crowding risk")

        self.assertEqual(["sentiment"], hands)
        self.assertEqual("hand mentioned in correction", reason)

    def test_fallback_selects_weakest_hand_evaluations(self):
        hands, reason = choose_repair_hands(_episode())

        self.assertEqual(["target", "sentiment"], hands)
        self.assertEqual("lowest-confidence hand evaluation", reason)

    def test_build_repair_plan_contains_episode_context(self):
        plan = build_repair_plan(_episode(), comment="fix target")

        self.assertEqual("ep-1", plan.episode_id)
        self.assertEqual("finance", plan.domain)
        self.assertEqual("Assess market risk", plan.question)
        self.assertTrue(plan.target_hands)

    def test_build_repair_task_mentions_user_correction_and_contract(self):
        task = build_repair_task(
            _episode(),
            hand_id="market",
            comment="The prior answer ignored liquidity risk.",
            corrected_stance="reduce",
        )

        self.assertIn("The prior answer ignored liquidity risk.", task)
        self.assertIn("Corrected stance requested by user: reduce", task)
        self.assertIn("metadata.confidence", task)

    def test_build_repair_task_uses_intent_delta_when_available(self):
        task = build_repair_task(
            _episode(),
            hand_id="market",
            comment="this source is weak",
            intent_delta={
                "target": "source_preference",
                "instruction": "Re-check claim:c1 with A/B tier sources.",
                "affected_objects": ["claim:c1", "source:reddit"],
            },
        )

        self.assertIn("Structured repair intent:", task)
        self.assertIn("source_preference", task)
        self.assertIn("Re-check claim:c1 with A/B tier sources.", task)
        self.assertIn("claim:c1", task)

    def test_summarize_repair_for_reply(self):
        text = summarize_repair_for_reply({
            "ok": True,
            "episode_id": "ep-1",
            "repair_plan": {"target_hands": ["market"]},
            "artifacts": {"market": {}},
        })

        self.assertIn("Repair completed", text)
        self.assertIn("market", text)
        self.assertIn("ep-1", text)


if __name__ == "__main__":
    unittest.main()

