"""RuntimeHand adapter — full CC agent for Brain-generated runtime hands.

Formats the invocation as a natural-language prompt so the agent receives
system_prompt as its behavioral role context, not buried in a JSON blob.
Stdin format:

    {system_prompt}

    --- TASK ---
    {task}

    --- CONTEXT ---
    domain: {domain}
    hand_id: {hand_id}
    capabilities: {capabilities_csv}

    Produce exactly one JSON line:
    {"type":"run.artifact","artifact":{"metadata":{"key_claims":[...],"gaps":[...],"confidence":0.8},"narrative":"..."}}
"""
from __future__ import annotations
import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any


class RuntimeHandAdapter:
    """Process adapter that formats stdin as a natural-language prompt."""

    def __init__(self, adapter_id: str, command: list[str], capabilities: list[str]) -> None:
        self.id = adapter_id
        self.capabilities = capabilities
        self._command = list(command)

    def _build_prompt(self, task: dict[str, Any]) -> str:
        system_prompt = task.get("system_prompt", "")
        task_str = task.get("task", "")
        ctx = task.get("context", {}) or {}
        domain = ctx.get("domain", "general")
        hand_id = task.get("hand_id", "")
        caps = task.get("capabilities", []) or []

        lines = []
        if system_prompt:
            lines.append(system_prompt)
            lines.append("")
        lines.append("--- TASK ---")
        lines.append(task_str)
        lines.append("")
        lines.append("--- CONTEXT ---")
        lines.append(f"domain: {domain}")
        if hand_id:
            lines.append(f"hand_id: {hand_id}")
        if caps:
            lines.append(f"capabilities: {', '.join(caps)}")
        lines.append("")
        lines.append('Produce exactly one JSON line:')
        lines.append('{"type":"run.artifact","artifact":{"metadata":{"key_claims":[...],"gaps":[...],"confidence":0.8},"narrative":"..."}}')
        return "\n".join(lines)

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        if not task:
            raise ValueError("task envelope must not be empty")
        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}
        try:
            async for event in self._invoke_process(task, run_id):
                yield event
        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def _invoke_process(self, task: dict[str, Any], run_id: str) -> AsyncIterator[dict[str, Any]]:
        prompt = self._build_prompt(task)
        proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=prompt.encode("utf-8"))
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


def create_runtime_hand_provider(base_command: list[str] | None = None) -> dict:
    """Create a RuntimeHandAdapter for Brain-generated runtime hands.

    base_command defaults to ["claude", "-p"].
    """
    cmd = list(base_command) if base_command else ["claude", "-p"]
    capabilities = ["runtime.hand"]
    adapter = RuntimeHandAdapter(
        adapter_id="runtime-hand",
        command=cmd,
        capabilities=capabilities,
    )
    return {
        "id": "runtime-hand",
        "label": "Runtime Hand (CC agent)",
        "capabilities": capabilities,
        "hw_capabilities": {},
        "instance": adapter,
    }
