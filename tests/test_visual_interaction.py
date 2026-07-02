"""Tests for visual_interaction.py"""
import unittest

from loom.brain_harness.bottleneck import EpistemicBottleneck
from loom.brain_harness.visual_interaction import (
    VisualQuery,
    VisualInteractionTrace,
    VisualQueryCompiler,
    VisualInteractionInterpreter,
)


class TestVisualQuery(unittest.TestCase):
    def test_to_dict_includes_all_fields(self):
        q = VisualQuery(
            query_id="vq_test", episode_id="ep1", bottleneck_id="B1",
            query_type="evidence_trust", anchor_type="claim", anchor_id="S1",
        )
        d = q.to_dict()
        self.assertEqual(d["query_id"], "vq_test")
        self.assertIn("allowed_interactions", d)


class TestVisualInteractionTrace(unittest.TestCase):
    def test_to_dict_starts_empty_consumed_by(self):
        t = VisualInteractionTrace(
            interaction_id="vi_1", query_id="vq_1", episode_id="ep1",
        )
        d = t.to_dict()
        self.assertEqual(len(d["consumed_by"]), 0)

    def test_mark_consumed_appends_without_mutating_original(self):
        t = VisualInteractionTrace(
            interaction_id="vi_1", query_id="vq_1", episode_id="ep1",
        )
        t.mark_consumed("BrainHarness.review", "created repair task")
        self.assertEqual(len(t.consumed_by), 1)
        self.assertEqual(t.consumed_by[0]["consumer"], "BrainHarness.review")


class TestVisualQueryCompiler(unittest.TestCase):
    def test_compiles_only_ask_bottlenecks(self):
        bottlenecks = [
            EpistemicBottleneck(
                bottleneck_id="B1", anchor_type="claim", anchor_id="S1",
                uncertainty=0.7, impact=0.9,
                human_answerability=0.8, agent_verifiability=0.3,
                interaction_cost=0.1, repair_cost_if_wrong=0.5,
            ),
            EpistemicBottleneck(
                bottleneck_id="B2", anchor_type="claim", anchor_id="S2",
                uncertainty=0.1, impact=0.2,
            ),
        ]
        # B1 should route to ask
        from loom.brain_harness.bottleneck import route_bottleneck
        for b in bottlenecks:
            b.recommended_action = route_bottleneck(b)
        self.assertEqual(bottlenecks[0].recommended_action, "ask")
        self.assertEqual(bottlenecks[1].recommended_action, "use")

        queries = VisualQueryCompiler.compile("ep1", bottlenecks)
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].bottleneck_id, "B1")

    def test_compiles_gap_to_gap_salience(self):
        from loom.brain_harness.bottleneck import route_bottleneck
        b = EpistemicBottleneck(
            bottleneck_id="B3", anchor_type="gap", anchor_id="S3",
            uncertainty=0.7, impact=0.9,
            human_answerability=0.8, agent_verifiability=0.3,
            interaction_cost=0.1, repair_cost_if_wrong=0.5,
        )
        b.recommended_action = route_bottleneck(b)
        queries = VisualQueryCompiler.compile("ep1", [b])
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].query_type, "gap_salience")


class TestVisualInteractionInterpreter(unittest.TestCase):
    def test_contest_converts_to_evidence_distrust(self):
        trace = VisualInteractionInterpreter.interpret(
            interaction_id="vi_1", query_id="vq_1", episode_id="ep1",
            gesture="contest", anchor_type="claim", anchor_id="S1",
        )
        self.assertEqual(trace.gesture, "contest")
        self.assertEqual(trace.inferred_signals[0]["type"], "evidence_distrust")

    def test_trust_converts_to_provisional_trust(self):
        trace = VisualInteractionInterpreter.interpret(
            interaction_id="vi_2", query_id="vq_2", episode_id="ep1",
            gesture="trust",
        )
        self.assertEqual(trace.inferred_signals[0]["type"], "provisional_trust")
