"""Loom Core daemon entry point.

Start the Python runtime HTTP server on port 3001.
The JS gateway (mcp/server.cjs) forwards finance task operations here.
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "channels":
        from loom_core.channel_admin import run as run_channel_admin
        raise SystemExit(run_channel_admin(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in {"agents", "runtimes"}:
        from loom_core.agent_runtime_admin import run as run_agent_runtime_admin
        raise SystemExit(run_agent_runtime_admin(sys.argv[2:]))

    from loom_core.runtime.app import LoomCoreRuntime
    from loom_core.runtime.http_api import start_http_server
    from loom_core.agent_adapters.registry import create_adapter_registry
    from loom_core.agent_adapters.providers import create_providers

    root = PROJECT_ROOT
    host = os.environ.get("LOOM_CORE_HOST", "127.0.0.1")
    port = int(os.environ.get("LOOM_CORE_PORT", "3001"))

    # Bootstrap runtime
    runtime = LoomCoreRuntime(root_dir=root)
    runtime.bootstrap()
    print(f"[loom-core] Booted: {runtime.health()}", file=sys.stderr, flush=True)

    # Create adapter registry and register providers
    registry = create_adapter_registry()
    providers = create_providers()
    for pid, info in providers.items():
        try:
            registry.register(info["instance"])
            print(f"[loom-core] Registered adapter: {pid}", file=sys.stderr, flush=True)
        except ValueError:
            pass  # already registered

    # Start HTTP server (blocking)
    server = start_http_server(
        runtime,
        registry,
        host=host,
        port=port,
        resource_provider=runtime.resource_provider,
        feedback_store=runtime.feedback_store,
        hand_config_store=runtime.hand_config_store,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[loom-core] Shutting down...", file=sys.stderr, flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
