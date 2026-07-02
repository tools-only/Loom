"""State-driven atomic task decomposition for Brain.

Brain decides task dimensions, task count, and task instructions from the
current question plus selected state. Config may provide executor shells, but it
must not provide a fixed task taxonomy.
"""
from __future__ import annotations

import json
from typing import Any

from .hand_plan import AtomicTask, HandPlan


def _parse_json(text: str) -> dict | None:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    for fence in ("```json", "```"):
        if fence in stripped:
            try:
                start = stripped.index(fence) + len(fence)
                end = stripped.index("```", start)
                data = json.loads(stripped[start:end].strip())
                if isinstance(data, dict):
                    return data
            except (ValueError, json.JSONDecodeError):
                pass
    return None


class TaskDecomposer:
    """Decompose one analyze() goal into Brain-generated AtomicTask objects.

    The LLM is used as Brain's planning engine. Brain freely creates dimensions,
    hand_ids, system_prompts, and capabilities from selected state + goal.
    Each task defaults to the inline "brain-inline" executor unless Brain
    explicitly routes to a registered shell.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        hand_capabilities: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._model = model
        # hand_capabilities is accepted for backward-compat but no longer used.
        # Brain creates dimensions freely; executor_id defaults to "brain-inline".
        self._executor_caps = hand_capabilities or {}

    async def decompose(
        self,
        goal: str,
        domain: str,
        state_context: dict,
        registered_shells: list[str] | None = None,
        analysis_plan: dict | None = None,
        projection: Any | None = None,
    ) -> HandPlan:
        """Decompose goal into atomic tasks.

        `registered_shells` lists optional executor shell IDs that Brain may
        route to; if empty or omitted, every task defaults to "brain-inline".
        Brain is free to design any number of dimensions, hand_ids, and
        capabilities — there is no fixed pool.
        """
        shells = list(registered_shells or [])
        try:
            return await self._llm_decompose(
                goal, domain, state_context, shells, analysis_plan, projection
            )
        except Exception:
            return self._fallback_plan(goal, domain)

    async def _llm_decompose(
        self,
        goal: str,
        domain: str,
        state_context: dict,
        available_executors: list[str],
        analysis_plan: dict | None,
        projection: Any | None,
    ) -> HandPlan:
        rubrics = (analysis_plan or {}).get("rubrics", [])
        rubric_text = (
            "\n".join(
                f"  - {r.get('dimension', '')}: {r.get('requirements', '')}"
                for r in rubrics[:8]
            )
            if rubrics
            else "  (none yet - derive dimensions from goal and state)"
        )
        state_summary = self._summarize_state_context(state_context, projection=projection)
        shells_text = (
            ", ".join(available_executors)
            if available_executors
            else "(none registered — always use \"brain-inline\")"
        )

        user_msg = (
            f"Goal: {goal}\n"
            f"Domain: {domain}\n\n"
            f"Selected state context:\n{state_summary}\n\n"
            f"Initial rubrics, if any:\n{rubric_text}\n\n"
            f"Registered shells (optional routing targets): {shells_text}\n\n"
            "Create Brain's task design for this run.\n"
            "Rules:\n"
            "- Derive dimensions from the goal + selected state; there is NO fixed taxonomy.\n"
            "- Decide how many tasks are needed: usually 1-6, up to 8 for complex goals.\n"
            "- Each task focuses on ONE generated analytical dimension, not the full question.\n"
            "- Create a generated hand_id for each task, e.g. runtime-thermal-risk-0.\n"
            "- executor_id defaults to \"codex\". Codex runs the hand as a real agent with native\n"
            "  web search, file ops, and tools. Only use \"brain-inline\" when the hand is pure\n"
            "  reasoning/synthesis/formatting that requires ZERO external information.\n"
            "- system_prompt: 2-5 sentences defining the hand agent's role contract\n"
            "  (e.g. \"You are a thermal management analysis expert. Assess cooling capacity, "
            "thermal headroom, and reliability risks. Cite measurements where available.\").\n"
            "- capabilities: list of short capability tags the hand needs, e.g. [\"portfolio\"],\n"
            "  [\"market_data\"], [\"filings\"]. Empty list [] is fine if no special capability is needed.\n"
            "- Higher priority numbers dispatch first; same priority tasks run in parallel. "
            "Use depends_on only for true dependencies.\n\n"
            "- When state references are available, populate state-aware fields:\n"
            "  state_slice (relevant state ids), target_state_ids, target_gap_ids,\n"
            "  rubric_ids, state_intent (use|establish|verify|refresh|resolve),\n"
            "  evidence_requirements (what sources/citations are needed).\n\n"
            "Output ONLY valid JSON, no explanation:\n"
            '{"rationale":"why this decomposition fits the goal/state","tasks":['
            '{"task_id":"t1","hand_id":"runtime-generated-agent",'
            '"executor_id":"codex","dimension":"generated dimension name",'
            '"task":"specific 1-3 sentence instruction",'
            '"system_prompt":"You are a ... expert. Assess ... and cite ...",'
            '"capabilities":[],'
            '"rubrics":[{"dimension":"same/generated dimension","requirements":"what to cover"}],'
            '"priority":0,"depends_on":[],'
            '"state_slice":["S1"],"target_state_ids":["S1"],"target_gap_ids":["G1"],'
            '"rubric_ids":["R_coverage"],"state_intent":"use","evidence_requirements":["cite source"]}'
            "]}"
        )

        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1800,
            system=(
                "You are Brain's state-driven task designer. "
                "You create dimensions, hand identities, role contracts, and capability tags "
                "from state and user intent. You never rely on a fixed domain taxonomy. "
                "Output only valid JSON."
            ),
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        parsed = _parse_json(text) or {}

        raw_tasks: list = parsed.get("tasks") or []
        rationale: str = parsed.get("rationale") or "state-driven decomposition"

        tasks: list[AtomicTask] = []
        for i, item in enumerate(raw_tasks):
            if not isinstance(item, dict):
                continue
            executor_id = str(
                item.get("executor_id") or item.get("base_hand_id") or ""
            ).strip() or "brain-inline"
            hand_id = str(item.get("hand_id") or f"runtime-{executor_id}-{i}").strip()
            dimension = str(item.get("dimension") or "").strip()
            system_prompt = str(item.get("system_prompt") or "").strip()
            capabilities = list(item.get("capabilities") or [])
            tasks.append(
                AtomicTask(
                    task_id=str(item.get("task_id") or f"t{i}"),
                    hand_id=hand_id,
                    executor_id=executor_id,
                    dimension=dimension,
                    task=str(item.get("task") or goal),
                    rubrics=list(item.get("rubrics") or []),
                    priority=int(item.get("priority") or 0),
                    depends_on=list(item.get("depends_on") or []),
                    system_prompt=system_prompt,
                    capabilities=capabilities,
                    state_slice=list(item.get("state_slice") or []),
                    target_state_ids=list(item.get("target_state_ids") or []),
                    target_gap_ids=list(item.get("target_gap_ids") or []),
                    rubric_ids=list(item.get("rubric_ids") or []),
                    state_intent=str(item.get("state_intent") or "use"),
                    evidence_requirements=list(item.get("evidence_requirements") or []),
                )
            )

        if not tasks:
            return self._fallback_plan(goal, domain, rationale)

        return HandPlan(
            domain=domain,
            mode="state_driven",
            tasks=tasks,
            rationale=rationale,
            decomposition_source="llm",
        )

    @staticmethod
    def _summarize_state_context(state_context: dict, projection: Any | None = None) -> str:
        if not state_context:
            return "(no selected state)"
        parts: list[str] = []
        binding = state_context.get("projection")
        if binding:
            parts.append(f"projection: {json.dumps(binding, ensure_ascii=False)}")

        if projection is not None:
            parts.append(
                "projection_binding: "
                + json.dumps({
                    "content_id": getattr(projection, "content_id", ""),
                    "state_version": getattr(projection, "state_version", 0),
                    "schema_version": getattr(projection, "schema_version", ""),
                }, ensure_ascii=False)
            )

        for key in (
            "strategy_rules",
            "frameworks",
            "learned_notes",
            "last_synthesis",
            "intent_context",
            "request_context",
        ):
            value = state_context.get(key)
            if not value:
                continue
            try:
                text = json.dumps(value, ensure_ascii=False)
            except TypeError:
                text = str(value)
            parts.append(f"{key}: {text[:900]}")
        return "\n".join(parts) if parts else "(selected state is empty)"

    @staticmethod
    def _fallback_plan(
        goal: str,
        domain: str,
        rationale: str = "fallback: single inline runtime task",
    ) -> HandPlan:
        tasks = [
            AtomicTask(
                task_id="t0",
                hand_id="runtime-inline-0",
                executor_id="brain-inline",
                dimension="Brain-generated fallback dimension",
                task=goal,
                rubrics=[],
                priority=0,
                system_prompt=(
                    "You are a Brain-generated analysis agent. "
                    "Produce a run.artifact JSON with narrative and metadata."
                ),
                capabilities=[],
            )
        ]
        return HandPlan(
            domain=domain,
            mode="state_driven_fallback",
            tasks=tasks,
            rationale=rationale,
            decomposition_source="fallback",
        )
