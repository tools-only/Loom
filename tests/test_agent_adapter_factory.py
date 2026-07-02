import unittest
from unittest.mock import patch

from loom_core.agent_adapters.adapter import AgentAdapter
from loom_core.agent_adapters.factory import (
    adapter_from_config,
    adapter_public_info,
    normalize_adapter_config,
    persistable_adapter_config,
)


class AgentAdapterFactoryTests(unittest.TestCase):
    def test_builds_process_adapter_from_list_command(self):
        adapter = adapter_from_config({
            "adapter_id": "codex-local",
            "transport": "process",
            "protocol": "loom",
            "command": ["codex", "run"],
            "capabilities": ["runtime.hand"],
        })

        self.assertIsInstance(adapter, AgentAdapter)
        self.assertEqual(adapter.id, "codex-local")
        self.assertEqual(adapter._command, ["codex", "run"])
        self.assertEqual(adapter._transport_kind, "process")
        self.assertEqual(adapter._protocol, "loom")

    def test_builds_openai_compatible_http_adapter(self):
        adapter = adapter_from_config({
            "adapter_id": "codex-app-service",
            "transport": "http",
            "protocol": "openai",
            "endpoint": "http://127.0.0.1:8787/v1/chat/completions",
            "auth_token": "sk-local",
            "capabilities": ["runtime.hand"],
            "system_prompt": "return run.artifact",
        })

        self.assertEqual(adapter.id, "codex-app-service")
        self.assertEqual(adapter._transport_kind, "http")
        self.assertEqual(adapter._protocol, "openai")
        self.assertEqual(adapter._endpoint, "http://127.0.0.1:8787/v1/chat/completions")

    def test_builds_codex_app_server_process_adapter(self):
        adapter = adapter_from_config({
            "adapter_id": "codex-app-server",
            "transport": "process",
            "protocol": "codex",
            "codex_home": "D:/agent/.codex",
            "capabilities": ["runtime.hand", "workspace.patch"],
        })

        self.assertEqual(adapter.id, "codex-app-server")
        self.assertEqual(adapter._transport_kind, "process")
        self.assertEqual(adapter._protocol, "codex")
        self.assertEqual(adapter._command, [])
        self.assertEqual(adapter._codex_backend, "sdk")
        self.assertEqual(adapter._codex_home, "D:/agent/.codex")
        self.assertEqual(
            persistable_adapter_config({
                "adapter_id": "codex-app-server",
                "transport": "process",
                "protocol": "codex",
                "codex_home": "D:/agent/.codex",
            })["codex_home"],
            "D:/agent/.codex",
        )
        self.assertEqual(adapter_public_info(adapter)["codex_home"], "D:/agent/.codex")

    def test_builds_raw_codex_app_server_process_adapter(self):
        adapter = adapter_from_config({
            "adapter_id": "codex-app-server-raw",
            "transport": "process",
            "protocol": "codex",
            "codex_backend": "raw",
            "command": ["codex", "app-server"],
        })

        self.assertEqual(adapter._codex_backend, "raw")
        self.assertEqual(adapter._command, ["codex", "app-server"])

    def test_builds_codex_app_server_websocket_adapter(self):
        adapter = adapter_from_config({
            "adapter_id": "codex-app-server-ws",
            "transport": "ws",
            "protocol": "codex",
            "endpoint": "ws://127.0.0.1:4222",
            "capabilities": ["runtime.hand", "workspace.patch"],
        })

        self.assertEqual(adapter.id, "codex-app-server-ws")
        self.assertEqual(adapter._transport_kind, "websocket")
        self.assertEqual(adapter._protocol, "codex")
        self.assertEqual(adapter._endpoint, "ws://127.0.0.1:4222")

    def test_rejects_process_adapter_without_command(self):
        with self.assertRaises(ValueError):
            normalize_adapter_config({
                "adapter_id": "bad-process",
                "transport": "process",
                "protocol": "loom",
            })

    def test_rejects_raw_codex_process_adapter_without_command(self):
        with self.assertRaises(ValueError):
            normalize_adapter_config({
                "adapter_id": "bad-codex-process",
                "transport": "process",
                "protocol": "codex",
                "codex_backend": "raw",
            })

    def test_public_info_excludes_auth_token(self):
        adapter = adapter_from_config({
            "adapter_id": "secure-http",
            "transport": "http",
            "protocol": "openai",
            "endpoint": "https://agent.example.com/v1/chat/completions",
            "auth_token": "secret-token",
        })

        info = adapter_public_info(adapter)
        self.assertNotIn("auth_token", info)
        self.assertNotIn("secret-token", repr(info))
        self.assertEqual(info["id"], "secure-http")

    def test_auth_token_env_resolves_without_exposing_secret(self):
        with patch.dict("os.environ", {"LOOM_TEST_AGENT_TOKEN": "env-secret"}):
            adapter = adapter_from_config({
                "adapter_id": "secure-http",
                "transport": "http",
                "protocol": "openai",
                "endpoint": "https://agent.example.com/v1/chat/completions",
                "auth_token_env": "LOOM_TEST_AGENT_TOKEN",
            })

        self.assertEqual("LOOM_TEST_AGENT_TOKEN", adapter._auth_token_env)
        self.assertEqual("env-secret", adapter._auth_token)
        info = adapter_public_info(adapter)
        self.assertEqual("LOOM_TEST_AGENT_TOKEN", info["auth_token_env"])
        self.assertTrue(info["auth_configured"])
        self.assertNotIn("env-secret", repr(info))

    def test_persistable_config_keeps_env_ref_and_drops_inline_token(self):
        persisted = persistable_adapter_config({
            "adapter_id": "secure-http",
            "transport": "http",
            "protocol": "openai",
            "endpoint": "https://agent.example.com/v1/chat/completions",
            "auth_token": "raw-secret",
            "auth_token_env": "LOOM_TEST_AGENT_TOKEN",
        })

        self.assertNotIn("auth_token", persisted)
        self.assertNotIn("raw-secret", repr(persisted))
        self.assertEqual("LOOM_TEST_AGENT_TOKEN", persisted["auth_token_env"])
        self.assertEqual("env", persisted["secret_mode"])

    def test_persistable_config_marks_inline_token_memory_only(self):
        persisted = persistable_adapter_config({
            "adapter_id": "secure-http",
            "transport": "http",
            "protocol": "openai",
            "endpoint": "https://agent.example.com/v1/chat/completions",
            "auth_token": "raw-secret",
        })

        self.assertNotIn("auth_token", persisted)
        self.assertNotIn("raw-secret", repr(persisted))
        self.assertEqual("", persisted["auth_token_env"])
        self.assertEqual("memory_only", persisted["secret_mode"])


if __name__ == "__main__":
    unittest.main()
