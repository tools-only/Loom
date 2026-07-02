import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from nacl.signing import SigningKey

from loom_core.interaction_protocol.social_verify import (
    extract_social_challenge,
    verify_social_request,
)


class SocialVerifyTests(unittest.TestCase):
    def test_loom_hmac_validates_trusted_bridge(self):
        body = b'{"text":"hello"}'
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LOOM_SOCIAL_INGRESS_SECRET": "secret"}, clear=True):
            result = verify_social_request(
                platform="generic",
                headers={"x-loom-signature": f"sha256={signature}"},
                body=body,
                payload={},
            )

        self.assertTrue(result.ok)
        self.assertEqual("loom_hmac", result.method)

    def test_required_verification_rejects_missing_signature(self):
        with patch.dict(os.environ, {"LOOM_SOCIAL_REQUIRE_VERIFICATION": "1"}, clear=True):
            result = verify_social_request(
                platform="generic",
                headers={},
                body=b"{}",
                payload={},
            )

        self.assertFalse(result.ok)
        self.assertIn("required", result.error)

    def test_extracts_feishu_challenge(self):
        challenge = extract_social_challenge(
            "feishu",
            {"type": "url_verification", "challenge": "abc"},
        )

        self.assertEqual("abc", challenge)

    def test_feishu_token_verification(self):
        payload = {"token": "vtok", "event": {"message": {"content": "{}"}}}

        with patch.dict(os.environ, {"LOOM_FEISHU_VERIFICATION_TOKEN": "vtok"}, clear=True):
            result = verify_social_request(
                platform="feishu",
                headers={},
                body=json.dumps(payload).encode(),
                payload=payload,
            )

        self.assertTrue(result.ok)
        self.assertEqual("feishu_token", result.method)

    def test_missing_bridge_hmac_does_not_block_platform_verifier(self):
        payload = {"token": "vtok"}

        with patch.dict(os.environ, {
            "LOOM_SOCIAL_INGRESS_SECRET": "bridge-secret",
            "LOOM_FEISHU_VERIFICATION_TOKEN": "vtok",
        }, clear=True):
            result = verify_social_request(
                platform="feishu",
                headers={},
                body=json.dumps(payload).encode(),
                payload=payload,
                require_verification=True,
            )

        self.assertTrue(result.ok)
        self.assertEqual("feishu_token", result.method)

    def test_feishu_bot_signature_verification(self):
        timestamp = "1781440000"
        secret = "bot-secret"
        digest = hmac.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
        sign = base64.b64encode(digest).decode()
        payload = {"timestamp": timestamp, "sign": sign}

        with patch.dict(os.environ, {"LOOM_FEISHU_BOT_SECRET": secret}, clear=True):
            result = verify_social_request(
                platform="feishu",
                headers={},
                body=json.dumps(payload).encode(),
                payload=payload,
            )

        self.assertTrue(result.ok)
        self.assertEqual("feishu_bot_hmac", result.method)

    def test_discord_ed25519_verification(self):
        signing_key = SigningKey.generate()
        verify_key_hex = signing_key.verify_key.encode().hex()
        timestamp = "1781440000"
        body = b'{"type":1}'
        signature = signing_key.sign(timestamp.encode() + body).signature.hex()

        with patch.dict(os.environ, {"LOOM_DISCORD_PUBLIC_KEY": verify_key_hex}, clear=True):
            result = verify_social_request(
                platform="discord",
                headers={
                    "x-signature-ed25519": signature,
                    "x-signature-timestamp": timestamp,
                },
                body=body,
                payload={"type": 1},
            )

        self.assertTrue(result.ok)
        self.assertEqual("discord_ed25519", result.method)


if __name__ == "__main__":
    unittest.main()
