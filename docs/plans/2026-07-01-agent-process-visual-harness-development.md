# Agent Process Visualization Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the minimal Loom harness that turns agent intermediate execution into a visual, state-causal workspace, and lets users intervene at high-value checkpoints without manually managing agents.

**Architecture:** Reuse the existing `WorkflowEpisode`, `LoomCoreAgent`, `BrainHarness`, `FlywheelRecord`, orchestration snapshot, and scoped feedback path. Add an environment-state and bottleneck layer between trace events and UI, then route selected human interactions back into planning, task decomposition, review, repair, synthesis, replay, and flywheel records.

**Tech Stack:** Python FastAPI (`loom/brain.py`), Python harness modules (`loom/brain_harness/*`), Python core orchestration (`loom_core/agents/core_agent.py`), Anchor webview JavaScript (`bridge/webview/*`), existing Node web service (`mcp/server.cjs`), Python `unittest`, Node `node:test`.

---

## Source Material Found

This document consolidates the prior discussion and repository notes from:

- `docs/plans/2026-06-28-loom-value-aware-visual-elicitation-harness.md`
- `docs/plans/2026-06-30-loop-dynamic-harness-comparison.md`
- `docs/plans/2026-06-30-feedback-repair-closed-loop-demo.md`
- Existing code around `WorkflowEpisode`, orchestration snapshots, scoped feedback, review repair, and flywheel persistence.

The extracted scheme is:

```text
agent execution trace
-> environment states
-> epistemic bottlenecks
-> ask / verify / defer / use
-> visual query or checkpoint
-> weak human signal
-> state-aware planning, decomposition, review, repair, synthesis
-> flywheel + replay
```

This is not a log viewer. The UI must not only show what agents did. It must expose the intermediate claims, gaps, weak evidence, stale assumptions, and goal-drift points that can change downstream execution.

## Core Product Decision

Build the first version as:

```text
EnvironmentStateFrame
+ state-aware review gate
+ targeted repair task generation
+ minimal visual checkpoint for high-impact bottlenecks
+ flywheel recording of state transitions and interaction consumption
```

Do not start with full self-evolution, full dashboard, broad gesture vocabulary, or model training. Prove that detecting and resolving bottlenecks earlier improves the agent loop.

## Current Code Anchors

| Concern | Existing File | Current Role | Development Direction |
|---|---|---|---|
| Episode event log | `loom/brain_harness/workflow_episode.py` | Append-only JSONL events under `brain/episodes/` | Add state, bottleneck, visual query, and interaction event families |
| Core execution phases | `loom_core/agents/core_agent.py` | plan -> decompose -> dispatch -> review -> repair -> synthesize | Insert state frame, bottleneck routing, state-aware task metadata, and synthesis guard |
| Atomic tasks | `loom/brain_harness/hand_plan.py` | `AtomicTask` carries task, hand, executor, rubrics, priority, dependencies | Add state/gap/rubric references and `state_intent` |
| Decomposition prompt | `loom/brain_harness/task_decomposer.py` | Brain creates runtime hand tasks from state and goal | Teach Brain to create verify/refresh/resolve tasks from bottlenecks |
| Brain harness | `loom/brain_harness/base.py` | Selects state context, plans rubrics, reviews gaps, synthesizes result | Add environment state frame, state-aware review, and guarded synthesis |
| Orchestration snapshot | `loom/brain_harness/orchestration.py` | Builds task/hand/artifact/review graph for UI | Add state and bottleneck refs, or expose them through a separate workspace payload |
| Scoped feedback | `loom/brain_harness/contextual_intent.py` | Converts object-scoped feedback into `IntentDelta` | Extend to consume visual interaction traces and checkpoint responses |
| Repair helpers | `loom_core/repair/episode_repair.py` | Builds targeted repair plan and repair task from feedback | Reuse for bottleneck-driven repair tasks |
| Flywheel | `loom/brain_harness/flywheel.py` | Stores episode details, artifacts, feedback, repair history | Add state transitions, bottlenecks, visual traces, consumed-by records |
| Feedback widget | `bridge/webview/hand-feedback-widget.js` | Posts scoped thumbs/note feedback to `/feedback` | Reuse event payload shape for checkpoint cards |
| Orchestration UI | `bridge/webview/orchestration-view.js` | Renders Brain/Task/Hand/Artifact/Review DAG | Add or pair with Live State Canvas and Checkpoint Review Deck |
| Brain API | `loom/brain.py` | `/analyze`, `/feedback`, `/feedback/repair`, `/orchestration/{episode_id}` | Add workspace and visual interaction endpoints |

