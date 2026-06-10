import unittest

from loom.hands.base import BaseHand


class HandArtifactDensityTests(unittest.TestCase):
    def test_market_prompt_is_loaded_from_project_root(self):
        prompt = BaseHand("market")._assemble_prompt({})

        self.assertIn("Output Format Override", prompt)
        self.assertIn("Dense Layered Artifact", prompt)

    def test_sparse_artifact_reports_density_gaps(self):
        sparse = {
            "metadata": {
                "confidence": 0.5,
                "key_claims": ["one claim"],
                "source_notes": [],
                "gaps": [],
            },
            "narrative": "Short view.",
            "sections": [
                {"id": "summary", "title": "Summary", "summary": "Thin.", "bullets": ["one"]}
            ],
            "evidence": [],
        }

        gaps = BaseHand._artifact_density_gaps(
            sparse,
            used_resources=["market-feed", "rates-feed"],
            shown_resources=["market-feed", "rates-feed"],
        )

        self.assertTrue(any("key_claims" in gap for gap in gaps))
        self.assertTrue(any("source_notes" in gap for gap in gaps))
        self.assertTrue(any("drill-down sections" in gap for gap in gaps))
        self.assertTrue(any("evidence rows" in gap for gap in gaps))

    def test_dense_artifact_has_no_density_gaps(self):
        dense = {
            "metadata": {
                "confidence": 0.8,
                "key_claims": ["claim 1", "claim 2", "claim 3"],
                "source_notes": [
                    {"source": "market-feed", "tier": "A", "freshness": "today", "note": "used"},
                    {"source": "rates-feed", "tier": "A", "freshness": "today", "note": "used"},
                ],
                "gaps": [],
            },
            "narrative": "Short view.",
            "sections": [
                {"id": "summary", "title": "Summary", "summary": "S.", "bullets": ["a", "b", "c"]},
                {"id": "macro", "title": "Macro", "summary": "S.", "bullets": ["a", "b", "c"]},
                {"id": "rotation", "title": "Rotation", "summary": "S.", "bullets": ["a", "b", "c"]},
                {"id": "gaps", "title": "Gaps", "summary": "S.", "bullets": ["a", "b", "c"]},
            ],
            "evidence": [
                {"claim": "c1", "support": "s", "source": "market-feed", "source_tier": "A", "freshness": "today", "confidence": 0.8},
                {"claim": "c2", "support": "s", "source": "market-feed", "source_tier": "A", "freshness": "today", "confidence": 0.8},
                {"claim": "c3", "support": "s", "source": "rates-feed", "source_tier": "A", "freshness": "today", "confidence": 0.8},
                {"claim": "c4", "support": "s", "source": "rates-feed", "source_tier": "A", "freshness": "today", "confidence": 0.8},
                {"claim": "c5", "support": "s", "source": "market-feed", "source_tier": "A", "freshness": "today", "confidence": 0.8},
            ],
        }

        gaps = BaseHand._artifact_density_gaps(
            dense,
            used_resources=["market-feed", "rates-feed"],
            shown_resources=["market-feed", "rates-feed"],
        )

        self.assertEqual([], gaps)

    def test_normalize_populates_layers_from_sections(self):
        """Artifact with only sections[] gets layers[] populated by shim."""
        art = {
            "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
            "narrative": "test",
            "sections": [
                {"id": "summary", "title": "Summary", "summary": "s", "bullets": ["a"]},
                {"id": "analysis", "title": "Analysis", "summary": "a", "bullets": ["b"]},
            ],
            "evidence": [],
        }
        result = BaseHand._normalize_artifact(art)
        self.assertIn("layers", result)
        self.assertEqual(len(result["layers"]), 2)
        self.assertEqual(result["layers"][0]["layer_type"], "summary")
        self.assertEqual(result["layers"][1]["layer_type"], "analysis")

    def test_normalize_populates_sections_from_layers(self):
        """Artifact with only layers[] gets sections[] populated by shim."""
        art = {
            "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
            "narrative": "test",
            "layers": [
                {"layer_id": "summary", "layer_type": "summary", "title": "Summary", "summary": "s", "items": [{"claim": "c"}]},
                {"layer_id": "gaps", "layer_type": "gaps", "title": "Gaps", "summary": "g", "items": [{"claim": "gap1"}]},
            ],
        }
        result = BaseHand._normalize_artifact(art)
        self.assertIn("sections", result)
        self.assertEqual(len(result["sections"]), 2)
        self.assertEqual(result["sections"][0]["id"], "summary")

    def test_normalize_populates_evidence_from_evidence_layer(self):
        """evidence layer_type items are promoted to top-level evidence[]."""
        art = {
            "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
            "narrative": "test",
            "layers": [
                {
                    "layer_id": "evidence",
                    "layer_type": "evidence",
                    "title": "Evidence",
                    "summary": "",
                    "items": [
                        {"claim": "c1", "support": "s1", "source": "FRED", "source_tier": "A", "freshness": "today"}
                    ],
                }
            ],
        }
        result = BaseHand._normalize_artifact(art)
        self.assertEqual(len(result.get("evidence", [])), 1)
        self.assertEqual(result["evidence"][0]["claim"], "c1")

    def test_normalize_adds_raw_defaults(self):
        """_normalize_artifact adds empty raw_sources/raw_items when absent."""
        art = {
            "metadata": {"confidence": 0.5, "key_claims": [], "gaps": [], "source_notes": []},
            "narrative": "test",
            "sections": [],
            "evidence": [],
        }
        result = BaseHand._normalize_artifact(art)
        self.assertIn("raw_sources", result)
        self.assertIn("raw_items", result)
        self.assertEqual(result["raw_sources"], [])
        self.assertEqual(result["raw_items"], [])


if __name__ == "__main__":
    unittest.main()
