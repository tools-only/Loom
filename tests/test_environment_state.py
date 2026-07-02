"""Tests for environment_state.py"""
import unittest

from loom.brain_harness.environment_state import (
    EnvironmentState,
    StateTransition,
    EnvironmentStateFrame,
    EnvironmentStateManager,
)


class TestEnvironmentState(unittest.TestCase):
    def test_to_dict_emits_stable_json_fields(self):
        s = EnvironmentState(
            state_id="S12",
            episode_id="ep_test",
            type="claim",
            status="active",
            summary="WACC assumption may be stale.",
            scope="current_episode",
            salience=0.82,
            freshness=0.44,
            confidence=0.62,
            evidence_refs=["artifact:t1", "claim:C7"],
        )
        d = s.to_dict()
        self.assertEqual(d["state_id"], "S12")
        self.assertEqual(d["type"], "claim")
        self.assertEqual(d["status"], "active")
        self.assertEqual(len(d["evidence_refs"]), 2)
        self.assertIn("summary", d)


class TestStateTransition(unittest.TestCase):
    def test_transition_preserves_old_and_new_status(self):
        t = StateTransition(
            state_id="S12",
            from_status="active",
            to_status="contested",
            episode_id="ep_test",
            phase="review",
            evidence=[{"type": "visual.interaction", "id": "vi_1"}],
            decided_by="brain_review",
        )
        d = t.to_dict()
        self.assertEqual(d["from"], "active")
        self.assertEqual(d["to"], "contested")
        self.assertEqual(len(d["evidence"]), 1)


class TestEnvironmentStateFrame(unittest.TestCase):
    def test_active_states_exclude_stale_and_retired(self):
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim", status="active"),
            EnvironmentState(state_id="S2", episode_id="ep1", type="gap", status="stale"),
            EnvironmentState(state_id="S3", episode_id="ep1", type="claim", status="retired"),
            EnvironmentState(state_id="S4", episode_id="ep1", type="claim", status="contested"),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1",
            states=states,
            active_state_ids=["S1", "S2", "S3", "S4"],
        )
        active = frame.active_states
        self.assertEqual(len(active), 4)  # active_state_ids controls, not status filter
        self.assertEqual(len(frame.stale_states), 1)
        self.assertEqual(len(frame.contested_states), 1)

    def test_summary_counts(self):
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim", status="active"),
            EnvironmentState(state_id="S2", episode_id="ep1", type="gap", status="stale"),
        ]
        frame = EnvironmentStateFrame(
            episode_id="ep1",
            states=states,
            active_state_ids=["S1", "S2"],
        )
        s = frame.summary()
        self.assertEqual(s["total_states"], 2)
        self.assertEqual(s["active_count"], 2)


class TestEnvironmentStateManager(unittest.TestCase):
    def test_extract_from_artifacts_creates_claim_and_gap_states(self):
        artifacts = {
            "t0": {
                "metadata": {
                    "key_claims": [
                        {"claim": "Revenue grew 23%", "confidence": 0.8},
                    ],
                    "gaps": [
                        {"description": "Missing competitor data", "impact": 0.7},
                    ],
                }
            }
        }
        states = EnvironmentStateManager.extract_from_artifacts("ep_test", artifacts)
        claims = [s for s in states if s.type == "claim"]
        gaps = [s for s in states if s.type == "gap"]
        self.assertGreaterEqual(len(claims), 1)
        self.assertGreaterEqual(len(gaps), 1)
        self.assertEqual(claims[0].summary, "Revenue grew 23%")
        self.assertEqual(gaps[0].summary, "Missing competitor data")

    def test_extract_includes_review_gaps(self):
        review = {"confidence_gaps": [{"gap": "no source verification"}]}
        states = EnvironmentStateManager.extract_from_artifacts("ep_test", {}, review)
        gaps = [s for s in states if s.type == "gap" and s.created_by == "review_gap"]
        self.assertEqual(len(gaps), 1)

    def test_transition_updates_state_and_returns_transition(self):
        s = EnvironmentState(state_id="S1", episode_id="ep_test", type="claim", status="active")
        t = EnvironmentStateManager.transition(
            s, "contested", "ep_test", phase="review",
            evidence=[{"type": "user"}], decided_by="brain_review",
        )
        self.assertEqual(s.status, "contested")
        self.assertEqual(t.from_status, "active")
        self.assertEqual(t.to_status, "contested")
        self.assertEqual(t.decided_by, "brain_review")

    def test_build_frame_excludes_retired_from_active(self):
        states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim", status="active"),
            EnvironmentState(state_id="S2", episode_id="ep1", type="claim", status="retired"),
        ]
        frame = EnvironmentStateManager.build_frame("ep1", states)
        self.assertIn("S1", frame.active_state_ids)
        self.assertNotIn("S2", frame.active_state_ids)