## Brain/Hand Process Visibility and Feedback Policy

The product surface should make the agent's intermediate work legible without exposing raw prompts, full traces, or model-internal reasoning. The useful unit is not "what the agent thought"; it is "which state, claim, gap, task, or routing decision can change the outcome."

### Brain Task Decomposition

Brain decomposition should be shown as a compact causal chain:

```text
Goal frame -> active state frame -> analysis dimensions -> atomic tasks -> hand/executor route
```

| Brain Step | What to Show Directly | Feedback Medium | Harness Signal |
|---|---|---|---|
| Goal interpretation | The current goal frame, excluded scope, success criteria | choose closer goal card, contest scope, add short correction | `goal_frame_calibration`, `scope_correction` |
| State selection | Top active constraints, assumptions, stale states, high-impact gaps | pin, mute, contest, expand evidence | `state_salience`, `state_contested`, `evidence_need` |
| Rubric/analysis dimensions | 3-6 dimensions Brain will evaluate, in user language | pin missing dimension, mark irrelevant dimension | `rubric_gap`, `rubric_downrank`, `coverage_priority` |
| Atomic task design | Task cards with "why this exists", target state/gap, expected output | mark task irrelevant, request missing angle, skip low-value task | `task_relevance`, `missing_dimension`, `interaction_budget_hint` |
| Dependency plan | Only meaningful dependencies and blockers | continue without blocker, verify first, defer | `dependency_priority`, `defer_allowed` |

Do not ask users to manually design the workflow. The interaction should calibrate Brain's assumptions, not turn the user into the orchestrator.

### Hand Scheduling and Routing

Hand scheduling should be presented as "why this capability is being used", not as an agent management console.

| Scheduling Content | Show Directly? | Interaction? | Notes |
|---|---:|---:|---|
| Selected hand/runtime id | Yes, but human-readable | No by default | Show "Market evidence checker" instead of raw `runtime-market-0` when possible |
| Executor shell or adapter | On expand | Rare | Useful for trust/debug, not primary UX |
| Capability tags | Yes | Pin/mute if capability is wrong | Shows why this hand was selected |
| Cost/latency/risk tier | Yes for expensive or high-risk tasks | Approve/skip only when high impact | Do not interrupt for cheap normal tasks |
| Source/tool access | On expand | Mark source untrusted or stale | Strong signal for future routing |
| Raw hand prompt/system prompt | No | No | Keep in developer audit only |
| Full token trace | No | No | Use for replay/OPD datasets, not user UI |

Good visible routing copy:

```text
Brain is asking Market Evidence to verify source freshness because the final answer depends on claim C7.
```

Bad visible routing copy:

```text
Dispatching runtime-market-evidence-agent via brain-inline with prompt: ...
```

### Agent Intermediate Outputs

Intermediate outputs should be layered. The default view should show decision-relevant artifacts; deeper detail should be available only when it helps trust, correction, or learning.

| Agent Content | Direct User View | Interactive Feedback View | Harness/OPD Data Only |
|---|---|---|---|
| Task graph | Compact DAG: Brain -> Task -> Hand -> Artifact -> Review | mark task irrelevant, pin missing angle | full event log |
| Task rationale | One sentence per task | contest rationale, add missing constraint | raw decomposition prompt |
| Hand status | running, blocked, repaired, skipped | cancel/defer only for high-cost work | timing trace |
| Key claims | claim cards with confidence and source count | trust, contest, expand evidence | raw claim extraction candidates |
| Evidence chain | expandable claim -> support -> source -> freshness | source stale, source untrusted, need more evidence | raw source payloads |
| Gaps | visible gap list when high impact | pin, mute, verify now, defer | low-impact gaps |
| Review result | why Brain rejected/caveated an artifact | confirm issue, override as acceptable, request repair | full rubric scoring detail |
| Repair attempt | before/after artifact summary | confirm corrected, still wrong, reuse pattern | repair prompts and raw traces |
| Final synthesis state use | used/excluded/caveated states | confirm correction, ask next check | full synthesis prompt |

The UI should strongly favor claim/evidence/gap cards over raw natural-language agent transcripts.

### What Should Be Intuitively Presented

These are suitable for direct visual presentation because users can understand them without learning the internals:

