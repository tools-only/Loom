import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from loom_core.interaction_protocol.social_channel import (
    available_social_channel_types,
    channel_config_fields,
    create_default_social_channel_registry,
    social_channel_from_config,
)
from loom_core.interaction_protocol.social_channel_config import (
    create_social_channel_registry_from_document,
    load_social_channel_document,
    registry_to_document,
    save_social_channel_document,
)


class SocialChannelTests(unittest.TestCase):
    def test_default_registry_resolves_platform_and_default(self):
        registry = create_default_social_channel_registry()

        self.assertEqual("generic", registry.get_default())
        self.assertEqual("generic", registry.resolve(platform="discord").id)
        self.assertEqual("generic", registry.resolve(platform="feishu").id)
        self.assertEqual("generic", registry.resolve().id)

    def test_nanobot_channel_catalog_includes_full_builtin_set(self):
        platforms = {item["platform"] for item in available_social_channel_types()}

        self.assertTrue({
            "dingtalk",
            "email",
            "matrix",
            "mochat",
            "msteams",
            "napcat",
            "qq",
            "signal",
            "slack",
            "telegram",
            "websocket",
            "wecom",
            "weixin",
            "whatsapp",
        }.issubset(platforms))

    def test_channel_catalog_is_bridge_only(self):
        catalog = available_social_channel_types()

        self.assertEqual({"bridge"}, {item["status"] for item in catalog})

    def test_channel_catalog_exposes_platform_field_schema(self):
        telegram_fields = {item["name"] for item in channel_config_fields("telegram")}
        discord_fields = {item["name"] for item in channel_config_fields("discord")}
        feishu = next(item for item in available_social_channel_types() if item["platform"] == "feishu")

        self.assertIn("token", telegram_fields)
        self.assertIn("mode", telegram_fields)
        self.assertIn("allowFrom", discord_fields)
        self.assertIn("allowChannels", discord_fields)
        self.assertIn("groupPolicy", discord_fields)
        self.assertIn("executionMode", discord_fields)
        self.assertIn("agentAdapterId", discord_fields)
        self.assertIn("agentAllowFrom", discord_fields)
        self.assertIn("agentWorkspace", discord_fields)
        self.assertIn("ingressTimeoutMs", discord_fields)
        self.assertIn("appId", feishu["config_fields"])
        self.assertIn("appSecret", feishu["config_fields"])
        self.assertIn("fields", feishu)

    def test_disabled_channel_cannot_be_selected_explicitly(self):
        registry = create_default_social_channel_registry()

        for channel_id in ("discord", "feishu", "telegram"):
            with self.subTest(channel_id=channel_id):
                with self.assertRaisesRegex(ValueError, "disabled"):
                    registry.resolve(channel_id=channel_id)

    def test_explicit_channel_id_wins_over_platform(self):
        registry = create_social_channel_registry_from_document({
            "default_channel": "generic",
            "channels": [
                {"channel_id": "generic", "platform": "generic", "enabled": True},
                {"channel_id": "discord", "platform": "discord", "enabled": True},
                {"channel_id": "feishu", "platform": "feishu", "enabled": True},
            ],
        })

        channel = registry.resolve(channel_id="feishu", platform="discord")

        self.assertEqual("feishu", channel.id)
        self.assertEqual("feishu", channel.platform)

    def test_nanobot_discord_config_shape_is_supported(self):
        registry = create_social_channel_registry_from_document({
            "default_channel": "discord",
            "channels": {
                "discord": {
                    "enabled": True,
                    "token": "YOUR_BOT_TOKEN",
                    "allowFrom": ["YOUR_USER_ID"],
                    "allowChannels": [],
                    "groupPolicy": "mention",
                    "streaming": True,
                }
            },
        })

        channel = registry.resolve(channel_id="discord")
        exported = channel.config_dict()
        info = channel.public_info()

        self.assertTrue(channel.is_allowed("YOUR_USER_ID"))
        self.assertFalse(channel.is_allowed("OTHER_USER_ID"))
        self.assertEqual("YOUR_BOT_TOKEN", exported["token"])
        self.assertEqual([], exported["allowChannels"])
        self.assertEqual("mention", exported["groupPolicy"])
        self.assertTrue(exported["streaming"])
        self.assertNotIn("YOUR_BOT_TOKEN", json.dumps(info))
        self.assertTrue(info["settings"]["token_configured"])

    def test_channel_context_injects_adapter_metadata(self):
        channel = social_channel_from_config({
            "channel_id": "discord-team-a",
            "platform": "discord",
            "label": "Discord Team A",
            "response_mode": "reply",
            "allowFrom": ["*"],
            "api_base": "https://discord.test/api",
            "default_context": {"workspace": "team-a"},
        })

        context = channel.context({"request_id": "req-1"})

        self.assertEqual("reply", context["response_mode"])
        self.assertEqual("team-a", context["workspace"])
        self.assertEqual("req-1", context["request_id"])
        self.assertEqual("discord-team-a", context["social_channel"]["id"])
        self.assertEqual("open", context["social_channel"]["allow_policy"])
        self.assertEqual("https://discord.test/api", context["channel_settings"]["api_base"])

    def test_direct_agent_channel_settings_round_trip(self):
        channel = social_channel_from_config({
            "channel_id": "discord-agent",
            "platform": "discord",
            "executionMode": "agent",
            "agentAdapterId": "codex-app-server",
            "agentAllowFrom": ["user-1"],
            "agentWorkspace": "D:/workspace",
            "ingressTimeoutMs": 1800000,
        })

        context = channel.context()

        self.assertEqual("agent", context["channel_settings"]["executionMode"])
        self.assertEqual("codex-app-server", context["channel_settings"]["agentAdapterId"])
        self.assertEqual(["user-1"], context["channel_settings"]["agentAllowFrom"])

    def test_platform_specific_settings_round_trip(self):
        channel = social_channel_from_config({
            "channel_id": "matrix-team",
            "platform": "matrix",
            "homeserver": "https://matrix.example",
            "room_id": "!room:example",
        })

        config = channel.config_dict(redact_secrets=True)

        self.assertEqual("https://matrix.example", config["homeserver"])
        self.assertEqual("!room:example", config["room_id"])

    def test_allow_from_supports_open_restricted_and_deny_all(self):
        open_channel = social_channel_from_config({
            "channel_id": "open",
            "platform": "generic",
            "allow_from": ["*"],
        })
        restricted = social_channel_from_config({
            "channel_id": "restricted",
            "platform": "generic",
            "allow_from": ["u1"],
        })
        deny_all = social_channel_from_config({
            "channel_id": "deny",
            "platform": "generic",
            "allow_from": [],
        })

        self.assertTrue(open_channel.is_allowed("anyone"))
        self.assertTrue(restricted.is_allowed("u1"))
        self.assertFalse(restricted.is_allowed("u2"))
        self.assertFalse(deny_all.is_allowed("u1"))
        self.assertEqual("restricted", restricted.public_info()["allow_policy"])
        self.assertEqual("deny_all", deny_all.public_info()["allow_policy"])

    def test_public_info_redacts_inline_secret_values(self):
        channel = social_channel_from_config({
            "channel_id": "secure-discord",
            "platform": "discord",
            "reply_webhook_url": "https://discord.example/private",
            "reply_token": "secret-token",
        })

        info = channel.public_info()

        self.assertTrue(info["webhook_configured"])
        self.assertTrue(info["token_configured"])
        self.assertNotIn("private", json.dumps(info))
        self.assertNotIn("secret-token", json.dumps(info))

    def test_misplaced_env_secret_is_memory_only(self):
        channel = social_channel_from_config({
            "channel_id": "secure-discord",
            "platform": "discord",
            "reply_token_env": "token.with.dots",
        })

        info = channel.public_info()
        persisted = channel.config_dict(redact_secrets=True)

        self.assertTrue(info["token_configured"])
        self.assertEqual("", info["replyTokenEnv"])
        self.assertNotIn("token.with.dots", json.dumps(info))
        self.assertNotIn("token.with.dots", json.dumps(persisted))
        self.assertEqual("memory_only", persisted["secret_mode"])

    def test_send_reply_uses_env_backed_webhook(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(204, content=b"")

        channel = social_channel_from_config({
            "channel_id": "discord-env",
            "platform": "discord",
            "reply_webhook_env": "LOOM_TEST_DISCORD_WEBHOOK",
        })
        message = channel.normalize_payload({
            "platform": "discord",
            "content": "hello",
            "author": {"id": "u1"},
            "channel_id": "c1",
            "id": "m1",
        })

        async def run():
            return await channel.send_reply(
                text="done",
                message=message,
                http_transport=httpx.MockTransport(handler),
            )

        with patch.dict(os.environ, {"LOOM_TEST_DISCORD_WEBHOOK": "https://discord.example/webhook"}):
            result = asyncio.run(run())

        self.assertTrue(result.ok)
        self.assertEqual("https://discord.example/webhook", captured["url"])
        self.assertEqual("done", captured["body"]["content"])

    def test_config_document_round_trips_and_redacts_inline_secrets(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "social-channels.json"
            save_social_channel_document(
                path,
                default_channel="generic",
                channels=[
                    {
                        "channel_id": "telegram-work",
                        "platform": "telegram",
                        "enabled": True,
                        "reply_token": "secret",
                        "reply_token_env": "LOOM_TELEGRAM_TOKEN",
                        "allow_from": ["*"],
                    }
                ],
            )
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"replyToken": "secret"', text)
            self.assertIn('"allowFrom"', text)

            document = load_social_channel_document(path)
            registry = create_social_channel_registry_from_document(document)
            self.assertEqual("telegram-work", registry.resolve(channel_id="telegram-work").id)

            exported = registry_to_document(registry)
            self.assertEqual("generic", exported["default_channel"])


if __name__ == "__main__":
    unittest.main()
