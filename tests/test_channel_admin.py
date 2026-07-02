import json
import tempfile
import unittest
from pathlib import Path

from loom_core.channel_admin import run


class ChannelAdminTests(unittest.TestCase):
    def test_cli_enable_writes_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run([
                "--root",
                tmp,
                "enable",
                "telegram",
                "--channel-id",
                "telegram-work",
                "--reply-token-env",
                "LOOM_TELEGRAM_TOKEN",
                "--set",
                "webhookUrl=https://telegram.test",
                "--allow-from",
                "*",
                "--set-default",
            ])

            self.assertEqual(0, code)
            path = Path(tmp) / "config" / "social-channels.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("telegram-work", data["default_channel"])
            channel = next(item for item in data["channels"] if item["channel_id"] == "telegram-work")
            self.assertEqual("telegram", channel["platform"])
            self.assertEqual("LOOM_TELEGRAM_TOKEN", channel["replyTokenEnv"])
            self.assertEqual("https://telegram.test", channel["webhookUrl"])
            self.assertEqual(["*"], channel["allowFrom"])

    def test_cli_enable_writes_nanobot_discord_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run([
                "--root",
                tmp,
                "enable",
                "discord",
                "--set",
                "token=YOUR_BOT_TOKEN",
                "--allow-from",
                "YOUR_USER_ID",
                "--set",
                "allowChannels=",
                "--set",
                "groupPolicy=mention",
                "--set",
                "streaming=true",
            ])

            self.assertEqual(0, code)
            path = Path(tmp) / "config" / "social-channels.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            channel = next(item for item in data["channels"] if item["channel_id"] == "discord")
            self.assertEqual({
                "enabled": True,
                "token": "YOUR_BOT_TOKEN",
                "allowFrom": ["YOUR_USER_ID"],
                "allowChannels": [],
                "groupPolicy": "mention",
                "streaming": True,
            }, {
                "enabled": channel["enabled"],
                "token": channel["token"],
                "allowFrom": channel["allowFrom"],
                "allowChannels": channel["allowChannels"],
                "groupPolicy": channel["groupPolicy"],
                "streaming": channel["streaming"],
            })

    def test_cli_available_runs(self):
        self.assertEqual(0, run(["available"]))


if __name__ == "__main__":
    unittest.main()