- Brain's current interpretation of the goal.
- The analysis dimensions Brain intends to cover.
- The task DAG at a compact level.
- Which hands/capabilities are working and why.
- High-confidence claims and low-confidence claims.
- Evidence chains, source freshness, and provenance.
- High-impact gaps and contradictions.
- Review decisions: accepted, rejected, caveated, repaired.
- Which user feedback changed the run.
- What changed after repair.

### What Should Become Interactive Feedback Media

These are best as interaction cards because the user can provide cheap, high-value signals:

- Goal forks: "Are we solving A or B?"
- Ambiguous scope: "Should this include implementation or design only?"
- Evidence trust: "Is this source/claim acceptable?"
- Gap salience: "Should we verify this now?"
- Task relevance: "Is this analysis angle useful?"
- Rubric coverage: "Is a key dimension missing?"
- Source preference: "Use/avoid this source in future."
- Repair confirmation: "Did the corrected artifact fix the issue?"
- Density preference: "Show less/more evidence for this kind of claim."

### What Should Stay in Harness/OPD/Replay Data

These are valuable for learning and evaluation but should not be normal user-facing content:

- Raw prompts, system prompts, hidden planning instructions.
- Full token-level traces.
- All candidate decompositions Brain considered.
- Failed parser attempts.
- Low-impact diagnostic events.
- Detailed reward ledger rows.
- OPD/OPSD training samples and teacher/student distributions.
- Replay comparison internals.
- Harness edit candidates before they have product meaning.

For Loom, OPD/OPSD/in-place TTT belong behind the harness boundary. Runtime UI should capture structured verbal/visual feedback and trace data; later training or distillation can consume curated episodes, but the user should interact with states, claims, gaps, and checkpoints.

### Feedback Signal Routing

| User Signal | Immediate Consumer | Long-Term Consumer | Example |
|---|---|---|---|
| Trust claim | `BrainHarness.review` | source/rubric preference | claim can be used with lower caveat |
| Contest claim | `ReviewRepairEngine` | replay failure class | create repair task |
| Expand evidence | `SynthesisGuard` | density policy | preserve provenance in final answer |
| Pin gap | `TaskDecomposer` | domain rubric composer | create verification task |
| Mute gap | `BottleneckDetector` | interaction budget policy | defer low-value bottleneck |
| Confirm repair | `FlywheelWriter` | reusable correction memory | mark repair pattern reusable |
| Mark task irrelevant | `TaskDecomposer` | offload/evaluator policy | downrank similar decomposition |

## Domain Model

### EnvironmentState

Structured representation of the task world, not user intent and not a UI card.

Examples:

- "The synthesis depends on claim C7, but C7 has only one weak source."
- "The user is asking for a development document, not implementation yet."
- "The current hand artifact has gaps around source freshness."
- "This goal has shifted from cost reduction to delivery speed."

Status values:

```text
proposed -> active -> contested -> verifying -> resolved
                         |            |
                         v            v
                       stale        retired
```

Rules:

- Human gestures never directly mutate status.
- Human gestures add evidence.
- Brain review decides transitions.
- Every transition records evidence and phase.
- `resolved` means sufficiently handled for the current episode, not globally true.

### EpistemicBottleneck

A state, claim, gap, or decision whose uncertainty may materially affect downstream work.

Scoring dimensions:

- `uncertainty`
- `impact`
- `human_answerability`
- `agent_verifiability`
- `interaction_cost`
- `repair_cost_if_wrong`
- `time_sensitivity`

Routing:

```text
ask    -> create visual query/checkpoint if human can answer cheaply
verify -> create targeted hand task if agents/tools can validate
defer  -> keep out of synthesis or include caveat
use    -> include in state frame and downstream prompts
```

### VisualQuery

A small, local interaction compiled from a bottleneck.

MVP query types:

| Query Type | Example | User Action | Harness Signal |
|---|---|---|---|
| `goal_fork` | "Is this about implementation now or design first?" | choose closer card | goal frame calibration |
| `evidence_trust` | show claim and evidence chain | trust, contest, expand | trust/evidence need |
| `gap_salience` | "Should we verify source freshness now?" | pin, mute, skip | gap priority |
| `drift_checkpoint` | timeline shows changed goal | accept, contest | goal drift evidence |

### VisualInteractionTrace

Raw interaction plus inferred weak signal and downstream consumption.

`consumed_by` is required. If a trace never affects review, repair, planning, or synthesis, it is not evidence of product value.

## Data Contracts

### EnvironmentState

