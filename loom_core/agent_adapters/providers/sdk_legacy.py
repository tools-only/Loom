"""SDK Legacy in-process adapter.

Wraps a domain-provided async invoke function so that existing SDK-based
hand implementations can be registered as AgentAdapters without subprocess
overhead. The trading domain creates these adapters at startup and registers
them; this module has no knowledge of domain business logic.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Callable, Awaitable

from ..adapter import LOOM_HAND_CONTRACT


_SDK_HW_CAPABILITIES: dict[str, bool] = {
    "supports_streaming": False,
    "supports_tool_call_loop": False,
    "supports_partial_events": False,
    "supports_seed": False,
    "supports_logprobs": False,
    "supports_constrained_decoding": False,
}


class InProcessAdapter:
    """Generic in-process adapter — domain provides the invoke callable.

    The domain passes an async callable with signature:
        async def invoke_fn(task: dict) -> dict  (returns artifact)
    """

    def __init__(
        self,
        adapter_id: str,
        invoke_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        capabilities: list[str] | None = None,
        hw_capabilities: dict[str, bool] | None = None,
    ) -> None:
        if not adapter_id:
            raise ValueError("adapter_id must be non-empty")
        self.id = adapter_id
        self._invoke_fn = invoke_fn
        self.capabilities = capabilities or []
        self.hw_capabilities: dict[str, bool] = hw_capabilities or dict(_SDK_HW_CAPABILITIES)

    async def invoke(self, task: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        if not task:
            raise ValueError("task envelope must not be empty")

        run_id = str(uuid.uuid4())
        yield {"type": "run.started", "run_id": run_id, "adapter_id": self.id}

        try:
            artifact = await self._invoke_fn(task)
            yield {"type": "run.artifact", "run_id": run_id, "artifact": artifact}
            yield {"type": "run.completed", "run_id": run_id, "exit_code": 0}
        except Exception as exc:
            yield {"type": "run.error", "run_id": run_id, "message": str(exc)}

    async def cancel(self, run_id: str) -> None:
        pass


def create_provider(
    adapter_id: str,
    invoke_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    capabilities: list[str] | None = None,
    hw_capabilities: dict[str, bool] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Factory used by trading domain to register a legacy SDK hand."""
    caps = capabilities or []
    hw_caps = hw_capabilities or dict(_SDK_HW_CAPABILITIES)
    adapter = InProcessAdapter(
        adapter_id=adapter_id,
        invoke_fn=invoke_fn,
        capabilities=caps,
        hw_capabilities=hw_caps,
    )
    return {
        "id": adapter_id,
        "label": label or f"SDK Legacy — {adapter_id}",
        "capabilities": caps,
        "hw_capabilities": hw_caps,
        "instance": adapter,
    }


def create_brain_inline_provider(
    client: Any,
    model: str,
    adapter_id: str = "brain-inline",
    capabilities: list[str] | None = None,
    hw_capabilities: dict[str, bool] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Factory for the Brain-inline adapter.

    Default execution engine for Brain-generated runtime hands. When Brain
    creates a task spec with ``executor_id="brain-inline"``, the brain hand
    runner routes here. The adapter takes Brain's generated ``system_prompt``
    from the envelope (or falls back to ``LOOM_HAND_CONTRACT``) and runs the
    LLM call in-process via the injected Anthropic client.

    Parameters
    ----------
    client : Any
        Anthropic client (or compatible) exposing ``messages.create``.
    model : str
        Model identifier passed to ``client.messages.create``.
    adapter_id : str
        Registry id; defaults to ``"brain-inline"``.
    capabilities : list[str] | None
        Adapter capabilities; defaults to ``["brain.inline", "runtime.generated"]``.
    hw_capabilities : dict[str, bool] | None
        Optional hardware capability map.
    label : str | None
        Human-readable label.
    """
    caps = capabilities or ["brain.inline", "runtime.generated"]
    hw_caps = hw_capabilities or dict(_SDK_HW_CAPABILITIES)

    async def _invoke(task: dict[str, Any]) -> dict[str, Any]:
        sys_prompt = task.get("system_prompt") or LOOM_HAND_CONTRACT
        user_msg = json.dumps(
            {
                "task": task.get("task", ""),
                "context": task.get("context", {}),
                "hand_id": task.get("hand_id", ""),
            },
            ensure_ascii=False,
        )

        resp = await client.messages.create(
            model=model,
            system=sys_prompt,
            tools=[],
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract textual content from Anthropic-style response.
        text = ""
        content = getattr(resp, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                block_text = getattr(block, "text", None)
                if block_text is None and isinstance(block, dict):
                    block_text = block.get("text")
                if block_text:
                    parts.append(block_text)
            text = "".join(parts)
        elif isinstance(content, str):
            text = content

        text = (text or "").strip()

        artifact: dict[str, Any] | None = None

        # Try whole-text JSON first — many models emit a single JSON object.
        if text:
            try:
                whole = json.loads(text)
            except json.JSONDecodeError:
                whole = None
            if isinstance(whole, dict):
                if whole.get("type") == "run.artifact" and isinstance(
                    whole.get("artifact"), dict
                ):
                    artifact = whole["artifact"]
                elif "artifact" in whole and isinstance(whole["artifact"], dict):
                    artifact = whole["artifact"]
                else:
                    # Treat the object itself as the artifact when it looks
                    # like the LOOM_HAND_CONTRACT shape.
                    if "narrative" in whole or "metadata" in whole:
                        artifact = whole

        # Fall back to line-by-line scan for a run.artifact event.
        if artifact is None and text:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "run.artifact" and isinstance(
                    event.get("artifact"), dict
                ):
                    artifact = event["artifact"]
                    break
                if "artifact" in event and isinstance(event["artifact"], dict):
                    artifact = event["artifact"]
                    break

        if artifact is None:
            artifact = {
                "narrative": text,
                "metadata": {
                    "key_claims": [],
                    "resources_used": [],
                    "gaps": [],
                },
            }

        return artifact

    adapter = InProcessAdapter(
        adapter_id=adapter_id,
        invoke_fn=_invoke,
        capabilities=caps,
        hw_capabilities=hw_caps,
    )
    return {
        "id": adapter_id,
        "label": label or f"Brain Inline — {adapter_id}",
        "capabilities": caps,
        "hw_capabilities": hw_caps,
        "instance": adapter,
    }
