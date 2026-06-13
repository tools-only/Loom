"""Loom Core Agent — Brain-level reasoning and multi-hand orchestration.

Responsibilities:
  - Resolve workflow (which hands to fire, for which domain)
  - Parallel hand execution via injected hand_runner callable
  - B-business synthesis: apply user strategy to multi-hand key_claims
  - Sediment last-synthesis to brain/context/
  - Track WorkflowEpisode events to brain/episodes/<id>.jsonl (Wave 0)
"""
from __future__ import annotations

import asyncio
import heapq
import inspect
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

# Episode tracking + task decomposition are optional: gracefully absent in
# test contexts where loom/ is not on sys.path.
try:
    from brain_harness.workflow_episode import WorkflowEpisode
    from brain_harness.budget_governor import BudgetGovernor, BudgetExceeded
    from brain_harness.task_decomposer import TaskDecomposer
    from brain_harness.hand_plan import ExecutionGraph
    from brain_harness.projection import build_projection
    _EPISODE_TRACKING = True
except ImportError:
    try:
        from loom.brain_harness.workflow_episode import WorkflowEpisode
        from loom.brain_harness.budget_governor import BudgetGovernor, BudgetExceeded
        from loom.brain_harness.task_decomposer import TaskDecomposer
        from loom.brain_harness.hand_plan import ExecutionGraph
        from loom.brain_harness.projection import build_projection
        _EPISODE_TRACKING = True
    except ImportError:
        _EPISODE_TRACKING = False


