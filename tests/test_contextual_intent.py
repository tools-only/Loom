from __future__ import annotations

import unittest

from loom.brain_harness.contextual_intent import (
    ContextualIntentCompiler,
    ScopedFeedback,
)


class ContextualIntentCompilerTests(unittest.TestCase):
    def test_claim_feedback_compiles_to_claim_scoped_repair_delta(self):
        feedback = ScopedFeedback(
            episode_id="ep-1",
            raw_signal="correction",
            comment="这个不对，需要重新验证",
            object_ref="claim:c1",
            object_type="claim",
        )
        compiler = ContextualIntentCompiler()

        analysis = compiler.compile(
            feedback,
            episode={
                "episode_id": "ep-1",
                "question": "assess market risk",
                "hand_artifacts": {
                    "t1": {
                        "metadata": {
                            "task_id": "t1",
                            "hand_id": "runtime-evidence",
                            "executor_id": "market",
                            "key_claims": ["claim c1"],
                        }
                    }
                },
            },
        )

        self.assertEqual("claim_revision", analysis.agent_readable_intent_delta.target)
        self.assertIn("claim:c1", analysis.affected_objects)
        self.assertEqual("medium", analysis.confidence)
        self.assertEqual("episode_only", analysis.persistence_level)
        self.assertTrue(analysis.intent_hypotheses)

    def test_source_feedback_compiles_to_source_trust_delta(self):
        feedback = ScopedFeedback(
            episode_id="ep-1",
            raw_signal="thumbs_down",
            comment="这个来源不可靠",
            object_ref="source:reddit",
            object_type="source",
        )

        analysis = ContextualIntentCompiler().compile(feedback, episode={})

        self.assertEqual("source_preference", analysis.agent_readable_intent_delta.target)
        self.assertIn("source:reddit", analysis.affected_objects)
        self.assertIn("source", analysis.agent_readable_intent_delta.instruction.lower())

    def test_unscoped_feedback_stays_weak_episode_signal(self):
        feedback = ScopedFeedback(
            episode_id="ep-1",
            raw_signal="thumbs_down",
            comment="这个不对",
        )

        analysis = ContextualIntentCompiler().compile(feedback, episode={})

        self.assertEqual("episode_diagnosis", analysis.agent_readable_intent_delta.target)
        self.assertEqual("low", analysis.confidence)
        self.assertEqual("episode_only", analysis.persistence_level)
        self.assertIn("needs_localization", analysis.ambiguities)


if __name__ == "__main__":
    unittest.main()
