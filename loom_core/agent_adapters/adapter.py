"""Unified agent adapter.

transport × protocol matrix:
  process × loom  → stdin JSON envelope + stdout NDJSON  (cc, codex, herms)
  process × loom  → task appended as CLI arg             (opencode, task_as_arg=True)
  http    × loom  → snapshot POST + NDJSON stream        (cloud Loom agents)
  http    × openai→ ChatCompletion POST + parse content  (openclaw, nanobot)

brain.py sees the same async-generator interface regardless of cell in the matrix.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

import httpx

# Default system prompt injected for http×openai adapters.
LOOM_HAND_CONTRACT = """\
You are a Loom Fin hand agent. Analyze the task and output EXACTLY ONE JSON line:
{"type":"run.artifact","artifact":{"metadata":{"resources_used":[...],"key_claims":[...],"gaps":[...]},"narrative":"..."}}

- resources_used: every data source you accessed (e.g. "fred", "reuters-rss")
- key_claims: 2-5 concrete analytical judgments backed by data
- gaps: data you needed but could not access
- narrative: 2-4 paragraph analysis in Chinese

Optionally prepend wiki write-backs (one per line, before the artifact line):
{"type":"wiki.write","path":"filename.md","content":"..."}

Output NO other text.\
"""


class AgentAdapter:
    """Universal hand-agent adapter.

    Parameters
    ----------
    transport : "process" | "http"
    protocol  : "loom" | "openai"
        loom   — Loom-native NDJSON event stream
        openai — OpenAI ChatCompletion API (content parsed as run.artifact JSON)
    command      : required when transport="process"
    task_as_arg  : if True, appends task["task"] to *command* instead of stdin
    endpoint     : required when transport="http"
    auth_token   : Bearer token for http transport
    timeout_s    : per-request timeout (seconds)
    runtime      : LoomCoreRuntime — required for http×loom (snapshot + writeback)
    hands_root   : Path to hands/ dir — required for http×loom
    system_prompt: overrides LOOM_HAND_CONTRACT for http×openai
    _transport   : httpx.MockTransport injection for tests
    """

    def __init__(
        self,
        adapter_id: str,
        transport: Literal["process", "http"],
        protocol: Literal["loom", "openai"],
        *,
        command: list[str] | None = None,
        task_as_arg: bool = False,
        endpoint: str | None = None,
        auth_token: str | None = None,
        timeout_s: float = 120.0,
        runtime: Any = None,
        hands_root: Path | None = None,
        system_prompt: str | None = None,
        capabilities: list[str] | None = None,
        _transport: Any = None,
    ) -> None:
        if not adapter_id:
            raise ValueError("adapter_id must be non-empty")
        self.id = adapter_id
        self.capabilities = capabilities or []
        self._transport_kind = transport
        self._protocol = protocol
        self._command = list(command or [])
        self._task_as_arg = task_as_arg
        self._endpoint = endpoint or ""
        self._auth_token = auth_token
        self._timeout_s = timeout_s
        self._runtime = runtime
        self._hands_root = Path(hands_root) if hands_root else None
        self._system_prompt = system_prompt or LOOM_HAND_CONTRACT
        self._http_transport = _transport  # injected in tests

    # ── public interface ───────────────────────────────────────────────────

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        if not task:
            raise ValueError("task envelope must not be empty")
        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}
        try:
            if self._transport_kind == "process":
                async for event in self._invoke_process(task, run_id):
                    yield event
            else:
                if self._protocol == "loom":
                    async for event in self._invoke_http_loom(task, run_id):
                        yield event
                else:
                    async for event in self._invoke_http_openai(task, run_id):
                        yield event
        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def cancel(self, run_id: str) -> None:
        pass  # v1: no-op

    # ── process transport ──────────────────────────────────────────────────

    async def _invoke_process(
        self, task: dict[str, Any], run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        cmd = list(self._command)
        if self._task_as_arg:
            cmd.append(task.get("task", ""))

        cwd = task.get("hand_dir") or None
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdin_data = b"" if self._task_as_arg else json.dumps(task).encode()
        stdout, stderr = await proc.communicate(input=stdin_data)

        for line in stdout.decode("utf-8", errors="replace").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "stdout", "data": line}

        if stderr:
            text = stderr.decode("utf-8", errors="replace").strip()
            if text:
                yield {"type": "stderr", "data": text}

        yield {"type": "run.completed", "run_id": run_id, "exit_code": proc.returncode}

    # ── http × loom transport (cloud Loom agents) ──────────────────────────

    async def _invoke_http_loom(
        self, task: dict[str, Any], run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        hand_id = task.get("hand_id", "")
        body = self._build_snapshot(task, hand_id)
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        client_kw: dict[str, Any] = {"timeout": self._timeout_s}
        if self._http_transport is not None:
            client_kw["transport"] = self._http_transport

        async with httpx.AsyncClient(**client_kw) as client:
            async with client.stream(
                "POST", self._endpoint, json=body, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    body_text = (await resp.aread()).decode("utf-8", errors="replace")
                    yield {
                        "type": "run.error",
                        "run_id": run_id,
                        "message": f"HTTP {resp.status_code}: {body_text[:500]}",
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
                        self._runtime.feedback_store.append(event.get("event", {}))
                        continue
                    yield event

        yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}

    # ── http × openai transport (openclaw, nanobot, any OAI-compat service) ─

    async def _invoke_http_openai(
        self, task: dict[str, Any], run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        user_content = json.dumps(
            {
                "task": task.get("task", ""),
                "hand_id": task.get("hand_id", ""),
                "context": task.get("context", {}),
            },
            ensure_ascii=False,
        )
        # Merge system prompt + task into one user message — many OAI-compat
        # agents (DeepSeek, nanobot) reject system role or multi-message.
        merged = f"{self._system_prompt}\n\n{user_content}"
        body: dict[str, Any] = {
            "messages": [{"role": "user", "content": merged}],
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        client_kw: dict[str, Any] = {"timeout": self._timeout_s}
        if self._http_transport is not None:
            client_kw["transport"] = self._http_transport

        async with httpx.AsyncClient(**client_kw) as client:
            resp = await client.post(self._endpoint, json=body, headers=headers)

        if resp.status_code >= 400:
            yield {
                "type": "run.error",
                "run_id": run_id,
                "message": f"HTTP {resp.status_code}: {resp.text[:500]}",
            }
            return

        try:
            data = resp.json()
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            yield {
                "type": "run.error",
                "run_id": run_id,
                "message": f"malformed ChatCompletion response: {exc}",
            }
            return

        # Parse content: may contain optional wiki.write lines then run.artifact
        artifact_event: dict | None = None
        for line in content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type", "")
            if etype == "wiki.write" and self._hands_root:
                self._apply_wiki_write(task.get("hand_id", ""), event)
            elif etype == "run.artifact":
                artifact_event = event

        if artifact_event is None:
            # Fallback: wrap plain text response as narrative artifact
            content_stripped = content.strip()
            if content_stripped:
                yield {
                    "type": "run.artifact",
                    "artifact": {
                        "metadata": {
                            "confidence": 0.5,
                            "key_claims": [],
                            "gaps": ["hand agent did not return structured JSON"],
                        },
                        "narrative": content_stripped,
                    },
                }
                yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}
            else:
                yield {
                    "type": "run.error",
                    "run_id": run_id,
                    "message": "agent response contained no run.artifact event",
                }
            return

        yield artifact_event
        yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}

    # ── http × loom helpers ────────────────────────────────────────────────

    def _build_snapshot(self, task: dict, hand_id: str) -> dict:
        hand_dir = self._hands_root / hand_id if self._hands_root else None
        cloud_cfg = self._read_cloud_json(hand_dir) if hand_dir else {}

        wiki_snapshot: dict[str, str] = {}
        if cloud_cfg.get("include_wiki_snapshot", True) and hand_dir:
            wiki_dir = hand_dir / "wiki"
            if wiki_dir.exists():
                for p in wiki_dir.rglob("*.md"):
                    rel = p.relative_to(wiki_dir).as_posix()
                    wiki_snapshot[rel] = p.read_text(encoding="utf-8")

        config = self._runtime.hand_config_store.read(hand_id) if self._runtime else {}
        feedback_recent = (
            self._runtime.feedback_store.read(hand_id=hand_id)[-100:]
            if self._runtime
            else []
        )
        resources: dict[str, Any] = {}
        for rid in cloud_cfg.get("prefetch_resources", []):
            try:
                resources[rid] = self._runtime.resource_provider.fetch(rid, {})
            except (KeyError, AttributeError):
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

    def _read_cloud_json(self, hand_dir: Path | None) -> dict:
        if hand_dir is None:
            return {}
        path = hand_dir / "cloud.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_wiki_write(self, hand_id: str, event: dict) -> None:
        if not self._hands_root:
            return
        wiki_dir = self._hands_root / hand_id / "wiki"
        rel = event.get("path", "").lstrip("/").replace("\\", "/")
        if not rel or ".." in rel.split("/"):
            return  # path traversal guard
        target = wiki_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(event.get("content", ""), encoding="utf-8")
