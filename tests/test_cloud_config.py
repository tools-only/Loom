import json
import os
import tempfile
import unittest
from pathlib import Path


class CloudConfigTests(unittest.TestCase):
    def _write_config(self, tmp: Path, data: dict) -> None:
        cfg_dir = tmp / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "cloud-agents.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_returns_empty_when_no_config_file(self):
        from loom_core.agent_adapters.cloud_config import load_cloud_agents

        with tempfile.TemporaryDirectory() as tmp:
            result = load_cloud_agents(Path(tmp))
        self.assertEqual(result, {})

    def test_skips_adapter_when_token_env_missing(self):
        from loom_core.agent_adapters.cloud_config import load_cloud_agents

        with tempfile.TemporaryDirectory() as tmp:
            self._write_config(Path(tmp), {
                "test-cloud": {
                    "endpoint": "https://example.com/run",
                    "capabilities": ["market.analysis"],
                    "token_env": "TEST_CLOUD_TOKEN_MISSING_XYZ",
                    "require_auth": True,
                }
            })
            os.environ.pop("TEST_CLOUD_TOKEN_MISSING_XYZ", None)
            result = load_cloud_agents(Path(tmp))
        self.assertEqual(result, {})

    def test_loads_adapter_when_token_in_env(self):
        from loom_core.agent_adapters.cloud_config import load_cloud_agents

        with tempfile.TemporaryDirectory() as tmp:
            self._write_config(Path(tmp), {
                "test-cloud": {
                    "endpoint": "https://example.com/run",
                    "capabilities": ["market.analysis"],
                    "token_env": "TEST_CLOUD_TOKEN_ABC",
                    "require_auth": True,
                    "timeout_s": 90,
                }
            })
            os.environ["TEST_CLOUD_TOKEN_ABC"] = "sk-test"
            try:
                result = load_cloud_agents(Path(tmp))
            finally:
                del os.environ["TEST_CLOUD_TOKEN_ABC"]

        self.assertIn("test-cloud", result)
        cfg = result["test-cloud"]
        self.assertEqual(cfg["endpoint"], "https://example.com/run")
        self.assertEqual(cfg["auth_token"], "sk-test")
        self.assertEqual(cfg["auth_token_env"], "TEST_CLOUD_TOKEN_ABC")
        self.assertEqual(cfg["capabilities"], ["market.analysis"])
        self.assertEqual(cfg["timeout_s"], 90.0)

    def test_allows_no_auth_adapter(self):
        from loom_core.agent_adapters.cloud_config import load_cloud_agents

        with tempfile.TemporaryDirectory() as tmp:
            self._write_config(Path(tmp), {
                "public-agent": {
                    "endpoint": "https://public.example.com/run",
                    "capabilities": [],
                    "require_auth": False,
                }
            })
            result = load_cloud_agents(Path(tmp))

        self.assertIn("public-agent", result)
        self.assertIsNone(result["public-agent"]["auth_token"])

    def test_default_token_env_derived_from_id(self):
        from loom_core.agent_adapters.cloud_config import load_cloud_agents

        with tempfile.TemporaryDirectory() as tmp:
            self._write_config(Path(tmp), {
                "my-cloud-agent": {
                    "endpoint": "https://example.com/run",
                    "require_auth": True,
                    # no token_env → derives MY_CLOUD_AGENT_TOKEN
                }
            })
            os.environ["MY_CLOUD_AGENT_TOKEN"] = "derived-token"
            try:
                result = load_cloud_agents(Path(tmp))
            finally:
                del os.environ["MY_CLOUD_AGENT_TOKEN"]

        self.assertIn("my-cloud-agent", result)
        self.assertEqual(result["my-cloud-agent"]["auth_token"], "derived-token")


if __name__ == "__main__":
    unittest.main()
