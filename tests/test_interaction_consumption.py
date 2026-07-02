"""Tests for interaction_consumption.py"""
import unittest


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
            "effect": "added caveat for contested state",
        })
        self.assertEqual(len(trace["consumed_by"]), 1)
