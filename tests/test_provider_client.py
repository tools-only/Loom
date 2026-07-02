import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from loom import provider_client


class ProviderClientAuthTests(unittest.TestCase):
    def test_default_brain_command_isolated_from_user_claude_settings(self):
        with patch.dict(os.environ, {
            "LOOM_BRAIN_AGENT_COMMAND": "",
            "LOOM_RUNTIME_HAND_COMMAND": "",
        }):
            command = provider_client._brain_agent_command()

        self.assertEqual("claude", command[0])
        self.assertIn("--setting-sources", command)
        self.assertEqual("project", command[command.index("--setting-sources") + 1])
        self.assertEqual("sonnet", command[command.index("--model") + 1])

    def test_social_router_uses_independent_lightweight_agent_command(self):
        with patch.dict(os.environ, {
            "LOOM_SOCIAL_ROUTER_AGENT_COMMAND": "",
            "LOOM_BRAIN_AGENT_COMMAND": json.dumps(["custom-brain", "--print"]),
        }):
            command = provider_client._social_router_agent_command()

        self.assertEqual("claude", command[0])
        self.assertEqual("project", command[command.index("--setting-sources") + 1])
        self.assertEqual("haiku", command[command.index("--model") + 1])
        self.assertEqual("low", command[command.index("--effort") + 1])

    def test_social_router_command_can_be_overridden(self):
        override = json.dumps([sys.executable, "router.py"])
        with patch.dict(os.environ, {"LOOM_SOCIAL_ROUTER_AGENT_COMMAND": override}):
            self.assertEqual(
                [sys.executable, "router.py"],
                provider_client._social_router_agent_command(),
            )

    def test_brain_agent_call_honors_per_request_timeout(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "slow_agent.py"
        script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
        messages = provider_client._BrainAgentMessages(
            [sys.executable, str(script)],
            timeout_s=180,
        )

        async def call():
            await messages.create(
                system="route",
                messages=[{"role": "user", "content": "hi"}],
                timeout_s=0.1,
            )

        started = time.monotonic()
        with self.assertRaisesRegex(
            provider_client.LLMConfigurationError,
            "timed out after 0.1s",
        ):
            asyncio.run(call())
        self.assertLess(time.monotonic() - started, 2.0)

    def setUp(self):
        self._original_config_path = provider_client.CONFIG_PATH
        self._original_config = provider_client._config
        self._original_client_cache = provider_client._client_cache
        provider_client._config = {}
        provider_client._client_cache = {}

    def tearDown(self):
        provider_client.CONFIG_PATH = self._original_config_path
        provider_client._config = self._original_config
        provider_client._client_cache = self._original_client_cache

    def _write_config(self, data: dict) -> tempfile.TemporaryDirectory:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "loom-config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        provider_client.CONFIG_PATH = path
        provider_client._config = {}
        provider_client._client_cache = {}
        return tmp

    def _write_default_provider_config(self, provider: str) -> None:
        self._write_config({
            "default": {
                "provider": provider,
                "model": "",
                "api_key": "",
                "base_url": "",
            },
            "hands": {},
        })

    def _assert_missing_credentials(self, provider: str, expected_env: str) -> str:
        self._write_default_provider_config(provider)

        async def call_missing_client():
            client, model = provider_client.get_client_for_brain()
            await client.messages.create(
                model=model,
                max_tokens=1,
                system="",
                tools=[],
                messages=[{"role": "user", "content": "hi"}],
            )

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "LOOM_BRAIN_AGENT_COMMAND": "",
            "LOOM_RUNTIME_HAND_COMMAND": "",
        }):
            with patch("loom.provider_client.shutil.which", return_value=None):
                provider_client._client_cache = {}
                with self.assertRaises(provider_client.LLMConfigurationError) as raised:
                    asyncio.run(call_missing_client())

        message = str(raised.exception)
        self.assertIn(expected_env, message)
        self.assertIn("LOOM_BRAIN_AGENT_COMMAND", message)
        self.assertNotIn("Could not resolve authentication method", message)
        return message

    def test_brain_defaults_to_agent_command_without_provider_key(self):
        self._write_default_provider_config("anthropic")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "brain_agent.py"
        script.write_text("print('agent-response')\n", encoding="utf-8")
        command = json.dumps([sys.executable, str(script)])

        async def call_brain_agent():
            client, model = provider_client.get_client_for_brain()
            response = await client.messages.create(
                model=model,
                max_tokens=1,
                system="system prompt",
                tools=[],
                messages=[{"role": "user", "content": "hello"}],
            )
            return model, response

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "LOOM_BRAIN_AGENT_COMMAND": command,
        }):
            model, response = asyncio.run(call_brain_agent())

        self.assertEqual("claude-sonnet-4-6", model)
        self.assertEqual("end_turn", response.stop_reason)
        self.assertEqual("agent-response", response.content[0].text)

    def test_router_has_separate_cached_client(self):
        self._write_default_provider_config("anthropic")
        override = json.dumps([sys.executable, "-c", "print('router-response')"])

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "LOOM_SOCIAL_ROUTER_AGENT_COMMAND": override,
        }):
            client, model = provider_client.get_client_for_social_router()

        self.assertIsInstance(client, provider_client._BrainAgentClient)
        self.assertEqual("claude-haiku-4-5-20251001", model)
        self.assertIn("__social_router__", provider_client._client_cache)

    def test_hand_provider_missing_key_still_reports_actionable_error(self):
        self._write_default_provider_config("anthropic")

        async def call_hand_client():
            client, model = provider_client.get_client_for_hand("market")
            await client.messages.create(
                model=model,
                max_tokens=1,
                system="",
                tools=[],
                messages=[{"role": "user", "content": "hi"}],
            )

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "LOOM_BRAIN_AGENT_COMMAND": json.dumps([sys.executable, "-c", "print('unused')"]),
        }):
            with self.assertRaises(provider_client.LLMConfigurationError) as raised:
                asyncio.run(call_hand_client())

        message = str(raised.exception)
        self.assertIn("ANTHROPIC_API_KEY", message)
        self.assertIn("Discord bot tokens only authenticate Discord", message)

    def test_missing_anthropic_api_key_reports_actionable_error(self):
        message = self._assert_missing_credentials("anthropic", "ANTHROPIC_API_KEY")
        self.assertIn("ANTHROPIC_AUTH_TOKEN", message)

    def test_missing_openai_compatible_key_reports_provider_env_name(self):
        self._assert_missing_credentials("deepseek", "DEEPSEEK_API_KEY")


if __name__ == "__main__":
    unittest.main()