```json
{
  "state_id": "S12",
  "episode_id": "ep_...",
  "type": "claim",
  "status": "active",
  "summary": "WACC assumption may be stale.",
  "scope": "current_episode",
  "salience": 0.82,
  "freshness": 0.44,
  "confidence": 0.62,
  "evidence_refs": ["artifact:t1", "claim:C7"],
  "conflicts_with": [],
  "created_by": "review",
  "updated_by": "brain_review",
  "created_at": 1782830000.0,
  "updated_at": 1782830008.0
}
```

### StateTransition

```json
{
  "state_id": "S12",
  "from": "active",
  "to": "contested",
  "episode_id": "ep_...",
  "phase": "review",
  "evidence": [
    {
      "type": "visual.interaction",
      "id": "vi_...",
      "summary": "user contested evidence freshness"
    },
    {
      "type": "review_gap",
      "id": "gap_...",
      "summary": "review found stale source"
    }
  ],
  "decided_by": "brain_review",
  "confidence": 0.71
}
```

### EpistemicBottleneck

```json
{
  "bottleneck_id": "B9",
  "anchor_type": "state",
  "anchor_id": "S12",
  "uncertainty": 0.58,
  "impact": 0.91,
  "human_answerability": 0.74,
  "agent_verifiability": 0.63,
  "interaction_cost": 0.18,
  "repair_cost_if_wrong": 0.86,
  "recommended_action": "ask",
  "rationale": "High-impact freshness concern can be calibrated cheaply."
}
```

### VisualQuery

```json
{
  "query_id": "vq_...",
  "episode_id": "ep_...",
  "bottleneck_id": "B9",
  "query_type": "evidence_trust",
  "anchor_type": "state",
  "anchor_id": "S12",
  "cards": [
    {
      "card_id": "claim",
      "label": "WACC assumption is current enough",
      "state_ids": ["S12"]
    }
  ],
  "allowed_interactions": ["trust", "contest", "expand", "skip"],
  "expires_after_phase": "review"
}
```

### VisualInteractionTrace

```json
{
  "interaction_id": "vi_...",
  "query_id": "vq_...",
  "episode_id": "ep_...",
  "anchor_type": "state",
  "anchor_id": "S12",
  "gesture": "contest",
  "visual_context": {
    "phase": "review",
    "shown_evidence_refs": ["artifact:t1", "claim:C7"]
  },
  "inferred_signals": [
    {
      "type": "evidence_distrust",
      "target": "S12",
      "confidence": 0.7
    }
  ],
  "consumed_by": [
    {
      "consumer": "BrainHarness.review",
      "effect": "created source freshness repair task"
    }
  ]
}
```

### AtomicTask Extension

```json
{
  "task_id": "t_verify_wacc_freshness",
  "hand_id": "runtime-source-freshness-agent",
  "executor_id": "brain-inline",
  "dimension": "source freshness verification",
  "task": "Verify whether the WACC assumption is supported by Q1 2026 source data.",
  "state_slice": ["S12"],
  "target_state_ids": ["S12"],
  "target_gap_ids": ["G4"],
  "rubric_ids": ["R_evidence_sufficiency", "R_freshness"],
  "state_intent": "verify",
  "evidence_requirements": [
    "cite source freshness",
    "mark unresolved if no Q1 2026 support is available"
  ],
  "priority": 10,
  "depends_on": []
}
```

## API Contract

Add these endpoints to `loom/brain.py`:

```text
GET  /episodes/{episode_id}/workspace
GET  /episodes/{episode_id}/experience-graph
POST /episodes/{episode_id}/visual-interactions
POST /episodes/{episode_id}/checkpoint-response
GET  /harness/evolution/candidates
```

MVP endpoint behavior:

| Endpoint | Purpose | Backing Store |
|---|---|---|
| `GET /episodes/{episode_id}/workspace` | Return state frame, bottlenecks, visual queries, orchestration snapshot, and diagnostics | `FlywheelWriter.load_detail()` plus episode JSONL |
| `POST /episodes/{episode_id}/visual-interactions` | Append raw visual interaction trace and inferred weak signal | `FlywheelWriter.append_visual_interaction()` |
| `POST /episodes/{episode_id}/checkpoint-response` | Same as visual interaction, but returns updated `intent_lens` and optional repair trigger | `ContextualIntentCompiler` plus flywheel |
| `GET /episodes/{episode_id}/experience-graph` | Developer/debug view linking state, claim, evidence, gap, task, repair, outcome | Derived from episode events and flywheel detail |
| `GET /harness/evolution/candidates` | Stub for later controlled self-evolution candidates | Empty list in MVP |

