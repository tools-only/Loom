"""CLI and simple TUI for Loom social channel configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from loom_core.interaction_protocol.social_channel import (
    available_social_channel_types,
    canonical_channel_field_name,
    channel_config_fields,
    channel_type_info,
    default_social_channel_config,
    persistable_social_channel_config,
)
from loom_core.interaction_protocol.social_channel_config import (
    load_social_channel_document,
    save_social_channel_document,
    social_channel_config_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m loom_core channels")
    parser.add_argument("--root", default=str(Path.cwd()), help="Project root. Defaults to current directory.")
    parser.add_argument("--config", default="", help="Path to social channel config file.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("available", help="List nanobot-compatible channel types.")
    sub.add_parser("list", help="List configured channels.")

    enable = sub.add_parser("enable", help="Enable or create a channel config.")
    enable.add_argument("platform", help="Channel platform, e.g. telegram, slack, dingtalk.")
    enable.add_argument("--channel-id", default="", help="Configured channel ID. Defaults to platform.")
    enable.add_argument("--label", default="", help="Display label.")
    enable.add_argument("--response-mode", default="", help="reply, auto_reply, or empty.")
    enable.add_argument("--receive-id-type", default="", help="Feishu/Lark receive_id_type, e.g. chat_id.")
    enable.add_argument("--reply-webhook-env", default="", help="Env var containing reply webhook URL.")
    enable.add_argument("--reply-token-env", default="", help="Env var containing bot/token secret.")
    enable.add_argument("--token", default="", help="Nanobot channel token, e.g. Discord or Telegram bot token.")
    enable.add_argument("--allow-from", action="append", default=None, help="Allowed sender ID. Repeatable. Use * for open.")
    enable.add_argument("--mode", default="", help="Channel mode. The current channel architecture is bridge-only.")
    enable.add_argument("--require-verification", default="", help="true, false, or empty for global default.")
    enable.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="Set a platform-specific config field. Repeatable.")
    enable.add_argument("--set-default", action="store_true", help="Make this channel the default.")

    disable = sub.add_parser("disable", help="Disable a configured channel.")
    disable.add_argument("channel_id")

    default = sub.add_parser("default", help="Set default channel.")
    default.add_argument("channel_id")

    remove = sub.add_parser("remove", help="Remove a configured channel.")
    remove.add_argument("channel_id")

    sub.add_parser("tui", help="Open a simple terminal menu.")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root)
    config_path = social_channel_config_path(root, args.config or None)
    document = load_social_channel_document(config_path)

    if args.command == "available":
        _print_available()
        return 0
    if args.command == "list":
        _print_config(document, config_path)
        return 0
    if args.command == "enable":
        _enable_channel(document, args)
        _save(document, config_path)
        _print_config(document, config_path)
        return 0
    if args.command == "disable":
        _update_enabled(document, args.channel_id, False)
        _save(document, config_path)
        _print_config(document, config_path)
        return 0
    if args.command == "default":
        document["default_channel"] = args.channel_id
        _save(document, config_path)
        _print_config(document, config_path)
        return 0
    if args.command == "remove":
        document["channels"] = [
            item for item in _channels(document)
            if str(item.get("channel_id")) != args.channel_id
        ]
        if document.get("default_channel") == args.channel_id:
            document["default_channel"] = "generic"
        _save(document, config_path)
        _print_config(document, config_path)
        return 0
    if args.command == "tui":
        return _run_tui(document, config_path)
    parser.print_help()
    return 2


def _channels(document: dict[str, Any]) -> list[dict[str, Any]]:
    channels = document.get("channels", [])
    return channels if isinstance(channels, list) else []


def _save(document: dict[str, Any], path: Path) -> None:
    save_social_channel_document(
        path,
        default_channel=str(document.get("default_channel") or "generic"),
        channels=[persistable_social_channel_config(item) for item in _channels(document)],
    )


def _print_available() -> None:
    print("available channel types:")
    for item in available_social_channel_types():
        fields = ", ".join(item.get("config_fields", []))
        print(f"- {item['platform']:<10} {item['status']:<6} {item['label']}")
        print(f"  fields: {fields}")


def _print_config(document: dict[str, Any], path: Path) -> None:
    print(f"config: {path}")
    print(f"default: {document.get('default_channel', 'generic')}")
    print("channels:")
    for item in _channels(document):
        channel_id = str(item.get("channel_id") or item.get("id") or "")
        platform = str(item.get("platform") or "")
        enabled = "on" if item.get("enabled", True) else "off"
        mode = str(item.get("status") or "bridge")
        label = str(item.get("label") or channel_id)
        print(f"- {channel_id:<16} {platform:<10} {enabled:<3} {mode:<7} {label}")


def _enable_channel(document: dict[str, Any], args: argparse.Namespace) -> None:
    platform = str(args.platform).lower()
    channel_id = args.channel_id or platform
    info = channel_type_info(platform)
    config = default_social_channel_config(platform, channel_id=channel_id, enabled=True)
    config.update({
        "label": args.label or info.get("label") or channel_id,
        "enabled": True,
        "responseMode": args.response_mode,
        "receiveIdType": args.receive_id_type,
        "replyWebhookEnv": args.reply_webhook_env,
        "replyTokenEnv": args.reply_token_env,
    })
    if args.token:
        config["token"] = args.token
    if args.allow_from is not None:
        config["allowFrom"] = args.allow_from
    if args.mode:
        if str(args.mode).lower() != "bridge":
            raise SystemExit("channel mode is bridge-only")
        config["mode"] = "bridge"
    if args.require_verification:
        config["require_verification"] = _parse_optional_bool(args.require_verification)
    config.update(_parse_assignments(args.set or [], platform=platform))
    channels = [item for item in _channels(document) if str(item.get("channel_id")) != channel_id]
    channels.append(config)
    document["channels"] = channels
    if args.set_default:
        document["default_channel"] = channel_id


def _update_enabled(document: dict[str, Any], channel_id: str, enabled: bool) -> None:
    found = False
    for item in _channels(document):
        if str(item.get("channel_id")) == channel_id:
            item["enabled"] = enabled
            found = True
            break
    if not found:
        raise SystemExit(f"unknown channel: {channel_id}")


def _run_tui(document: dict[str, Any], path: Path) -> int:
    while True:
        print()
        _print_config(document, path)
        print()
        print("[1] list available  [2] enable  [3] disable  [4] set default  [5] save and exit  [q] quit")
        choice = input("loom channels> ").strip().lower()
        if choice == "1":
            _print_available()
        elif choice == "2":
            platform = input("platform> ").strip().lower()
            channel_id = input(f"channel id [{platform}]> ").strip() or platform
            config = _prompt_channel_config(document, platform=platform, channel_id=channel_id)
            channels = [item for item in _channels(document) if str(item.get("channel_id")) != channel_id]
            channels.append(config)
            document["channels"] = channels
            if input("set default? [y/N]> ").strip().lower() == "y":
                document["default_channel"] = channel_id
        elif choice == "3":
            _update_enabled(document, input("channel id> ").strip(), False)
        elif choice == "4":
            document["default_channel"] = input("channel id> ").strip()
        elif choice == "5":
            _save(document, path)
            print(f"saved: {path}")
            return 0
        elif choice in {"q", "quit", "exit"}:
            return 0


def _parse_assignments(assignments: list[str], *, platform: str) -> dict[str, Any]:
    field_specs: dict[str, dict[str, Any]] = {}
    for field in channel_config_fields(platform):
        field_specs[str(field["name"])] = field
        for alias in field.get("aliases", []):
            field_specs[str(alias)] = field
        field_specs[canonical_channel_field_name(platform, str(field["name"]))] = field
    parsed: dict[str, Any] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise SystemExit(f"--set expects KEY=VALUE, got: {assignment}")
        key, value = assignment.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"--set expects KEY=VALUE, got: {assignment}")
        canonical = canonical_channel_field_name(platform, key)
        parsed[canonical] = _coerce_field_value(value.strip(), field_specs.get(key) or field_specs.get(canonical, {}))
    return parsed


def _parse_optional_bool(value: str) -> bool | None:
    normalized = (value or "").strip().lower()
    if normalized in {"", "default", "none", "null"}:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SystemExit("--require-verification must be true, false, or empty")


def _prompt_channel_config(document: dict[str, Any], *, platform: str, channel_id: str) -> dict[str, Any]:
    existing = next((item for item in _channels(document) if str(item.get("channel_id")) == channel_id), {})
    config = default_social_channel_config(platform, channel_id=channel_id, enabled=True)
    if isinstance(existing, dict):
        config.update(existing)
    for key in list(config):
        canonical = canonical_channel_field_name(platform, str(key))
        if canonical != key:
            config.setdefault(canonical, config.pop(key))
    config["platform"] = platform
    config["channel_id"] = channel_id
    config["enabled"] = True
    field_specs = channel_config_fields(platform)
    for field in field_specs:
        name = field["name"]
        if name in {"channel_id", "platform", "enabled"}:
            continue
        current = config.get(name, field.get("default", ""))
        value = input(f"{field.get('label', name)} [{_format_prompt_default(current)}]> ").strip()
        if value:
            config[name] = _coerce_field_value(value, field)
    return config


def _format_prompt_default(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _coerce_field_value(value: str, field: dict[str, Any]) -> Any:
    kind = str(field.get("kind") or "text")
    if kind == "boolean":
        return bool(_parse_optional_bool(value))
    if kind == "tri_state_boolean":
        return _parse_optional_bool(value)
    if kind == "list":
        return [item.strip() for item in value.split(",") if item.strip()]
    if kind == "number":
        try:
            return int(value)
        except ValueError:
            return float(value)
    if kind == "json":
        import json

        return json.loads(value)
    return value


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
