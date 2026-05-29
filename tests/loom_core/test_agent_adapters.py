import unittest

from loom_core.agent_adapters.registry import create_adapter_registry


class FakeAdapter:
    id = "fake-codex"
    capabilities = ["market.regime.review", "workspace.patch"]

    async def invoke(self, task):
        yield {"type": "complete", "task": task}

    async def cancel(self, run_id):
        return None


class AgentAdapterRegistryTests(unittest.TestCase):
    def test_registers_and_lists_adapters(self):
        registry = create_adapter_registry()
        adapter = FakeAdapter()

        registry.register(adapter)

        self.assertEqual(registry.list(), [adapter])

    def test_resolves_adapter_by_capability(self):
        registry = create_adapter_registry()
        adapter = FakeAdapter()
        registry.register(adapter)

        self.assertIs(registry.find_by_capability("market.regime.review"), adapter)
        self.assertIsNone(registry.find_by_capability("sentiment.scan"))


if __name__ == "__main__":
    unittest.main()
