"""Real HTTP server for the Loom Core runtime.

Uses stdlib http.server — no external dependencies.
"""

from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse, parse_qs

from loom_core.domain_sdk.registry import build_domain_manifest_response
from loom_core.runtime.task_router import resolve_task_route


class CoreHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler that delegates to a LoomCoreRuntime instance."""

    runtime: Any = None  # set by factory
    adapter_registry: Any = None
    providers: dict[str, Any] = {}
    resource_provider: Any = None
    feedback_store: Any = None
    hand_config_store: Any = None

    def _send_json(self, code: int, data: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _route(self) -> None:
        method = self.command
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        body = self._read_body() if method in ("POST", "PUT", "PATCH") else {}

        # --- Resource routes ---
        if method == "GET" and path.startswith("/resources/"):
            resource_id = path[len("/resources/"):]
            params = {k: v[0] for k, v in query.items()}
            if self.resource_provider is None:
                return self._send_json(503, {"error": "resource_provider not initialised"})
            try:
                data = self.resource_provider.fetch(resource_id, params)
                return self._send_json(200, {"ok": True, "resource_id": resource_id, "data": data})
            except KeyError:
                return self._send_json(404, {"error": f"unknown resource: {resource_id}"})
            except Exception as e:
                return self._send_json(500, {"error": str(e)})

        if method == "POST" and path == "/resources/custom":
            resource_id = body.get("resource_id", "")
            url = body.get("url", "")
            hand_id = body.get("hand_id", "")
            if not resource_id or not url:
                return self._send_json(400, {"error": "resource_id and url required"})
            if self.resource_provider is not None:
                import urllib.request
                def _url_fetcher(params: dict, _url: str = url) -> dict:
                    req = urllib.request.urlopen(_url, timeout=10)
                    return json.loads(req.read().decode("utf-8"))
                self.resource_provider.register(resource_id, _url_fetcher)
            if hand_id and self.hand_config_store is not None:
                import os
                from pathlib import Path
                cr_path = Path(self.hand_config_store._root) / hand_id / "custom_resources.json"
                cr_path.parent.mkdir(parents=True, exist_ok=True)
                existing = json.loads(cr_path.read_text()) if cr_path.exists() else []
                existing.append({"resource_id": resource_id, "url": url})
                cr_path.write_text(json.dumps(existing, indent=2))
            return self._send_json(200, {"ok": True, "resource_id": resource_id})

        # --- Timing stages (computed by Python, replaces JS timing-waterfall) ---
        if method == "POST" and path == "/timing/stages":
            try:
                from loom.timing_stats import compute_stages
                result = compute_stages(body.get("timing", {}))
                return self._send_json(200, {"ok": True, **result})
            except Exception as e:
                return self._send_json(500, {"error": str(e)})

        # --- Feedback routes ---
        if method == "GET" and path == "/feedback":
            if self.feedback_store is None:
                return self._send_json(503, {"error": "feedback_store not initialised"})
            hand_id = query.get("hand_id", [None])[0]
            since_raw = query.get("since", [None])[0]
            since = float(since_raw) if since_raw else None
            events = self.feedback_store.read(hand_id=hand_id, since=since)
            return self._send_json(200, {"ok": True, "events": events})

        if method == "POST" and path == "/feedback":
            if self.feedback_store is None:
                return self._send_json(503, {"error": "feedback_store not initialised"})
            if not body:
                return self._send_json(400, {"error": "event body required"})
            self.feedback_store.append(body)
            return self._send_json(200, {"ok": True})

        # --- Hand config routes ---
        if method == "GET" and path.startswith("/hand/") and path.endswith("/config"):
            hand_id = path.split("/")[2]
            if self.hand_config_store is None:
                return self._send_json(503, {"error": "hand_config_store not initialised"})
            config = self.hand_config_store.read(hand_id)
            return self._send_json(200, {"ok": True, "hand_id": hand_id, "config": config})

        if method == "PUT" and path.startswith("/hand/") and path.endswith("/config"):
            hand_id = path.split("/")[2]
            if self.hand_config_store is None:
                return self._send_json(503, {"error": "hand_config_store not initialised"})
            self.hand_config_store.write(hand_id, body)
            return self._send_json(200, {"ok": True, "hand_id": hand_id})

        if path == "/":
            return self._send_json(200, {
                "service": "Loom Core Python runtime",
                "docs": "GET /health, GET /domains, GET /domains/:pack/tasks, POST /task/resolve, GET /adapters, POST /providers/refresh",
                "webview": "http://localhost:3000",
            })

        if method == "GET" and path == "/health":
            return self._send_json(200, self.runtime.health())

        if method == "GET" and path == "/domains":
            return self._send_json(200, build_domain_manifest_response(self.runtime.manifests))

        if method == "GET" and path.startswith("/domains/") and path.endswith("/tasks"):
            pack_id = path.split("/")[2]
            manifest = next(
                (m for m in self.runtime.manifests if m.get("id") == pack_id), None
            )
            if manifest is None:
                return self._send_json(404, {"error": f"unknown domain pack: {pack_id}"})
            return self._send_json(200, {"ok": True, "tasks": manifest.get("agentTasks", [])})

        if method == "POST" and path == "/task/resolve":
            if not body.get("task_pack_id") or not body.get("task_id"):
                return self._send_json(400, {"error": "task_pack_id and task_id required"})
            try:
                route = resolve_task_route(
                    manifests=self.runtime.manifests,
                    task_pack_id=body["task_pack_id"],
                    task_id=body["task_id"],
                    adapters=self.adapter_registry,
                )
                return self._send_json(200, {
                    "ok": True,
                    "task_pack_id": body["task_pack_id"],
                    "task_id": body["task_id"],
                    "agent": route.task.get("agent"),
                    "adapter": route.adapter.id,
                    "artifact_contract": route.task.get("artifactContract"),
                })
            except LookupError as e:
                return self._send_json(404, {"error": str(e)})

        if method == "GET" and path == "/adapters":
            adapters = self.adapter_registry.list()
            return self._send_json(200, {
                "ok": True,
                "adapters": [
                    {"id": a.id, "capabilities": a.capabilities}
                    for a in adapters
                ],
            })

        if method == "POST" and path == "/providers/refresh":
            from loom_core.agent_adapters.providers import create_providers
            providers = create_providers()
            registered = []
            for pid, info in providers.items():
                try:
                    self.adapter_registry.register(info["instance"])
                    registered.append(pid)
                except ValueError:
                    pass  # already registered
            return self._send_json(200, {
                "ok": True,
                "registered": registered,
            })

        return self._send_json(404, {"error": f"unknown route: {method} {path}"})

    do_GET = _route
    do_POST = _route
    do_PUT = _route
    do_PATCH = _route
    do_DELETE = _route
    do_OPTIONS = _route


def start_http_server(
    runtime: Any,
    adapter_registry: Any,
    host: str = "127.0.0.1",
    port: int = 3001,
    resource_provider: Any = None,
    feedback_store: Any = None,
    hand_config_store: Any = None,
) -> HTTPServer:
    """Start the Core HTTP server on the given host:port."""
    factory = type(
        "Handler",
        (CoreHTTPHandler,),
        {
            "runtime": runtime,
            "adapter_registry": adapter_registry,
            "resource_provider": resource_provider,
            "feedback_store": feedback_store,
            "hand_config_store": hand_config_store,
        },
    )
    server = HTTPServer((host, port), factory)
    log(f"Loom Core runtime listening on http://{host}:{port}")
    return server


def log(msg: str) -> None:
    import sys
    print(f"[loom-core] {msg}", file=sys.stderr, flush=True)


class LoomCoreHttpApi:
    """In-process test shim — exercises route logic without a live socket."""

    def __init__(self, runtime: Any) -> None:
        from loom_core.agent_adapters.registry import create_adapter_registry
        self._runtime = runtime
        self._registry = create_adapter_registry()

    def handle_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        from loom_core.domain_sdk.registry import build_domain_manifest_response
        body = body or {}
        parsed = urlparse(path)
        clean_path = parsed.path

        if method == "GET" and clean_path == "/health":
            return self._runtime.health()

        if method == "GET" and clean_path == "/domains":
            return build_domain_manifest_response(self._runtime.manifests)

        return {"error": f"unknown route: {method} {path}"}
