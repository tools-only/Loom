"""Tests for loom.brain_harness.projection — content-addressed Brain state."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.brain_harness.projection import (
    Projection,
    build_projection,
    canonical_serialize,
    content_id,
)
from loom.brain_harness.state import BrainState


class TestCanonicalSerialize(unittest.TestCase):
    def test_deterministic_order(self):
        assert canonical_serialize({"a": 2, "b": 1}) == canonical_serialize({"b": 1, "a": 2})

    def test_returns_bytes(self):
        assert isinstance(canonical_serialize({"x": 1}), bytes)

    def test_nested_order_independent(self):
        a = canonical_serialize({"outer": {"a": 1, "b": 2}, "x": [1, 2]})
        b = canonical_serialize({"x": [1, 2], "outer": {"b": 2, "a": 1}})
        assert a == b

    def test_normalizes_iso_timestamps(self):
        # T-separator + Z + microseconds should normalize to the same hash
        a = canonical_serialize({"ts": "2026-06-13T10:00:00.123456Z"})
        b = canonical_serialize({"ts": "2026-06-13 10:00:00"})
        assert a == b


class TestContentId(unittest.TestCase):
    def test_format(self):
        cid = content_id({"x": 1})
        assert cid.startswith("sha256:")
        assert len(cid) == len("sha256:") + 16

    def test_stable(self):
        assert content_id({"x": 1}) == content_id({"x": 1})

    def test_different_data_different_id(self):
        assert content_id({"x": 1}) != content_id({"x": 2})

    def test_order_independent(self):
        assert content_id({"a": 1, "b": 2}) == content_id({"b": 2, "a": 1})


def _make_mock_harness(tmp_root: Path | None = None) -> MagicMock:
    """Build a minimal harness mock that satisfies build_projection."""
    harness = MagicMock()
    harness.root = tmp_root or Path(".")

    # BrainState
    harness.state = MagicMock()
    harness.state._reload = MagicMock(return_value=None)
    harness.state.query_rules = MagicMock(return_value=[])
    harness.state.query_frameworks = MagicMock(return_value=[])
    harness.state.query_notes = MagicMock(return_value=[])
    harness.state.get_state_version = MagicMock(return_value=0)

    # IntentStream — None by default
    harness._intent_stream = None

    # IntentWiki
    harness.intent_wiki = MagicMock()
    harness.intent_wiki.activate = MagicMock(return_value=MagicMock())
    harness.intent_wiki.format_activation_for_prompt = MagicMock(return_value="")

    # RewardedIntentHarness
    harness.rewarded_intent_harness = MagicMock()
    harness.rewarded_intent_harness.plan = MagicMock(return_value=MagicMock())
    harness.rewarded_intent_harness.format_plan_for_prompt = MagicMock(return_value="")

    # Side-effect storage
    harness._last_intent_activation = None
    harness._last_policy_plan = None

    return harness


class TestBuildProjection(unittest.TestCase):
    EXPECTED_SECTIONS = {
        "brain_md",
        "strategy_rules",
        "frameworks",
        "intent_stream",
        "intent_wiki",
        "policy_plan",
        "learned_notes",
        "last_synthesis",
        "intent_context",
        "recent_intents",
    }

    def test_returns_projection_with_10_sections(self):
        harness = _make_mock_harness()
        result = build_projection(harness, domain="equities", question="What now?")
        assert isinstance(result, Projection)
        assert set(result.sections.keys()) == self.EXPECTED_SECTIONS
        assert len(result.sections) == 10

    def test_content_id_starts_with_sha256(self):
        harness = _make_mock_harness()
        result = build_projection(harness, domain="equities", question="What now?")
        assert result.content_id.startswith("sha256:")
        assert len(result.content_id) == len("sha256:") + 16

    def test_schema_version_is_1_0(self):
        harness = _make_mock_harness()
        result = build_projection(harness, domain="equities", question="x")
        assert result.schema_version == "1.0"

    def test_state_version_defaults_to_zero_when_missing(self):
        harness = _make_mock_harness()
        # Remove get_state_version to simulate older BrainState without the attr.
        del harness.state.get_state_version
        result = build_projection(harness, domain="equities", question="x")
        assert result.state_version == 0

    def test_state_version_uses_harness_value(self):
        harness = _make_mock_harness()
        harness.state.get_state_version = MagicMock(return_value=42)
        result = build_projection(harness, domain="equities", question="x")
        assert result.state_version == 42

    def test_materialized_at_is_iso_utc(self):
        harness = _make_mock_harness()
        result = build_projection(harness, domain="equities", question="x")
        assert result.materialized_at.endswith("Z")
        # YYYY-MM-DDTHH:MM:SS(.ffffff)?Z
        assert "T" in result.materialized_at

    def test_state_reload_is_called(self):
        harness = _make_mock_harness()
        build_projection(harness, domain="equities", question="x")
        harness.state._reload.assert_called_once()

    def test_intent_wiki_activation_stored_on_harness(self):
        harness = _make_mock_harness()
        sentinel = MagicMock(name="activation")
        harness.intent_wiki.activate = MagicMock(return_value=sentinel)
        build_projection(harness, domain="equities", question="x")
        assert harness._last_intent_activation is sentinel

    def test_policy_plan_stored_on_harness(self):
        harness = _make_mock_harness()
        sentinel = MagicMock(name="policy_plan")
        harness.rewarded_intent_harness.plan = MagicMock(return_value=sentinel)
        build_projection(harness, domain="equities", question="x")
        assert harness._last_policy_plan is sentinel

    def test_content_id_stable_same_state(self):
        harness = _make_mock_harness()
        a = build_projection(harness, domain="equities", question="What now?")
        b = build_projection(harness, domain="equities", question="What now?")
        # materialized_at differs across calls but is not part of sections;
        # the content_id is computed only over sections, so it must be stable.
        assert a.content_id == b.content_id

    def test_content_id_changes_when_sections_change(self):
        harness = _make_mock_harness()
        a = build_projection(harness, domain="equities", question="What now?")
        harness.intent_wiki.format_activation_for_prompt = MagicMock(
            return_value="ACTIVE INTENT: prefer fresh sources"
        )
        b = build_projection(harness, domain="equities", question="What now?")
        assert a.content_id != b.content_id

    def test_intent_stream_none_yields_empty_defaults(self):
        harness = _make_mock_harness()
        # _intent_stream is None by default in the mock factory
        result = build_projection(harness, domain="equities", question="x")
        assert result.sections["intent_stream"] == ""
        assert result.sections["intent_context"] == {}
        assert result.sections["recent_intents"] == []


class TestBrainStateVersion(unittest.TestCase):
    def test_append_note_increments_state_version(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state = BrainState(Path(tmp))
            before = state.get_state_version()

            state.append_note("general", "prefer source-backed detail")

            self.assertEqual(before + 1, state.get_state_version())

    def test_append_framework_increments_state_version(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state = BrainState(Path(tmp))
            before = state.get_state_version()

            state.append_framework({
                "framework_id": "fw-1",
                "name": "Framework",
                "key_variables": [],
                "decision_logic": "Use evidence.",
                "weight_hints": {},
                "failure_conditions": [],
                "confidence": "medium",
                "tags": [],
                "distilled_at": "2026-06-13T00:00:00",
            })

            self.assertEqual(before + 1, state.get_state_version())


if __name__ == "__main__":
    unittest.main()
