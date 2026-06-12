"""AtomicTask and HandPlan — typed output of Brain task decomposition.

One HandPlan = Brain's decision about how to split one analyze() call into
atomic tasks. Each AtomicTask carries its own task instruction, rubrics, and
executor assignment. Brain (not config) decides the count, dimensions, and
content; executor_id is only the compatibility shell used to run the task.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DecompositionSource = Literal["llm", "fallback", "domain_hint", "keyword"]


@dataclass
class AtomicTask:
    """One unit of work dispatched to a specific hand."""

    task_id: str
    hand_id: str                                      # Brain-generated runtime hand id
    task: str                                         # specific instruction for this task
    executor_id: str = ""                             # existing hand/adapter shell
    dimension: str = ""                               # Brain-generated rubric/dimension label
    rubrics: list[dict] = field(default_factory=list)
    priority: int = 0                                  # lower = higher priority; same = parallel
    depends_on: list[str] = field(default_factory=list)
    system_prompt: str = ""                           # Brain-generated role contract for the hand agent
    capabilities: list[str] = field(default_factory=list)  # Brain-declared capability tags (e.g. ["portfolio"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "hand_id": self.hand_id,
            "executor_id": self.executor_id,
            "dimension": self.dimension,
            "task": self.task,
            "rubrics": self.rubrics,
            "priority": self.priority,
            "depends_on": self.depends_on,
            "system_prompt": self.system_prompt,
            "capabilities": self.capabilities,
        }


@dataclass
class HandPlan:
    """Brain's decomposed dispatch plan for one analyze() call."""

    domain: str
    mode: str
    tasks: list[AtomicTask]
    rationale: str
    decomposition_source: DecompositionSource = "llm"

    def unique_hands(self) -> list[str]:
        """Unique hand IDs in priority order (stable, deduped)."""
        seen: set[str] = set()
        result: list[str] = []
        for task in sorted(self.tasks, key=lambda t: t.priority):
            if task.hand_id not in seen:
                seen.add(task.hand_id)
                result.append(task.hand_id)
        return result

    def tasks_for_hand(self, hand_id: str) -> list[AtomicTask]:
        return [t for t in self.tasks if t.hand_id == hand_id]

    def unique_executors(self) -> list[str]:
        """Unique executor shell IDs in priority order (stable, deduped)."""
        seen: set[str] = set()
        result: list[str] = []
        for task in sorted(self.tasks, key=lambda t: t.priority):
            executor_id = task.executor_id or task.hand_id
            if executor_id not in seen:
                seen.add(executor_id)
                result.append(executor_id)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "mode": self.mode,
            "tasks": [t.to_dict() for t in self.tasks],
            "rationale": self.rationale,
            "decomposition_source": self.decomposition_source,
        }
