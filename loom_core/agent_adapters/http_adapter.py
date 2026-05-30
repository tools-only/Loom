"""HTTP-based adapter for cloud-deployed hand agents.

Self-contained: builds wiki/config/feedback snapshot BEFORE the POST,
applies wiki.write / feedback.signal events locally AFTER, and only
yields standard run.* events to the caller (brain.py sees no difference).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx


class HttpAgentAdapter:
    """Adapter for a cloud-deployed agent reachable via HTTPS POST + NDJSON stream.

    The cloud agent receives a self-contained snapshot envelope (wiki, config,
    recent feedback, pre-fetched resources) and returns a stream of NDJSON events.
    Cloud-only event types (wiki.write, feedback.signal) are handled locally;
    only standard run.* events are yielded to the caller.
    """

    def __init__(
        self,
        adapter_id: str,
        endpoint: str,
        runtime: Any,
        hands_root: Path,
        auth_token: str | None = None,
        capabilities: list[str] | None = None,
        timeout_s: float = 120.0,
        _transport: Any = None,
    ) -> None:
        self.id = adapter_id
        self._endpoint = endpoint
        self._auth_token = auth_token
        self._runtime = runtime
        self._hands_root = Path(hands_root)
        self.capabilities = capabilities or []
        self._timeout_s = timeout_s
        self._transport = _transport  # injected in tests to avoid real HTTP

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}

        hand_id = task.get("hand_id", "")
        snapshot_body = self._build_snapshot(task, hand_id)

        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        client_kwargs: dict[str, Any] = {"timeout": self._timeout_s}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream(
                    "POST", self._endpoint, json=snapshot_body, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        yield {
                            "type": "run.error",
                            "run_id": run_id,
                            "message": f"HTTP {resp.status_code}: {body[:500]}",
                        }
                        return

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        etype = event.get("type", "")
                        if etype == "wiki.write":
                            self._apply_wiki_write(hand_id, event)
                            continue
                        if etype == "feedback.signal":
                            self._runtime.feedback_store.append(
                                event.get("event", {})
                            )
                            continue
                        yield event

            yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}

        except httpx.TimeoutException as exc:
            yield {"type": "run.error", "run_id": run_id, "message": f"timeout: {exc}"}
        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def cancel(self, run_id: str) -> None:
        pass  # v1: no-op; abort requires WS channel (future work)

    # ── private helpers ────────────────────────────────────────────────────

    def _build_snapshot(self, task: dict, hand_id: str) -> dict:
        hand_dir = self._hands_root / hand_id
        cloud_cfg = self._read_cloud_json(hand_dir)

        wiki_snapshot: dict[str, str] = {}
        if cloud_cfg.get("include_wiki_snapshot", True):
            wiki_dir = hand_dir / "wiki"
            if wiki_dir.exists():
                for p in wiki_dir.rglob("*.md"):
                    rel = p.relative_to(wiki_dir).as_posix()
                    wiki_snapshot[rel] = p.read_text(encoding="utf-8")

        config = self._runtime.hand_config_store.read(hand_id)
        feedback_recent = self._runtime.feedback_store.read(hand_id=hand_id)[-100:]

        resources: dict[str, Any] = {}
        for rid in cloud_cfg.get("prefetch_resources", []):
            try:
                resources[rid] = self._runtime.resource_provider.fetch(rid, {})
            except KeyError:
                pass

        return {
            "task": task.get("task", ""),
            "context": task.get("context", {}),
            "hand_id": hand_id,
            "wiki_snapshot": wiki_snapshot,
            "config": config,
            "feedback_recent": feedback_recent,
            "resources": resources,
        }

    def _read_cloud_json(self, hand_dir: Path) -> dict:
        path = hand_dir / "cloud.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_wiki_write(self, hand_id: str, event: dict) -> None:
        wiki_dir = self._hands_root / hand_id / "wiki"
        rel = event.get("path", "").lstrip("/").replace("\\", "/")
        if not rel or ".." in rel.split("/"):
            return  # path traversal guard
        target = wiki_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(event.get("content", ""), encoding="utf-8")