## UI Contract

Build two surfaces:

```text
Live State Canvas + Checkpoint Review Deck
```

Live State Canvas:

- Shows only high-value current states, claims, gaps, evidence chains, and pending repairs.
- Does not show full traces by default.
- Supports expand/collapse for provenance.
- Uses `GET /episodes/{episode_id}/workspace`.

Checkpoint Review Deck:

- Appears only when bottleneck routing returns `ask`.
- Contains a small number of cards.
- Posts to `POST /episodes/{episode_id}/visual-interactions` or `POST /episodes/{episode_id}/checkpoint-response`.
- Must not block the agent loop by default. If the user skips or ignores it, the harness uses `verify`, `defer`, or caveated `use`.

MVP interactions:

| UI Action | Payload Gesture | Meaning |
|---|---|---|
| Trust | `trust` | provisional acceptance |
| Contest | `contest` | weak distrust or correction candidate |
| Expand evidence | `expand` | evidence need |
| Pin | `pin` | high salience |
| Mute | `mute` | low salience |
| Skip | `skip` | no current value |

## Implementation Plan

### Task 1: Add Environment State Data Model

**Files:**

- Create: `loom/brain_harness/environment_state.py`
- Test: `tests/test_environment_state.py`

**Step 1: Write failing tests**

Cover:

- `EnvironmentState.to_dict()` emits stable JSON fields.
- `EnvironmentStateManager.extract_from_artifacts()` creates `claim` and `gap` states from `metadata.key_claims`, `metadata.gaps`, and `evidence`.
- State transitions require evidence and preserve old/new status.
- `EnvironmentStateFrame` selects active states and excludes stale/retired states by default.

**Step 2: Implement minimal dataclasses**

Implement:

- `EnvironmentState`
- `StateTransition`
- `EnvironmentStateFrame`
- `EnvironmentStateManager`

Do not add persistence yet. Keep this module deterministic and testable.

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_environment_state
```

Expected: tests pass.

### Task 2: Add Bottleneck Routing

**Files:**

- Create: `loom/brain_harness/bottleneck.py`
- Test: `tests/test_bottleneck_routing.py`

**Step 1: Write failing tests**

Cover:

- High impact + high human answerability + low interaction cost routes to `ask`.
- High impact + high agent verifiability routes to `verify`.
- Low impact routes to `defer`.
- High confidence/low risk routes to `use`.

**Step 2: Implement deterministic scorer**

Implement:

- `EpistemicBottleneck`
- `BottleneckDetector.detect(frame, hand_artifacts, review_result=None)`
- `route_bottleneck(bottleneck)`

Start with simple heuristic scoring. Do not call an LLM in MVP.

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_bottleneck_routing
```

Expected: tests pass.

### Task 3: Add Visual Query and Interaction Model

**Files:**

- Create: `loom/brain_harness/visual_interaction.py`
- Test: `tests/test_visual_interaction.py`

**Step 1: Write failing tests**

Cover:

- `VisualQueryCompiler` creates an `evidence_trust` query from an `ask` bottleneck.
- `VisualInteractionInterpreter` converts `contest` into weak `evidence_distrust`.
- `consumed_by` starts empty and can be appended without mutating the original trace unexpectedly.

**Step 2: Implement dataclasses and pure helpers**

Implement:

- `VisualQuery`
- `VisualInteractionTrace`
- `VisualQueryCompiler`
- `VisualInteractionInterpreter`

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_visual_interaction
```

Expected: tests pass.

### Task 4: Extend WorkflowEpisode Events

**Files:**

- Modify: `loom/brain_harness/workflow_episode.py`
- Modify: `tests/test_workflow_episode.py`

**Step 1: Write failing tests**

Add tests that `write_event()` can persist and sink:

- `state.proposed`
- `state.transition`
- `claim.created`
- `gap.detected`
- `bottleneck.detected`
- `visual.query_created`
- `visual.interaction`
- `state.used_by_synthesis`

The implementation does not need a whitelist if the event writer remains generic. The test should protect the shape and event sink behavior.

**Step 2: Add helper constants only if useful**

Keep `WorkflowEpisode.write_event()` generic. Add event name constants only if they reduce duplication.

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_workflow_episode
```

Expected: tests pass.

### Task 5: Persist State and Interaction Summaries in Flywheel

**Files:**

