"""Minimal orchestration snapshots for harness-facing UI and feedback scope."""

from __future__ import annotations

import re
from typing import Any


def _compute_artifact_quality_metrics(artifact: dict) -> dict[str, Any]:
    """Derive quantitative evaluation dimensions from an artifact."""
    metrics: dict[str, Any] = {
        "char_length": 0,
        "estimated_tokens": 0,
        "estimated_words": 0,
        "section_count": 0,
        "evidence_count": 0,
        "claim_count": 0,
        "gap_count": 0,
        "heading_count": 0,
        "list_item_count": 0,
        "code_block_count": 0,
        "evidence_density": 0.0,
        "freshness_flag": "unknown",
        "consistency_flag": "clean",
        "structured_output": False,
        "source_count": 0,
        "confidence_score": 0,
    }

    if not isinstance(artifact, dict):
        return metrics

    narrative = str(artifact.get("narrative", "") or "")
    sections = artifact.get("sections") or []
    evidence = artifact.get("evidence") or []
    meta = artifact.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(sections, list):
        sections = []
    if not isinstance(evidence, list):
        evidence = []

    full_text = narrative
    for sec in sections:
        if isinstance(sec, dict):
            full_text += " " + str(sec.get("heading", "") or "")
            full_text += " " + str(sec.get("body", "") or "")
        elif isinstance(sec, str):
            full_text += " " + sec

    metrics["char_length"] = len(full_text.strip())
    metrics["estimated_words"] = len(full_text.split())
    metrics["estimated_tokens"] = max(1, metrics["char_length"] // 4)
    metrics["section_count"] = len(sections)
    metrics["evidence_count"] = len(evidence)

    headings = re.findall(r"^#{1,4}\s", full_text, re.MULTILINE)
    metrics["heading_count"] = len(headings)

    list_items = re.findall(r"^\s*[-*+]\s", full_text, re.MULTILINE)
    numbered_items = re.findall(r"^\s*\d+[.)]\s", full_text, re.MULTILINE)
    metrics["list_item_count"] = len(list_items) + len(numbered_items)

    metrics["code_block_count"] = full_text.count("```")

    claims = meta.get("key_claims") or []
    if isinstance(claims, list):
        metrics["claim_count"] = len(claims)
    gaps = meta.get("gaps") or []
    if isinstance(gaps, list):
        metrics["gap_count"] = len(gaps)

    sources = []
    for ev in evidence:
        if isinstance(ev, dict):
            src = ev.get("source") or ev.get("url") or ev.get("ref")
            if src:
                sources.append(src)
    metrics["source_count"] = len(set(str(s) for s in sources))

    if metrics["char_length"] > 0:
        metrics["evidence_density"] = round(
            (metrics["claim_count"] + metrics["source_count"])
            / max(1, metrics["estimated_words"] / 100),
            2,
        )

    # Extended quality dimensions
    words = max(1, metrics["estimated_words"])
    claims = max(1, metrics["claim_count"])
    sections = max(1, metrics["section_count"])

    # Content richness: combines word depth, section density, evidence breadth
    metrics["content_richness"] = round(
        (words / 200.0 + metrics["heading_count"] * 2.0 + metrics["evidence_count"] * 3.0) / 3.0, 1
    )

    # Argumentation quality: claims per section, evidence per claim
    metrics["claims_per_section"] = round(claims / sections, 1)
    metrics["evidence_per_claim"] = round(metrics["evidence_count"] / claims, 2)

    # Structural coherence: heading hierarchy quality (0-10)
    has_h1 = bool(re.search(r"^#\s", full_text, re.MULTILINE))
    has_h2 = bool(re.search(r"^##\s", full_text, re.MULTILINE))
    has_h3 = bool(re.search(r"^###\s", full_text, re.MULTILINE))
    structure_score = 0
    if has_h2 and has_h3:
        structure_score = 8
    elif has_h2:
        structure_score = 6
    elif has_h1:
        structure_score = 4
    else:
        structure_score = 2 if sections > 1 else 0
    metrics["structural_coherence"] = structure_score

    # Source diversity: estimate unique domains in sources
    sources_for_div = []
    for ev in evidence:
        if isinstance(ev, dict):
            src = ev.get("source") or ev.get("url") or ev.get("ref") or ""
            # Extract domain from URL
            domain_match = re.search(r"https?://([^/\s]+)", str(src))
            if domain_match:
                sources_for_div.append(domain_match.group(1).lower())
            elif src:
                sources_for_div.append(str(src)[:60])
    unique_sources = len(set(s for s in sources_for_div if s))
    metrics["source_diversity"] = unique_sources

    # Token efficiency: claims per 100 estimated tokens
    metrics["token_efficiency"] = round(claims / max(1, metrics["estimated_tokens"] / 100.0), 2)

    # Readability estimate: avg sentence length (approximate via period count)
    sentence_count = len(re.findall(r"[.!?]+\s+", full_text)) or 1
    metrics["avg_sentence_length"] = round(words / sentence_count, 1)

    # Content-to-structure ratio: how much meaningful content per structural element
    metrics["content_structure_ratio"] = round(
        (metrics["char_length"] / max(1, metrics["heading_count"] + metrics["section_count"] * 100)), 1
    )

    confidence = meta.get("confidence", 0.0)
    if isinstance(confidence, (int, float)):
        metrics["confidence_score"] = round(float(confidence) * 100)
    else:
        metrics["confidence_score"] = 0

    if metrics["gap_count"] > 0:
        metrics["consistency_flag"] = "gaps_present"
    if meta.get("error") or meta.get("status") == "failed":
        metrics["consistency_flag"] = "error"

    if metrics["heading_count"] > 0 and metrics["section_count"] > 0:
        metrics["structured_output"] = True

    freshness = meta.get("freshness") or meta.get("data_freshness")
    if freshness is not None:
        metrics["freshness_flag"] = str(freshness)
    elif metrics["source_count"] == 0:
        metrics["freshness_flag"] = "unverifiable"
    elif metrics["evidence_count"] > 0:
        metrics["freshness_flag"] = "sourced"

    return metrics


def _compute_episode_quality(
    hand_artifacts: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate quality metrics across all artifacts in the episode."""
    all_metrics = []
    for key, art in (hand_artifacts or {}).items():
        if isinstance(art, dict):
            m = _compute_artifact_quality_metrics(art)
            m["artifact_key"] = key
            all_metrics.append(m)

    if not all_metrics:
        return {"artifact_count": 0, "total_chars": 0, "total_claims": 0,
                "total_gaps": 0, "avg_confidence": 0}

    total_chars = sum(m["char_length"] for m in all_metrics)
    total_claims = sum(m["claim_count"] for m in all_metrics)
    total_gaps = sum(m["gap_count"] for m in all_metrics)
    avg_conf = sum(m["confidence_score"] for m in all_metrics) / len(all_metrics)
    structured_count = sum(1 for m in all_metrics if m["structured_output"])
    error_count = sum(1 for m in all_metrics if m["consistency_flag"] == "error")

    return {
        "artifact_count": len(all_metrics),
        "total_chars": total_chars,
        "total_claims": total_claims,
        "total_gaps": total_gaps,
        "avg_confidence": round(avg_conf),
        "structured_ratio": round(structured_count / len(all_metrics) * 100),
        "error_count": error_count,
        "total_sources": sum(m["source_count"] for m in all_metrics),
    }


def _resolve_hand_profile(
    hand_id: str,
    executor_id: str,
    hand_registry: dict | None = None,
    adapter_registry=None,
    task: dict | None = None,
) -> dict[str, Any]:
    """Build a rich hand profile from registries, falling back to task metadata."""
    profile: dict[str, Any] = {
        "agent_id": hand_id,
        "adapter_id": executor_id,
        "label": hand_id,
        "description": "",
        "capabilities": [],
        "status": "selected",
        "base_model": "unknown",
        "tools": [],
        "mcp_servers": [],
        "skills": [],
        "system_prompt_snippet": "",
        "task_snippet": "",
        "dimension": "",
        "prompt_excerpt": "",
        "function_description": "",
        "domain_hint": "",
    }

    task_obj = task or {}
    profile["task_snippet"] = str(task_obj.get("task", "") or "")[:200]
    profile["dimension"] = str(task_obj.get("dimension", "") or "")

    hand_registry = hand_registry or {}
    if hand_id in hand_registry:
        entry = hand_registry[hand_id]
        profile["label"] = str(entry.get("label", hand_id))
        profile["description"] = str(entry.get("description", ""))
        profile["tools"] = list(entry.get("tools", []) or [])
        profile["mcp_servers"] = list(entry.get("mcp_servers", []) or [])
        profile["skills"] = list(entry.get("skills", []) or [])
        profile["base_model"] = str(entry.get("base_model", "unknown"))
        if entry.get("prompt"):
            try:
                with open(str(entry["prompt"]), encoding="utf-8") as f:
                    profile["system_prompt_snippet"] = f.read()[:500]
            except Exception:
                pass
        profile["function_description"] = str(entry.get("function_description", "") or entry.get("description", "") or profile["description"])[:300]
        profile["domain_hint"] = str(entry.get("domain", "") or entry.get("domain_hint", ""))

    if adapter_registry is not None:
        try:
            adapter = adapter_registry.find_by_id(executor_id)
            if adapter is None:
                adapter = adapter_registry.find_by_id(hand_id)
            if adapter is not None:
                profile["capabilities"] = list(getattr(adapter, "capabilities", []) or [])
                if not profile["description"]:
                    profile["description"] = str(getattr(adapter, "description", "") or "")
                if profile["base_model"] == "unknown":
                    profile["base_model"] = str(getattr(adapter, "model", "unknown") or "unknown")
                adapter_tools = getattr(adapter, "tools", None) or []
                if adapter_tools:
                    profile["tools"] = list(adapter_tools)
        except Exception:
            pass

    # Fallback to task-level capabilities when registry/adapter provide none
    # Populate prompt excerpt and function description from task
    if task_obj.get("system_prompt"):
        profile["prompt_excerpt"] = str(task_obj.get("system_prompt", ""))[:500]
    elif task_obj.get("task"):
        profile["prompt_excerpt"] = str(task_obj.get("task", ""))[:300]
    if task_obj.get("dimension") and not profile["function_description"]:
        profile["function_description"] = f"Hand for: {task_obj['dimension']}"
    if not profile["domain_hint"] and task_obj.get("domain"):
        profile["domain_hint"] = str(task_obj["domain"])

    if not profile["capabilities"] and task_obj.get("capabilities"):
        profile["capabilities"] = list(task_obj["capabilities"])

    return profile


def build_minimal_orchestration_snapshot(
    *,
    episode_id: str,
    goal: str,
    domain: str = "general",
    workflow: dict[str, Any] | None = None,
    hand_plan: dict[str, Any] | None = None,
    hand_artifacts: dict[str, Any] | None = None,
    review_result: dict[str, Any] | None = None,
    hand_registry: dict[str, Any] | None = None,
    adapter_registry: Any = None,
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

        task_label = task.get("dimension") or task.get("task") or task_id
        task_description = task.get("task", "")

        nodes.append({
            "id": task_node,
            "type": "task",
            "label": task_label,
            "task": task_description,
            "depends_on": list(task.get("depends_on") or []),
        })
        nodes.append({
            "id": hand_node,
            "type": "hand",
            "label": f"Hand: {hand_id}",
            "executor_id": executor_id,
        })
        edges.append({"from": "brain", "to": task_node, "reason": "task decomposition"})
        edges.append({
            "from": task_node,
            "to": hand_node,
            "reason": "hand routing",
            "executor_id": executor_id,
        })

        profiles[hand_id] = _resolve_hand_profile(
            hand_id, executor_id, hand_registry, adapter_registry, task
        )

        artifact = hand_artifacts.get(task_id) or hand_artifacts.get(hand_id) or {}
        if isinstance(artifact, dict):
            meta = artifact.get("metadata", {}) if isinstance(artifact.get("metadata"), dict) else {}
            quality = _compute_artifact_quality_metrics(artifact)
            nodes.append({
                "id": artifact_node,
                "type": "artifact",
                "label": f"Artifact {task_id}",
                "confidence": meta.get("confidence", 0.0),
                "gap_count": len(meta.get("gaps", []) or []),
                "claim_count": len(meta.get("key_claims", []) or []),
                "quality_metrics": quality,
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

    quality_summary = _compute_episode_quality(hand_artifacts or {}, profiles)

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
        "quality_summary": quality_summary,
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
