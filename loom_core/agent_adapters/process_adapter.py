"""Generic process-based agent adapter.

Launches an external agent worker process, passes the task envelope,
and streams events back into Core.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any


class ProcessAgentAdapter:
    """Adapter that invokes an external agent via subprocess.

    The command receives the task envelope on stdin and writes JSON
    event lines to stdout.
    """

    def __init__(
        self,
        adapter_id: str,
        command: list[str],
        capabilities: list[str] | None = None,
    ) -> None:
        if not adapter_id:
            raise ValueError("adapter_id must be non-empty")
        self.id = adapter_id
        self._command = command
        self.capabilities = capabilities or []

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        if not task:
            raise ValueError("task envelope must not be empty")

        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}

        try:
            cwd = task.get("hand_dir") or None
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            input_data = json.dumps(task).encode("utf-8")
            stdout, stderr = await proc.communicate(input=input_data)

            if stdout:
                for line in stdout.decode("utf-8").strip().split("\n"):
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            yield {"type": "stdout", "data": line}

            if stderr:
                stderr_text = stderr.decode("utf-8").strip()
                if stderr_text:
                    yield {"type": "stderr", "data": stderr_text}

            yield {
                "type": "run.completed",
                "run_id": run_id,
                "exit_code": proc.returncode,
            }

        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def cancel(self, run_id: str) -> None:
        pass
