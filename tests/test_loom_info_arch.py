import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "loom"))


class StateEngineTests(unittest.TestCase):

    def _make_goal(self, stances=None):
        from loom.brain_harness.goal_context import GoalContext, SynthesisSnapshot
        goal = GoalContext.new(goal_type="ad_hoc", title="Test Goal")
        for s in (stances or []):
            snap = SynthesisSnapshot(
                episode_id="ep-1",
                ts="2026-06-11T10:00:00Z",
                stance=s["stance"],
                confidence=s["confidence"],
                reversal_condition=s.get("reversal_condition", ""),
            )
            goal.append_synthesis(snap)
        return goal

    def test_build_state_engine_shape(self):
        from loom.brain import _build_state_engine

        goal = self._make_goal([
            {"stance": "hold", "confidence": 0.6},
            {"stance": "buy", "confidence": 0.75, "reversal_condition": "CPI > 4%"},
        ])

        fw_record = MagicMock()
        fw_record.episode_id = "ep-test"
        fw_record.domain = "equities"

        synthesis = {
            "stance": "buy",
            "confidence": 0.75,
            "key_drivers": [{"hand": "market", "claim": "rates falling", "rule": "rule-1"}],
            "regime_relevance": "pivot regime",
            "watch_conditions": ["CPI", "NFP"],
            "priority_signal": "Watch CPI next print",
        }

        result = _build_state_engine(goal, fw_record, synthesis, None, None)

        self.assertIn("goal", result)
        self.assertIn("flywheel", result)
        self.assertIn("intent_focus", result)
        self.assertIn("reward", result)
        self.assertIn("targeted_abstract", result)

        self.assertEqual(result["goal"]["title"], "Test Goal")
        self.assertEqual(len(result["goal"]["stance_history"]), 2)
        self.assertEqual(result["goal"]["stance_history"][-1]["stance"], "buy")
        self.assertEqual(result["goal"]["latest_reversal"], "CPI > 4%")
        self.assertEqual(result["flywheel"]["domain"], "equities")
        self.assertEqual(result["targeted_abstract"]["priority_signal"], "Watch CPI next print")
        self.assertEqual(result["targeted_abstract"]["watch_conditions"], ["CPI", "NFP"])

    def test_build_state_engine_handles_none_activation_and_reward(self):
        from loom.brain import _build_state_engine

        goal = self._make_goal()
        fw_record = MagicMock()
        fw_record.episode_id = "ep-2"
        fw_record.domain = "macro"

        synthesis = {"stance": "n/a", "confidence": 0.0, "key_drivers": []}

        result = _build_state_engine(goal, fw_record, synthesis, None, None)
        self.assertEqual(result["intent_focus"]["active_nodes"], [])
        self.assertIsNone(result["reward"]["latest_score"])

    def test_render_state_engine_returns_html_with_key_elements(self):
        from loom.brain import _build_state_engine, _render_state_engine

        goal = self._make_goal([{"stance": "buy", "confidence": 0.8, "reversal_condition": "CPI > 4%"}])
        fw_record = MagicMock()
        fw_record.episode_id = "ep-3"
        fw_record.domain = "equities"

        synthesis = {
            "stance": "buy",
            "confidence": 0.8,
            "key_drivers": [],
            "regime_relevance": "rate cut cycle",
            "watch_conditions": ["CPI", "PCE"],
            "priority_signal": "Monitor rate trajectory",
        }

        se = _build_state_engine(goal, fw_record, synthesis, None, None)
        html = _render_state_engine(se)

        self.assertIn('data-anc="brain-state-engine"', html)
        self.assertIn("状态推理", html)
        self.assertIn("Monitor rate trajectory", html)
        self.assertIn("anc-detail", html)


class RawRenderingTests(unittest.TestCase):

    def test_render_raw_sources_empty(self):
        from loom.brain import _render_raw_sources
        html = _render_raw_sources({"raw_sources": []})
        self.assertEqual(html, "")

    def test_render_raw_sources_with_json_entry(self):
        from loom.brain import _render_raw_sources
        art = {
            "raw_sources": [
                {
                    "resource_id": "fred",
                    "fetched_at": "2026-06-11T10:00:00Z",
                    "content_type": "json",
                    "summary": "10Y Treasury 4.52%",
                    "raw": {"rate": 4.52},
                }
            ]
        }
        html = _render_raw_sources(art)
        self.assertIn("fred", html)
        self.assertIn("10Y Treasury 4.52%", html)
        self.assertIn('data-layer-type="raw_source"', html)

    def test_render_raw_items_empty(self):
        from loom.brain import _render_raw_items
        html = _render_raw_items({"raw_items": []})
        self.assertEqual(html, "")

    def test_render_raw_items_news_and_data_point(self):
        from loom.brain import _render_raw_items
        art = {
            "raw_items": [
                {
                    "item_type": "news",
                    "title": "Fed holds rates",
                    "source": "Reuters",
                    "tier": "C",
                    "published_at": "2026-06-10",
                    "summary": "Fed kept rates unchanged.",
                    "relevance": "regime signal",
                },
                {
                    "item_type": "data_point",
                    "label": "10Y Treasury",
                    "value": "4.52%",
                    "source": "FRED",
                    "tier": "A",
                    "freshness": "2026-06-10",
                    "relevance": "rate anchor",
                },
            ]
        }
        html = _render_raw_items(art)
        self.assertIn("Fed holds rates", html)
        self.assertIn("4.52%", html)
        self.assertIn('data-layer-type="raw_item"', html)
        self.assertIn("regime signal", html)

    def test_render_artifact_includes_agent_detail_section(self):
        from loom.brain import _render_artifact

        artifact = {
            "metadata": {
                "hand_id": "runtime-risk-agent-0",
                "executor_id": "brain-inline",
                "task_id": "t1",
                "dimension": "Risk synthesis",
                "system_prompt": "You are a runtime risk analyzer. Focus on failure modes.",
                "capabilities": ["portfolio"],
                "confidence": 0.8,
                "key_claims": ["Risk is concentrated"],
                "gaps": [],
            },
            "narrative": "Risk agent result.",
            "sections": [],
            "evidence": [],
        }

        html = _render_artifact(artifact, "t1")

        self.assertIn('data-detail-section="agents"', html)
        self.assertIn('data-detail-label="Agent"', html)
        self.assertIn("runtime-risk-agent-0", html)
        self.assertIn("brain-inline", html)
        self.assertIn("Risk synthesis", html)
        self.assertIn("runtime risk analyzer", html.lower())


if __name__ == "__main__":
    unittest.main()