class LoomCoreAgent:
    """Brain agent: orchestrates hands and synthesizes under user strategy."""

    def __init__(
        self,
        brain_harness=None,
        dispatcher=None,
        hand_runner: Callable[[str, str, dict], Awaitable[dict]] | None = None,
        client=None,
        model: str = "",
    ) -> None:
        self._harness = brain_harness
        self._dispatcher = dispatcher
        self._hand_runner = hand_runner
        self._client = client
        self._model = model
        self._running = all(
            value is not None for value in (brain_harness, dispatcher, hand_runner)
        )

    @property
    def is_running(self) -> bool:
        return self._running

    async def analyze(self, question: str, context: dict) -> dict[str, Any]:
        """Full Brain pipeline: plan → dispatch → review → synthesize."""

        # ── Episode setup (additive — does not change existing behaviour) ──
        root: Path | None = getattr(self._harness, "root", None)
        ep: Any = None   # WorkflowEpisode | None
        governor: Any = None  # BudgetGovernor | None

        if _EPISODE_TRACKING and root is not None:
            ep = WorkflowEpisode.new(
                goal=question,
                domain=context.get("domain", "general"),
            )
            governor = BudgetGovernor()
            ep.write_event(root, "episode.start", {"context_keys": list(context.keys())})

        def _ep(event_type: str, payload: dict | None = None) -> None:
            if ep is not None and root is not None:
                ep.write_event(root, event_type, payload)

        try:
            cold = self._harness.cold_start()
            wf = await self._dispatcher.resolve(question, context)

            projection = None
            domain = wf.get("domain", "general")
            if _EPISODE_TRACKING and hasattr(self._harness, "state"):
                try:
                    projection = build_projection(
                        self._harness,
                        domain=domain,
                        question=question,
                    )
                except Exception as exc:
                    _ep("projection.build_error", {"message": str(exc)})

            state_context = {}
            if hasattr(self._harness, "select_state_context"):
                if projection is not None and self._accepts_kwarg(
                    self._harness.select_state_context, "projection"
                ):
                    state_context = self._harness.select_state_context(
                        domain=domain,
                        question=question,
                        context=context,
                        projection=projection,
                    )
                else:
                    state_context = self._harness.select_state_context(
                        domain=domain,
                        question=question,
                        context=context,
                    )
            presentation_spec = self._build_presentation_spec(question, wf, state_context)

            # ── Phase 1: Plan — Brain writes rubrics ─────────────────────────
            _ep("phase.start", {"phase": "plan"})
            if ep is not None and root is not None:
                ep.transition(root, "Planning")

            plan_kwargs = {
                "question": question,
                "workflow_decision": wf,
                "client": self._client,
                "model": self._model,
            }
            if projection is not None and self._accepts_kwarg(self._harness.plan, "projection"):
                plan_kwargs["projection"] = projection
                _ep("projection-binding", {
                    "fn": "plan",
                    "state_version": projection.state_version,
                    "schema_version": projection.schema_version,
                    "content_id": projection.content_id,
                })
            analysis_plan = await self._harness.plan(**plan_kwargs)
            rubrics = analysis_plan.get("rubrics", [])
            excluded = set(analysis_plan.get("excluded_hands", []) or [])
            registered_shells = list(
                wf.get("registered_shells")
                or wf.get("candidate_executors")
                or wf.get("hands")
                or wf.get("executor_pool")
                or []
            )
            selected_shells = [h for h in registered_shells if h not in excluded]

            _ep("phase.end", {
                "phase": "plan",
                "rubric_count": len(rubrics),
                "registered_shells": selected_shells,
            })

            # ── Wave 1: LLM-driven task decomposition ─────────────────────────
            # Brain freely creates tasks; `selected_shells` is now an optional hint list
            # (may be empty — empty means Brain decides freely).
            hand_plan: Any = None
            if _EPISODE_TRACKING:
                try:
                    decomposer = TaskDecomposer(self._client, self._model)
                    decompose_kwargs = {
                        "goal": question,
                        "domain": wf.get("domain", "general"),
                        "state_context": state_context,
                        "registered_shells": selected_shells,
                        "analysis_plan": analysis_plan,
                    }
                    if projection is not None:
                        decompose_kwargs["projection"] = projection
                        _ep("projection-binding", {
                            "fn": "decompose",
                            "state_version": projection.state_version,
                            "schema_version": projection.schema_version,
                            "content_id": projection.content_id,
                        })
                    hand_plan = await decomposer.decompose(**decompose_kwargs)
                    if projection is not None:
                        hand_plan.graph = ExecutionGraph.build(
                            hand_plan.tasks,
                            projection.content_id,
                            projection.state_version,
                            projection.schema_version,
                        )
                    _ep("plan.tasks_decomposed", {
                        "task_count": len(hand_plan.tasks),
                        "decomposition_source": hand_plan.decomposition_source,
                        "rationale": hand_plan.rationale,
                    })
                    # Enrich workflow decision with Brain-generated task plan.
                    wf = {
                        **wf,
                        "mode": "state_driven",
                        "tasks": [t.to_dict() for t in hand_plan.tasks],
                    }
                except Exception as exc:
                    _ep("plan.decompose_error", {"message": str(exc)})
                    hand_plan = None

            # ── Phase 2: Dispatch — all hands receive full rubric framework ──
            if ep is not None and root is not None:
                ep.transition(root, "Dispatching")
                ep.hands_dispatched = (
                    hand_plan.unique_hands() if hand_plan is not None else list(selected_shells)
                )

            async def _run_one(
                hand_id: str,
                repair_hint: str | None = None,
                atomic_task_str: str | None = None,
                executor_id: str | None = None,
                dimension: str | None = None,
                system_prompt: str = "",
                capabilities: list[str] | None = None,
                task_id: str | None = None,
            ) -> tuple[str, dict]:
                try:
                    run_executor_id = executor_id or hand_id
                    hand_context = {
                        **context,
                        "workflow_decision": wf,
                        "hand_id": hand_id,
                        "executor_id": run_executor_id,
                        "agentic_hand_spec": {
                            "hand_id": hand_id,
                            "executor_id": run_executor_id,
                            "task_id": task_id or "",
                            "dimension": dimension or "",
                            "task": atomic_task_str or question,
                            "lifecycle": "runtime",
                            "system_prompt": system_prompt,
                            "capabilities": capabilities or [],
                        },
                        "analysis_rubrics": rubrics,
                        "analysis_plan": analysis_plan,
                        "artifact_contract": self._artifact_contract(),
                        "presentation_spec": presentation_spec,
                        "hand_presentation_spec": presentation_spec.get("hand_specs", {}).get(hand_id, {}),
                        "brain_state_context": state_context,
                    }
                    if repair_hint:
                        hand_context["repair_feedback"] = repair_hint

                    _ep("dispatch.sent", {
                        "hand_id": hand_id,
                        "executor_id": run_executor_id,
                        "dimension": dimension or "",
                        "is_repair": repair_hint is not None,
                    })

                    # Use the LLM-generated task string when available
                    effective_question = atomic_task_str if atomic_task_str else question
                    task_str = self._build_hand_task(
                        hand_id,
                        effective_question,
                        wf,
                        presentation_spec,
                        analysis_plan,
                        executor_id=run_executor_id,
                        dimension=dimension or "",
                    )
                    if repair_hint:
                        task_str += (
                            f"\n\n⚠️ REPAIR REQUIRED — previous output failed schema validation.\n"
                            f"Issue: {repair_hint}\n"
                            "Ensure the output is a JSON object with: "
                            "'narrative' (string), 'metadata.key_claims' (list), 'metadata.confidence' (float)."
                        )

                    artifact = await self._hand_runner(run_executor_id, task_str, hand_context)

                    # ── Schema validation ────────────────────────────────────
                    issues = self._validate_artifact(artifact)
                    if issues:
                        _ep("dispatch.schema_violation", {
                            "hand_id": hand_id,
                            "executor_id": run_executor_id,
                            "issues": issues,
                            "is_repair": repair_hint is not None,
                        })
                        if repair_hint is None:
                            hint = (
                                f"Output from '{hand_id}' failed validation: {'; '.join(issues)}. "
                                "Fix these issues in your next response."
                            )
                            return await _run_one(
                                hand_id,
                                repair_hint=hint,
                                atomic_task_str=atomic_task_str,
                                executor_id=run_executor_id,
                                dimension=dimension,
                                system_prompt=system_prompt,
                                capabilities=capabilities,
                                task_id=task_id,
                            )
                        else:
                            _ep("dispatch.repair_failed", {"hand_id": hand_id, "issues": issues})
                            if ep is not None:
                                ep.quality_gaps.append(
                                    f"{hand_id}: schema unrecoverable after repair — {'; '.join(issues)}"
                                )
                    else:
                        _ep("dispatch.artifact", {
                            "hand_id": hand_id,
                            "executor_id": run_executor_id,
                            "is_repair": repair_hint is not None,
                        })

                    return hand_id, artifact

                except Exception as exc:
                    _ep("dispatch.error", {"hand_id": hand_id, "message": str(exc)})
                    return hand_id, {
                        "metadata": {"key_claims": [], "error": str(exc), "confidence": 0.0},
                        "narrative": "",
                    }

            dispatch_targets = (
                hand_plan.unique_hands() if hand_plan is not None else list(selected_shells)
            )
            _ep("phase.start", {"phase": "dispatch", "dispatch_targets": dispatch_targets})
            hand_artifacts: dict = {}
            try:
                if governor is not None:
                    governor.check_wall_clock()

                if hand_plan is not None and _EPISODE_TRACKING:
                    # Wave 1: dispatch per AtomicTask with dependency and priority ordering.
                    if hand_plan.graph is None:
                        binding = state_context.get("projection", {})
                        hand_plan.graph = ExecutionGraph.build(
                            hand_plan.tasks,
                            binding.get("content_id", "sha256:unknown"),
                            int(binding.get("state_version", 0) or 0),
                            binding.get("schema_version", ""),
                        )

                    tasks_by_id = {t.task_id: t for t in hand_plan.graph.tasks}
                    pending_deps = {
                        t.task_id: set(t.depends_on) for t in hand_plan.graph.tasks
                    }
                    completed: set[str] = set()
                    skipped: set[str] = set()
                    ready: list[tuple[int, str]] = [
                        (-tasks_by_id[tid].priority, tid)
                        for tid in hand_plan.graph.roots
                    ]
                    heapq.heapify(ready)

                    def _annotate_artifact(atom_task, artifact: dict) -> dict:
                        if not isinstance(artifact, dict):
                            artifact = {"metadata": {}, "narrative": "", "sections": [], "evidence": []}
                        meta = artifact.get("metadata")
                        if not isinstance(meta, dict):
                            artifact["metadata"] = meta = {}
                        meta["hand_id"] = atom_task.hand_id
                        meta["executor_id"] = atom_task.executor_id
                        meta["task_id"] = atom_task.task_id
                        meta["dimension"] = atom_task.dimension
                        meta["system_prompt"] = atom_task.system_prompt
                        meta["capabilities"] = atom_task.capabilities
                        return artifact

                    def _skipped_artifact(atom_task, cause: str) -> dict:
                        return _annotate_artifact(atom_task, {
                            "metadata": {
                                "key_claims": [],
                                "confidence": 0.0,
                                "gaps": [],
                                "status": "skipped",
                                "cause": cause,
                            },
                            "narrative": "",
                            "sections": [],
                            "evidence": [],
                        })

                    def _descendants(task_id: str) -> set[str]:
                        seen: set[str] = set()
                        stack = list(hand_plan.graph.adjacency.get(task_id, frozenset()))
                        while stack:
                            child = stack.pop()
                            if child in seen:
                                continue
                            seen.add(child)
                            stack.extend(hand_plan.graph.adjacency.get(child, frozenset()))
                        return seen

                    while ready:
                        priority_key, task_id = heapq.heappop(ready)
                        batch = [task_id]
                        while ready and ready[0][0] == priority_key:
                            batch.append(heapq.heappop(ready)[1])
                        _ep("dispatch.batch", {"task_ids": batch, "priority": -priority_key})

                        raw_pairs = list(await asyncio.gather(*[
                            _run_one(
                                tasks_by_id[tid].hand_id,
                                atomic_task_str=tasks_by_id[tid].task,
                                executor_id=tasks_by_id[tid].executor_id,
                                dimension=tasks_by_id[tid].dimension,
                                system_prompt=tasks_by_id[tid].system_prompt,
                                capabilities=tasks_by_id[tid].capabilities,
                                task_id=tasks_by_id[tid].task_id,
                            )
                            for tid in batch
                            if tid not in skipped
                        ]))

                        for tid, (_, artifact) in zip(
                            [tid for tid in batch if tid not in skipped],
                            raw_pairs,
                        ):
                            atom_task = tasks_by_id[tid]
                            artifact = _annotate_artifact(atom_task, artifact)
                            hand_artifacts[tid] = artifact
                            meta = artifact.get("metadata", {})
                            failed = bool(meta.get("error")) or meta.get("status") == "failed"
                            if failed:
                                for desc_id in _descendants(tid):
                                    if desc_id in completed or desc_id in skipped:
                                        continue
                                    skipped.add(desc_id)
                                    hand_artifacts[desc_id] = _skipped_artifact(tasks_by_id[desc_id], tid)
                                    _ep("dispatch.skipped", {"task_id": desc_id, "cause": tid})
                            else:
                                completed.add(tid)
                                for child in sorted(hand_plan.graph.adjacency.get(tid, frozenset())):
                                    if child in skipped:
                                        continue
                                    pending_deps[child].discard(tid)
                                    if not pending_deps[child]:
                                        heapq.heappush(ready, (-tasks_by_id[child].priority, child))
                else:
                    results: list[tuple[str, dict]] = list(
                        await asyncio.gather(*[
                            _run_one(f"runtime-{h}-0", executor_id=h)
                            for h in selected_shells
                        ])
                    )
                    hand_artifacts = dict(results)

            except BudgetExceeded as bex:
                _ep("budget.exceeded", {
                    "resource": bex.resource,
                    "used": bex.used,
                    "cap": bex.cap,
                    "phase": "dispatch",
                })
                if ep is not None:
                    ep.quality_gaps.append(
                        f"Budget exceeded ({bex.resource}) before full dispatch — partial results only"
                    )
            _ep("phase.end", {"phase": "dispatch", "hand_count": len(hand_artifacts)})

            # ── Phase 3: Review — Brain checks for gaps ─────────────────────
            if ep is not None and root is not None:
                ep.transition(root, "Reviewing")
            _ep("phase.start", {"phase": "review"})

            review_result: dict = {"follow_up_needed": False, "follow_up_tasks": []}
            try:
                if governor is not None:
                    governor.check_wall_clock()
                review_result = await self._harness.review(
                    question=question,
                    analysis_plan=analysis_plan,
                    hand_artifacts=hand_artifacts,
                    client=self._client,
                    model=self._model,
                )
            except BudgetExceeded as bex:
                _ep("budget.exceeded", {
                    "resource": bex.resource,
                    "used": bex.used,
                    "cap": bex.cap,
                    "phase": "review",
                })
                if ep is not None:
                    ep.quality_gaps.append(
                        f"Budget exceeded at review — follow-up skipped"
                    )

            follow_up_tasks = (
                review_result.get("follow_up_tasks", [])
                if isinstance(review_result, dict) and review_result.get("follow_up_needed")
                else []
            )
            if follow_up_tasks:
                if ep is not None and root is not None:
                    ep.transition(root, "Repairing")
                follow_up_results = await asyncio.gather(*[
                    _run_one(
                        t.get("hand_id", f"runtime-{t.get('executor_id', t.get('hand_id', 'agent'))}-followup"),
                        atomic_task_str=t.get("task"),
                        executor_id=t.get("executor_id", t.get("hand_id")),
                        dimension=t.get("dimension", ""),
                    )
                    for t in follow_up_tasks
                ])
                for ft, (_, artifact) in zip(follow_up_tasks, follow_up_results):
                    fkey = f"followup_{ft['hand_id']}"
                    if isinstance(artifact, dict):
                        meta = artifact.get("metadata")
                        if not isinstance(meta, dict):
                            artifact["metadata"] = meta = {}
                        meta["hand_id"] = ft["hand_id"]
                        meta["executor_id"] = ft.get("executor_id", ft["hand_id"])
                        meta["task_id"] = fkey
                    hand_artifacts[fkey] = artifact

            _ep("phase.end", {"phase": "review", "follow_up_count": len(follow_up_tasks)})

            # ── Phase 4: Synthesize ──────────────────────────────────────────
            if ep is not None and root is not None:
                ep.transition(root, "Synthesizing")
            _ep("phase.start", {"phase": "synthesize"})

            synthesis = await self._harness.synthesize(
                question, hand_artifacts, wf, self._client, self._model,
                analysis_plan=analysis_plan,
                review_result=review_result,
            )
            intent_activation = getattr(self._harness, "_last_intent_activation", None)
            policy_plan = getattr(self._harness, "_last_policy_plan", None)
            reward_report = getattr(self._harness, "_last_reward_report", None)
            self._harness.write_last_synthesis(question, wf, synthesis)

            presentation = None
            if hasattr(self._harness, "compose_presentation"):
                presentation = self._harness.compose_presentation(
                    question=question,
                    synthesis=synthesis,
                    hand_artifacts=hand_artifacts,
                    workflow_decision=wf,
                    presentation_spec=presentation_spec,
                )

            _ep("phase.end", {"phase": "synthesize"})

            # ── Finish episode ────────────────────────────────────────────────
            if ep is not None and root is not None:
                if governor is not None:
                    ep.budget_token_used = governor.token_used
                    ep.budget_cost_used_usd = governor.cost_used_usd
                ep.finish(root, "synthesis_success")

        except Exception as outer_exc:
            _ep("episode.error", {"message": str(outer_exc)})
            if ep is not None and root is not None:
                try:
                    ep.finish(root, "adapter_error", {"message": str(outer_exc)})
                except Exception:
                    pass
            raise

        return {
            "synthesis": synthesis,
            "hand_artifacts": hand_artifacts,
            "workflow_decision": wf,
            "presentation_spec": presentation_spec,
            "presentation": presentation,
            "analysis_plan": analysis_plan,
            "review_result": review_result,
            "cold_start": cold,
            "intent_activation": self._asdict_or_none(intent_activation),
            "intent_policy_plan": self._asdict_or_none(policy_plan),
            "intent_reward_report": self._asdict_or_none(reward_report),
            "episode": ep.to_summary() if ep is not None else None,
            "hand_plan": hand_plan.to_dict() if hand_plan is not None else None,
        }

    def suggest(self, query: str) -> Any:
        """Legacy stub — prefer analyze() for new callers."""
        return None

    @staticmethod
    def _accepts_kwarg(fn: Callable[..., Any], name: str) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        return any(
            param.kind == inspect.Parameter.VAR_KEYWORD or param_name == name
            for param_name, param in signature.parameters.items()
        )

    @staticmethod
    def _validate_artifact(artifact: Any) -> list[str]:
        """Check an artifact against the minimum schema contract.

        Returns a list of violation strings; empty list = valid.
        Checks only the fields that hands are required to produce.
        """
        if not isinstance(artifact, dict):
            return ["artifact must be a dict"]
        issues: list[str] = []
        if "narrative" not in artifact:
            issues.append("missing top-level field: narrative")
        meta = artifact.get("metadata")
        if not isinstance(meta, dict):
            issues.append("missing top-level field: metadata (must be a dict)")
        else:
            if "key_claims" not in meta:
                issues.append("metadata missing: key_claims")
            if "confidence" not in meta:
                issues.append("metadata missing: confidence")
        return issues

    @staticmethod
    def _artifact_contract() -> dict[str, Any]:
        return {
            "required_top_level": ["metadata", "narrative", "sections"],
            "metadata": [
                "confidence",
                "key_claims",
                "gaps",
                "resources_used",
                "source_notes",
            ],
            "sections": [
                {"id": "summary", "title": "High-level judgment"},
                {"id": "evidence", "title": "Evidence and data support"},
                {"id": "analysis", "title": "Detailed analysis"},
                {"id": "gaps", "title": "Coverage gaps"},
            ],
            "evidence_items": [
                "claim",
                "support",
                "source",
                "source_tier",
                "freshness",
                "confidence",
            ],
        }

    @staticmethod
    def _build_presentation_spec(
        question: str,
        workflow: dict[str, Any],
        state_context: dict[str, Any],
    ) -> dict[str, Any]:
        domain = workflow.get("domain", "general")
        hands = list(
            workflow.get("registered_shells")
            or workflow.get("candidate_executors")
            or workflow.get("hands")
            or workflow.get("executor_pool")
            or []
        )
        return {
            "version": "brain.presentation.v1",
            "question": question,
            "domain": domain,
            "mode": workflow.get("mode", "dynamic"),
            "ui_contract": {
                "visible_layer": {
                    "owner": "brain",
                    "purpose": "high-level user-facing judgment",
                    "content_policy": "overview_only",
                    "constraints": [
                        "short narrative",
                        "decision-relevant stance",
                        "no duplicated detail content",
                        "do not include drivers, evidence rows, source tables, or long claim lists",
                    ],
                },
                "detail_layer": {
                    "owner": "brain",
                    "purpose": "expandable evidence, analysis, source notes, and gaps",
                    "required_blocks": ["sections", "evidence", "sources", "gaps"],
                    "all_content_requires_provenance": True,
                    "card_detail_schema": LoomCoreAgent._card_detail_schema(),
                },
            },
            "hand_specs": {
                hand_id: LoomCoreAgent._hand_presentation_spec(hand_id, domain)
                for hand_id in hands
            },
            "state_context": state_context,
        }

    @staticmethod
    def _card_detail_schema() -> list[dict[str, Any]]:
        return [
            {
                "id": "judgment",
                "title": "Judgment",
                "purpose": "State the current conclusion this card contributes to the user-facing decision.",
                "brain_role": "Brain writes or normalizes this from synthesis and hand narrative.",
                "inputs": ["synthesis", "hand narrative", "key_claims"],
            },
            {
                "id": "drivers",
                "title": "Drivers",
                "purpose": "Explain why the judgment holds by grouping the most important causal factors.",
                "brain_role": "Brain selects and orders drivers from hand claims and strategy/framework state.",
                "inputs": ["key_claims", "sections", "strategy_rules", "frameworks"],
            },
            {
                "id": "evidence",
                "title": "Evidence",
                "purpose": "Show traceable claim/support/source/freshness/confidence rows.",
                "brain_role": "Brain validates that claims are backed by evidence or marks gaps.",
                "inputs": ["evidence", "source_notes", "resources_used"],
            },
            {
                "id": "implications",
                "title": "Implications",
                "purpose": "Translate the analysis into what the user should understand, monitor, or decide next.",
                "brain_role": "Brain adapts implications to the active intent, goal context, and domain.",
                "inputs": ["synthesis", "workflow_decision", "intent_context", "hand sections"],
            },
            {
                "id": "gaps",
                "title": "Gaps",
                "purpose": "Expose missing, stale, conflicting, or low-confidence information.",
                "brain_role": "Brain keeps uncertainty visible instead of hiding weak support.",
                "inputs": ["metadata.gaps", "quality_gaps", "source_notes"],
            },
            {
                "id": "watchlist",
                "title": "Watchlist",
                "purpose": "List signals that would update or reverse the judgment.",
                "brain_role": "Brain combines reversal conditions, next checks, and hand monitoring items.",
                "inputs": ["reversal_condition", "next_steps", "gaps"],
            },
        ]

    @staticmethod
    def _hand_presentation_spec(hand_id: str, domain: str) -> dict[str, Any]:
        provenance_requirements = [
            "all information units require provenance, not only numerical data",
            "source",
            "source_tier",
            "freshness",
            "confidence",
            "claim/support separation",
            "mark derived interpretation as derived and identify the input it was derived from",
            "explicit gap when source is missing or stale",
        ]
        specs = {
            "market": {
                "visible_role": "market regime judgment",
                "detail_requirements": [
                    "macro and rates support",
                    "sector or factor rotation",
                    "catalysts and event risk",
                    "confidence limits and missing data",
                ],
                "evidence_requirements": [
                    "price/index behavior",
                    "volatility or breadth signal",
                    "rates/liquidity or macro datapoint",
                    "source freshness",
                ],
                "provenance_requirements": provenance_requirements,
            },
            "sentiment": {
                "visible_role": "crowd and sentiment read",
                "detail_requirements": [
                    "sentiment direction",
                    "crowding or positioning",
                    "contrarian risk",
                    "signal quality caveats",
                ],
                "evidence_requirements": [
                    "sentiment indicator",
                    "community or news signal",
                    "breadth/participation proxy",
                    "source freshness",
                ],
                "provenance_requirements": provenance_requirements,
            },
            "target": {
                "visible_role": "target-specific setup",
                "detail_requirements": [
                    "ticker trigger map",
                    "fundamental or technical support",
                    "event calendar",
                    "monitoring checklist",
                ],
                "evidence_requirements": [
                    "company or asset data",
                    "valuation/technical trigger",
                    "filing/news/event source",
                    "source freshness",
                ],
                "provenance_requirements": provenance_requirements,
            },
            "position": {
                "visible_role": "portfolio and exposure implication",
                "detail_requirements": [
                    "exposure concentration",
                    "P/L and risk drivers",
                    "sizing or review trigger",
                    "action constraints",
                ],
                "evidence_requirements": [
                    "position exposure",
                    "risk concentration",
                    "performance driver",
                    "source freshness",
                ],
                "provenance_requirements": provenance_requirements,
            },
        }
        return specs.get(
            hand_id,
            {
                "visible_role": f"{domain} specialist contribution",
                "detail_requirements": ["supporting analysis", "evidence", "sources", "gaps"],
                "evidence_requirements": ["claim", "support", "source", "freshness"],
                "provenance_requirements": provenance_requirements,
            },
        )

    @staticmethod
    def _build_hand_task(
        hand_id: str,
        question: str,
        workflow: dict[str, Any],
        presentation_spec: dict[str, Any] | None = None,
        analysis_plan: dict[str, Any] | None = None,
        executor_id: str | None = None,
        dimension: str = "",
    ) -> str:
        domain = workflow.get("domain", "general")
        rubrics = (analysis_plan or {}).get("rubrics", [])
        rubric_text = ""
        if rubrics:
            lines = ["\nBrain analysis rubrics (analysis dimensions to cover):"]
            for r in rubrics:
                dim = r.get("dimension", "")
                req = r.get("requirements", "")
                lines.append(f"  - {dim}: {req}")
            lines.append("\nChoose which rubric(s) you can contribute to. "
                         "Tag your key_claims and evidence with `rubric` field (optional). "
                         "Overlap across hands is encouraged for cross-validation.")
            rubric_text = "\n".join(lines) + "\n"

        return (
            f"User request:\n{question}\n\n"
            f"Brain workflow domain: {domain}\n"
            f"Generated hand: {hand_id}\n"
            f"Executor shell: {executor_id or hand_id}\n"
            f"Brain-generated dimension: {dimension or '(not specified)'}\n\n"
            f"{rubric_text}"
            "Do not return a flat essay. Produce an L0-L3 layered artifact for Loom's drill-down UI:\n"
            "  L3 (visible overview): `narrative` (2-4 sentences) + `metadata.key_claims`.\n"
            "  L2 (expandable analysis): `sections` (each with id/title/summary/bullets). "
            "`metadata.source_notes`: source-by-source notes with tier/freshness.\n"
            "  L1 (structured evidence): `evidence` array with claim, support, source, source_tier, freshness, confidence.\n"
            "  L0 (raw data): `raw_items` + `raw_sources` — annotated data points collected. Each raw_item must have a populated url field.\n"
            "`metadata.gaps` at any level: missing or stale data that limits confidence.\n\n"
            "Optional: tag claims and evidence with `rubric` dimension name for cross-referencing.\n\n"
            "Brain presentation contract:\n"
            f"{LoomCoreAgent._compact_json(LoomCoreAgent._hand_task_presentation_contract(presentation_spec, hand_id, executor_id))}\n\n"
            "Brain owns the final user-facing hierarchy. Your job is to provide dense, source-backed raw material "
            "matching the assigned hand presentation spec.\n\n"
            "Output only the JSON artifact object expected by the hand contract."
        )

    @staticmethod
    def _asdict_or_none(value: Any) -> dict | None:
        if value is None:
            return None
        if is_dataclass(value):
            return asdict(value)
        return value if isinstance(value, dict) else None

    @staticmethod
    def _compact_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _hand_task_presentation_contract(
        presentation_spec: dict[str, Any] | None,
        hand_id: str,
        executor_id: str | None = None,
    ) -> dict[str, Any]:
        spec = presentation_spec or {}
        hand_specs = spec.get("hand_specs", {})
        return {
            **(hand_specs.get(hand_id) or hand_specs.get(executor_id or "") or {}),
            "card_detail_schema": spec.get("ui_contract", {})
            .get("detail_layer", {})
            .get("card_detail_schema", []),
        }
