"""Minimal orchestration snapshots for harness-facing UI and feedback scope."""

from __future__ import annotations

from typing import Any


def build_minimal_orchestration_snapshot(
    *,
    episode_id: str,
    goal: str,
    domain: str = "general",
    workflow: dict[str, Any] | None = None,
    hand_plan: dict[str, Any] | None = None,
    hand_artifacts: dict[str, Any] | None = None,
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow = workflow or {}
    hand_plan = hand_plan or {}
    hand_artifacts = hand_artifacts or {}
    review_result = review_result or {}

    nodes: list[dict[str, Any]] = [
        {"id": "brain", "type": "brain", "label": "Brain"},
    ]
    edges: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []

    tasks = hand_plan.get("tasks") if isinstance(hand_plan.get("tasks"), list) else []
    if not tasks and hand_artifacts:
        tasks = [_task_from_artifact(key, artifact) for key, artifact in hand_artifacts.items()]

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or task.get("id") or "")
        if not task_id:
            continue
        hand_id = str(task.get("hand_id") or task.get("executor_id") or "unknown")
        executor_id = str(task.get("executor_id") or hand_id)
        task_node = f"task:{task_id}"
        hand_node = f"hand:{hand_id}"
        artifact_node = f"artifact:{task_id}"

        nodes.append({
            "id": task_node,
            "type": "task",
            "label": task.get("dimension") or task.get("task") or task_id,
            "task": task.get("task", ""),
            "depends_on": list(task.get("depends_on") or []),
        })
        nodes.append({
            "id": hand_node,
            "type": "hand",
            "label": hand_id,
            "executor_id": executor_id,
        })
        edges.append({"from": "brain", "to": task_node, "reason": "task decomposition"})
        edges.append({
            "from": task_node,
            "to": hand_node,
            "reason": "hand routing",
            "executor_id": executor_id,
        })

        profiles[hand_id] = {
            "agent_id": hand_id,
            "adapter_id": executor_id,
            "capabilities": list(task.get("capabilities") or []),
            "status": "selected",
            "base_model": "unknown",
            "tools": [],
            "mcp_servers": [],
            "skills": [],
        }

        artifact = hand_artifacts.get(task_id) or hand_artifacts.get(hand_id) or {}
        if isinstance(artifact, dict):
            meta = artifact.get("metadata", {}) if isinstance(artifact.get("metadata"), dict) else {}
            nodes.append({
                "id": artifact_node,
                "type": "artifact",
                "label": f"Artifact {task_id}",
                "confidence": meta.get("confidence", 0.0),
                "gap_count": len(meta.get("gaps", []) or []),
                "claim_count": len(meta.get("key_claims", []) or []),
            })
            edges.append({"from": hand_node, "to": artifact_node, "reason": "returned artifact"})
            for gap in meta.get("gaps", []) or []:
                diagnostics.append({
                    "type": "artifact_gap",
                    "object_ref": artifact_node,
                    "message": str(gap),
                })

    if review_result.get("follow_up_needed"):
        nodes.append({"id": "review", "type": "review", "label": "Review gaps"})
        edges.append({"from": "brain", "to": "review", "reason": "quality review"})
        for gap in review_result.get("confidence_gaps", []) or []:
            diagnostics.append({"type": "review_gap", "object_ref": "review", "message": str(gap)})

    return {
        "episode_id": episode_id,
        "goal": goal,
        "domain": domain,
        "workflow_mode": workflow.get("mode", hand_plan.get("mode", "")),
        "rationale": workflow.get("rationale", hand_plan.get("rationale", "")),
        "nodes": _dedupe_nodes(nodes),
        "edges": edges,
        "profiles": profiles,
        "diagnostics": diagnostics,
    }


def _task_from_artifact(key: str, artifact: Any) -> dict[str, Any]:
    meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    task_id = str(meta.get("task_id") or key)
    return {
        "task_id": task_id,
        "hand_id": str(meta.get("hand_id") or key),
        "executor_id": str(meta.get("executor_id") or meta.get("hand_id") or key),
        "dimension": str(meta.get("dimension") or ""),
        "task": str(meta.get("task") or ""),
        "capabilities": list(meta.get("capabilities") or []),
        "depends_on": [],
    }


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        out.append(node)
    return out
