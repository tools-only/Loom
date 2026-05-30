"""Tests for HttpAgentAdapter — NDJSON parsing, error handling, snapshot, writeback."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import httpx


def _make_runtime(hand_id: str = "market", feedback: list | None = None,
                  config: dict | None = None):
    rt = MagicMock()
    rt.hand_config_store.read.return_value = config or {}
    rt.feedback_store.read.return_value = feedback or []
    rt.resource_provider.fetch.side_effect = KeyError("unknown")
    return rt


def _ndjson_transport(lines: list[str], status: int = 200) -> httpx.MockTransport:
    body = ("\n".join(lines) + "\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler=handler)


def _make_adapter(
    endpoint: str = "https://agent.example.com/run",
    auth_token: str | None = "sk-test",
    runtime=None,
    hands_root: Path | None = None,
    transport: httpx.MockTransport | None = None,
    ndjson_lines: list[str] | None = None,
):
    from loom_core.agent_adapters.http_adapter import HttpAgentAdapter

    if ndjson_lines is not None:
        transport = _ndjson_transport(ndjson_lines)

    return HttpAgentAdapter(
        adapter_id="test-cloud",
        endpoint=endpoint,
        runtime=runtime or _make_runtime(),
        hands_root=hands_root or Path(tempfile.mkdtemp()),
        auth_token=auth_token,
        capabilities=["market.analysis"],
        timeout_s=10.0,
        _transport=transport,
    )


class HttpAdapterProtocolTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_has_required_protocol_fields(self):
        adapter = _make_adapter()
        self.assertEqual(adapter.id, "test-cloud")
        self.assertIsInstance(adapter.capabilities, list)

    def test_cancel_does_not_raise(self):
        adapter = _make_adapter()
        self._run(adapter.cancel("any-run-id"))

    def test_yields_run_started_first(self):
        async def run():
            adapter = _make_adapter(ndjson_lines=[
                json.dumps({"type": "run.artifact", "artifact": {"narrative": "ok"}}),
            ])
            events = []
            async for e in adapter.invoke({"task": "test", "hand_id": "market"}):
                events.append(e)
            return events

        events = self._run(run())
        self.assertEqual(events[0]["type"], "run.started")

    def test_yields_run_artifact_from_ndjson(self):
        async def run():
            adapter = _make_adapter(ndjson_lines=[
                json.dumps({"type": "run.started", "run_id": "x"}),
                json.dumps({"type": "run.artifact", "artifact": {"narrative": "market ok"}}),
                json.dumps({"type": "run.completed"}),
            ])
            events = []
            async for e in adapter.invoke({"task": "test", "hand_id": "market"}):
                events.append(e)
            return events

        events = self._run(run())
        types = [e["type"] for e in events]
        self.assertIn("run.artifact", types)
        artifact_event = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual(artifact_event["artifact"]["narrative"], "market ok")

    def test_http_4xx_yields_run_error(self):
        async def run():
            adapter = _make_adapter(transport=_ndjson_transport([], status=401))
            events = []
            async for e in adapter.invoke({"task": "test", "hand_id": "market"}):
                events.append(e)
            return events

        events = self._run(run())
        error_events = [e for e in events if e["type"] == "run.error"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("401", error_events[0]["message"])

    def test_wiki_write_not_yielded_to_caller(self):
        """wiki.write events must be applied locally, not yielded."""
        with tempfile.TemporaryDirectory() as tmp:
            hands_root = Path(tmp)

            async def run():
                adapter = _make_adapter(
                    hands_root=hands_root,
                    ndjson_lines=[
                        json.dumps({"type": "wiki.write", "path": "macro.md",
                                    "content": "hello"}),
                        json.dumps({"type": "run.artifact",
                                    "artifact": {"narrative": "done"}}),
                    ],
                )
                events = []
                async for e in adapter.invoke({"task": "test", "hand_id": "market"}):
                    events.append(e)
                return events

            events = self._run(run())
            types = [e["type"] for e in events]
            self.assertNotIn("wiki.write", types)
            self.assertIn("run.artifact", types)

            wiki_file = hands_root / "market" / "wiki" / "macro.md"
            self.assertTrue(wiki_file.exists())
            self.assertEqual(wiki_file.read_text(encoding="utf-8"), "hello")

    def test_wiki_write_path_traversal_rejected(self):
        """Paths with .. must be silently rejected — target must not be written."""
        with tempfile.TemporaryDirectory() as tmp:
            hands_root = Path(tmp)

            async def run():
                adapter = _make_adapter(
                    hands_root=hands_root,
                    ndjson_lines=[
                        json.dumps({"type": "wiki.write",
                                    "path": "../../../etc/passwd",
                                    "content": "pwned"}),
                        json.dumps({"type": "run.artifact", "artifact": {}}),
                    ],
                )
                async for _ in adapter.invoke({"task": "t", "hand_id": "market"}):
                    pass

            self._run(run())
            # Nothing should escape the wiki dir
            self.assertEqual(
                list((hands_root / "market" / "wiki").glob("**/*")
                     if (hands_root / "market" / "wiki").exists() else []),
                [],
            )

    def test_feedback_signal_not_yielded(self):
        """feedback.signal events must be stored locally, not yielded."""
        rt = _make_runtime()

        async def run():
            adapter = _make_adapter(
                runtime=rt,
                ndjson_lines=[
                    json.dumps({"type": "feedback.signal",
                                "event": {"hand_id": "market", "vote": "up"}}),
                    json.dumps({"type": "run.artifact",
                                "artifact": {"narrative": "ok"}}),
                ],
            )
            events = []
            async for e in adapter.invoke({"task": "t", "hand_id": "market"}):
                events.append(e)
            return events

        events = self._run(run())
        types = [e["type"] for e in events]
        self.assertNotIn("feedback.signal", types)
        rt.feedback_store.append.assert_called_once_with(
            {"hand_id": "market", "vote": "up"}
        )

    def test_bearer_token_sent_in_header(self):
        """Authorization: Bearer must be set when auth_token provided."""
        captured_headers: dict = {}

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(
                200,
                content=(json.dumps({"type": "run.artifact", "artifact": {}}) + "\n").encode(),
            )

        async def run():
            adapter = _make_adapter(
                auth_token="sk-secret",
                transport=httpx.MockTransport(handler=capturing_handler),
            )
            async for _ in adapter.invoke({"task": "t", "hand_id": "market"}):
                pass

        self._run(run())
        self.assertIn("authorization", captured_headers)
        self.assertEqual(captured_headers["authorization"], "Bearer sk-secret")

    def test_snapshot_contains_wiki_config_feedback(self):
        """_build_snapshot must include wiki_snapshot, config, feedback_recent."""
        with tempfile.TemporaryDirectory() as tmp:
            hands_root = Path(tmp)
            wiki_dir = hands_root / "market" / "wiki"
            wiki_dir.mkdir(parents=True)
            (wiki_dir / "index.md").write_text("# Index", encoding="utf-8")

            rt = _make_runtime(
                config={"watched_sectors": ["tech"]},
                feedback=[{"hand_id": "market", "vote": "up"}],
            )
            adapter = _make_adapter(runtime=rt, hands_root=hands_root)
            snapshot = adapter._build_snapshot(
                {"task": "test", "context": {}}, "market"
            )

        self.assertIn("index.md", snapshot["wiki_snapshot"])
        self.assertEqual(snapshot["config"], {"watched_sectors": ["tech"]})
        self.assertEqual(len(snapshot["feedback_recent"]), 1)
        self.assertEqual(snapshot["hand_id"], "market")
        self.assertEqual(snapshot["task"], "test")

    def test_snapshot_respects_cloud_json_include_wiki_false(self):
        """include_wiki_snapshot: false in cloud.json must omit wiki."""
        with tempfile.TemporaryDirectory() as tmp:
            hands_root = Path(tmp)
            hand_dir = hands_root / "market"
            (hand_dir / "wiki").mkdir(parents=True)
            (hand_dir / "wiki" / "macro.md").write_text("content", encoding="utf-8")
            (hand_dir / "cloud.json").write_text(
                json.dumps({"include_wiki_snapshot": False}), encoding="utf-8"
            )

            adapter = _make_adapter(hands_root=hands_root)
            snapshot = adapter._build_snapshot({}, "market")

        self.assertEqual(snapshot["wiki_snapshot"], {})


if __name__ == "__main__":
    unittest.main()
