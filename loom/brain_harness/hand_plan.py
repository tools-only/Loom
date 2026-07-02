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
    priority: int = 0                                  # higher = higher priority; same = parallel
    depends_on: list[str] = field(default_factory=list)
    system_prompt: str = ""                           # Brain-generated role contract for the hand agent
    capabilities: list[str] = field(default_factory=list)  # Brain-declared capability tags (e.g. ["portfolio"])
    # State-aware decomposition fields (MVP):
    state_slice: list[str] = field(default_factory=list)
    target_state_ids: list[str] = field(default_factory=list)
    target_gap_ids: list[str] = field(default_factory=list)
    rubric_ids: list[str] = field(default_factory=list)
    state_intent: str = "use"  # use, establish, verify, refresh, resolve
    evidence_requirements: list[str] = field(default_factory=list)

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
            "state_slice": self.state_slice,
            "target_state_ids": self.target_state_ids,
            "target_gap_ids": self.target_gap_ids,
            "rubric_ids": self.rubric_ids,
            "state_intent": self.state_intent,
            "evidence_requirements": self.evidence_requirements,
        }


class ExecutionGraph:
    """Immutable DAG of AtomicTask execution order.

    Built once from a list of AtomicTask via :meth:`build`. Once constructed,
    no field can be mutated (enforced by ``__slots__``). Cycle detection runs
    at construction time using Kahn's algorithm — a cyclic plan raises
    ``ValueError`` before any dispatch.
    """

    __slots__ = (
        "tasks",
        "adjacency",
        "reverse_adjacency",
        "roots",
        "projection_content_id",
        "projection_state_version",
        "projection_schema_version",
    )

    def __init__(
        self,
        tasks: tuple[AtomicTask, ...],
        adjacency: dict[str, frozenset[str]],
        reverse_adjacency: dict[str, frozenset[str]],
        roots: frozenset[str],
        projection_content_id: str,
        projection_state_version: int = 0,
        projection_schema_version: str = "",
    ) -> None:
        self.tasks = tasks
        self.adjacency = adjacency
        self.reverse_adjacency = reverse_adjacency
        self.roots = roots
        self.projection_content_id = projection_content_id
        self.projection_state_version = projection_state_version
        self.projection_schema_version = projection_schema_version

    @classmethod
    def build(
        cls,
        tasks: list[AtomicTask],
        projection_content_id: str,
        projection_state_version: int = 0,
        projection_schema_version: str = "",
    ) -> "ExecutionGraph":
        """Build an immutable DAG from ``tasks`` and detect cycles.

        Raises:
            ValueError: if the dependency graph contains a cycle (including
                self-loops). The message includes the number of unresolvable
                tasks.
        """
        # Forward adjacency: task_id -> set of successor task_ids
        adjacency_builder: dict[str, set[str]] = {t.task_id: set() for t in tasks}
        # Reverse adjacency: task_id -> set of predecessor task_ids
        reverse_adjacency_builder: dict[str, set[str]] = {
            t.task_id: set(t.depends_on) for t in tasks
        }

        # Populate forward adjacency from each task's depends_on list.
        # Tolerate references to unknown task ids by ignoring them in the
        # forward map (cycle detection still uses in-degree from depends_on).
        for t in tasks:
            for dep in t.depends_on:
                if dep in adjacency_builder:
                    adjacency_builder[dep].add(t.task_id)

        adjacency: dict[str, frozenset[str]] = {
            tid: frozenset(succs) for tid, succs in adjacency_builder.items()
        }
        reverse_adjacency: dict[str, frozenset[str]] = {
            tid: frozenset(preds) for tid, preds in reverse_adjacency_builder.items()
        }

        roots: frozenset[str] = frozenset(
            tid for tid, preds in reverse_adjacency.items() if not preds
        )

        # Kahn's algorithm — cycle detection via topological sort.
        in_degree: dict[str, int] = {
            t.task_id: len(t.depends_on) for t in tasks
        }
        queue: list[str] = [tid for tid, d in in_degree.items() if d == 0]
        processed = 0
        while queue:
            tid = queue.pop(0)
            processed += 1
            for succ in adjacency[tid]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if processed < len(tasks):
            unresolvable = len(tasks) - processed
            raise ValueError(
                f"ExecutionGraph contains a cycle: {unresolvable} tasks unresolvable"
            )

        return cls(
            tuple(tasks),
            adjacency,
            reverse_adjacency,
            roots,
            projection_content_id,
            projection_state_version,
            projection_schema_version,
        )


@dataclass
class HandPlan:
    """Brain's decomposed dispatch plan for one analyze() call."""

    domain: str
    mode: str
    tasks: list[AtomicTask]
    rationale: str
    decomposition_source: DecompositionSource = "llm"
    graph: ExecutionGraph | None = None

    def unique_hands(self) -> list[str]:
        """Unique hand IDs in priority order (stable, deduped)."""
        seen: set[str] = set()
        result: list[str] = []
        for task in sorted(self.tasks, key=lambda t: t.priority, reverse=True):
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
        for task in sorted(self.tasks, key=lambda t: t.priority, reverse=True):
            executor_id = task.executor_id or task.hand_id
            if executor_id not in seen:
                seen.add(executor_id)
                result.append(executor_id)
        return result

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": self.domain,
            "mode": self.mode,
            "tasks": [t.to_dict() for t in self.tasks],
            "rationale": self.rationale,
            "decomposition_source": self.decomposition_source,
        }
        if self.graph is not None:
            payload["graph"] = {
                "task_count": len(self.graph.tasks),
                "root_count": len(self.graph.roots),
            }
            payload["projection"] = {
                "content_id": self.graph.projection_content_id,
                "state_version": self.graph.projection_state_version,
                "schema_version": self.graph.projection_schema_version,
            }
        return payload
