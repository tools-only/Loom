"""Tests for bottleneck.py"""
import unittest

from loom.brain_harness.environment_state import EnvironmentState, EnvironmentStateFrame
from loom.brain_harness.bottleneck import (
    EpistemicBottleneck,
    BottleneckDetector,
    route_bottleneck,
)


class TestRouteBottleneck(unittest.TestCase):
    def test_high_impact_high_answerability_low_cost_routes_to_ask(self):
        b = EpistemicBottleneck(
            bottleneck_id="B1", anchor_type="claim", anchor_id="S1",
            uncertainty=0.6, impact=0.9,
            human_answerability=0.8, agent_verifiability=0.3,
            interaction_cost=0.15, repair_cost_if_wrong=0.5,
        )
        self.assertEqual(route_bottleneck(b), "ask")

    def test_high_impact_high_agent_verifiability_routes_to_verify(self):
        b = EpistemicBottleneck(
            bottleneck_id="B2", anchor_type="claim", anchor_id="S2",
            uncertainty=0.6, impact=0.8,
            human_answerability=0.3, agent_verifiability=0.6,
            interaction_cost=0.5, repair_cost_if_wrong=0.5,
        )
        self.assertEqual(route_bottleneck(b), "verify")

    def test_low_impact_routes_to_use(self):
        b = EpistemicBottleneck(
            bottleneck_id="B3", anchor_type="claim", anchor_id="S3",
            uncertainty=0.1, impact=0.2,
            human_answerability=0.5, agent_verifiability=0.5,
            interaction_cost=0.5, repair_cost_if_wrong=0.5,
        )
        self.assertEqual(route_bottleneck(b), "use")

    def test_high_repair_cost_routes_to_ask(self):
        b = EpistemicBottleneck(
            bottleneck_id="B4", anchor_type="claim", anchor_id="S4",
            uncertainty=0.5, impact=0.5,
            human_answerability=0.4, agent_verifiability=0.3,
            interaction_cost=0.5, repair_cost_if_wrong=0.8,
        )
        self.assertEqual(route_bottleneck(b), "ask")

    def test_default_fallback_routes_to_defer(self):
        b = EpistemicBottleneck(
            bottleneck_id="B5", anchor_type="claim", anchor_id="S5",
            uncertainty=0.4, impact=0.5,
            human_answerability=0.3, agent_verifiability=0.3,
            interaction_cost=0.5, repair_cost_if_wrong=0.3,
        )
        self.assertEqual(route_bottleneck(b), "defer")


class TestBottleneckDetector(unittest.TestCase):
    def test_detect_creates_bottlenecks_from_frame(self):
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim",
                             status="active", summary="Claim A", confidence=0.3, salience=0.8),
            EnvironmentState(state_id="S2", episode_id="ep1", type="gap",
                             status="active", summary="Gap B", confidence=0.2, salience=0.9),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1", states=states, active_state_ids=["S1", "S2"],
        )
        bottlenecks = BottleneckDetector.detect(frame)
        self.assertGreaterEqual(len(bottlenecks), 2)
        actions = {b.recommended_action for b in bottlenecks}
        self.assertIn("ask", actions)

    def test_detect_includes_review_gaps(self):
        states = [EnvironmentState(state_id="S1", episode_id="ep1",
                   type="claim", status="active", summary="X", confidence=0.8, salience=0.3)]
        frame = EnvironmentStateFrame(
            episode_id="ep1", states=states, active_state_ids=["S1"],
        )
        review = {"confidence_gaps": [{"gap": "missing sources"}]}
        bottlenecks = BottleneckDetector.detect(frame, review_result=review)
        self.assertGreaterEqual(len(bottlenecks), 2)