- Modify: `loom/brain_harness/flywheel.py`
- Modify: `tests/test_flywheel.py`

**Step 1: Write failing tests**

Cover new append helpers:

- `append_state_transition(episode_id, transition)`
- `append_bottleneck(episode_id, bottleneck)`
- `append_visual_query(episode_id, query)`
- `append_visual_interaction(episode_id, trace)`
- `append_interaction_consumption(episode_id, interaction_id, consumption)`

**Step 2: Add fields to `FlywheelRecord`**

Add default lists:

- `state_transitions`
- `bottlenecks`
- `visual_queries`
- `visual_interactions`
- `interaction_consumption`

Use the existing `_append_to_detail_list()` pattern.

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_flywheel
```

Expected: tests pass.

### Task 6: Extend AtomicTask for State-Aware Decomposition

**Files:**

- Modify: `loom/brain_harness/hand_plan.py`
- Modify: `loom/brain_harness/task_decomposer.py`
- Modify: `tests/test_core_agent_task_decomposition.py`

**Step 1: Write failing tests**

Add tests that parsed LLM JSON preserves:

- `state_slice`
- `target_state_ids`
- `target_gap_ids`
- `rubric_ids`
- `state_intent`
- `evidence_requirements`

Also test fallback tasks include empty values for these fields.

**Step 2: Modify `AtomicTask`**

Add fields:

```python
state_slice: list[str] = field(default_factory=list)
target_state_ids: list[str] = field(default_factory=list)
target_gap_ids: list[str] = field(default_factory=list)
rubric_ids: list[str] = field(default_factory=list)
state_intent: str = "use"
evidence_requirements: list[str] = field(default_factory=list)
```

Update `to_dict()`.

**Step 3: Modify `TaskDecomposer` prompt**

Prompt Brain to use:

- `use`
- `establish`
- `verify`
- `refresh`
- `resolve`

Require tasks to cite state/gap/rubric references when created from bottlenecks.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition
```

Expected: tests pass.

### Task 7: Build EnvironmentStateFrame in Core Agent

**Files:**

- Modify: `loom_core/agents/core_agent.py`
- Modify: `tests/test_core_agent_task_decomposition.py`

**Step 1: Write failing tests**

Cover:

- `LoomCoreAgent.analyze()` passes `environment_state_frame` into `state_context`.
- `dispatch.sent` events include state refs when the task has them.
- `hand_context["agentic_hand_spec"]` includes state-aware fields.
- `presentation_spec["state_context"]` includes environment state frame summary.

**Step 2: Implement insertion point**

After `select_state_context()` and before `plan()`:

```text
EnvironmentStateManager extracts candidate states
EnvironmentStateFrame is selected
BottleneckDetector scores bottlenecks
VisualQueryCompiler creates only ask-worthy checkpoints
```

Write episode events:

- `state.proposed`
- `gap.detected`
- `bottleneck.detected`
- `visual.query_created`

**Step 3: Keep user interaction non-blocking**

Do not wait for checkpoint response in the first pass. The normal loop continues with `verify`, `defer`, or caveated `use`.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition
```

Expected: tests pass.

### Task 8: Make Review State-Aware

**Files:**

- Modify: `loom/brain_harness/base.py`
- Modify: `loom_core/agents/core_agent.py`
- Test: `tests/test_state_aware_review.py`

**Step 1: Write failing tests**

Cover:

- Active state without evidence creates a review gap.
- Contested state used by an artifact produces a follow-up repair task.
- Stale state used without refresh produces a refresh task.
- Repair task includes `target_state_ids`, `target_gap_ids`, `state_intent`, and evidence requirements.

**Step 2: Update `BrainHarness.review()`**

Add optional kwarg:

```python
environment_state_frame: dict | None = None
visual_interactions: list[dict] | None = None
```

Use `_accepts_kwarg()` in `LoomCoreAgent` if needed, consistent with projection handling.

**Step 3: Reuse existing review repair path**

The existing `follow_up_tasks` path in `LoomCoreAgent` should handle targeted repair. Extend the follow-up task shape instead of adding a second repair system.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_state_aware_review tests.test_core_agent_task_decomposition
```

Expected: tests pass.

### Task 9: Add SynthesisGuard

**Files:**

- Create: `loom/brain_harness/synthesis_guard.py`
- Modify: `loom/brain_harness/base.py`
- Test: `tests/test_synthesis_guard.py`

**Step 1: Write failing tests**

Cover:

