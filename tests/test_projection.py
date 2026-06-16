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
from loom.brain_harness.base import BrainHarness
from loom.brain_harness.state import BrainState
from loom.brain_harness.intent_wiki import IntentActivation
from loom.brain_harness.intent_harness import RubricSpec


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
    activation = IntentActivation(
        ts="2026-06-13T00:00:00",
        run_id="run-test",
        question="",
        domain="general",
        active_intents=[],
        inactive_intents=[],
    )
    rubric = RubricSpec(
        ts="2026-06-13T00:00:00",
        rubric_id="rubric-test",
        domain="general",
        question="",
        criteria=[],
        suppressed_policies=[],
    )

    # BrainState
    harness.state = MagicMock()
    harness.state._reload = MagicMock(return_value=None)
    harness.state.query_rules = MagicMock(return_value=[])
    harness.state.query_frameworks = MagicMock(return_value=[])
    harness.state.query_notes = MagicMock(return_value=[])
    harness.state.get_state_version = MagicMock(return_value=0)
    harness.resource_registry = None

    # IntentStream — None by default
    harness._intent_stream = None

    # IntentWiki
    harness.intent_wiki = MagicMock()
    harness.intent_wiki.activate = MagicMock(return_value=activation)

    # RewardedIntentHarness
    harness.rewarded_intent_harness = MagicMock()
    harness.rewarded_intent_harness.compile_rubric = MagicMock(return_value=rubric)

    # Side-effect storage
    harness._last_intent_activation = None
    harness._last_policy_plan = None
    harness._last_intent_rubric = None

    return harness


class TestBuildProjection(unittest.TestCase):
    EXPECTED_SECTIONS = {
        "brain_md",
        "strategy_rules",
        "frameworks",
        "intent_stream",
        "intent_activation",
        "intent_rubric",
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
        sentinel = IntentActivation(
            ts="2026-06-13T00:00:00",
            run_id="run-sentinel",
            question="x",
            domain="general",
            active_intents=[{"intent_id": "intent.test", "zone": "content_requirements"}],
            inactive_intents=[],
        )
        harness.intent_wiki.activate = MagicMock(return_value=sentinel)
        build_projection(harness, domain="equities", question="x")
        assert harness._last_intent_activation is sentinel

    def test_intent_rubric_stored_on_harness(self):
        harness = _make_mock_harness()
        sentinel = RubricSpec(
            ts="2026-06-13T00:00:00",
            rubric_id="rubric-sentinel",
            domain="general",
            question="x",
            criteria=[],
            suppressed_policies=[],
        )
        harness.rewarded_intent_harness.compile_rubric = MagicMock(return_value=sentinel)
        build_projection(harness, domain="equities", question="x")
        assert harness._last_intent_rubric is sentinel
        assert harness._last_policy_plan is None

    def test_resource_context_is_passed_to_rubric_compiler(self):
        harness = _make_mock_harness()
        resource_context = {
            "resources": [{"resource_id": "res-1"}],
            "strategy_primitives": [{"primitive_id": "sp-1"}],
        }
        harness.resource_registry = MagicMock()
        harness.resource_registry.query_rubric_context = MagicMock(return_value=resource_context)

        build_projection(harness, domain="loom-fin", question="AI capex")

        harness.resource_registry.query_rubric_context.assert_called_once_with(
            domain="loom-fin",
            question="AI capex",
            limit=5,
        )
        self.assertEqual(
            resource_context,
            harness.rewarded_intent_harness.compile_rubric.call_args.kwargs["resource_context"],
        )

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
        harness.rewarded_intent_harness.compile_rubric = MagicMock(
            return_value=RubricSpec(
                ts="2026-06-13T00:00:00",
                rubric_id="rubric-changed",
                domain="general",
                question="What now?",
                criteria=[{"criterion_id": "rubric.source_fit", "weight": 0.4}],
                suppressed_policies=[],
            )
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

    def test_prompt_excludes_evaluator_only_intent_metadata(self):
        import tempfile

        sections = {
            "brain_md": "Brain role contract",
            "strategy_rules": [],
            "frameworks": [],
            "intent_stream": "SHOULD_NOT_REACH_PROMPT",
            "intent_activation": {"active_intents": [{"intent_id": "intent.hidden"}]},
            "intent_rubric": {"criteria": [{"criterion_id": "rubric.hidden"}]},
            "learned_notes": [],
            "last_synthesis": "",
            "intent_context": {"decision_context": "compact"},
            "recent_intents": [{"raw_input": "hidden"}],
        }
        projection = Projection(
            content_id="sha256:test",
            state_version=0,
            schema_version="1.0",
            sections=sections,
            materialized_at="2026-06-13T00:00:00Z",
        )

        with tempfile.TemporaryDirectory() as tmp:
            harness = BrainHarness(Path(tmp))
            prompt = harness._prompt_from_projection(projection, domain="general")
            state_context = harness.select_state_context(
                domain="general",
                question="x",
                context={},
                projection=projection,
            )

        assert "SHOULD_NOT_REACH_PROMPT" not in prompt
        assert "intent.hidden" not in prompt
        assert "rubric.hidden" not in prompt
        assert "intent_stream" not in state_context
        assert "intent_activation" not in state_context
        assert "intent_rubric" not in state_context
        assert "recent_intents" not in state_context


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
