"""Tests for synthesis_guard.py"""
import unittest

from loom.brain_harness.environment_state import EnvironmentState, EnvironmentStateFrame
from loom.brain_harness.synthesis_guard import SynthesisGuard


class TestSynthesisGuard(unittest.TestCase):
    def setUp(self):
        self.states = [
            EnvironmentState(state_id="S1", episode_id="ep1", type="claim",
                             status="active", summary="Claim A"),
            EnvironmentState(state_id="S2", episode_id="ep1", type="claim",
                             status="contested", summary="Contested B"),
            EnvironmentState(state_id="S3", episode_id="ep1", type="claim",
                             status="stale", summary="Stale C"),
            EnvironmentState(state_id="S4", episode_id="ep1", type="claim",
                             status="verifying", summary="Verifying D"),
            EnvironmentState(state_id="S5", episode_id="ep1", type="claim",
                             status="resolved", summary="Resolved E"),
        ]
        self.frame = EnvironmentStateFrame(
            episode_id="ep1", states=self.states,
            active_state_ids=["S1", "S2", "S3", "S4", "S5"],
        )

    def test_contested_states_get_caveat(self):
        result = SynthesisGuard.build_constraints(self.frame)
        caveats = [c for c in result.constraints if c.constraint_type == "caveat"]
        self.assertGreaterEqual(len(caveats), 1)
        self.assertIn("S2", [c.state_id for c in caveats])

    def test_stale_states_require_refresh(self):
        result = SynthesisGuard.build_constraints(self.frame)
        refresh = [c for c in result.constraints if c.constraint_type == "refresh_required"]
        self.assertGreaterEqual(len(refresh), 1)
        self.assertIn("S3", [c.state_id for c in refresh])

    def test_verifying_states_require_pending(self):
        result = SynthesisGuard.build_constraints(self.frame)
        pending = [c for c in result.constraints if c.constraint_type == "pending"]
        self.assertGreaterEqual(len(pending), 1)
        self.assertIn("S4", [c.state_id for c in pending])

    def test_resolved_and_active_states_are_allowed(self):
        result = SynthesisGuard.build_constraints(self.frame)
        self.assertIn("S1", result.allowed_state_ids)
        self.assertIn("S5", result.allowed_state_ids)

    def test_guard_prompt_generates_constraint_lines(self):
        result = SynthesisGuard.build_constraints(self.frame)
        prompt = SynthesisGuard.guard_prompt(result)
        self.assertIn("caveat", prompt)
        self.assertIn("Contested B", prompt)

    def test_empty_frame_produces_no_constraints(self):
        frame = EnvironmentStateFrame(episode_id="ep2")
        result = SynthesisGuard.build_constraints(frame)
        self.assertEqual(len(result.constraints), 0)
        self.assertEqual(SynthesisGuard.guard_prompt(result), "")