- `contested` states cannot be used as uncaveated facts.
- `stale` states require refresh or exclusion.
- `verifying` states require pending/caveat language.
- `resolved` states can be used with provenance.

**Step 2: Implement pure guard helper**

Implement `SynthesisGuard.build_constraints(frame, review_result)` returning prompt constraints and state usage records.

**Step 3: Wire into `BrainHarness.synthesize()`**

Append guard constraints to the synthesis user message. Record `state.used_by_synthesis` events from `LoomCoreAgent` after synthesis when possible.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_synthesis_guard
```

Expected: tests pass.

### Task 10: Add Workspace and Interaction APIs

**Files:**

- Modify: `loom/brain.py`
- Test: `tests/test_brain_workspace_api.py`

**Step 1: Write failing tests**

Use FastAPI test client if already available in the repo. Otherwise test endpoint helper functions directly.

Cover:

- `GET /episodes/{episode_id}/workspace` returns `orchestration`, `states`, `bottlenecks`, `visual_queries`, and `diagnostics`.
- `POST /episodes/{episode_id}/visual-interactions` appends trace and returns inferred signals.
- `POST /episodes/{episode_id}/checkpoint-response` appends trace and returns `intent_lens`.

**Step 2: Implement endpoint helpers first**

Keep endpoint code thin:

- load flywheel detail;
- derive or read workspace fields;
- append interaction;
- return JSON.

**Step 3: Integrate with `ContextualIntentCompiler`**

For checkpoint responses with a concrete `anchor_id`/`object_ref`, reuse the same scoped feedback interpretation path as `/feedback`.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_workspace_api
```

Expected: tests pass.

### Task 11: Build Minimal Webview State Canvas

**Files:**

- Create: `bridge/webview/live-state-canvas.js`
- Create: `bridge/webview/live-state-canvas.test.cjs`
- Modify: `mcp/server.cjs`
- Modify: `bridge/webview/index.html` if scripts are directly listed there

**Step 1: Write failing tests**

Follow the style of `bridge/webview/hand-feedback-widget.test.cjs`.

Assert source contains:

- `/episodes/`
- `/workspace`
- `data-state-id`
- `data-bottleneck-id`
- `VisualInteraction`

**Step 2: Implement self-mounting script**

Mount on:

```html
<section data-anc="live-state-canvas" data-episode-id="..."></section>
```

Render:

- state summary;
- status;
- evidence count;
- linked gaps;
- linked bottlenecks;
- expand provenance button.

**Step 3: Register script in served page**

Use the same inclusion path as `hand-feedback-widget.js` and `orchestration-view.js`.

**Step 4: Run tests**

Run:

```powershell
node bridge/webview/live-state-canvas.test.cjs
```

Expected: tests pass.

### Task 12: Build Minimal Checkpoint Review Deck

**Files:**

- Create: `bridge/webview/checkpoint-review-deck.js`
- Create: `bridge/webview/checkpoint-review-deck.test.cjs`
- Modify: `mcp/server.cjs`

**Step 1: Write failing tests**

Assert source contains:

- `/checkpoint-response`
- `trust`
- `contest`
- `expand`
- `skip`
- `consumed_by`

**Step 2: Implement deck**

Mount on:

```html
<section data-anc="checkpoint-review-deck" data-episode-id="..."></section>
```

Behavior:

- fetch workspace;
- render only `visual_queries`;
- post selected action;
- show returned `intent_lens.summary`;
- remove or collapse answered query.

**Step 3: Keep it low interruption**

No modal in MVP. Render as a compact deck near orchestration or synthesis.

**Step 4: Run tests**

Run:

```powershell
node bridge/webview/checkpoint-review-deck.test.cjs
```

Expected: tests pass.

### Task 13: Patch Brain Rendering to Include New Surfaces

**Files:**

- Modify: `loom/brain.py`
- Modify: `tests/test_orchestration_snapshot.py` or add `tests/test_brain_rendering.py`

**Step 1: Write failing tests**

Cover:

- analysis result includes sections with `data-anc="live-state-canvas"` and `data-anc="checkpoint-review-deck"` when workspace data exists.
- existing `brain-synthesis`, hand cards, and `orchestration-snapshot` are still rendered.

**Step 2: Add render helpers**

Add helpers:

- `_render_live_state_canvas_placeholder(episode_id)`
- `_render_checkpoint_deck_placeholder(episode_id)`

