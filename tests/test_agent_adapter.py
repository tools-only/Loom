"""Tests for the unified AgentAdapter — covers all four transport×protocol cells."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

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

    def test_missing_artifact_wraps_plain_text_as_narrative_artifact(self):
        content = "Sorry, I cannot help with that."
        adapter = self._adapter(self._chatcompletion(content))
        events = asyncio.run(self._collect(adapter))
        errors = [e for e in events if e["type"] == "run.error"]
        artifacts = [e for e in events if e["type"] == "run.artifact"]
        self.assertEqual([], errors)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual("Sorry, I cannot help with that.", artifacts[0]["artifact"]["narrative"])
        self.assertIn("hand agent did not return structured JSON", artifacts[0]["artifact"]["metadata"]["gaps"])

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
        self.assertEqual(1, len(messages))
        self.assertEqual(messages[0]["role"], "user")
        self.assertTrue(messages[0]["content"].startswith("custom-prompt\n\n"))

    def test_per_call_system_prompt_overrides_bound_prompt(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            artifact_line = json.dumps({"type": "run.artifact", "artifact": {}})
            return httpx.Response(200, content=json.dumps({
                "choices": [{"message": {"content": artifact_line}}]
            }).encode())

        adapter = AgentAdapter(
            adapter_id="test-sp-override",
            transport="http",
            protocol="openai",
            endpoint="https://x.example.com/v1/chat/completions",
            system_prompt="bound-prompt",
            _transport=httpx.MockTransport(handler=handler),
        )
        asyncio.run(self._collect(adapter, task_overrides={"system_prompt": "runtime-prompt"}))
        content = captured["body"]["messages"][0]["content"]
        self.assertTrue(content.startswith("runtime-prompt\n\n"))
        self.assertNotIn("bound-prompt", content)

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

    def test_bearer_token_resolved_from_env_at_invoke_time(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization", "")
            artifact_line = json.dumps({"type": "run.artifact", "artifact": {}})
            return httpx.Response(200, content=json.dumps({
                "choices": [{"message": {"content": artifact_line}}]
            }).encode())

        adapter = AgentAdapter(
            adapter_id="test-bearer-env",
            transport="http",
            protocol="openai",
            endpoint="https://x.example.com/v1/chat/completions",
            auth_token_env="LOOM_TEST_ADAPTER_TOKEN",
            _transport=httpx.MockTransport(handler=handler),
        )
        with patch.dict(os.environ, {"LOOM_TEST_ADAPTER_TOKEN": "env-secret"}):
            asyncio.run(self._collect(adapter))

        self.assertEqual(captured["auth"], "Bearer env-secret")

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

    async def _collect(self, adapter, hand_id="market", task_overrides=None):
        events = []
        task = {"task": "test", "hand_id": hand_id}
        if task_overrides:
            task.update(task_overrides)
        async for e in adapter.invoke(task):
            events.append(e)
        return events


# ── backward compat aliases ────────────────────────────────────────────────

class ProcessCodexAppServerTests(unittest.TestCase):
    def _adapter(self, script: str, log_path: str) -> AgentAdapter:
        return AgentAdapter(
            adapter_id="codex-app-server",
            transport="process",
            protocol="codex",
            command=[_PY, "-c", script, log_path],
            codex_backend="raw",
            timeout_s=5.0,
        )

    def test_codex_process_uses_jsonrpc_lifecycle(self):
        script = r"""
import json
import pathlib
import sys

log = pathlib.Path(sys.argv[1])

def record(msg):
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg) + "\n")

def emit(msg):
    print(json.dumps(msg), flush=True)

for line in sys.stdin:
    msg = json.loads(line)
    record(msg)
    method = msg.get("method")
    if method == "initialize":
        emit({"id": msg["id"], "result": {"userAgent": "fake-codex"}})
    elif method == "thread/start":
        emit({"id": msg["id"], "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        emit({"id": msg["id"], "result": {"turn": {"id": "turn-1"}}})
        artifact = json.dumps({
            "type": "run.artifact",
            "artifact": {
                "metadata": {"confidence": 0.9, "key_claims": ["implemented"], "gaps": []},
                "narrative": "codex finished",
            },
        })
        emit({
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "id": "msg-1", "text": artifact}},
        })
        emit({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
        break
"""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "rpc.jsonl")
            workspace = str(Path(tmp) / "workspace")
            Path(workspace).mkdir()
            adapter = self._adapter(script, log_path)
            events = asyncio.run(self._collect(adapter, {
                "task": "Implement the feature",
                "hand_id": "runtime-codex",
                "cwd": workspace,
                "context": {"goal_id": "goal-1"},
            }))

            artifact = next(e for e in events if e["type"] == "run.artifact")
            self.assertEqual("codex finished", artifact["artifact"]["narrative"])

            messages = [
                json.loads(line)
                for line in Path(log_path).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                ["initialize", "initialized", "thread/start", "turn/start"],
                [m.get("method") for m in messages],
            )
            thread_params = messages[2]["params"]
            self.assertEqual(workspace, thread_params["cwd"])
            self.assertTrue(thread_params["ephemeral"])
            turn_params = messages[3]["params"]
            self.assertEqual("thread-1", turn_params["threadId"])
            self.assertEqual("text", turn_params["input"][0]["type"])
            self.assertIn("Implement the feature", turn_params["input"][0]["text"])
            self.assertEqual("run.artifact", turn_params["outputSchema"]["properties"]["type"]["const"])

    def test_codex_process_answers_approval_requests(self):
        script = r"""
import json
import pathlib
import sys

log = pathlib.Path(sys.argv[1])

def record(msg):
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg) + "\n")

