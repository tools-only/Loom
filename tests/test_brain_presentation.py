import tempfile
import unittest
from pathlib import Path

from loom.brain_harness.base import BrainHarness


class BrainPresentationTests(unittest.TestCase):
    def test_compose_presentation_normalizes_hand_outputs_for_ui_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = BrainHarness(Path(tmp))
            synthesis = {
                "stance": "hold",
                "confidence": 0.72,
                "key_drivers": [
                    {"rule": "risk", "hand": "market", "claim": "Volatility is elevated"}
                ],
                "reversal_condition": "VIX compression with breadth recovery",
                "strategy_refs": ["risk"],
                "clarifying_question": None,
            }
            hand_artifacts = {
                "market": {
                    "metadata": {
                        "hand_id": "runtime-market-risk-0",
                        "executor_id": "market",
                        "task_id": "t1",
                        "dimension": "Market risk",
                        "system_prompt": "You assess market regime risk and summarize the evidence.",
                        "capabilities": ["market_data"],
                        "confidence": 0.7,
                        "key_claims": ["Volatility is elevated", "Breadth is weak", "Rates are mixed"],
                        "source_notes": [
                            {"source": "market-feed", "tier": "A", "freshness": "today", "note": "index data"}
                        ],
                        "gaps": [],
                    },
                    "narrative": "Market regime is cautious.",
                    "sections": [
                        {
                            "id": "macro",
                            "title": "Macro support",
                            "summary": "Rates and volatility are the main constraints.",
                            "bullets": ["VIX elevated", "yields mixed", "breadth weak"],
                        }
                    ],
                    "evidence": [
                        {
                            "claim": "Volatility is elevated",
                            "support": "VIX remains above recent baseline",
                            "source": "market-feed",
                            "source_tier": "A",
                            "freshness": "today",
                            "confidence": 0.7,
                        }
                    ],
                }
            }
            spec = {
                "version": "brain.presentation.v1",
                "domain": "market",
                "ui_contract": {
                    "visible_layer": {},
                    "detail_layer": {
                        "card_detail_schema": [
                            {"id": "judgment"},
                            {"id": "drivers"},
                            {"id": "evidence"},
                            {"id": "implications"},
                            {"id": "gaps"},
                            {"id": "watchlist"},
                        ]
                    },
                },
                "hand_specs": {"market": {"visible_role": "regime card"}},
                "state_context": {"intent_context": {"decision_context": "compare before action"}},
            }

            presentation = harness.compose_presentation(
                question="today market brief",
                synthesis=synthesis,
                hand_artifacts=hand_artifacts,
                workflow_decision={"domain": "market", "mode": "dynamic", "hands": ["market"]},
                presentation_spec=spec,
            )

            self.assertEqual("brain.presentation.v1", presentation["version"])
            self.assertEqual("hold", presentation["overview"]["stance"])
            self.assertEqual("compare before action", presentation["state_context"]["intent_context"]["decision_context"])
            self.assertEqual(["market"], [card["hand_id"] for card in presentation["cards"]])
            self.assertEqual("Market regime is cautious.", presentation["cards"][0]["visible_summary"])
            self.assertNotIn("key_claims", presentation["cards"][0])
            self.assertIn("market", presentation["detail_panels"])
            self.assertEqual(
                ["judgment", "drivers", "evidence", "implications", "gaps", "watchlist"],
                [layer["id"] for layer in presentation["detail_panels"]["market"]["layers"]],
            )
            for layer in presentation["detail_panels"]["market"]["layers"]:
                self.assertIn("provenance", layer)
                self.assertTrue(layer["provenance"])
            self.assertEqual("macro", presentation["detail_panels"]["market"]["sections"][0]["id"])
            self.assertEqual("Volatility is elevated", presentation["detail_panels"]["market"]["evidence"][0]["claim"])
            agents = presentation["detail_panels"]["market"]["agents"]
            self.assertEqual(1, len(agents))
            self.assertEqual("runtime-market-risk-0", agents[0]["hand_id"])
            self.assertEqual("market", agents[0]["executor_id"])
            self.assertEqual("Market risk", agents[0]["dimension"])
            self.assertEqual(
                "Assess market regime risk and summarize the evidence.",
                agents[0]["responsibility"],
            )


if __name__ == "__main__":
    unittest.main()
