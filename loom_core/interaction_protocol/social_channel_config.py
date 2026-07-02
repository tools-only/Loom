"""Config-file support for Loom social channels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loom_core.interaction_protocol.social_channel import (
    SocialChannelRegistry,
    default_social_channel_configs,
    social_channel_from_config,
)


DEFAULT_SOCIAL_CHANNEL_CONFIG = Path("config/social-channels.json")


def social_channel_config_path(root: str | Path, path: str | Path | None = None) -> Path:
    if path is not None:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else Path(root) / candidate
    return Path(root) / DEFAULT_SOCIAL_CHANNEL_CONFIG


def default_social_channel_document() -> dict[str, Any]:
    return {
        "version": 1,
        "default_channel": "generic",
        "channels": default_social_channel_configs(),
    }


def load_social_channel_document(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return default_social_channel_document()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_social_channel_document()
    if not isinstance(data, dict):
        return default_social_channel_document()
    channels = data.get("channels")
    if isinstance(channels, dict):
        channels = [
            {"channel_id": channel_id, **config}
            for channel_id, config in channels.items()
            if isinstance(config, dict)
        ]
    if not isinstance(channels, list):
        channels = []
    base = default_social_channel_document()
    by_id = {
        str(item.get("channel_id") or item.get("id") or ""): item
        for item in base["channels"]
        if isinstance(item, dict)
    }
    for item in channels:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("channel_id") or item.get("id") or "")
        if not channel_id:
            continue
        by_id[channel_id] = {**by_id.get(channel_id, {}), **item, "channel_id": channel_id}
    return {
        "version": int(data.get("version", 1) or 1),
        "default_channel": str(data.get("default_channel") or data.get("defaultChannel") or "generic"),
        "channels": list(by_id.values()),
    }


def save_social_channel_document(
    path: str | Path,
    *,
    default_channel: str,
    channels: list[dict[str, Any]],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_channels: list[dict[str, Any]] = []
    for item in channels:
        try:
            normalized_channels.append(social_channel_from_config(item).config_dict(redact_secrets=True))
        except ValueError:
            continue
    enabled_ids = {
        str(item.get("channel_id") or "")
        for item in normalized_channels
        if item.get("enabled", True)
    }
    if default_channel != "generic" and default_channel not in enabled_ids:
        default_channel = "generic" if "generic" in enabled_ids else next(iter(enabled_ids), default_channel)
    data = {
        "version": 1,
        "default_channel": default_channel,
        "channels": normalized_channels,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_social_channel_registry_from_document(document: dict[str, Any]) -> SocialChannelRegistry:
    default_channel = str(document.get("default_channel") or "generic")
    registry = SocialChannelRegistry(default_channel_id=default_channel)
    channels = document.get("channels", [])
    if isinstance(channels, dict):
        channels = [
            {"channel_id": channel_id, **config}
            for channel_id, config in channels.items()
            if isinstance(config, dict)
        ]
    if not isinstance(channels, list):
        channels = []
    for config in channels:
        if not isinstance(config, dict):
            continue
        try:
            registry.upsert(social_channel_from_config(config))
        except ValueError:
            continue
    current_default = registry.find_by_id(registry.get_default())
    generic = registry.find_by_id("generic")
    if (current_default is None or not current_default.enabled) and generic is not None and generic.enabled:
        registry.set_default("generic")
    return registry


def registry_to_document(registry: SocialChannelRegistry) -> dict[str, Any]:
    return {
        "version": 1,
        "default_channel": registry.get_default(),
        "channels": [channel.config_dict(redact_secrets=True) for channel in registry.list()],
    }
