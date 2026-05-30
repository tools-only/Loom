import unittest

from loom_core.agent_adapters.registry import create_adapter_registry
from loom_core.agent_adapters.providers import create_providers


class ProviderRegistryTests(unittest.TestCase):
    def test_create_providers_returns_dict(self):
        providers = create_providers()
        self.assertIsInstance(providers, dict)

    def test_codex_provider_has_required_fields(self):
        providers = create_providers()
        codex = providers.get("codex")
        self.assertIsNotNone(codex)
        self.assertEqual(codex["id"], "codex")
        self.assertIn("capabilities", codex)

    def test_cc_provider_has_required_fields(self):
        providers = create_providers()
        cc = providers.get("cc")
        self.assertIsNotNone(cc)
        self.assertEqual(cc["id"], "cc")
        self.assertIn("capabilities", cc)

    def test_providers_can_be_registered_in_registry(self):
        registry = create_adapter_registry()
        providers = create_providers()
        for pid, info in providers.items():
            registry.register(info["instance"])
        self.assertGreaterEqual(len(registry.list()), 2)

    def test_registry_resolves_codex_by_capability(self):
        registry = create_adapter_registry()
        providers = create_providers()
        for info in providers.values():
            registry.register(info["instance"])
        for cap in ["market.regime.review", "ticker.thesis.review"]:
            self.assertIsNotNone(registry.find_by_capability(cap))


if __name__ == "__main__":
    unittest.main()
