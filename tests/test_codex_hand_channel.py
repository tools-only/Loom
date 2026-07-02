import asyncio
import copy
import json
import os
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from loom_core.codex_hand_channel import (
    CodexHandChannel,
    CodexHandChannelTimeout,
    HandRequest,
    complete_artifact_schema,
    validate_complete_artifact,
)


def _complete_artifact_event() -> dict:
    return {
        "type": "run.artifact",
        "artifact": {
            "metadata": {
                "confidence": 0.95,
                "key_claims": ["The direct Codex channel completed."],
                "gaps": [],
                "resources_used": ["provided evidence"],
                "source_notes": [
                    {
                        "source": "fixture",
                        "tier": "provided",
                        "freshness": "current",
                        "note": "Test evidence supplied in the request.",
                    }
                ],
            },
            "narrative": "The hand completed through Codex app-server.",
            "sections": [
                {
                    "id": "result",
                    "title": "Result",
                    "summary": "Direct execution succeeded.",
                    "bullets": ["A complete artifact was returned."],
                }
            ],
            "evidence": [
                {
                    "claim": "The direct Codex channel completed.",
                    "support": "The app-server emitted a completed agent message.",
                    "source": "fixture",
                    "source_tier": "provided",
                    "freshness": "current",
                    "confidence": 0.95,
                }
            ],
            "raw_items": [
                {
                    "item_type": "data_point",
                    "title": "",
                    "label": "Channel state",
                    "value": "completed",
                    "source": "fixture",
                    "tier": "provided",
                    "published_at": "",
                    "freshness": "current",
                    "summary": "The direct channel completed.",
                    "relevance": "Direct channel validation",
                    "url": "https://example.invalid/evidence/fixture-1",
                }
            ],
            "raw_sources": [
                {
                    "resource_id": "fixture",
                    "fetched_at": "current",
                    "content_type": "provided evidence",
                    "summary": "Evidence supplied by the test request.",
                    "url": "https://example.invalid/evidence",
                    "query": "",
                }
            ],
        },
    }


