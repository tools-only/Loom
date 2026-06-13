"""Tests for RuntimeHandAdapter and registry default cascade."""
import unittest
from loom_core.agent_adapters.registry import AgentAdapterRegistry
from loom_core.agent_adapters.providers.runtime_hand import RuntimeHandAdapter, create_runtime_hand_provider


class TestRegistry(unittest.TestCase):
    def test_default_is_brain_inline(self):
        reg = AgentAdapterRegistry()
        assert reg.resolve_runtime_adapter("brain-inline") == "brain-inline"

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
        assert reg._default_runtime_adapter_id == "custom-adapter"


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

    def test_default_command_is_claude(self):
        prov = create_runtime_hand_provider()
        adapter = prov["instance"]
        assert adapter._command == ["claude", "-p"]

    def test_custom_command(self):
        prov = create_runtime_hand_provider(["my-model", "--json"])
        assert prov["instance"]._command == ["my-model", "--json"]
