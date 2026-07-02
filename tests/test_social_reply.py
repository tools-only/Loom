import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from loom_core.interaction_protocol.social_reply import (
    _FEISHU_TOKEN_CACHE,
    edit_discord_message,
    render_analysis_reply,
    send_social_reply,
)


class SocialReplyTests(unittest.TestCase):
    def setUp(self):
        _FEISHU_TOKEN_CACHE.clear()

    def test_render_analysis_reply_includes_episode_and_drivers(self):
        text = render_analysis_reply({
            "ok": True,
            "episode_id": "ep-1",
            "synthesis": {
                "stance": "hold",
                "confidence": 0.72,
                "key_drivers": [{"claim": "liquidity is neutral"}],
                "reversal_condition": "rates spike",
            },
        })

        self.assertIn("stance=hold", text)
        self.assertIn("confidence=0.72", text)
        self.assertIn("episode_id=ep-1", text)
        self.assertIn("liquidity is neutral", text)

    def test_send_discord_reply_posts_content(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(204, content=b"")

        async def run():
            return await send_social_reply(
                platform="discord",
                text="hello",
                webhook_url="https://discord.example/webhook",
                http_transport=httpx.MockTransport(handler),
            )

        result = asyncio.run(run())
        self.assertTrue(result.ok)
        self.assertEqual(204, result.status_code)
        self.assertEqual("hello", captured["body"]["content"])
        self.assertEqual([], captured["body"]["allowed_mentions"]["parse"])

    def test_send_feishu_reply_posts_text_payload(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"StatusCode": 0})

        async def run():
            return await send_social_reply(
                platform="feishu",
                text="done",
                webhook_url="https://feishu.example/webhook",
                http_transport=httpx.MockTransport(handler),
            )

        result = asyncio.run(run())
        self.assertTrue(result.ok)
        self.assertEqual("text", captured["body"]["msg_type"])
        self.assertEqual("done", captured["body"]["content"]["text"])

    def test_send_discord_bot_reply_posts_channel_message(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "reply_1"})

        async def run():
            return await send_social_reply(
                platform="discord",
                text="hello",
                token="bot-token",
                channel_id="channel_1",
                message_id="message_1",
                http_transport=httpx.MockTransport(handler),
            )

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_DISCORD_WEBHOOK": "",
            "DISCORD_WEBHOOK_URL": "",
        }):
            result = asyncio.run(run())

        self.assertTrue(result.ok)
        self.assertEqual("discord_bot", result.transport)
        self.assertEqual(200, result.status_code)
        self.assertTrue(captured["url"].endswith("/api/v10/channels/channel_1/messages"))
        self.assertEqual("Bot bot-token", captured["auth"])
        self.assertEqual("hello", captured["body"]["content"])
        self.assertEqual("message_1", captured["body"]["message_reference"]["message_id"])
        self.assertFalse(captured["body"]["message_reference"]["fail_if_not_exists"])

    def test_edit_discord_message_patches_embed(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "status_1"})

        result = asyncio.run(edit_discord_message(
            token="bot-token",
            channel_id="channel_1",
            message_id="status_1",
            embed={"title": "Brain 正在汇总"},
            http_transport=httpx.MockTransport(handler),
        ))

        self.assertTrue(result.ok)
        self.assertEqual("PATCH", captured["method"])
        self.assertTrue(captured["url"].endswith("/channels/channel_1/messages/status_1"))
        self.assertEqual("Bot bot-token", captured["auth"])
        self.assertEqual([{"title": "Brain 正在汇总"}], captured["body"]["embeds"])
        self.assertEqual([], captured["body"]["allowed_mentions"]["parse"])

    def test_send_feishu_im_reply_posts_receive_id_message(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0})

        async def run():
            return await send_social_reply(
                platform="feishu",
                text="done",
                token="tenant-token",
                channel_id="chat_1",
                receive_id_type="chat_id",
                http_transport=httpx.MockTransport(handler),
            )

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_FEISHU_WEBHOOK": "",
            "FEISHU_WEBHOOK_URL": "",
        }):
            result = asyncio.run(run())

        self.assertTrue(result.ok)
        self.assertEqual("feishu_im", result.transport)
        self.assertIn("/im/v1/messages?receive_id_type=chat_id", captured["url"])
        self.assertEqual("Bearer tenant-token", captured["auth"])
        self.assertEqual("chat_1", captured["body"]["receive_id"])
        self.assertEqual("text", captured["body"]["msg_type"])
        self.assertEqual({"text": "done"}, json.loads(captured["body"]["content"]))

    def test_send_feishu_im_reply_fetches_tenant_token_from_app_credentials(self):
        captured = {"requests": []}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["requests"].append(str(request.url))
            body = json.loads(request.content)
            if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
                captured["token_body"] = body
                return httpx.Response(200, json={
                    "code": 0,
                    "tenant_access_token": "tenant-from-app",
                    "expire": 7200,
                })
            captured["message_auth"] = request.headers.get("Authorization")
            captured["message_body"] = body
            return httpx.Response(200, json={"code": 0})

        async def run():
            return await send_social_reply(
                platform="feishu",
                text="done",
                channel_id="chat_1",
                receive_id_type="chat_id",
                http_transport=httpx.MockTransport(handler),
            )

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_FEISHU_WEBHOOK": "",
            "FEISHU_WEBHOOK_URL": "",
            "LOOM_FEISHU_TENANT_ACCESS_TOKEN": "",
            "FEISHU_TENANT_ACCESS_TOKEN": "",
            "LOOM_FEISHU_APP_ID": "app-id",
            "LOOM_FEISHU_APP_SECRET": "app-secret",
            "LOOM_FEISHU_API_BASE": "https://feishu.test/open-apis",
        }):
            result = asyncio.run(run())

        self.assertTrue(result.ok)
        self.assertEqual("feishu_im", result.transport)
        self.assertEqual({
            "app_id": "app-id",
            "app_secret": "app-secret",
        }, captured["token_body"])
        self.assertEqual("Bearer tenant-from-app", captured["message_auth"])
        self.assertEqual("chat_1", captured["message_body"]["receive_id"])
        self.assertEqual(2, len(captured["requests"]))

    def test_send_feishu_im_reply_reuses_cached_app_token(self):
        counts = {"token": 0, "message": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
                counts["token"] += 1
                return httpx.Response(200, json={
                    "code": 0,
                    "tenant_access_token": "cached-token",
                    "expire": 7200,
                })
            counts["message"] += 1
            self.assertEqual("Bearer cached-token", request.headers.get("Authorization"))
            return httpx.Response(200, json={"code": 0})

        async def run():
            transport = httpx.MockTransport(handler)
            first = await send_social_reply(
                platform="feishu",
                text="one",
                channel_id="chat_1",
                http_transport=transport,
            )
            second = await send_social_reply(
                platform="feishu",
                text="two",
                channel_id="chat_1",
                http_transport=transport,
            )
            return first, second

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_FEISHU_WEBHOOK": "",
            "FEISHU_WEBHOOK_URL": "",
            "LOOM_FEISHU_TENANT_ACCESS_TOKEN": "",
            "FEISHU_TENANT_ACCESS_TOKEN": "",
            "LOOM_FEISHU_APP_ID": "app-id",
            "LOOM_FEISHU_APP_SECRET": "app-secret",
            "LOOM_FEISHU_API_BASE": "https://feishu.test/open-apis",
        }):
            first, second = asyncio.run(run())

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(1, counts["token"])
        self.assertEqual(2, counts["message"])

    def test_send_feishu_im_reply_surfaces_token_fetch_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 999, "msg": "bad app credentials"})

        async def run():
            return await send_social_reply(
                platform="feishu",
                text="done",
                channel_id="chat_1",
                http_transport=httpx.MockTransport(handler),
            )

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_FEISHU_WEBHOOK": "",
            "FEISHU_WEBHOOK_URL": "",
            "LOOM_FEISHU_TENANT_ACCESS_TOKEN": "",
            "FEISHU_TENANT_ACCESS_TOKEN": "",
            "LOOM_FEISHU_APP_ID": "app-id",
            "LOOM_FEISHU_APP_SECRET": "bad-secret",
            "LOOM_FEISHU_API_BASE": "https://feishu.test/open-apis",
        }):
            result = asyncio.run(run())

        self.assertFalse(result.ok)
        self.assertEqual("feishu_token", result.transport)
        self.assertIn("bad app credentials", result.error)

    def test_missing_webhook_skips_without_error(self):
        with patch.dict(os.environ, {
            "LOOM_SOCIAL_REPLY_DISCORD_WEBHOOK": "",
            "DISCORD_WEBHOOK_URL": "",
            "LOOM_DISCORD_BOT_TOKEN": "",
            "DISCORD_BOT_TOKEN": "",
        }):
            result = asyncio.run(send_social_reply(platform="discord", text="hello"))

        self.assertTrue(result.ok)
        self.assertTrue(result.skipped)


if __name__ == "__main__":
    unittest.main()
