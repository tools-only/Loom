import unittest

from loom_core.agent_adapters.registry import AgentAdapterRegistry
from loom_core.agent_service import AgentSessionService


class _FakeAdapter:
    id = "full-agent"
    capabilities = ["runtime.hand", "workspace.patch"]

    async def invoke(self, task):
        assert task["execution_mode"] == "agent"
        assert task["task"] == "inspect the workspace"
        yield {"type": "run.started", "run_id": "run-1"}
        yield {"type": "run.partial", "text": "working"}
        yield {"type": "run.message", "text": "workspace inspected"}
        yield {"type": "run.completed", "run_id": "run-1", "exit_code": 0}


class AgentSessionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_selected_adapter_as_full_agent_session(self):
        registry = AgentAdapterRegistry()
        registry.register(_FakeAdapter())
        service = AgentSessionService(registry)

        result = await service.run(
            adapter_id="full-agent",
            task="inspect the workspace",
            cwd=".",
            context={"source": "social"},
        )

        self.assertEqual("run-1", result["run_id"])
        self.assertEqual("full-agent", result["adapter_id"])
        self.assertEqual("workspace inspected", result["text"])
        self.assertEqual("completed", result["status"])

    async def test_rejects_unknown_adapter_before_starting_a_session(self):
        service = AgentSessionService(AgentAdapterRegistry())

        with self.assertRaisesRegex(ValueError, "unknown agent adapter"):
            await service.run(adapter_id="missing", task="hello")

    async def test_rejects_prompt_only_adapter_for_full_agent_session(self):
        class PromptOnlyAdapter:
            id = "brain-inline"
            capabilities = ["brain.inline"]

        registry = AgentAdapterRegistry()
        registry.register(PromptOnlyAdapter())
        service = AgentSessionService(registry)

        with self.assertRaisesRegex(ValueError, "not a full agent runtime"):
            await service.run(adapter_id="brain-inline", task="hello")


if __name__ == "__main__":
    unittest.main()
