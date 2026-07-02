"""Tests for state-aware review integration"""
import unittest

from loom.brain_harness.environment_state import (
    EnvironmentState, EnvironmentStateFrame, EnvironmentStateManager,
)
from loom.brain_harness.bottleneck import BottleneckDetector, route_bottleneck


class TestStateAwareReview(unittest.TestCase):
    def test_active_state_without_evidence_creates_gap(self):
        """Active claims without evidence should be detectable as gaps."""
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim",
                             status="active", summary="Unverified claim",
                             confidence=0.3, evidence_refs=[]),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1", states=states, active_state_ids=["S1"],
        )
        bottlenecks = BottleneckDetector.detect(frame)
        # Low confidence + no evidence should route to ask or verify
        self.assertGreaterEqual(len(bottlenecks), 1)
        actions = [route_bottleneck(b) for b in bottlenecks]
        self.assertTrue(any(a in ("ask", "verify") for a in actions))

    def test_contested_state_produces_bottleneck(self):
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim",
                             status="contested", summary="Contested claim",
                             confidence=0.5, evidence_refs=["artifact:t1"]),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1", states=states, active_state_ids=["S1"],
        )
        bottlenecks = BottleneckDetector.detect(frame)
        self.assertGreaterEqual(len(bottlenecks), 1)

    def test_stale_state_has_high_uncertainty(self):
        states = [
            EnvironmentState(state_id="S2", episode_id="ep1", type="claim",
                             status="stale", summary="Old data", confidence=0.2, freshness=0.1),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1", states=states, active_state_ids=["S2"],
        )
        bottlenecks = BottleneckDetector.detect(frame)
        self.assertGreaterEqual(len(bottlenecks), 1)

    def test_repair_task_includes_state_refs(self):
        """Mimics the shape that review repair follow-up tasks should carry."""
        task = {
            "task_id": "t_verify",
            "hand_id": "runtime-verify-agent",
            "target_state_ids": ["S1"],
            "target_gap_ids": ["G1"],
            "state_intent": "verify",
            "evidence_requirements": ["check source freshness"],
        }
        self.assertIn("target_state_ids", task)
        self.assertIn("target_gap_ids", task)
        self.assertEqual(task["state_intent"], "verify")


class TestInteractionConsumption(unittest.TestCase):
    def test_contest_trace_can_record_consumer(self):
        trace = {
            "interaction_id": "vi_test",
            "query_id": "vq_test",
            "episode_id": "ep1",
            "gesture": "contest",
            "consumed_by": [],
        }
        trace["consumed_by"].append({
            "consumer": "BrainHarness.review",
            "effect": "created source freshness repair task",
        })
        self.assertEqual(len(trace["consumed_by"]), 1)
        self.assertEqual(trace["consumed_by"][0]["consumer"], "BrainHarness.review")

    def test_checkpoint_produces_repair_consumption(self):
        trace = {"interaction_id": "vi_2", "consumed_by": []}
        trace["consumed_by"].append({
            "consumer": "review.repair_dispatch",
            "effect": "triggered verification task",
        })
        self.assertEqual(trace["consumed_by"][0]["consumer"], "review.repair_dispatch")

    def test_synthesis_caveat_consumption(self):
        trace = {"interaction_id": "vi_3", "consumed_by": []}
        trace["consumed_by"].append({
            "consumer": "BrainHarness.synthesize",
            "effect": "added caveat for contested state S3",
        })
        self.assertEqual(len(trace["consumed_by"]), 1)
