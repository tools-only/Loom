"""Tests for RuntimeHandAdapter and registry default cascade."""
import unittest
from unittest import mock

from loom_core.agent_adapters.registry import AgentAdapterRegistry
from loom_core.agent_adapters.providers.runtime_hand import RuntimeHandAdapter, create_runtime_hand_provider


class TestRegistry(unittest.TestCase):
    def test_default_is_brain_inline(self):
        reg = AgentAdapterRegistry()
        assert reg.resolve_runtime_adapter("brain-inline") == "brain-inline"
        assert reg.get_default_runtime_adapter() == "brain-inline"

    def test_resolve_returns_custom_default(self):
        reg = AgentAdapterRegistry()
        reg.set_default_runtime_adapter("runtime-hand")
        assert reg.resolve_runtime_adapter("brain-inline") == "runtime-hand"

    def test_resolve_non_brain_inline_unchanged(self):
        reg = AgentAdapterRegistry()
        reg.set_default_runtime_adapter("runtime-hand")
        assert reg.resolve_runtime_adapter("cc") == "cc"

    def test_set_default_updates_id(self):
        reg = AgentAdapterRegistry()
        reg.set_default_runtime_adapter("custom-adapter")
        assert reg.get_default_runtime_adapter() == "custom-adapter"


class TestRuntimeHandAdapter(unittest.TestCase):
    def test_create_provider_structure(self):
        prov = create_runtime_hand_provider(["echo"])
        assert prov["id"] == "runtime-hand"
        assert isinstance(prov["instance"], RuntimeHandAdapter)

    def test_build_prompt_contains_system_prompt(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["echo"], [])
        task = {
            "system_prompt": "You are a risk analyst.",
            "task": "Assess portfolio risk.",
            "context": {"domain": "finance"},
            "hand_id": "runtime-risk-0",
            "capabilities": ["portfolio"],
        }
        prompt = adapter._build_prompt(task)
        assert "You are a risk analyst." in prompt
        assert "Assess portfolio risk." in prompt
        assert "domain: finance" in prompt
        assert "hand_id: runtime-risk-0" in prompt
        assert "capabilities: portfolio" in prompt

    def test_build_prompt_system_prompt_comes_first(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["echo"], [])
        task = {
            "system_prompt": "ROLE_CONTEXT",
            "task": "TASK_CONTENT",
            "context": {},
        }
        prompt = adapter._build_prompt(task)
        assert prompt.index("ROLE_CONTEXT") < prompt.index("TASK_CONTENT")

    def test_build_prompt_no_system_prompt(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["echo"], [])
        task = {"task": "Do something.", "context": {}}
        prompt = adapter._build_prompt(task)
        assert "--- TASK ---" in prompt
        assert "Do something." in prompt

    def test_agent_session_prompt_does_not_force_loom_artifact_contract(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["claude", "-p"], [])
        prompt = adapter._build_prompt({
            "execution_mode": "agent",
            "task": "Use the available tools and report the result.",
            "system_prompt": "You are the configured workspace agent.",
        })

        assert "You are the configured workspace agent." in prompt
        assert "Use the available tools and report the result." in prompt
        assert "run.artifact" not in prompt

    def test_default_command_is_claude(self):
        prov = create_runtime_hand_provider()
        adapter = prov["instance"]
        assert adapter._command == ["claude", "-p"]

    def test_custom_command(self):
        prov = create_runtime_hand_provider(["my-model", "--json"])
        assert prov["instance"]._command == ["my-model", "--json"]


class TestRuntimeHandAdapterInvoke(unittest.IsolatedAsyncioTestCase):
    async def test_agent_session_returns_plain_claude_code_final_message(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["claude", "-p"], [])

        class FakeProc:
            returncode = 0

            async def communicate(self, input=None):
                return "已使用工具完成工作区任务。".encode("utf-8"), b""

        async def fake_create_subprocess_exec(*args, **kwargs):
            assert kwargs["cwd"]
            return FakeProc()

        with mock.patch(
            "loom_core.agent_adapters.providers.runtime_hand.asyncio.create_subprocess_exec",
            new=fake_create_subprocess_exec,
        ):
            events = []
            async for event in adapter._invoke_process(
                {"execution_mode": "agent", "task": "test", "cwd": "."},
                "run-agent",
            ):
                events.append(event)

        message = next(event for event in events if event["type"] == "run.message")
        assert "完成工作区任务" in message["text"]
        assert any(event["type"] == "run.completed" for event in events)
        assert not any(event["type"] == "run.error" for event in events)
    async def test_invoke_process_emits_run_error_for_api_error_output(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["claude", "-p"], [])

        class FakeProc:
            returncode = 1

            async def communicate(self, input=None):
                return (
                    b"API Error: 503 status code (no body) \xc2\xb7 check status.claude.com\n",
                    b"",
                )

        async def fake_create_subprocess_exec(*args, **kwargs):
            return FakeProc()

        with mock.patch(
            "loom_core.agent_adapters.providers.runtime_hand.asyncio.create_subprocess_exec",
            new=fake_create_subprocess_exec,
        ):
            events = []
            async for event in adapter._invoke_process({"task": "test"}, "run-1"):
                events.append(event)

        assert any(event["type"] == "run.error" for event in events)
        assert not any(event["type"] == "run.completed" for event in events)
        assert "503" in next(event["message"] for event in events if event["type"] == "run.error")

    async def test_invoke_process_emits_completed_when_artifact_exists(self):
        adapter = RuntimeHandAdapter("runtime-hand", ["claude", "-p"], [])

        class FakeProc:
            returncode = 0

            async def communicate(self, input=None):
                payload = b'{"type":"run.artifact","artifact":{"metadata":{"confidence":0.8},"narrative":"ok"}}\n'
                return payload, b""

        async def fake_create_subprocess_exec(*args, **kwargs):
            return FakeProc()

        with mock.patch(
            "loom_core.agent_adapters.providers.runtime_hand.asyncio.create_subprocess_exec",
            new=fake_create_subprocess_exec,
        ):
            events = []
            async for event in adapter._invoke_process({"task": "test"}, "run-2"):
                events.append(event)

        assert any(event["type"] == "run.artifact" for event in events)
        assert any(event["type"] == "run.completed" for event in events)
