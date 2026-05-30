from pathlib import Path
import unittest

from loom_core.runtime.app import LoomCoreRuntime
from loom_core.domain_sdk.registry import load_domain_manifests


class RuntimeBootstrapTests(unittest.TestCase):
    def test_core_runtime_boots_locally(self):
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        self.assertTrue(runtime.is_booted)

    def test_exposes_health_status(self):
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        status = runtime.health()
        self.assertIn("status", status)
        self.assertEqual(status["status"], "ok")
        self.assertIn("manifests_loaded", status)

    def test_loads_domain_manifests_on_boot(self):
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        self.assertGreater(len(runtime.manifests), 0)
        ids = [m["id"] for m in runtime.manifests]
        self.assertIn("loom-fin", ids)

    def test_runtime_works_without_core_agent(self):
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        self.assertIsNone(runtime.core_agent)

    def test_http_api_exposes_health_endpoint(self):
        from loom_core.runtime.http_api import LoomCoreHttpApi
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        api = LoomCoreHttpApi(runtime)
        response = api.handle_request("GET", "/health")
        self.assertIn("status", response)
        self.assertEqual(response["status"], "ok")

    def test_http_api_exposes_domains(self):
        from loom_core.runtime.http_api import LoomCoreHttpApi
        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        api = LoomCoreHttpApi(runtime)
        response = api.handle_request("GET", "/domains")
        self.assertEqual(response["ok"], True)
        self.assertIn("domains", response)


if __name__ == "__main__":
    unittest.main()
