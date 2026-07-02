"""Outbound social reply helpers for Brain results."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

_FEISHU_TOKEN_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class SocialReplyResult:
    ok: bool
    platform: str
    skipped: bool = False
    status_code: int = 0
    error: str = ""
    text: str = ""
    transport: str = ""


@dataclass(frozen=True)
class _FeishuTokenResult:
    ok: bool
    token: str = ""
    reply: SocialReplyResult | None = None


def render_analysis_reply(result: dict[str, Any], *, visual_html_file: str = "") -> str:
    """Render a compact social reply from a Brain /analyze result."""
    if not result.get("ok"):
        return "Loom Brain failed: " + str(result.get("error", "unknown error"))
    synthesis = result.get("synthesis", {}) or {}
    episode_id = result.get("episode_id", "")
    stance = synthesis.get("stance", "n/a")
    confidence = synthesis.get("confidence", 0.0)
    try:
        confidence_text = f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        confidence_text = str(confidence)
    drivers = []
    for item in synthesis.get("key_drivers", []) or []:
        if isinstance(item, dict):
            claim = item.get("claim", "")
        else:
            claim = str(item)
        if claim:
            drivers.append(claim)
        if len(drivers) >= 3:
            break
    lines = [
        f"Loom Brain: stance={stance}, confidence={confidence_text}",
    ]
    if episode_id:
        lines.append(f"episode_id={episode_id}")
    if drivers:
        lines.append("Key drivers:")
        lines.extend(f"- {driver}" for driver in drivers)
    reversal = synthesis.get("reversal_condition")
    if reversal:
        lines.append(f"Reversal: {reversal}")

    # Include hand narratives when synthesis is thin
    hand_artifacts = result.get("hand_artifacts", {})
    if hand_artifacts and (not drivers or confidence < 0.4):
        for art in hand_artifacts.values():
            if not isinstance(art, dict):
                continue
            narrative = art.get("narrative", "")
            if narrative:
                lines.append("")
                lines.append(narrative[:1500])
                break

    if visual_html_file:
        lines.append("")
        lines.append("📊 HTML分析页面见附件")

    return "\n".join(lines)


async def send_social_reply(
    *,
    platform: str,
    text: str,
    webhook_url: str = "",
    token: str = "",
    app_id: str = "",
    app_secret: str = "",
    channel_id: str = "",
    message_id: str = "",
    receive_id_type: str = "",
    proxy_url: str = "",
    http_transport: Any = None,
    file_path: str = "",
) -> SocialReplyResult:
    """Send a reply through webhook or supported platform message APIs."""
    platform = (platform or "generic").lower()
    webhook_url = webhook_url or _webhook_from_env(platform)
    if not webhook_url:
        if platform == "discord":
            return await _send_discord_bot_reply(
                text=text,
                token=token,
                channel_id=channel_id,
                message_id=message_id,
                proxy_url=proxy_url,
                http_transport=http_transport,
                file_path=file_path,
            )
        if platform in {"feishu", "lark"}:
            return await _send_feishu_im_reply(
                platform=platform,
                text=text,
                token=token,
                app_id=app_id,
                app_secret=app_secret,
                receive_id=channel_id,
                receive_id_type=receive_id_type,
                proxy_url=proxy_url,
                http_transport=http_transport,
            )
        return SocialReplyResult(
            ok=True,
            skipped=True,
            platform=platform,
            text=text,
            transport="none",
        )

    if platform == "discord":
        if file_path:
            return await _send_discord_webhook_file(
                webhook_url=webhook_url,
                text=text,
                file_path=file_path,
                token=token,
                proxy_url=proxy_url,
                http_transport=http_transport,
            )
        body = {"content": text, "allowed_mentions": {"parse": []}}
    elif platform in {"feishu", "lark"}:
        body = {"msg_type": "text", "content": {"text": text}}
    else:
        body = {"text": text}

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    client_kw = _client_kwargs(http_transport=http_transport, proxy_url=proxy_url)
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            resp = await client.post(webhook_url, json=body, headers=headers)
        if resp.status_code >= 400:
            return SocialReplyResult(
                ok=False,
                platform=platform,
                status_code=resp.status_code,
                error=resp.text[:500],
                text=text,
                transport="webhook",
            )
        return SocialReplyResult(
            ok=True,
            platform=platform,
            status_code=resp.status_code,
            text=text,
            transport="webhook",
        )
    except Exception as exc:
        return SocialReplyResult(
            ok=False,
            platform=platform,
            error=str(exc),
            text=text,
            transport="webhook",
        )


def _webhook_from_env(platform: str) -> str:
    key = "FEISHU" if platform == "lark" else platform.upper()
    return (
        os.environ.get(f"LOOM_SOCIAL_REPLY_{key}_WEBHOOK")
        or os.environ.get(f"{key}_WEBHOOK_URL")
        or ""
    )


async def _send_discord_webhook_file(
    *,
    webhook_url: str,
    text: str,
    file_path: str,
    token: str = "",
    proxy_url: str = "",
    http_transport: Any = None,
) -> SocialReplyResult:
    """Send a text message + HTML file via Discord webhook as multipart."""
    if not os.path.exists(file_path):
        return SocialReplyResult(
            ok=False, platform="discord", transport="webhook_file",
            error=f"file not found: {file_path}", text=text,
        )
    try:
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
    except OSError as exc:
        return SocialReplyResult(
            ok=False, platform="discord", transport="webhook_file",
            error=str(exc), text=text,
        )
    if file_size > 25 * 1024 * 1024:  # Discord 25 MB limit
        return SocialReplyResult(
            ok=False, platform="discord", transport="webhook_file",
            error=f"file too large ({file_size} bytes)", text=text,
        )

    client_kw = _client_kwargs(http_transport=http_transport, proxy_url=proxy_url)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with open(file_path, "rb") as fh:
        files = {"file": (filename, fh.read(), "text/html; charset=utf-8")}

    data = {"content": text, "allowed_mentions": {"parse": []}}
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            resp = await client.post(
                webhook_url,
                data={"payload_json": json.dumps(data, ensure_ascii=False)},
                files=files,
                headers=headers,
            )
        if resp.status_code >= 400:
            return SocialReplyResult(
                ok=False, platform="discord", status_code=resp.status_code,
                error=resp.text[:500], text=text, transport="webhook_file",
            )
        return SocialReplyResult(
            ok=True, platform="discord", status_code=resp.status_code,
            text=text, transport="webhook_file",
        )
    except Exception as exc:
        return SocialReplyResult(
            ok=False, platform="discord", error=str(exc),
            text=text, transport="webhook_file",
        )


async def _send_discord_bot_reply(
    *,
    text: str,
    token: str = "",
    channel_id: str = "",
    message_id: str = "",
    proxy_url: str = "",
    http_transport: Any = None,
    file_path: str = "",
) -> SocialReplyResult:
    token = token or os.environ.get("LOOM_DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN") or ""
    if not token or not channel_id:
        return SocialReplyResult(
            ok=True,
            skipped=True,
            platform="discord",
            text=text,
            transport="discord_bot",
            error="missing Discord bot token or channel_id",
        )
    api_base = os.environ.get("LOOM_DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")
    body: dict[str, Any] = {"content": text, "allowed_mentions": {"parse": []}}
    if message_id:
        body["message_reference"] = {
            "message_id": message_id,
            "channel_id": channel_id,
            "fail_if_not_exists": False,
        }
    # Send as multipart with file attachment when file_path is provided
    if file_path and os.path.exists(file_path):
        filename = os.path.basename(file_path)
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0
        if file_size > 25 * 1024 * 1024:
            return SocialReplyResult(
                ok=False, platform="discord", transport="discord_bot",
                error=f"file too large ({file_size} bytes)", text=text,
            )
        with open(file_path, "rb") as fh:
            file_data = fh.read()
        files = {"file": (filename, file_data, "text/html; charset=utf-8")}
        client_kw = _client_kwargs(http_transport=http_transport, proxy_url=proxy_url)
        try:
            async with httpx.AsyncClient(**client_kw) as client:
                resp = await client.post(
                    f"{api_base}/channels/{channel_id}/messages",
                    data={"payload_json": json.dumps(body, ensure_ascii=False)},
                    files=files,
                    headers={"Authorization": f"Bot {token}"},
                )
            if resp.status_code >= 400:
                return SocialReplyResult(
                    ok=False, platform="discord", status_code=resp.status_code,
                    error=resp.text[:500], text=text, transport="discord_bot",
                )
            return SocialReplyResult(
                ok=True, platform="discord", status_code=resp.status_code,
                text=text, transport="discord_bot",
            )
        except Exception as exc:
            return SocialReplyResult(
                ok=False, platform="discord", error=str(exc),
                text=text, transport="discord_bot",
            )
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    return await _post_json(
        platform="discord",
        transport="discord_bot",
        url=f"{api_base}/channels/{channel_id}/messages",
        body=body,
        headers=headers,
        text=text,
        proxy_url=proxy_url,
        http_transport=http_transport,
    )


async def edit_discord_message(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    embed: dict[str, Any],
    proxy_url: str = "",
    http_transport: Any = None,
) -> SocialReplyResult:
    """Edit a Discord bot message with a progress Embed."""
    if not token or not channel_id or not message_id:
        return SocialReplyResult(
            ok=True, skipped=True, platform="discord", transport="discord_bot_edit",
            error="missing Discord bot token, channel_id, or message_id",
        )
    api_base = os.environ.get("LOOM_DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")
    return await _post_json(
        platform="discord",
        transport="discord_bot_edit",
        method="PATCH",
        url=f"{api_base}/channels/{channel_id}/messages/{message_id}",
        body={"embeds": [embed], "allowed_mentions": {"parse": []}},
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        text=str(embed.get("title") or ""),
        proxy_url=proxy_url,
        http_transport=http_transport,
    )


async def _send_feishu_im_reply(
    *,
    platform: str,
    text: str,
    token: str = "",
    app_id: str = "",
    app_secret: str = "",
    receive_id: str = "",
    receive_id_type: str = "",
    proxy_url: str = "",
    http_transport: Any = None,
) -> SocialReplyResult:
    api_base = os.environ.get("LOOM_FEISHU_API_BASE", "https://open.feishu.cn/open-apis").rstrip("/")
    token = (
        token
        or os.environ.get("LOOM_FEISHU_TENANT_ACCESS_TOKEN")
        or os.environ.get("FEISHU_TENANT_ACCESS_TOKEN")
        or ""
    )
    if not receive_id:
        return SocialReplyResult(
            ok=True,
            skipped=True,
            platform=platform,
            text=text,
            transport="feishu_im",
            error="missing Feishu receive_id",
        )
    if not token:
        token_result = await _feishu_tenant_access_token(
            platform=platform,
            api_base=api_base,
            text=text,
            app_id=app_id,
            app_secret=app_secret,
            proxy_url=proxy_url,
            http_transport=http_transport,
        )
        if not token_result.ok:
            return token_result.reply or SocialReplyResult(
                ok=False,
                platform=platform,
                text=text,
                transport="feishu_token",
                error="Feishu tenant access token acquisition failed",
            )
        token = token_result.token
    if not token:
        return SocialReplyResult(
            ok=True,
            skipped=True,
            platform=platform,
            text=text,
            transport="feishu_im",
            error="missing Feishu app credentials or tenant access token",
        )
    receive_id_type = receive_id_type or os.environ.get("LOOM_FEISHU_RECEIVE_ID_TYPE", "chat_id")
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    return await _post_json(
        platform=platform,
        transport="feishu_im",
        url=f"{api_base}/im/v1/messages?receive_id_type={receive_id_type}",
        body=body,
        headers=headers,
        text=text,
        proxy_url=proxy_url,
        http_transport=http_transport,
    )


async def _feishu_tenant_access_token(
    *,
    platform: str,
    api_base: str,
    text: str,
    app_id: str = "",
    app_secret: str = "",
    proxy_url: str = "",
    http_transport: Any = None,
) -> _FeishuTokenResult:
    app_id = app_id or os.environ.get("LOOM_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or ""
    app_secret = app_secret or os.environ.get("LOOM_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or ""
    if not app_id or not app_secret:
        return _FeishuTokenResult(ok=True)

    cache_key = f"{api_base}|{app_id}"
    cached = _FEISHU_TOKEN_CACHE.get(cache_key)
    now = time.time()
    if isinstance(cached, dict) and cached.get("token") and float(cached.get("expires_at", 0)) > now:
        return _FeishuTokenResult(ok=True, token=str(cached["token"]))

    client_kw = _client_kwargs(http_transport=http_transport, proxy_url=proxy_url)
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            resp = await client.post(
                f"{api_base}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        if resp.status_code >= 400:
            return _FeishuTokenResult(
                ok=False,
                reply=SocialReplyResult(
                    ok=False,
                    platform=platform,
                    status_code=resp.status_code,
                    error=resp.text[:500],
                    text=text,
                    transport="feishu_token",
                ),
            )
        try:
            data = resp.json()
        except ValueError:
            data = {}
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, "0", None):
            return _FeishuTokenResult(
                ok=False,
                reply=SocialReplyResult(
                    ok=False,
                    platform=platform,
                    status_code=resp.status_code,
                    error=str(data.get("msg") or data.get("message") or data)[:500],
                    text=text,
                    transport="feishu_token",
                ),
            )
        token = str(data.get("tenant_access_token") or "")
        if not token:
            return _FeishuTokenResult(
                ok=False,
                reply=SocialReplyResult(
                    ok=False,
                    platform=platform,
                    status_code=resp.status_code,
                    error="Feishu token response missing tenant_access_token",
                    text=text,
                    transport="feishu_token",
                ),
            )
        try:
            expires_in = max(0, int(data.get("expire", 7200)))
        except (TypeError, ValueError):
            expires_in = 7200
        _FEISHU_TOKEN_CACHE[cache_key] = {
            "token": token,
            "expires_at": now + max(60, expires_in - 120),
        }
        return _FeishuTokenResult(ok=True, token=token)
    except Exception as exc:
        return _FeishuTokenResult(
            ok=False,
            reply=SocialReplyResult(
                ok=False,
                platform=platform,
                error=str(exc),
                text=text,
                transport="feishu_token",
            ),
        )


async def _post_json(
    *,
    platform: str,
    transport: str,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    text: str,
    method: str = "POST",
    proxy_url: str = "",
    http_transport: Any = None,
) -> SocialReplyResult:
    client_kw = _client_kwargs(http_transport=http_transport, proxy_url=proxy_url)
    try:
        async with httpx.AsyncClient(**client_kw) as client:
            resp = await client.request(method, url, json=body, headers=headers)
        if resp.status_code >= 400:
            return SocialReplyResult(
                ok=False,
                platform=platform,
                status_code=resp.status_code,
                error=resp.text[:500],
                text=text,
                transport=transport,
            )
        return SocialReplyResult(
            ok=True,
            platform=platform,
            status_code=resp.status_code,
            text=text,
            transport=transport,
        )
    except Exception as exc:
        return SocialReplyResult(
            ok=False,
            platform=platform,
            error=str(exc),
            text=text,
            transport=transport,
        )


def _client_kwargs(*, http_transport: Any = None, proxy_url: str = "") -> dict[str, Any]:
    client_kw: dict[str, Any] = {"timeout": 15.0}
    if http_transport is not None:
        client_kw["transport"] = http_transport
    elif proxy_url:
        client_kw["proxy"] = proxy_url
    return client_kw
