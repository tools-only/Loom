from pathlib import Path
import unittest

from loom_core.domain_sdk.registry import (
    build_domain_manifest_response,
    load_domain_manifests,
)


class DomainRegistryTests(unittest.TestCase):
    def test_loads_loom_fin_manifest(self):
        root = Path(__file__).resolve().parents[1]
        manifests = load_domain_manifests(root)
        loom_fin = next(item for item in manifests if item["id"] == "loom-fin")

        self.assertEqual(loom_fin["runtime"], "local-desktop-single-user")
        self.assertEqual(loom_fin["interface"], "loom-agent-adapter")
        self.assertIs(loom_fin["compatibility"]["preserveExistingExperience"], True)
        self.assertIn("market.regime.review", loom_fin["capabilities"])
        self.assertIn(
            "market.regime.review",
            {task["id"] for task in loom_fin["agentTasks"]},
        )
        self.assertNotIn("legacyPythonBrain", loom_fin["paths"])

    def test_public_response_omits_manifest_path(self):
        root = Path(__file__).resolve().parents[1]
        response = build_domain_manifest_response(load_domain_manifests(root))

        self.assertIs(response["ok"], True)
        loom_fin = next(item for item in response["domains"] if item["id"] == "loom-fin")
        self.assertNotIn("manifest_path", loom_fin)


if __name__ == "__main__":
    unittest.main()
