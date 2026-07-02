import json
import unittest

from loom_core.interaction_protocol.social import (
    build_analyze_request_from_social,
    is_explicit_loom_command,
    normalize_social_payload,
    parse_social_command,
    parse_agent_command,
    resolve_social_agent_request,
    parse_yes_no,
)


class SocialIngressTests(unittest.TestCase):
    def test_parse_agent_command_supports_generic_and_provider_aliases(self):
        generic = parse_agent_command("/agent codex-app-server inspect the workspace")
        codex = parse_agent_command("/codex inspect the workspace")
        claude = parse_agent_command("/claude inspect the workspace")

        self.assertEqual(("codex-app-server", "inspect the workspace"), (generic.adapter_id, generic.task))
        self.assertEqual(("codex-app-server", "inspect the workspace"), (codex.adapter_id, codex.task))
        self.assertEqual(("runtime-hand", "inspect the workspace"), (claude.adapter_id, claude.task))
        self.assertIsNone(parse_agent_command("/loom inspect the workspace"))

    def test_resolve_agent_request_supports_channel_default_and_keeps_loom_explicit(self):
        settings = {
            "channel_settings": {
                "executionMode": "agent",
                "agentAdapterId": "codex-app-server",
                "agentAllowFrom": ["u1"],
            }
        }

        direct = resolve_social_agent_request(
            text="inspect the workspace",
            user_id="u1",
            context=settings,
            default_adapter_id="runtime-hand",
        )
        loom = resolve_social_agent_request(
            text="/loom inspect the workspace",
            user_id="u1",
            context=settings,
            default_adapter_id="runtime-hand",
        )

        self.assertEqual("codex-app-server", direct.adapter_id)
        self.assertEqual("inspect the workspace", direct.task)
        self.assertIsNone(loom)

    def test_agent_request_requires_explicit_agent_allowlist(self):
        with self.assertRaisesRegex(PermissionError, "agentAllowFrom"):
            resolve_social_agent_request(
                text="/codex inspect the workspace",
                user_id="u1",
                context={"channel_settings": {"allowFrom": ["*"]}},
                default_adapter_id="runtime-hand",
            )
    def test_parses_binary_confirmation_answers_only(self):
        self.assertIs(parse_yes_no("是"), True)
        self.assertIs(parse_yes_no("yes"), True)
        self.assertIs(parse_yes_no("否"), False)
        self.assertIs(parse_yes_no("no"), False)
        self.assertIsNone(parse_yes_no("我想先看看"))

    def test_normalizes_feishu_text_message(self):
        payload = {
            "header": {"event_id": "evt_1", "create_time": "1781440000"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_1"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_1",
                    "content": json.dumps({"text": "<at user_id=\"bot\">Loom</at> /loom finance review AI capex"}),
                },
            },
        }

        message = normalize_social_payload(payload, platform="feishu")

        self.assertEqual(message.platform, "feishu")
        self.assertEqual(message.user_id, "ou_1")
        self.assertEqual(message.channel_id, "oc_1")
        self.assertEqual(message.message_id, "om_1")
        self.assertEqual(message.text, "/loom finance review AI capex")

    def test_normalizes_discord_message_and_strips_bot_mention(self):
        message = normalize_social_payload({
            "id": "msg_1",
            "channel_id": "chan_1",
            "author": {"id": "user_1"},
            "content": "<@12345> loom general summarize this thread",
        }, platform="discord")

        self.assertEqual(message.platform, "discord")
        self.assertEqual(message.text, "loom general summarize this thread")
        self.assertEqual(message.user_id, "user_1")

    def test_parse_social_command_maps_finance_and_hand_hint(self):
        command = parse_social_command("/loom market check NVDA risk")

        self.assertEqual(command.domain_hint, "finance")
        self.assertEqual(command.hands, ("market",))
        self.assertEqual(command.question, "check NVDA risk")

    def test_explicit_loom_command_detection_only_matches_slash_commands(self):
        self.assertTrue(is_explicit_loom_command("/loom finance check NVDA"))
        self.assertTrue(is_explicit_loom_command("/loom-visual draw a chart"))
        self.assertFalse(is_explicit_loom_command("loom finance check NVDA"))
        self.assertFalse(is_explicit_loom_command("hello loom"))

    def test_parse_social_command_strips_loom_command_extensions(self):
        command = parse_social_command("/loom-visual draw NVDA drawdown")

        self.assertEqual(command.question, "draw NVDA drawdown")

    def test_parse_social_command_leaves_bare_loom_to_dynamic_routing(self):
        command = parse_social_command("loom finance check NVDA")

        self.assertEqual(command.question, "loom finance check NVDA")
        self.assertEqual(command.domain_hint, "")
        self.assertEqual(command.hands, ())

    def test_build_analyze_request_preserves_social_context(self):
        message = normalize_social_payload({
            "platform": "discord",
            "text": "/loom finance review portfolio drawdown",
            "user_id": "u1",
            "channel_id": "c1",
            "message_id": "m1",
        })

        request = build_analyze_request_from_social(
            message,
            extra_context={"response_mode": "reply"},
        )

        self.assertEqual(request["question"], "review portfolio drawdown")
        self.assertEqual(request["domain_hint"], "finance")
        self.assertEqual(request["context"]["source"], "social")
        self.assertEqual(request["context"]["entrypoint"], "social")
        self.assertEqual(request["context"]["session_id"], "discord:c1:u1")
        self.assertEqual(request["context"]["response_mode"], "reply")
        self.assertEqual(request["context"]["social"]["message_id"], "m1")


if __name__ == "__main__":
    unittest.main()
