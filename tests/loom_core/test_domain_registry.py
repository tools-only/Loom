from pathlib import Path
import unittest

from loom_core.domain_sdk.registry import (
    build_domain_manifest_response,
    load_domain_manifests,
)


class DomainRegistryTests(unittest.TestCase):
    def test_loads_loom_fin_manifest(self):
        root = Path(__file__).resolve().parents[2]
        manifests = load_domain_manifests(root)
        loom_fin = next(item for item in manifests if item["id"] == "loom-fin")

        self.assertEqual(loom_fin["runtime"], "local-desktop-single-user")
        self.assertIs(loom_fin["compatibility"]["preserveExistingExperience"], True)
        self.assertIn("market.regime.review", loom_fin["capabilities"])

    def test_public_response_omits_manifest_path(self):
        root = Path(__file__).resolve().parents[2]
        response = build_domain_manifest_response(load_domain_manifests(root))

        self.assertIs(response["ok"], True)
        loom_fin = next(item for item in response["domains"] if item["id"] == "loom-fin")
        self.assertNotIn("manifest_path", loom_fin)


if __name__ == "__main__":
    unittest.main()
