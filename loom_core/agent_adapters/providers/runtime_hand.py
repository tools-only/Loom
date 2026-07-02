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
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
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
        if task.get("execution_mode") == "agent":
            return "\n\n".join(
                part for part in (str(system_prompt).strip(), str(task_str).strip()) if part
            )
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
        cwd = Path(str(task.get("cwd") or task.get("workspace_root") or ".")).expanduser().resolve()
        cmd = list(self._command)
        if task.get("dangerous"):
            cmd.append("--dangerously-skip-permissions")
        # Strip inherited proxy overrides so the agent reaches its own API endpoint.
        # cc-switch-like ANTHROPIC_BASE_URL proxies commonly reject or corrupt large
        # payloads, causing empty agent output and "no run.artifact" failures.
        clean_env = {
            **__import__("os").environ,
            "ANTHROPIC_BASE_URL": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        }
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=clean_env,
        )
        stdout, stderr = await proc.communicate(input=prompt.encode("utf-8"))
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if task.get("execution_mode") == "agent":
            if stderr_text:
                yield {"type": "stderr", "data": stderr_text}
            failure_text = self._summarize_failure(stdout_text, stderr_text, proc.returncode)
            if failure_text:
                yield {"type": "run.error", "run_id": run_id, "message": failure_text}
                return
            if not stdout_text:
                yield {
                    "type": "run.error",
                    "run_id": run_id,
                    "message": "Claude Code agent session completed without a final message",
                }
                return
            yield {"type": "run.message", "run_id": run_id, "text": stdout_text}
            yield {"type": "run.completed", "run_id": run_id, "exit_code": proc.returncode}
            return

        emitted_artifact = False

        for line in stdout_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "stdout", "data": line}
                continue
            if isinstance(event, dict) and event.get("type") == "run.artifact":
                emitted_artifact = True
            if isinstance(event, dict):
                yield event
            else:
                yield {"type": "stdout", "data": line}

        if stderr_text:
            yield {"type": "stderr", "data": stderr_text}

        if emitted_artifact:
            yield {"type": "run.completed", "run_id": run_id, "exit_code": proc.returncode}
            return

        failure_text = self._summarize_failure(stdout_text, stderr_text, proc.returncode)
        if failure_text:
            yield {"type": "run.error", "run_id": run_id, "message": failure_text}
            return

        yield {
            "type": "run.error",
            "run_id": run_id,
            "message": "runtime hand completed without a run.artifact",
        }

    @staticmethod
    def _summarize_failure(stdout_text: str, stderr_text: str, returncode: int | None) -> str:
        text = "\n".join(part for part in (stderr_text, stdout_text) if part).strip()
        if not text:
            if returncode not in (None, 0):
                return f"runtime hand exited with code {returncode}"
            return ""

        markers = (
            r"API Error:",
            r"status\.claude\.com",
            r"server_error",
            r"\b503\b",
            r"\b502\b",
            r"request timed out",
            r"timed out waiting",
            r"exceeded the 120s channel deadline",
        )
        if returncode not in (None, 0) or any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in markers):
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
            if returncode not in (None, 0):
                return f"runtime hand failed with exit code {returncode}: {first_line[:500]}"
            return first_line[:500]
        return ""


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
