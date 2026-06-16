from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loom.brain_harness.resources import ResourceRegistry


class ResourceRegistryTests(unittest.TestCase):
    def test_capture_deduplicates_by_url_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ResourceRegistry(Path(tmp))

            first = registry.capture({
                "title": "AI capex note",
                "url": "https://example.com/ai-capex",
                "text": "Cloud capex and GPU backlog need tracking.",
                "domain": "loom-fin",
                "tags": ["loom-fin", "semis"],
                "trust_tier": "C",
                "intent_hint": "Useful for AI infrastructure cycle checks.",
            })
            second = registry.capture({
                "title": "AI capex note updated",
                "url": "https://example.com/ai-capex",
                "text": "Updated note",
                "domain": "loom-fin",
                "trust_tier": "B",
            })

            self.assertEqual(first.resource_id, second.resource_id)
            resources = registry.list_resources(include_channel=False)
            self.assertEqual(1, len(resources))
            self.assertEqual("B", resources[0]["trust_tier"])
            self.assertEqual("loom-fin", resources[0]["domain"])

    def test_query_rubric_context_returns_resources_and_strategy_primitives(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ResourceRegistry(Path(tmp))
            resource = registry.capture({
                "title": "AI capex framework",
                "text": "GPU backlog and cloud capex are the core variables.",
                "domain": "loom-fin",
                "tags": ["loom-fin", "ai", "capex"],
                "trust_tier": "C",
            })
            primitives = registry.add_strategy_primitives(
                resource_id=resource.resource_id,
                domain="loom-fin",
                trust_tier="C",
                frameworks=[{
                    "framework_id": "fw-ai-capex",
                    "name": "AI capex digestion",
                    "decision_logic": "Track capex guidance against GPU backlog.",
                    "key_variables": ["capex guidance", "GPU backlog"],
                    "failure_conditions": ["cloud capex accelerates again"],
                    "confidence": "medium",
                    "tags": ["loom-fin", "ai"],
                }],
            )

            context = registry.query_rubric_context(
                domain="loom-fin",
                question="How should I evaluate AI capex risk?",
            )

            self.assertEqual(resource.resource_id, context["resources"][0]["resource_id"])
            self.assertEqual(primitives[0].primitive_id, context["strategy_primitives"][0]["primitive_id"])
            self.assertIn("GPU backlog", context["strategy_primitives"][0]["variables"])

    def test_reads_existing_channel_resources_as_resource_wiki_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            channel_path = root / "logs" / "workspace" / "channel-resources.json"
            channel_path.parent.mkdir(parents=True)
            channel_path.write_text(json.dumps({
                "version": 1,
                "resources": [{
                    "resource_id": "channel_x_ai_thread",
                    "channel": "x",
                    "source": "analyst",
                    "title": "AI capex thread",
                    "url": "https://x.example/thread",
                    "text": "AI capex and GPU supply observations.",
                    "tags": ["loom-fin", "ai"],
                    "trust_tier": "E",
                    "resource_kind": "social_post",
                    "intent_hint": "Good hypothesis, verify with filings.",
                    "value_signal": "AI capex hypothesis",
                }],
            }), encoding="utf-8")

            registry = ResourceRegistry(root)
            context = registry.query_rubric_context(
                domain="loom-fin",
                question="AI capex",
            )

            self.assertEqual("channel_x_ai_thread", context["resources"][0]["resource_id"])
            self.assertEqual("E", context["resources"][0]["trust_tier"])


if __name__ == "__main__":
    unittest.main()
