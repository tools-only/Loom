import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import loom.brain as brain


class BrainCodexHandRouteTests(unittest.TestCase):
    def test_brain_generated_hand_routes_default_codex_runtime_directly(self):
        artifact = {
            "metadata": {"confidence": 1.0, "key_claims": [], "gaps": []},
            "narrative": "Brain-dispatched Codex Hand completed.",
            "sections": [],
            "evidence": [],
            "raw_items": [],
            "raw_sources": [],
        }
        context = {
            "source": "brain-dispatch-test",
            "agentic_hand_spec": {
                "executor_id": "brain-inline",
                "dimension": "manual verification",
                "system_prompt": "Return the requested verification artifact.",
            },
        }
        direct_run = AsyncMock(return_value=artifact)

        with (
            patch.object(brain, "_run_direct_codex_hand", direct_run),
            patch.object(
                brain._adapter_registry,
                "find_by_id",
                side_effect=AssertionError("adapter path must not be used"),
            ),
        ):
            result = asyncio.run(
                brain._brain_hand_runner(
                    "runtime-manual-verification",
                    "Verify Brain can call Codex Hand.",
                    context,
                )
            )

        self.assertEqual(artifact, result)
        direct_run.assert_awaited_once_with(
            "runtime-manual-verification",
            "Verify Brain can call Codex Hand.",
            context,
        )

    def test_run_routes_codex_runtime_through_direct_hand_channel(self):
        artifact = {
            "metadata": {
                "confidence": 1.0,
                "key_claims": ["Codex Hand was called."],
                "gaps": [],
                "resources_used": [],
                "source_notes": [],
            },
            "narrative": "Codex Hand completed.",
            "sections": [],
            "evidence": [],
            "raw_items": [],
            "raw_sources": [],
        }
        direct_run = AsyncMock(return_value=artifact)
        request = brain.RunRequest(
            hand_id="manual-codex-hand",
            task="Return a complete artifact.",
            context={"source": "manual-test"},
            runtime="codex-app-server",
        )

        with (
            patch.object(brain, "_run_direct_codex_hand", direct_run, create=True),
            patch.object(
                brain,
                "_ensure_runtime_adapter",
                side_effect=AssertionError("adapter path must not be used"),
            ),
            patch.object(brain, "patch_webview", new=AsyncMock()),
            patch.object(brain, "append_signal"),
        ):
            response = asyncio.run(brain.run(request))

        self.assertTrue(response["ok"])
        self.assertEqual("codex-app-server", response["runtime"])
        self.assertEqual(artifact, response["artifact"])
        direct_run.assert_awaited_once_with(
            "manual-codex-hand",
            "Return a complete artifact.",
            {"source": "manual-test"},
        )


if __name__ == "__main__":
    unittest.main()