class CodexHandChannelTests(unittest.TestCase):
    def test_run_emits_stage_progress_callbacks(self):
        progress_events: list[tuple[str, dict]] = []
        artifact_line = json.dumps(_complete_artifact_event())

        class FakeCodexConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeApprovalMode:
            deny_all = "deny_all"

        class FakeSandbox:
            workspace_write = "workspace_write"

        class FakePayload:
            def __init__(self, value):
                self.value = value

            def model_dump(self, **_kwargs):
                return self.value

        class FakeNotification:
            def __init__(self, method, params):
                self.method = method
                self.payload = FakePayload(params)

        class FakeTurn:
            async def stream(self):
                yield FakeNotification(
                    "item/agentMessage/delta",
                    {"itemId": "msg-1", "delta": artifact_line[:24]},
                )
                yield FakeNotification(
                    "item/completed",
                    {"item": {"type": "agentMessage", "id": "msg-1", "text": artifact_line}},
                )
                yield FakeNotification(
                    "turn/completed",
                    {"turn": {"id": "turn-1", "status": "completed"}},
                )

        class FakeThread:
            async def turn(self, *_args, **_kwargs):
                return FakeTurn()

        class FakeAsyncCodex:
            def __init__(self, config=None):
                self.config = config

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def thread_start(self, **_kwargs):
                return FakeThread()

        fake_sdk = ModuleType("openai_codex")
        fake_sdk.AsyncCodex = FakeAsyncCodex
        fake_sdk.CodexConfig = FakeCodexConfig
        fake_sdk.ApprovalMode = FakeApprovalMode
        fake_sdk.Sandbox = FakeSandbox

        channel = CodexHandChannel(
            codex_home="D:/agent/.codex",
            timeout_s=1,
            progress_callback=lambda stage, details: progress_events.append((stage, details)),
        )
        request = HandRequest(
            task="Return the supplied result as a complete artifact.",
            hand_id="research-hand",
            cwd=os.getcwd(),
        )

        with patch.dict(sys.modules, {"openai_codex": fake_sdk}):
            artifact = asyncio.run(channel.run(request))

        self.assertEqual("The hand completed through Codex app-server.", artifact["narrative"])
        self.assertIn(("run.start", {"hand_id": "research-hand", "cwd": os.getcwd()}), progress_events)
        self.assertTrue(any(stage == "thread.start" for stage, _details in progress_events))
        self.assertTrue(any(stage == "turn.start" for stage, _details in progress_events))
        self.assertTrue(any(stage == "turn.completed" for stage, _details in progress_events))
        self.assertTrue(any(stage == "artifact.validated" for stage, _details in progress_events))

    def test_deadline_covers_sdk_startup_not_only_turn_notifications(self):
        class FakeCodexConfig:
            def __init__(self, **_kwargs):
                pass

        class FakeApprovalMode:
            deny_all = "deny_all"

        class FakeSandbox:
            workspace_write = "workspace_write"

        class HangingAsyncCodex:
            def __init__(self, config=None):
                self.config = config

            async def __aenter__(self):
                await asyncio.Event().wait()

            async def __aexit__(self, *_args):
                return None

        fake_sdk = ModuleType("openai_codex")
        fake_sdk.AsyncCodex = HangingAsyncCodex
        fake_sdk.CodexConfig = FakeCodexConfig
        fake_sdk.ApprovalMode = FakeApprovalMode
        fake_sdk.Sandbox = FakeSandbox
        channel = CodexHandChannel(timeout_s=0.01)

        with patch.dict(sys.modules, {"openai_codex": fake_sdk}):
            with self.assertRaisesRegex(CodexHandChannelTimeout, "channel deadline"):
                asyncio.run(channel.run(HandRequest(task="hang", hand_id="test-hand")))

    def test_schema_matches_loom_l0_drill_down_fields(self):
        artifact_schema = complete_artifact_schema()["properties"]["artifact"]
        raw_item = artifact_schema["properties"]["raw_items"]["items"]
        raw_source = artifact_schema["properties"]["raw_sources"]["items"]

        self.assertEqual(
            {
                "item_type",
                "title",
                "label",
                "value",
                "source",
                "tier",
                "published_at",
                "freshness",
                "summary",
                "relevance",
                "url",
            },
            set(raw_item["properties"]),
        )
        self.assertEqual(
            {"resource_id", "fetched_at", "content_type", "summary", "url", "query"},
            set(raw_source["properties"]),
        )

    def test_validation_rejects_incomplete_evidence_and_untraceable_raw_data(self):
        artifact = copy.deepcopy(_complete_artifact_event()["artifact"])
        del artifact["evidence"][0]["support"]
        artifact["evidence"][0]["confidence"] = 2
        artifact["raw_items"][0]["url"] = ""
        artifact["raw_sources"][0]["url"] = "  "

        violations = validate_complete_artifact(artifact)

        self.assertIn("evidence[0].support must be non-empty", violations)
        self.assertIn("evidence[0].confidence must be between 0 and 1", violations)
        self.assertIn("raw_items[0].url must be non-empty", violations)
        self.assertIn("raw_sources[0].url must be non-empty", violations)

    def test_run_returns_complete_artifact_from_official_sdk(self):
        captured: dict = {}
        artifact_line = json.dumps(_complete_artifact_event())

        class FakeCodexConfig:
            def __init__(self, **kwargs):
                captured["config"] = kwargs

        class FakeApprovalMode:
            deny_all = "deny_all"

        class FakeSandbox:
            workspace_write = "workspace_write"

        class FakePayload:
            def __init__(self, value):
                self.value = value

            def model_dump(self, **_kwargs):
                return self.value

        class FakeNotification:
            def __init__(self, method, params):
                self.method = method
                self.payload = FakePayload(params)

        class FakeTurn:
            async def stream(self):
                yield FakeNotification(
                    "item/completed",
                    {"item": {"type": "agentMessage", "id": "msg-1", "text": artifact_line}},
                )
                yield FakeNotification(
                    "turn/completed",
                    {"turn": {"id": "turn-1", "status": "completed"}},
                )

        class FakeThread:
            async def turn(self, prompt, **kwargs):
                captured["prompt"] = prompt
                captured["turn"] = kwargs
                return FakeTurn()

        class FakeAsyncCodex:
            def __init__(self, config=None):
                captured["client_config"] = config

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def thread_start(self, **kwargs):
                captured["thread"] = kwargs
                return FakeThread()

        fake_sdk = ModuleType("openai_codex")
        fake_sdk.AsyncCodex = FakeAsyncCodex
        fake_sdk.CodexConfig = FakeCodexConfig
        fake_sdk.ApprovalMode = FakeApprovalMode
        fake_sdk.Sandbox = FakeSandbox

        channel = CodexHandChannel(codex_home="D:/agent/.codex", timeout_s=1)
        request = HandRequest(
            task="Return the supplied result as a complete artifact.",
            hand_id="research-hand",
            cwd=os.getcwd(),
            context={"evidence_url": "https://example.invalid/evidence"},
        )

        with patch.dict(sys.modules, {"openai_codex": fake_sdk}):
            artifact = asyncio.run(channel.run(request))

        self.assertEqual("The hand completed through Codex app-server.", artifact["narrative"])
        self.assertEqual(["provided evidence"], artifact["metadata"]["resources_used"])
        self.assertEqual("https://example.invalid/evidence", artifact["raw_sources"][0]["url"])
        self.assertIsNone(captured["config"]["launch_args_override"])
        self.assertEqual({"CODEX_HOME": "D:/agent/.codex"}, captured["config"]["env"])
        self.assertEqual("deny_all", captured["thread"]["approval_mode"])
        schema_artifact = captured["turn"]["output_schema"]["properties"]["artifact"]
        self.assertEqual(
            {"metadata", "narrative", "sections", "evidence", "raw_items", "raw_sources"},
            set(schema_artifact["required"]),
        )
        self.assertIn("Return the supplied result", captured["prompt"])

    def test_default_timeout_is_300_seconds(self):
        channel = CodexHandChannel()

        self.assertEqual(300.0, channel._timeout_s)


if __name__ == "__main__":
    unittest.main()
