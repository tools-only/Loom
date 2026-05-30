"""Tests for the unified AgentAdapter — covers all four transport×protocol cells."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from loom_core.agent_adapters.adapter import AgentAdapter

_PY = sys.executable


def _mock_transport(response_body: dict | str, status: int = 200) -> httpx.MockTransport:
    if isinstance(response_body, dict):
        body = json.dumps(response_body).encode()
    else:
        body = response_body.encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler=handler)


def _run(coro):
    return asyncio.run(coro)


# ── process × loom ────────────────────────────────────────────────────────

class ProcessLoomTests(unittest.TestCase):
    def _adapter(self, script: str) -> AgentAdapter:
        return AgentAdapter(
            adapter_id="test-pl",
            transport="process",
            protocol="loom",
            command=[_PY, "-c", script],
        )

    def test_rejects_empty_adapter_id(self):
        with self.assertRaises(ValueError):
            AgentAdapter(adapter_id="", transport="process", protocol="loom", command=[])

    def test_rejects_empty_task(self):
        adapter = self._adapter("pass")
        async def run():
            with self.assertRaises(ValueError):
                async for _ in adapter.invoke({}):
                    pass
        _run(run())

    def test_yields_run_started_first(self):
        adapter = self._adapter("import json,sys; d=json.loads(sys.stdin.read()); print(json.dumps({'type':'run.artifact','artifact':{}}))")
        events = _run(self._collect(adapter, {"task": "t"}))
        self.assertEqual(events[0]["type"], "run.started")

    def test_sends_envelope_on_stdin(self):
        adapter = self._adapter(
            "import json,sys; d=json.loads(sys.stdin.read()); "
            "print(json.dumps({'type':'run.artifact','artifact':{'task':d['task']}}))"
        )
        events = _run(self._collect(adapter, {"task": "hello"}))
        art = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual(art["artifact"]["task"], "hello")

    def test_cwd_set_from_hand_dir(self):
        tmpdir = tempfile.mkdtemp()
        adapter = self._adapter(
            "import os,json,sys; json.loads(sys.stdin.read()); "
            "print(json.dumps({'type':'run.artifact','artifact':{'cwd':os.getcwd()}}))"
        )
        events = _run(self._collect(adapter, {"task": "t", "hand_dir": tmpdir}))
        art = next(e for e in events if e["type"] == "run.artifact")
        import os
        self.assertEqual(os.path.normcase(art["artifact"]["cwd"]), os.path.normcase(tmpdir))

    async def _collect(self, adapter, task):
        events = []
        async for e in adapter.invoke(task):
            events.append(e)
        return events


# ── process × loom, task_as_arg=True (opencode) ──────────────────────────

class ProcessLoomArgTests(unittest.TestCase):
    def test_task_appended_as_cli_arg(self):
        # Script prints sys.argv[1] as the artifact task field; stdin is empty
        adapter = AgentAdapter(
            adapter_id="test-arg",
            transport="process",
            protocol="loom",
            command=[_PY, "-c",
                     "import sys,json; "
                     "print(json.dumps({'type':'run.artifact','artifact':{'arg':sys.argv[1]}}))"],
            task_as_arg=True,
        )
        async def run():
            events = []
            async for e in adapter.invoke({"task": "my-task"}):
                events.append(e)
            return events

        events = asyncio.run(run())
        art = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual(art["artifact"]["arg"], "my-task")

    def test_stdin_is_empty_when_task_as_arg(self):
        # stdin.read() should return empty string (no hanging)
        adapter = AgentAdapter(
            adapter_id="test-arg2",
            transport="process",
            protocol="loom",
            command=[_PY, "-c",
                     "import sys,json; "
                     "stdin=sys.stdin.read(); "
                     "print(json.dumps({'type':'run.artifact','artifact':{'stdin_len':len(stdin)}}))"],
            task_as_arg=True,
        )
        async def run():
            events = []
            async for e in adapter.invoke({"task": "x"}):
                events.append(e)
            return events

        events = asyncio.run(run())
        art = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual(art["artifact"]["stdin_len"], 0)


# ── http × openai (openclaw, nanobot) ─────────────────────────────────────

class HttpOpenAITests(unittest.TestCase):
    def _adapter(self, transport) -> AgentAdapter:
        return AgentAdapter(
            adapter_id="test-oai",
            transport="http",
            protocol="openai",
            endpoint="https://agent.example.com/v1/chat/completions",
            auth_token="sk-test",
            _transport=transport,
        )

    def _chatcompletion(self, content: str, status: int = 200) -> httpx.MockTransport:
        body = {
            "choices": [{"message": {"role": "assistant", "content": content}}]
        }
        return _mock_transport(body, status)

    def test_yields_run_started(self):
        artifact_line = json.dumps({"type": "run.artifact", "artifact": {"metadata": {"resources_used": [], "key_claims": [], "gaps": []}, "narrative": "ok"}})
        adapter = self._adapter(self._chatcompletion(artifact_line))
        events = asyncio.run(self._collect(adapter))
        self.assertEqual(events[0]["type"], "run.started")

    def test_parses_artifact_from_content(self):
        artifact = {"metadata": {"resources_used": ["fred"], "key_claims": ["claim"], "gaps": []}, "narrative": "test analysis"}
        content = json.dumps({"type": "run.artifact", "artifact": artifact})
        adapter = self._adapter(self._chatcompletion(content))
        events = asyncio.run(self._collect(adapter))
        art_events = [e for e in events if e["type"] == "run.artifact"]
        self.assertEqual(len(art_events), 1)
        self.assertEqual(art_events[0]["artifact"]["narrative"], "test analysis")

    def test_http_4xx_yields_run_error(self):
        adapter = self._adapter(self._chatcompletion("", status=401))
        events = asyncio.run(self._collect(adapter))
        errors = [e for e in events if e["type"] == "run.error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("401", errors[0]["message"])

    def test_missing_artifact_yields_run_error(self):
        content = "Sorry, I cannot help with that."
        adapter = self._adapter(self._chatcompletion(content))
        events = asyncio.run(self._collect(adapter))
        errors = [e for e in events if e["type"] == "run.error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("run.artifact", errors[0]["message"])

    def test_system_prompt_sent_in_messages(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            artifact_line = json.dumps({"type": "run.artifact", "artifact": {}})
            return httpx.Response(200, content=json.dumps({
                "choices": [{"message": {"content": artifact_line}}]
            }).encode())

        adapter = AgentAdapter(
            adapter_id="test-sp",
            transport="http",
            protocol="openai",
            endpoint="https://x.example.com/v1/chat/completions",
            system_prompt="custom-prompt",
            _transport=httpx.MockTransport(handler=handler),
        )
        asyncio.run(self._collect(adapter))
        messages = captured["body"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "custom-prompt")

    def test_bearer_token_sent(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization", "")
            artifact_line = json.dumps({"type": "run.artifact", "artifact": {}})
            return httpx.Response(200, content=json.dumps({
                "choices": [{"message": {"content": artifact_line}}]
            }).encode())

        adapter = AgentAdapter(
            adapter_id="test-bearer",
            transport="http",
            protocol="openai",
            endpoint="https://x.example.com/v1/chat/completions",
            auth_token="sk-secret",
            _transport=httpx.MockTransport(handler=handler),
        )
        asyncio.run(self._collect(adapter))
        self.assertEqual(captured["auth"], "Bearer sk-secret")

    def test_wiki_write_in_content_applied_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            hands_root = Path(tmp)
            wiki_write = json.dumps({"type": "wiki.write", "path": "macro.md", "content": "hello"})
            artifact = json.dumps({"type": "run.artifact", "artifact": {}})
            content = wiki_write + "\n" + artifact

            adapter = AgentAdapter(
                adapter_id="test-ww",
                transport="http",
                protocol="openai",
                endpoint="https://x.example.com/v1/chat/completions",
                hands_root=hands_root,
                _transport=self._chatcompletion(content),
            )
            asyncio.run(self._collect(adapter, hand_id="market"))

            wiki_file = hands_root / "market" / "wiki" / "macro.md"
            self.assertTrue(wiki_file.exists())
            self.assertEqual(wiki_file.read_text(), "hello")

    async def _collect(self, adapter, hand_id="market"):
        events = []
        async for e in adapter.invoke({"task": "test", "hand_id": hand_id}):
            events.append(e)
        return events


# ── backward compat aliases ────────────────────────────────────────────────

class BackwardCompatTests(unittest.TestCase):
    def test_process_adapter_alias_still_works(self):
        from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter
        a = ProcessAgentAdapter(adapter_id="x", command=["echo"])
        self.assertIsInstance(a, AgentAdapter)

    def test_http_adapter_alias_still_works(self):
        from loom_core.agent_adapters.http_adapter import HttpAgentAdapter
        rt = MagicMock()
        a = HttpAgentAdapter(
            adapter_id="x",
            endpoint="https://example.com",
            runtime=rt,
            hands_root=Path(tempfile.mkdtemp()),
        )
        self.assertIsInstance(a, AgentAdapter)
        self.assertEqual(a._transport_kind, "http")
        self.assertEqual(a._protocol, "loom")


if __name__ == "__main__":
    unittest.main()
