"""Webhook verification helpers for social ingress."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SocialVerificationResult:
    ok: bool
    platform: str
    method: str = ""
    skipped: bool = False
    error: str = ""
    challenge: str = ""


def verify_social_request(
    *,
    platform: str,
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any] | None = None,
    require_verification: bool | None = None,
) -> SocialVerificationResult:
    """Verify a social webhook request when credentials are configured.

    Local/manual calls remain allowed by default. Set
    ``LOOM_SOCIAL_REQUIRE_VERIFICATION=1`` to require one configured verifier.
    """
    platform = (platform or "generic").lower()
    payload = payload if isinstance(payload, dict) else {}
    challenge = extract_social_challenge(platform, payload)
    if challenge:
        return SocialVerificationResult(
            ok=True,
            platform=platform,
            method="challenge",
            challenge=challenge,
        )

    require = _env_truthy("LOOM_SOCIAL_REQUIRE_VERIFICATION")
    if require_verification is not None:
        require = require_verification

    generic = verify_loom_hmac(headers=headers, body=body)
    if generic.ok:
        return SocialVerificationResult(ok=True, platform=platform, method=generic.method)
    if generic.method:
        return SocialVerificationResult(ok=False, platform=platform, method=generic.method, error=generic.error)

    if platform == "discord":
        discord = verify_discord_ed25519(headers=headers, body=body)
        if discord.ok:
            return discord
        if discord.method:
            return discord if require else SocialVerificationResult(
                ok=True,
                platform=platform,
                skipped=True,
                error=discord.error,
            )

    if platform in {"feishu", "lark"}:
        feishu = verify_feishu_request(headers=headers, body=body, payload=payload)
        if feishu.ok:
            return feishu
        if feishu.method:
            return feishu if require else SocialVerificationResult(
                ok=True,
                platform=platform,
                skipped=True,
                error=feishu.error,
            )

    if require:
        return SocialVerificationResult(
            ok=False,
            platform=platform,
            error="social webhook verification is required but no valid verifier matched",
        )
    return SocialVerificationResult(ok=True, platform=platform, skipped=True)


def extract_social_challenge(platform: str, payload: dict[str, Any]) -> str:
    """Return platform URL-verification challenge text, if present."""
    platform = (platform or "generic").lower()
    event_payload = _event_payload(payload)
    if platform in {"feishu", "lark"}:
        challenge = (
            event_payload.get("challenge")
            or payload.get("challenge")
            or (payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}).get("challenge")
        )
        if challenge and str(event_payload.get("type", payload.get("type", "")) or "").lower() in {"url_verification", ""}:
            return str(challenge)
    return ""


def verify_loom_hmac(*, headers: Mapping[str, str], body: bytes) -> SocialVerificationResult:
    """Verify a trusted bridge HMAC signature.

    Header: ``X-Loom-Signature: sha256=<hex>`` or plain hex digest.
    Secret: ``LOOM_SOCIAL_INGRESS_SECRET``.
    """
    secret = os.environ.get("LOOM_SOCIAL_INGRESS_SECRET", "")
    if not secret:
        return SocialVerificationResult(ok=False, platform="generic")
    signature = _header(headers, "x-loom-signature") or _header(headers, "x-hub-signature-256")
    if not signature:
        return SocialVerificationResult(ok=False, platform="generic")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    supplied = signature.split("=", 1)[-1].strip()
    if hmac.compare_digest(expected, supplied):
        return SocialVerificationResult(ok=True, platform="generic", method="loom_hmac")
    return SocialVerificationResult(ok=False, platform="generic", method="loom_hmac", error="invalid HMAC signature")


def verify_feishu_request(
    *,
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
) -> SocialVerificationResult:
    """Verify Feishu/Lark callbacks using configured token or bot signature."""
    event_payload = _event_payload(payload)
    token = os.environ.get("LOOM_FEISHU_VERIFICATION_TOKEN") or os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
    if token:
        supplied = str(event_payload.get("token") or payload.get("token") or "")
        if hmac.compare_digest(token, supplied):
            return SocialVerificationResult(ok=True, platform="feishu", method="feishu_token")
        return SocialVerificationResult(ok=False, platform="feishu", method="feishu_token", error="invalid Feishu verification token")

    secret = os.environ.get("LOOM_FEISHU_BOT_SECRET") or os.environ.get("FEISHU_BOT_SECRET", "")
    if not secret:
        return SocialVerificationResult(ok=False, platform="feishu")
    timestamp = str(event_payload.get("timestamp") or payload.get("timestamp") or _header(headers, "x-lark-request-timestamp") or "")
    supplied = str(event_payload.get("sign") or payload.get("sign") or _header(headers, "x-lark-signature") or "")
    if not timestamp or not supplied:
        return SocialVerificationResult(ok=False, platform="feishu", method="feishu_bot_hmac", error="missing Feishu timestamp/signature")
    digest = hmac.new(f"{timestamp}\n{secret}".encode("utf-8"), b"", hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    if hmac.compare_digest(expected, supplied):
        return SocialVerificationResult(ok=True, platform="feishu", method="feishu_bot_hmac")
    return SocialVerificationResult(ok=False, platform="feishu", method="feishu_bot_hmac", error="invalid Feishu signature")


def verify_discord_ed25519(*, headers: Mapping[str, str], body: bytes) -> SocialVerificationResult:
    """Verify Discord interaction signatures with PyNaCl when configured."""
    public_key = os.environ.get("LOOM_DISCORD_PUBLIC_KEY") or os.environ.get("DISCORD_PUBLIC_KEY", "")
    if not public_key:
        return SocialVerificationResult(ok=False, platform="discord")
    signature = _header(headers, "x-signature-ed25519")
    timestamp = _header(headers, "x-signature-timestamp")
    if not signature or not timestamp:
        return SocialVerificationResult(ok=False, platform="discord", method="discord_ed25519", error="missing Discord signature headers")
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except Exception as exc:
        return SocialVerificationResult(ok=False, platform="discord", method="discord_ed25519", error=f"PyNaCl unavailable: {exc}")
    try:
        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
        return SocialVerificationResult(ok=True, platform="discord", method="discord_ed25519")
    except (ValueError, BadSignatureError) as exc:
        return SocialVerificationResult(ok=False, platform="discord", method="discord_ed25519", error=f"invalid Discord signature: {exc}")


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("payload")
    if isinstance(nested, dict):
        return nested
    return payload


def _header(headers: Mapping[str, str], name: str) -> str:
    try:
        value = headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())
        return str(value or "")
    except Exception:
        return ""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