def emit(msg):
    print(json.dumps(msg), flush=True)

for line in sys.stdin:
    msg = json.loads(line)
    record(msg)
    method = msg.get("method")
    if method == "initialize":
        emit({"id": msg["id"], "result": {}})
    elif method == "thread/start":
        emit({"id": msg["id"], "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        emit({"id": msg["id"], "result": {"turn": {"id": "turn-1"}}})
        emit({
            "id": 99,
            "method": "item/commandExecution/requestApproval",
            "params": {"itemId": "cmd-1"},
        })
        approval_response = json.loads(sys.stdin.readline())
        record(approval_response)
        artifact = json.dumps({
            "type": "run.artifact",
            "artifact": {
                "metadata": {"confidence": 0.8, "key_claims": [], "gaps": []},
                "narrative": "approved",
            },
        })
        emit({
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "id": "msg-1", "text": artifact}},
        })
        emit({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
        break
"""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = str(Path(tmp) / "rpc.jsonl")
            adapter = self._adapter(script, log_path)
            events = asyncio.run(self._collect(adapter, {
                "task": "Run command",
                "hand_id": "runtime-codex",
                "codex": {"approvalDecision": "acceptForSession"},
            }))

            artifact = next(e for e in events if e["type"] == "run.artifact")
            self.assertEqual("approved", artifact["artifact"]["narrative"])
            messages = [
                json.loads(line)
                for line in Path(log_path).read_text(encoding="utf-8").splitlines()
            ]
            approval = next(m for m in messages if m.get("id") == 99 and "result" in m)
            self.assertEqual("acceptForSession", approval["result"]["decision"])

    async def _collect(self, adapter, task):
        events = []
        async for e in adapter.invoke(task):
            events.append(e)
        return events


class ProcessCodexSdkTests(unittest.TestCase):
    def test_agent_session_uses_plain_final_message_without_output_schema(self):
        captured = {}

        class FakeCodexConfig:
            def __init__(self, **kwargs):
                captured["config"] = kwargs

        class FakeApprovalMode:
            deny_all = "deny_all"
            auto_review = "auto_review"

        class FakeSandbox:
            read_only = "read_only"
            workspace_write = "workspace_write"
            full_access = "full_access"

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
                    {"item": {"type": "agentMessage", "id": "msg-1", "text": "agent finished"}},
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
                self.config = config

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

        adapter = AgentAdapter(
            adapter_id="codex-app-server",
            transport="process",
            protocol="codex",
            codex_backend="sdk",
        )
        task = {
            "execution_mode": "agent",
            "task": "Inspect and modify the workspace as needed.",
            "cwd": os.getcwd(),
        }

        with patch.dict(sys.modules, {"openai_codex": fake_sdk}):
            events = asyncio.run(self._collect(adapter, task))

        self.assertEqual("Inspect and modify the workspace as needed.", captured["prompt"])
        self.assertNotIn("output_schema", captured["turn"])
        self.assertEqual(
            "agent finished",
            next(event["text"] for event in events if event["type"] == "run.message"),
        )
        self.assertTrue(any(event["type"] == "run.completed" for event in events))

    def test_codex_sdk_runs_hand_through_official_async_client(self):
        captured: dict = {}
        artifact_line = json.dumps({
            "type": "run.artifact",
            "artifact": {
                "metadata": {"confidence": 0.9, "key_claims": ["done"], "gaps": []},
                "narrative": "sdk finished",
            },
        })

        class FakeCodexConfig:
            def __init__(self, **kwargs):
                captured["config"] = kwargs

        class FakeApprovalMode:
            deny_all = "deny_all"
            auto_review = "auto_review"

        class FakeSandbox:
            read_only = "read_only"
            workspace_write = "workspace_write"
            full_access = "full_access"

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

        adapter = AgentAdapter(
            adapter_id="codex-sdk",
            transport="process",
            protocol="codex",
            codex_backend="sdk",
            codex_home="D:/agent/.codex",
        )
        task = {
            "task": "Implement through SDK",
            "hand_id": "runtime-codex",
            "cwd": os.getcwd(),
            "codex": {
                "approvalMode": "deny_all",
                "sandbox": "workspace-write",
                "model": "gpt-test",
            },
        }

        with patch.dict(sys.modules, {"openai_codex": fake_sdk}):
            events = asyncio.run(self._collect(adapter, task))

        artifact = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual("sdk finished", artifact["artifact"]["narrative"])
        self.assertIsNone(captured["config"]["launch_args_override"])
        self.assertEqual({"CODEX_HOME": "D:/agent/.codex"}, captured["config"]["env"])
        self.assertEqual("deny_all", captured["thread"]["approval_mode"])
        self.assertEqual("workspace_write", captured["thread"]["sandbox"])
        self.assertEqual("gpt-test", captured["thread"]["model"])
        self.assertIn("Implement through SDK", captured["prompt"])
        self.assertEqual("run.artifact", captured["turn"]["output_schema"]["properties"]["type"]["const"])
        self.assertEqual("string", captured["turn"]["output_schema"]["properties"]["type"]["type"])

    async def _collect(self, adapter, task):
        return [event async for event in adapter.invoke(task)]


class HttpCodexTests(unittest.TestCase):
    def _adapter(self, handler) -> AgentAdapter:
        return AgentAdapter(
            adapter_id="codex-app-service",
            transport="http",
            protocol="codex",
            endpoint="http://127.0.0.1:8787/loom/hand/run",
            auth_token="codex-token",
            _transport=httpx.MockTransport(handler),
        )

    def test_codex_request_contains_full_hand_envelope(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={
                "artifact": {
                    "metadata": {"confidence": 0.8, "key_claims": [], "gaps": []},
                    "narrative": "done",
                }
            })

        adapter = self._adapter(handler)
        events = asyncio.run(self._collect(adapter, task_overrides={
            "task": "Implement the feature",
            "hand_id": "runtime-impl-agent",
            "system_prompt": "You are a Codex implementation agent.",
            "context": {"goal_id": "goal-1"},
            "capabilities": ["workspace.patch"],
            "resource_api": "http://127.0.0.1:3001/resources",
        }))

        self.assertEqual("Bearer codex-token", captured["auth"])
        body = captured["body"]
        self.assertEqual("loom.hand.run", body["type"])
        self.assertEqual("codex-app-service", body["adapter_id"])
        self.assertEqual("runtime-impl-agent", body["hand_id"])
        self.assertEqual("Implement the feature", body["task"])
        self.assertEqual({"goal_id": "goal-1"}, body["context"])
        self.assertEqual(["workspace.patch"], body["capabilities"])
        self.assertEqual("run.artifact", body["output_contract"]["required_event"])
        self.assertEqual("Implement the feature", body["envelope"]["task"])
        artifact = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual("done", artifact["artifact"]["narrative"])

    def test_codex_parses_events_array_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "events": [
                    {"type": "run.partial", "text": "working"},
                    {
                        "type": "run.artifact",
                        "artifact": {
                            "metadata": {"confidence": 0.9, "key_claims": ["ok"], "gaps": []},
                            "narrative": "artifact from events",
                        },
                    },
                ]
            })

        events = asyncio.run(self._collect(self._adapter(handler)))
        self.assertIn("run.partial", [e["type"] for e in events])
        artifact = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual("artifact from events", artifact["artifact"]["narrative"])

    def test_codex_parses_openai_style_content(self):
        artifact_line = json.dumps({
            "type": "run.artifact",
            "artifact": {
                "metadata": {"confidence": 0.7, "key_claims": [], "gaps": []},
                "narrative": "from choices",
            },
        })

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": artifact_line}}]
            })

        events = asyncio.run(self._collect(self._adapter(handler)))
        artifact = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual("from choices", artifact["artifact"]["narrative"])

    def test_codex_plain_text_response_becomes_artifact(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"implementation finished")

        events = asyncio.run(self._collect(self._adapter(handler)))
        artifact = next(e for e in events if e["type"] == "run.artifact")
        self.assertEqual("implementation finished", artifact["artifact"]["narrative"])
        self.assertIn("Codex app service returned plain text", artifact["artifact"]["metadata"]["gaps"])

    async def _collect(self, adapter, task_overrides=None):
        events = []
        task = {"task": "test", "hand_id": "runtime-codex"}
        if task_overrides:
            task.update(task_overrides)
        async for e in adapter.invoke(task):
            events.append(e)
        return events


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