Patch them through existing `patch_webview()` flow after orchestration snapshot.

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_orchestration_snapshot
```

Expected: tests pass.

### Task 14: Record Interaction Consumption

**Files:**

- Modify: `loom_core/agents/core_agent.py`
- Modify: `loom/brain_harness/base.py`
- Modify: `loom/brain_harness/flywheel.py`
- Test: `tests/test_interaction_consumption.py`

**Step 1: Write failing tests**

Cover:

- A `contest` trace consumed by review records `consumer="BrainHarness.review"`.
- A checkpoint that produces repair records `consumer="review.repair_dispatch"`.
- A synthesis caveat records `consumer="BrainHarness.synthesize"`.

**Step 2: Implement consumption updates**

When review or synthesis uses a visual trace, append:

```json
{
  "interaction_id": "vi_...",
  "consumer": "BrainHarness.review",
  "effect": "created source freshness repair task",
  "episode_id": "..."
}
```

**Step 3: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_interaction_consumption
```

Expected: tests pass.

### Task 15: End-to-End Smoke Test

**Files:**

- Add: `docs/plans/2026-07-01-agent-process-visual-harness-smoke-test.md` only if the manual flow becomes long
- Modify: no production file unless smoke test reveals issues

**Step 1: Start services**

Run:

```powershell
scripts\start-anchor.bat
```

In another shell:

```powershell
cd loom
D:\conda\python.exe -m uvicorn brain:app --host 127.0.0.1 --port 3002
```

**Step 2: Run analysis**

Use:

```text
/brain Analyze NVIDIA investment value across macro, fundamentals, and sentiment
```

Expected:

- Brain synthesis appears.
- Hand cards appear.
- Orchestration snapshot appears.
- Live State Canvas appears.
- Checkpoint Review Deck appears only if bottlenecks are generated.

**Step 3: Submit checkpoint response**

Contest or expand a checkpoint.

Expected:

- `POST /episodes/{episode_id}/checkpoint-response` succeeds.
- Flywheel detail includes `visual_interactions`.
- `consumed_by` is populated after review/repair/synthesis consumes the trace.

**Step 4: Trigger repair path**

Use existing `/feedback/repair` or checkpoint repair if implemented.

Expected:

- Repair task includes state/gap references.
- Updated artifact replaces or annotates the rejected artifact.
- Synthesis caveats unresolved states.

## Test Matrix

Run the focused test set first:

```powershell
D:\conda\python.exe -m unittest `
  tests.test_environment_state `
  tests.test_bottleneck_routing `
  tests.test_visual_interaction `
  tests.test_workflow_episode `
  tests.test_flywheel `
  tests.test_core_agent_task_decomposition `
  tests.test_state_aware_review `
  tests.test_synthesis_guard
```

Run webview tests:

```powershell
node bridge/webview/hand-feedback-widget.test.cjs
node bridge/webview/live-state-canvas.test.cjs
node bridge/webview/checkpoint-review-deck.test.cjs
node bridge/webview/canvas-feedback.test.cjs
```

Run broader regression when the core tasks pass:

```powershell
D:\conda\python.exe -m unittest discover tests
```

## Acceptance Criteria

The implementation is acceptable when:

- State transitions are tied to concrete evidence.
- Selected states influence Brain planning and hand decomposition.
- Review can block or caveat unsafe state usage.
- High-impact gaps can produce targeted repair tasks.
- Visual interactions are optional, low-cost, and reversible.
- Interactions record where they were consumed.
- The harness still runs with no human input.
- Flywheel stores state transitions, bottlenecks, visual queries, traces, and repair outcomes.
- The UI shows current state and checkpoint cards without becoming a full trace dashboard.
- Tests prove the new loop does more than visualize logs.

## Non-Goals for MVP

- Automatic harness self-mutation.
- Model weight training, OPD, OPSD, or in-place TTT.
- Broad gesture vocabulary.
- User-managed agent routing.
- Full execution trace dashboard as the main surface.
- Long mandatory feedback forms.

## Follow-On Phases

Phase 2:

- Add replay evaluation over stored episodes.
- Compare current harness vs candidate policies.
- Track cost, repair count, weak-evidence synthesis rate, and interaction usefulness.

Phase 3:

- Add controlled harness evolution candidates:
  - rubric seed;
  - verifier prompt;
  - repair trigger;
  - state extraction rule;
  - artifact compression policy;
  - visual query policy.

Phase 4:

- Promote candidates only through replay, held-out checks, cost limits, integrity checks, and manual audit.



