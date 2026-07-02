"""Generic full-agent session service shared by social channels and Loom APIs."""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Awaitable, Callable


EventSink = Callable[[dict[str, Any]], Awaitable[Any] | Any]

# In-memory conversation history for full agent sessions (e.g. /codex, /claude).
# Keyed by "adapter_id:session_key" to keep different users/channels isolated.
# Each entry is a list of {"user": ..., "assistant": ...} turn pairs.
_AGENT_CONVERSATION: dict[str, list[dict]] = {}
_CONVERSATION_TTL = 3600  # auto-expire after 1 hour


class AgentSessionService:
    """Run one configured adapter without imposing Loom's hand artifact contract."""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    async def run(
        self,
        *,
        adapter_id: str,
        task: str,
        cwd: str = "",
        context: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
        dangerous: bool = False,
        session_key: str = "",
    ) -> dict[str, Any]:
        adapter_id = str(adapter_id or "").strip()
        adapter = self._registry.find_by_id(adapter_id)
        if adapter is None:
            raise ValueError(f"unknown agent adapter: {adapter_id}")
        capabilities = {str(item) for item in getattr(adapter, "capabilities", [])}
        if not capabilities.intersection({"runtime.hand", "workspace.patch"}):
            raise ValueError(f"agent adapter {adapter_id} is not a full agent runtime")
        if not str(task or "").strip():
            raise ValueError("agent task is required")

        # ── Conversation history: weave prior turns into the prompt ──────
        history_key = f"{adapter_id}:{session_key}" if session_key else ""
        augmented_task = str(task).strip()
        if history_key and history_key in _AGENT_CONVERSATION:
            entries = _AGENT_CONVERSATION[history_key]
            if entries:
                lines = ["--- PREVIOUS CONVERSATION WITH THIS USER ---"]
                for i, entry in enumerate(entries[-10:]):
                    user = entry.get("user", "")
                    assistant = entry.get("assistant", "")[:1500]
                    lines.append(f"[Turn {i + 1}]\nUser: {user}\nAssistant: {assistant}")
                lines.append("--- END OF PREVIOUS CONVERSATION ---")
                lines.append("Continue the conversation above. The user's latest message follows.")
                lines.append("")
                augmented_task = "\n".join(lines) + "\n" + augmented_task

        resolved_cwd = str(Path(cwd or ".").expanduser().resolve())
        envelope = {
            "execution_mode": "agent",
            "task": augmented_task,
            "cwd": resolved_cwd,
            "workspace_root": resolved_cwd,
            "context": dict(context or {}),
            "dangerous": bool(dangerous),
        }
        # Codex dangerous mode: auto-approve all operations with full sandbox access
        if dangerous and "codex" in adapter_id.lower():
            envelope["codex"] = {
                "approvalMode": "auto_review",
                "sandbox": "danger-full-access",
            }
        run_id = ""
        final_text = ""
        partial_text: list[str] = []
        artifact: dict[str, Any] | None = None
        completed = False

        async for event in adapter.invoke(envelope):
            event = dict(event or {})
            run_id = str(event.get("run_id") or run_id)
            event_type = str(event.get("type") or "")
            if event_type == "run.partial" and event.get("text"):
                partial_text.append(str(event["text"]))
            elif event_type == "run.message":
                final_text = str(event.get("text") or "").strip()
            elif event_type == "run.artifact" and isinstance(event.get("artifact"), dict):
                artifact = event["artifact"]
            elif event_type == "run.error":
                raise RuntimeError(str(event.get("message") or "agent session failed"))
            elif event_type == "run.completed":
                completed = True
            if event_sink is not None:
                maybe_awaitable = event_sink(event)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable

        if not final_text and artifact is not None:
            final_text = str(artifact.get("narrative") or "").strip()
        if not final_text and partial_text:
            final_text = "".join(partial_text).strip()
        if not final_text:
            raise RuntimeError(f"agent adapter {adapter_id} returned no final message")

        # ── Store turn in conversation history ────────────────────────────
        if history_key:
            if history_key not in _AGENT_CONVERSATION:
                _AGENT_CONVERSATION[history_key] = []
            _AGENT_CONVERSATION[history_key].append({
                "user": str(task).strip(),
                "assistant": final_text[:2000],
                "ts": time.time(),
            })
            # Trim to keep max 20 turns
            if len(_AGENT_CONVERSATION[history_key]) > 20:
                _AGENT_CONVERSATION[history_key] = _AGENT_CONVERSATION[history_key][-20:]
            # Expire stale entries
            now = time.time()
            _AGENT_CONVERSATION[history_key] = [
                e for e in _AGENT_CONVERSATION[history_key]
                if now - e.get("ts", 0) < _CONVERSATION_TTL
            ]

        return {
            "run_id": run_id,
            "adapter_id": adapter_id,
            "status": "completed" if completed else "finished",
            "text": final_text,
            "artifact": artifact,
        }
