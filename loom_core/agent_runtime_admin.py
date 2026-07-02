"""CLI and terminal UI for agent adapters and per-Hand runtime bindings."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from loom_core.agent_adapters.cloud_config import load_cloud_agents
from loom_core.agent_adapters.factory import persistable_adapter_config
from loom_core.agent_adapters.runtime_bindings import (
    HandRuntimeBindingStore,
    hand_runtime_config_path,
)


BUILTIN_ADAPTERS = ("sdk", "brain-inline", "cc", "codex", "openclaw", "herms", "opencode")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m loom_core agents")
    parser.add_argument("--root", default=str(Path.cwd()), help="Project root. Defaults to current directory.")
    parser.add_argument("--config", default="", help="Hand runtime binding JSON path.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List Hand runtime bindings and available adapters.")
    sub.add_parser("adapters", help="List available adapter IDs.")

    register = sub.add_parser("register", help="Register a persistent agent adapter.")
    register.add_argument("adapter_id")
    register.add_argument("--transport", choices=("process", "http", "websocket"), default="process")
    register.add_argument("--protocol", choices=("loom", "openai", "codex"), default="codex")
    register.add_argument("--codex-backend", choices=("sdk", "raw"), default="sdk")
    register.add_argument("--command", dest="process_command", default="", help="Process command. SDK-backed Codex does not require one.")
    register.add_argument("--endpoint", default="", help="HTTP or WebSocket endpoint.")
    register.add_argument("--auth-token-env", default="", help="Environment variable containing the bearer token.")
    register.add_argument("--timeout", type=float, default=120.0)
    register.add_argument("--capability", action="append", default=[])
    register.add_argument("--system-prompt", default="")
    register.add_argument("--set-default", action="store_true")
    register.add_argument("--bind-hand", action="append", default=[], help="Bind a Hand after registration. Repeatable.")

    bind = sub.add_parser("bind", help="Bind a Hand to an adapter or sdk.")
    bind.add_argument("hand_id")
    bind.add_argument("adapter_id")

    unbind = sub.add_parser("unbind", help="Return a Hand to its declared/default runtime.")
    unbind.add_argument("hand_id")

    remove = sub.add_parser("remove", help="Remove a persistent dynamic adapter and its bindings.")
    remove.add_argument("adapter_id")

    sub.add_parser("tui", help="Open the terminal configuration UI.")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    store = HandRuntimeBindingStore(hand_runtime_config_path(root, args.config or None))
    dynamic_path = root / "loom" / "agent-adapters.json"

    if args.command in {"list", "adapters"}:
        _print_state(root, store, dynamic_path, bindings=args.command == "list")
        return 0
    if args.command == "register":
        config = {
            "adapter_id": args.adapter_id,
            "transport": args.transport,
            "protocol": args.protocol,
            "codex_backend": args.codex_backend,
            "command": args.process_command,
            "endpoint": args.endpoint,
            "auth_token_env": args.auth_token_env,
            "timeout_s": args.timeout,
            "capabilities": args.capability,
            "system_prompt": args.system_prompt,
        }
        _register_dynamic(dynamic_path, config, set_default=args.set_default)
        for hand_id in args.bind_hand:
            store.set(hand_id, args.adapter_id)
        _print_state(root, store, dynamic_path)
        return 0
    if args.command == "bind":
        _require_known_adapter(root, dynamic_path, args.adapter_id)
        store.set(args.hand_id, args.adapter_id)
        _print_state(root, store, dynamic_path)
        return 0
    if args.command == "unbind":
        store.remove(args.hand_id)
        _print_state(root, store, dynamic_path)
        return 0
    if args.command == "remove":
        _remove_dynamic(dynamic_path, args.adapter_id)
        store.remove_adapter(args.adapter_id)
        _print_state(root, store, dynamic_path)
        return 0
    if args.command == "tui":
        return _run_tui(root, store, dynamic_path)
    return 2


def _load_dynamic(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    adapters = raw.get("adapters", {}) if isinstance(raw, dict) else {}
    return {str(key): value for key, value in adapters.items() if isinstance(value, dict)}


def _write_dynamic(path: Path, adapters: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "adapters": adapters}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _register_dynamic(path: Path, config: dict[str, Any], *, set_default: bool = False) -> None:
    normalized = persistable_adapter_config(config)
    adapter_id = normalized.pop("adapter_id")
    adapters = _load_dynamic(path)
    if set_default:
        for current in adapters.values():
            current["set_default_runtime"] = False
    adapters[adapter_id] = {**normalized, "set_default_runtime": bool(set_default)}
    _write_dynamic(path, adapters)


def _remove_dynamic(path: Path, adapter_id: str) -> None:
    adapters = _load_dynamic(path)
    if adapter_id not in adapters:
        raise SystemExit(f"adapter is not dynamic: {adapter_id}")
    adapters.pop(adapter_id)
    _write_dynamic(path, adapters)


def _adapter_catalog(root: Path, dynamic_path: Path) -> dict[str, str]:
    catalog = {adapter_id: "built-in" for adapter_id in BUILTIN_ADAPTERS}
    for adapter_id in load_cloud_agents(root):
        catalog[adapter_id] = "cloud config"
    for adapter_id in _load_dynamic(dynamic_path):
        catalog[adapter_id] = "dynamic"
    return catalog


def _require_known_adapter(root: Path, dynamic_path: Path, adapter_id: str) -> None:
    if adapter_id not in _adapter_catalog(root, dynamic_path):
        raise SystemExit(f"unknown adapter: {adapter_id}; register it first")


def _print_state(
    root: Path,
    store: HandRuntimeBindingStore,
    dynamic_path: Path,
    *,
    bindings: bool = True,
) -> None:
    print("adapters:")
    for adapter_id, source in sorted(_adapter_catalog(root, dynamic_path).items()):
        print(f"- {adapter_id:<24} {source}")
    if bindings:
        print(f"bindings: {store.path}")
        if not store.list():
            print("- (none; Hands follow their declared/default runtime)")
        for hand_id, adapter_id in sorted(store.list().items()):
            print(f"- {hand_id:<16} -> {adapter_id}")


def _run_tui(root: Path, store: HandRuntimeBindingStore, dynamic_path: Path) -> int:
    while True:
        print()
        _print_state(root, store, dynamic_path)
        print()
        print("[1] register Codex App Server  [2] register other agent  [3] bind Hand")
        print("[4] unbind Hand  [5] remove adapter  [q] quit")
        choice = input("loom agents> ").strip().lower()
        if choice == "1":
            adapter_id = input("adapter id [codex-app-server]> ").strip() or "codex-app-server"
            backend = input("backend [sdk/raw] (sdk)> ").strip().lower() or "sdk"
            command = ""
            if backend == "raw":
                command = input("app-server command [codex app-server --listen stdio://]> ").strip() or "codex app-server --listen stdio://"
            _register_dynamic(dynamic_path, {
                "adapter_id": adapter_id,
                "transport": "process",
                "protocol": "codex",
                "codex_backend": backend,
                "command": command,
                "capabilities": ["runtime.hand", "workspace.patch"],
            })
            hand_id = input("bind Hand now (empty to skip)> ").strip()
            if hand_id:
                store.set(hand_id, adapter_id)
        elif choice == "2":
            adapter_id = input("adapter id> ").strip()
            transport = input("transport [process/http/websocket] (process)> ").strip() or "process"
            protocol = input("protocol [loom/openai/codex] (loom)> ").strip() or "loom"
            command = input("command (process only)> ").strip() if transport == "process" else ""
            endpoint = input("endpoint (http/websocket only)> ").strip() if transport != "process" else ""
            token_env = input("auth token env (optional)> ").strip()
            _register_dynamic(dynamic_path, {
                "adapter_id": adapter_id,
                "transport": transport,
                "protocol": protocol,
                "command": command,
                "endpoint": endpoint,
                "auth_token_env": token_env,
            })
        elif choice == "3":
            hand_id = input("Hand id> ").strip()
            adapter_id = input("adapter id (or sdk)> ").strip()
            _require_known_adapter(root, dynamic_path, adapter_id)
            store.set(hand_id, adapter_id)
        elif choice == "4":
            store.remove(input("Hand id> ").strip())
        elif choice == "5":
            adapter_id = input("dynamic adapter id> ").strip()
            _remove_dynamic(dynamic_path, adapter_id)
            store.remove_adapter(adapter_id)
        elif choice in {"q", "quit", "exit"}:
            return 0
