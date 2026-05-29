from pathlib import Path
import unittest

from loom_core.agent_adapters.registry import create_adapter_registry
from loom_core.domain_sdk.registry import load_domain_manifests
from loom_core.runtime.task_router import resolve_task_route


class FakeAdapter:
    def __init__(self, adapter_id):
        self.id = adapter_id
        self.capabilities = []

    async def invoke(self, task):
        yield {"type": "complete", "task": task}

    async def cancel(self, run_id):
        return None


class TaskRoutingTests(unittest.TestCase):
    def test_resolves_fin_task_to_concrete_agent_and_adapter(self):
        root = Path(__file__).resolve().parents[1]
        manifests = load_domain_manifests(root)
        registry = create_adapter_registry()
        codex = FakeAdapter("codex")
        registry.register(codex)

        route = resolve_task_route(
            manifests=manifests,
            task_pack_id="loom-fin",
            task_id="market.regime.review",
            adapters=registry,
        )

        self.assertEqual(route.task["agent"], "fin-market-agent")
        self.assertIs(route.adapter, codex)

    def test_requires_registered_adapter(self):
        root = Path(__file__).resolve().parents[1]
        manifests = load_domain_manifests(root)
        registry = create_adapter_registry()

        with self.assertRaises(LookupError):
            resolve_task_route(
                manifests=manifests,
                task_pack_id="loom-fin",
                task_id="market.regime.review",
                adapters=registry,
            )


if __name__ == "__main__":
    unittest.main()
