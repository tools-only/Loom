"""Resolve task-pack tasks to concrete external agent adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom_core.agent_adapters.base import AgentAdapter
from loom_core.agent_adapters.registry import AgentAdapterRegistry


@dataclass(frozen=True)
class TaskRoute:
    task_pack: dict[str, Any]
    task: dict[str, Any]
    adapter: AgentAdapter


def resolve_task_route(
    *,
    manifests: list[dict[str, Any]],
    task_pack_id: str,
    task_id: str,
    adapters: AgentAdapterRegistry,
) -> TaskRoute:
    task_pack = next(
        (manifest for manifest in manifests if manifest.get("id") == task_pack_id),
        None,
    )
    if task_pack is None:
        raise LookupError(f"unknown task pack: {task_pack_id}")

    task = next(
        (item for item in task_pack.get("agentTasks", []) if item.get("id") == task_id),
        None,
    )
    if task is None:
        raise LookupError(f"unknown task: {task_pack_id}/{task_id}")

    adapter_id = task.get("adapter")
    adapter = adapters.find_by_id(adapter_id)
    if adapter is None:
        raise LookupError(f"adapter not registered for task {task_id}: {adapter_id}")

    return TaskRoute(task_pack=task_pack, task=task, adapter=adapter)
