# Loom Value-Aware Visual Elicitation Harness Design

Date: 2026-06-28
Status: design proposal
Scope: Loom Brain harness, environment state, visual interaction, human-agent collaboration, review/repair/replay loop

## 1. Executive Summary

Loom should not be positioned as a UI that visualizes generated AI content. The stronger design is:

> Loom turns long-horizon agent execution into a visual, interactive, state-causal work surface. The harness detects epistemic bottlenecks in the agent's work, compiles only high-value bottlenecks into low-cost visual interactions, and routes the resulting signals into planning, hand-agent decomposition, review, repair, synthesis, replay, and future harness improvement.

The central goal is to improve long-horizon agent capability:

- reduce goal drift;
- reduce weak-evidence synthesis;
- reduce irrelevant hand-agent work;
- shorten repair latency;
- reduce prompt/context noise;
- improve cross-episode learning without relying only on human feedback.

Human interaction is not the main supervision source. It is a sparse, high-value signal source. The harness must still work in unsupervised rollout and replay settings.

The key shift is from:

```text
human interaction -> feedback -> better output
```

to:

```text
execution trace -> environment states -> epistemic bottlenecks
-> ask / verify / defer / use
-> state-aware planning, review, repair, synthesis, replay
```

## 2. What This Design Rejects

This design intentionally rejects several weaker versions of the idea.

1. A visual log viewer.
   If Loom only shows agent traces, hand-agent progress, and generated content, it improves observability but does not reliably improve agent capability.

2. A rigid human feedback form.
   Users should not classify every signal as "contest state", "verify claim", or "adjust rubric". Most useful interaction should be low-cost and natural.

3. A dashboard where users manage agents.
   Users should not manually route tasks to hand agents or maintain rubric weights. Brain and the harness should do that.

4. A state lifecycle that is just labels.
   Status values such as `active`, `contested`, or `resolved` are useful only if they change prompt selection, task decomposition, review gates, repair targets, or persistence.

5. Unvalidated self-evolution.
   Harness edits must not be promoted only because one episode looked better. They require replay, held-out checks, cost checks, and integrity checks.

## 3. Core Concepts

### 3.1 Environment State

An `EnvironmentState` is Loom's structured representation of the task world. It is not a UI card and not simply user intent.

Examples:

- "The user is asking for an implementation plan, not code changes."
- "The current synthesis depends on claim C7, but C7 has only one weak source."
- "The task is blocked because the repo has no reliable test fixture for this behavior."
- "The user's true priority appears to be delivery speed rather than cost reduction."

Environment states are maintained by both agents and humans, but no single human gesture should directly mutate them. Human interaction adds evidence. Brain/review decide state transitions.

### 3.2 Epistemic Bottleneck

An `EpistemicBottleneck` is a state, claim, gap, or decision whose uncertainty may materially affect downstream work.

The bottleneck is the real unit of human-agent collaboration:

```text
What does the agent not know?
Does it matter?
Can the agent verify it alone?
Can the human answer it cheaply?
What is the cost of being wrong?
```

This is the main novelty over a plain state graph. The graph is useful only because it lets Loom detect and act on bottlenecks.

### 3.3 Visual Query

A `VisualQuery` is a low-cost interaction generated from an epistemic bottleneck.

Examples:

- Show two competing goal interpretations and let the user swipe toward the closer one.
- Show a claim with its evidence chain and let the user expand, accept provisionally, or mark it as untrusted.
- Show a high-impact gap and let the user pin it or mute it.
- Show a dense state card and let the user swipe right for more evidence or left for compression.

The user is not "labeling data". The system is asking the smallest possible question at the point where human judgment is likely to reduce downstream cost.

### 3.4 Ask / Verify / Defer / Use

For each bottleneck, Brain chooses one action:

| Action | When to use | Effect |
|---|---|---|
| `ask` | high impact, human can answer cheaply, interaction cost is low | create a visual query or checkpoint card |
| `verify` | high impact, agent can validate with tools or hand agents | create a targeted verification hand task |
| `defer` | low impact, high uncertainty, or too expensive to resolve now | keep out of prompt or include as caveat only |
| `use` | high confidence or low risk | include in state frame, hand context, or synthesis |

This strategy is more important than the state lifecycle itself. Lifecycle states are an implementation detail supporting this routing.

## 4. Environment State Types

Version 1 should support only practical, task-relevant state types.

| Type | Meaning | Example | Main producer |
|---|---|---|---|
| `goal_frame` | user goal, success criteria, exclusions | "Design the harness, do not implement yet." | request parser, Brain, human correction |
| `constraint` | limits on solution space | "Do not require heavy user text input." | user request, visual interaction, Brain |
| `assumption` | belief currently used but not fully verified | "The user prefers lower information density." | Brain, hand artifact, prior episodes |
| `claim` | intermediate judgment from Brain or hand agent | "The weak evidence is from an outdated source." | hand agents, review, synthesis |
| `gap` | missing information or unresolved contradiction | "No verifier exists for this rubric." | review, hand artifacts, failed synthesis |
| `risk` | possible source of failure or reward hacking | "Self-evolution may overfit a single episode." | review, replay, integrity checker |
| `resource_context` | availability/freshness of tools, files, sources | "Network access unavailable." | tool/runtime events |

`AgentRuntimeState` is separate. A hand agent being `running`, `failed`, or `blocked` is runtime state, not environment state. It can produce environment states such as a `gap` or `risk`.

## 5. State Lifecycle

The lifecycle must correspond to real Loom stages and event evidence.

| Status | Meaning | Typical stage | Enters when | Leaves when | Harness effect |
|---|---|---|---|---|---|
| `proposed` | plausible but not yet relied on | Planning, Dispatching | request parsing, last synthesis, historical flywheel, first hand claim | selected into active frame, contradicted, or ignored | can seed a task or visual query, but cannot be treated as fact |
| `active` | currently relied on by Brain or hand agents | Planning, Dispatching, Synthesis | Brain includes it in `EnvironmentStateFrame`; enough evidence; resolved prior still fresh | contested, stale, resolved, or retired | included in prompts, rubrics, task context, synthesis |
| `contested` | disputed or unsafe to use as fact | Review, Interaction | human distrust signal; hand disagreement; verifier failure; review follow-up; schema/quality issue | verification passes, repair resolves it, or it is retired | blocked from uncaveated synthesis; prioritized for repair/verification |
| `verifying` | actively being checked | Dispatching, Repairing | targeted hand task or repair task is created | artifact arrives, verifier passes/fails, budget exceeded | shown as pending; can be used only with caveat |
| `stale` | may be outdated or context-inappropriate | Planning, Review | old source, goal drift, new contradicting evidence, age threshold, repeated non-use | refreshed, retired, or reactivated | excluded or downweighted unless refreshed |
| `resolved` | sufficiently handled for this episode | Review, Synthesis, Persist | verifier passes; repair succeeds; Brain explicitly adopts/rejects with evidence | later contradicted, stale, or superseded | eligible for flywheel and future state priors |
| `retired` | no longer relevant | Persist, future Planning | superseded, scope changed, repeatedly muted/unused, explicit human correction | manually restored or rediscovered | not included in default state frame, provenance kept |

Important constraints:

- `resolved` means "sufficient for this task", not globally true.
- `retired` means "not active by default", not deleted.
- Human gestures never directly force a status transition. They add evidence.
- The same source material can produce multiple states with different lifecycle statuses.

## 6. Lifecycle Transition Evidence

Every state transition must record evidence. This avoids fake precision.

Required transition record:

```json
{
  "state_id": "S12",
  "from": "active",
  "to": "contested",
  "episode_id": "ep_...",
  "phase": "review",
  "evidence": [
    {
      "type": "visual_interaction",
      "id": "vi_...",
      "summary": "user swiped left on claim card"
    },
    {
      "type": "review_gap",
      "id": "gap_...",
      "summary": "review found weak evidence"
    }
  ],
  "decided_by": "brain_review",
  "confidence": 0.71
}
```

Typical evidence sources:

- `phase.start` / `phase.end`
- `dispatch.sent`
- `dispatch.artifact`
- `dispatch.error`
- `dispatch.schema_violation`
- `review.follow_up_task`
- `review.repair_dispatch`
- `review.repair_budget_exceeded`
- `synthesis.used_state`
- `visual.interaction`
- `flywheel.recurrent_failure`
- `replay.regression`
- verifier pass/fail events

## 7. Harness Modules

### 7.1 EnvironmentStateManager

Responsibilities:

- extract state candidates from request, `Projection`, last synthesis, hand artifacts, review results, visual traces, and flywheel;
- maintain lifecycle, salience, freshness, evidence refs, and provenance;
- generate an `EnvironmentStateFrame` for the current episode;
- enforce prompt budget by selecting only relevant states.

Inputs:

- user question and context;
- existing `Projection` sections;
- prior goal context and last synthesis;
- hand artifacts with `metadata.key_claims`, `metadata.gaps`, evidence, resources;
- review result and repair history;
- visual interaction traces.

Outputs:

- `EnvironmentStateFrame`;
- state transition events;
- candidate bottlenecks.

Selection policy:

```text
include states with high impact and sufficient freshness;
include contested states only as caveats or repair targets;
exclude stale states unless the current task is to refresh them;
include high-impact gaps as task candidates, not as facts.
```

### 7.2 EpistemicBottleneckDetector

Responsibilities:

- score which states/claims/gaps matter for downstream quality;
- decide whether uncertainty should be handled by human, agent verification, deferral, or direct use;
- prevent unnecessary user prompts.

Core dimensions:

| Dimension | Meaning |
|---|---|
| `uncertainty` | how unclear or under-supported the item is |
| `impact` | expected downstream damage if wrong |
| `human_answerability` | whether a human can answer cheaply |
| `agent_verifiability` | whether tools/hand agents can verify it |
| `interaction_cost` | expected human cost |
| `repair_cost_if_wrong` | cost of discovering the issue late |
| `time_sensitivity` | whether it may go stale soon |

Routing:

```text
if impact high and human_answerability high and interaction_cost low:
    ask
elif impact high and agent_verifiability high:
    verify
elif impact low or cost too high:
    defer
else:
    use with caveat
```

### 7.3 VisualQueryCompiler

Responsibilities:

- turn selected bottlenecks into minimal visual interactions;
- choose the right presentation density;
- make interaction reversible and low cost;
- avoid interrupting users unless the expected value is high.

Query types:

| Query | Example | User action | Harness signal |
|---|---|---|---|
| goal fork | "Is this about cost reduction or delivery speed?" | swipe/select closer card | goal frame calibration |
| evidence trust | show claim with evidence chain | expand, left/right swipe | trust/evidence need |
| gap salience | "Should we verify migration cost now?" | pin/mute | gap priority |
| density preference | same state at low/medium/high detail | left/right swipe | artifact compression policy |
| drift checkpoint | timeline shows goal changed | accept/contest | goal drift evidence |

The compiler must avoid asking users to do agent work. It should ask only questions humans can answer faster than agents can verify.

### 7.4 VisualInteractionInterpreter

Responsibilities:

- record raw interaction traces;
- infer weak signals with confidence;
- avoid deterministic over-interpretation;
- expose signals to review, repair, synthesis, and visual policy.

Data shape:

```json
{
  "interaction_id": "vi_...",
  "episode_id": "ep_...",
  "anchor_type": "state",
  "anchor_id": "S12",
  "gesture": "swipe_right",
  "visual_dimension": "information_density",
  "visible_variant": "medium",
  "visible_context": {
    "phase": "review",
    "related_claims": ["C7"],
    "related_gaps": ["G3"]
  },
  "inferred_signals": [
    {
      "type": "evidence_need",
      "confidence": 0.62
    }
  ],
  "consumed_by": []
}
```

`consumed_by` is required for product accountability. Unused traces should not be treated as proof of improvement.

### 7.5 RubricComposer

Responsibilities:

- maintain a small base rubric set;
- derive targeted rubric dimensions only from concrete state/gap/failure evidence;
- prevent rubric explosion.

Base rubrics:

- task completion;
- evidence sufficiency;
- constraint satisfaction;
- risk coverage;
- output usability.

Derived rubrics:

| Source | Rubric example |
|---|---|
| contested state | disambiguate conflicting assumptions |
| stale state | verify freshness before use |
| high-impact gap | close or caveat the gap |
| recurrent failure | prevent repeated failure class |
| evidence expansion signals | preserve provenance in synthesis |

Each derived rubric must have:

- source state/gap/failure id;
- expected failure prevented;
- expiry or review condition.

### 7.6 StateAwareTaskDecomposer

This extends existing `TaskDecomposer` and `AtomicTask`; it should not create a second orchestration system.

Add fields to `AtomicTask`:

```json
{
  "state_slice": ["S12", "S19"],
  "target_state_ids": ["S12"],
  "target_gap_ids": ["G4"],
  "rubric_ids": ["R_evidence_sufficiency"],
  "state_intent": "verify",
  "evidence_requirements": [
    "cite source freshness",
    "separate user pain from management KPI"
  ]
}
```

`state_intent` values:

| Value | Meaning |
|---|---|
| `use` | rely on active states to do downstream work |
| `establish` | create a new state from exploration |
| `verify` | test a proposed or contested state |
| `refresh` | update stale state with fresh evidence |
| `resolve` | close a high-impact gap or conflict |

Two task modes are required:

- state-bound task: verifies, refreshes, uses, or resolves known states;
- exploratory task: searches for unknown gaps or states when the current frame is insufficient.

This prevents over-constraining hand agents to only validate existing assumptions.

### 7.7 ReviewRepairEngine

Responsibilities:

- inspect whether synthesis would rely on weak, contested, or stale states;
- inspect whether high-impact gaps remain unresolved;
- convert issues into targeted follow-up tasks;
- update state lifecycle after repair results.

Review checks:

```text
active state without enough evidence -> verify or caveat
contested state used as fact -> repair required
stale state used without refresh -> refresh required
high-impact gap unresolved -> repair or explicit deferral
hand artifact with schema/quality issue -> artifact risk
```

Repair task shape:

```json
{
  "repair_task_id": "repair_G4_1",
  "target_state_ids": ["S12"],
  "target_gap_ids": ["G4"],
  "repair_reason": "synthesis depends on contested pain-point state",
  "expected_resolution": "separate end-user pain from management KPI",
  "evidence_requirements": ["use at least two source fragments or mark unresolved"]
}
```

### 7.8 SynthesisGuard

Responsibilities:

- prevent unsafe state usage in final synthesis;
- require caveats where states remain unresolved;
- preserve provenance when user or review signals indicate trust bottlenecks.

Rules:

- `active` states may be used directly.
- `proposed` states may be used only as hypotheses.
- `contested` states require caveat or repair before use.
- `verifying` states require pending/caveat language.
- `stale` states require refresh or exclusion.
- `resolved` states may be used with provenance.
- `retired` states should not appear unless explaining why excluded.

### 7.9 HarnessExperienceGraph

Responsibilities:

- connect state, claim, evidence, gap, rubric, hand task, decision, interaction, repair, and outcome;
- support failure attribution and replay;
- support developer audit.

Important edges:

```text
claim supports state
evidence supports claim
gap blocks state
state drives hand task
rubric evaluates state
hand task resolves gap
interaction calibrates bottleneck
repair changes state status
synthesis uses state
outcome validates or contradicts state
```

This graph is not a product surface by default. The UI renders selected parts of it.

### 7.10 SelfEvolutionManager

Version 1 should not automatically mutate production harness behavior. It should propose candidates and evaluate them.

Candidate edits:

- new rubric seed;
- verifier prompt;
- hand template adjustment;
- repair trigger;
- state extraction rule;
- artifact compression policy;
- visual query policy.

Promotion gates:

- replay set improves or stays neutral;
- held-out set does not regress;
- cost increase is within budget;
- integrity checker passes;
- developer can audit source episodes and evidence.

## 8. Human-Agent Collaboration Model

### 8.1 Human Role

Humans should provide information that agents cannot cheaply infer:

- goal interpretation;
- hidden priorities;
- tacit constraints;
- trust thresholds;
- domain plausibility;
- salience judgments;
- whether a direction is obviously wrong.

Humans should not:

- manually route hand agents;
- maintain rubric weights;
- inspect full traces;
- classify every state transition;
- write detailed feedback unless they choose to.

### 8.2 Brain Role

Brain is responsible for:

- selecting relevant environment states;
- detecting epistemic bottlenecks;
- deciding ask/verify/defer/use;
- composing rubrics;
- decomposing tasks;
- reviewing and repairing;
- explaining how human signals were consumed.

### 8.3 Hand-Agent Role

Hand agents are responsible for:

- executing scoped tasks;
- producing claims, evidence, gaps, and failure reasons;
- verifying or refreshing states;
- proposing state updates, not writing long-term memory directly.

### 8.4 Harness Role

The harness is responsible for:

- state lifecycle governance;
- review gates;
- replay and regression checks;
- interaction budget;
- auditability and provenance;
- preventing self-evolution from overfitting.

## 9. Visual Interaction Design

### 9.1 Product Surface

The main product surface is:

```text
Live State Canvas + Checkpoint Review Deck
```

Live State Canvas:

- shows only high-value current states, claims, gaps, evidence chains, and pending repairs;
- does not show the full trace by default;
- supports semantic zoom and provenance expansion.

Checkpoint Review Deck:

- appears only when a bottleneck has high expected value for human input;
- contains a small number of cards;
- each card has a clear local purpose.

### 9.2 Minimal Interactions

| Interaction | Natural meaning | Possible harness signal |
|---|---|---|
| left swipe | reduce, reject, distrust, or not relevant depending on card | compression, contest, low salience |
| right swipe | expand, accept provisionally, or keep depending on card | evidence need, provisional trust, salience |
| click evidence | inspect provenance | trust bottleneck |
| pin | follow this item | salience increase |
| mute | show less of this | salience decrease, possible future retirement |
| dwell | implicit interest | weak salience |
| skip | low current value | weak downranking |
| long press text/voice | optional correction | high-value correction candidate |

The same gesture is not globally fixed. Meaning comes from card type and visible context.

### 9.3 Information Density Example

Low density:

```text
S12: Users care about reducing coordination time.
```

Medium density:

```text
S12: Users care about reducing coordination time, not direct cost reduction.
Evidence: 3 interview fragments.
Risk: conflicts with S04 "cost reduction is primary".
```

High density:

```text
State: Users care about reducing coordination time.
Evidence:
- interview-note-03: repeated cross-team coordination pain
- market-hand claim C7: cost is a management KPI, not end-user pain
Linked rubrics:
- pain intensity
- migration friction
Used by:
- product strategy hand task
- synthesis section 2
Conflict:
- S04: cost reduction is primary
```

User right-swipes from medium to high density.

Recorded signal:

```json
{
  "anchor_type": "state",
  "anchor_id": "S12",
  "gesture": "swipe_right",
  "visual_dimension": "information_density",
  "inferred_signals": [
    {"type": "evidence_need", "confidence": 0.62}
  ]
}
```

Possible downstream use:

- synthesis preserves provenance for S12;
- review raises evidence sufficiency for similar states;
- future cards for similar state types default to medium/high density.

### 9.4 Interaction Budget

Loom should ask for human input only when:

```text
expected downstream value > expected user cost
```

Inputs:

- bottleneck impact;
- uncertainty;
- human answerability;
- agent verifiability;
- repair cost if wrong;
- recent interruption count;
- task urgency.

The default should be no interruption. User interaction should feel like occasional high-leverage calibration, not monitoring.

## 10. Data Contracts

### 10.1 EnvironmentState

```json
{
  "state_id": "S12",
  "episode_id": "ep_...",
  "type": "assumption",
  "status": "active",
  "summary": "Users care about reducing coordination time.",
  "scope": "current_goal",
  "salience": 0.82,
  "freshness": 0.77,
  "confidence": 0.69,
  "evidence_refs": ["E3", "C7"],
  "conflicts_with": ["S04"],
  "created_by": "brain",
  "updated_by": "brain_review",
  "created_at": "2026-06-28T...",
  "updated_at": "2026-06-28T..."
}
```

### 10.2 EpistemicBottleneck

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
  "rationale": "High-impact goal interpretation can be calibrated cheaply."
}
```

### 10.3 VisualQuery

```json
{
  "query_id": "vq_...",
  "episode_id": "ep_...",
  "bottleneck_id": "B9",
  "query_type": "goal_fork",
  "cards": [
    {
      "card_id": "A",
      "label": "Reduce cost",
      "state_ids": ["S04"]
    },
    {
      "card_id": "B",
      "label": "Reduce coordination time",
      "state_ids": ["S12"]
    }
  ],
  "allowed_interactions": ["swipe_left", "swipe_right", "skip"],
  "expires_after_phase": "review"
}
```

### 10.4 VisualInteractionTrace

```json
{
  "interaction_id": "vi_...",
  "query_id": "vq_...",
  "episode_id": "ep_...",
  "anchor_type": "state",
  "anchor_id": "S12",
  "gesture": "swipe_right",
  "visual_context": {
    "phase": "review",
    "density": "medium",
    "shown_evidence_refs": ["E3", "C7"]
  },
  "inferred_signals": [
    {"type": "goal_preference", "target": "S12", "confidence": 0.7}
  ],
  "consumed_by": [
    {
      "consumer": "BrainHarness.review",
      "effect": "prioritized pain-point verification"
    }
  ]
}
```

### 10.5 AtomicTask Extensions

```json
{
  "task_id": "t_verify_pain_point",
  "hand_id": "runtime-pain-point-verifier",
  "executor_id": "brain-inline",
  "dimension": "pain point verification",
  "task": "Verify whether the user's primary concern is coordination time or cost reduction.",
  "state_slice": ["S04", "S12"],
  "target_state_ids": ["S12"],
  "target_gap_ids": ["G2"],
  "rubric_ids": ["R_evidence_sufficiency", "R_goal_disambiguation"],
  "state_intent": "verify",
  "evidence_requirements": [
    "separate end-user pain from management KPI",
    "cite at least two evidence fragments or mark unresolved"
  ],
  "priority": 10,
  "depends_on": []
}
```

## 11. Current Loom Architecture Changes

### 11.1 `WorkflowEpisode`

Current role:

- append-only event log for one `/analyze` call;
- tracks Planning, Dispatching, Reviewing, Repairing, Synthesizing, Persisted, Failed.

Changes:

- add event families:
  - `state.proposed`
  - `state.transition`
  - `claim.created`
  - `gap.detected`
  - `bottleneck.detected`
  - `visual.query_created`
  - `visual.interaction`
  - `state.used_by_synthesis`
  - `harness.edit.proposed`
  - `harness.edit.evaluated`
- keep the append-only design;
- derive workspace views from events, not from mutable UI state.

### 11.2 `Projection`

Current role:

- builds shared state selected for Brain `plan()` and `decompose()`.

Changes:

- add `environment_state_frame` section;
- include selected state ids, statuses, evidence summaries, and excluded stale/retired states;
- keep content-addressing so plan and decompose use the same state view.

### 11.3 `IntentWiki`

Current role:

- long-lived user intent and preference memory.

Changes:

- keep intent memory separate from environment state;
- intent can influence bottleneck routing and visual preference, but should not be mixed with task-world state;
- examples:
  - intent: user prefers concise review;
  - environment state: current claim lacks evidence.

### 11.4 `RewardedIntentHarness`

Current role:

- generates intent-derived policies/rubrics and reward reports.

Changes:

- evolve into two responsibilities:
  - `RubricComposer`: base, state-induced, failure-induced, risk-induced, and intent-derived rubric composition;
  - `HarnessEvaluator`: evaluates whether outputs respected state/rubric constraints.
- keep legacy intent rubric as one input, not the whole harness.

### 11.5 `TaskDecomposer` and `HandPlan`

Current role:

- Brain dynamically creates `AtomicTask` objects with task, dimension, rubrics, priority, dependencies, hand id, system prompt, capabilities.

Changes:

- extend `AtomicTask` with state/gap/rubric references;
- support `state_intent`;
- allow exploratory tasks when the state frame is incomplete;
- include bottleneck information in the decomposition prompt.

### 11.6 `BrainHarness.review`

Current role:

- reviews hand artifacts and may create follow-up tasks.

Changes:

- become state-aware review:
  - inspect state status;
  - detect weak evidence;
  - block unsafe synthesis use;
  - generate targeted verification/repair tasks;
  - record state lifecycle transitions.

### 11.7 `BrainHarness.synthesize`

Current role:

- combines hand artifacts and workflow decision into synthesis.

Changes:

- consume state frame and review result;
- apply `SynthesisGuard`;
- preserve provenance when there is a trust bottleneck;
- caveat unresolved states instead of flattening them into confident claims.

### 11.8 `FlywheelRecord`

Current role:

- stores per-episode self-eval, hand evals, artifacts, intent activation, reward report.

Changes:

- add:
  - state transition summaries;
  - bottleneck summaries;
  - visual interaction traces;
  - repair outcomes;
  - replay evaluation;
  - candidate harness edits and promotion status.

### 11.9 Web UI

Current role:

- final content rendering, intelligence ledger, timelines, dashboards.

Changes:

- add an episode workspace:
  - Live State Canvas;
  - Checkpoint Review Deck;
  - evidence chain expansion;
  - minimal interaction capture;
  - developer audit view for harness edits.
- avoid making the full agent dashboard the primary user surface.

### 11.10 APIs

Add:

```text
GET  /episodes/{episode_id}/workspace
GET  /episodes/{episode_id}/experience-graph
POST /episodes/{episode_id}/visual-interactions
POST /episodes/{episode_id}/checkpoint-response
GET  /harness/evolution/candidates
```

Reuse existing websocket/event stream for live updates.

## 12. Execution Flow

### 12.1 Normal Episode

```text
1. request arrives
2. Projection builds base context
3. EnvironmentStateManager extracts candidate states
4. BottleneckDetector scores uncertainty/impact/routing
5. Brain plans with EnvironmentStateFrame
6. TaskDecomposer creates state-aware hand tasks
7. hand agents produce claims/evidence/gaps
8. ReviewRepairEngine updates lifecycle and repair needs
9. VisualQueryCompiler asks only high-value human questions
10. Brain consumes visual traces if available
11. repair tasks run if needed
12. SynthesisGuard composes final synthesis
13. Flywheel records state transitions, interactions, outcomes
```

### 12.2 No Human Interaction

The harness still works:

```text
trace -> state extraction -> bottleneck routing
-> agent verification/defer/use
-> review/repair/synthesis
-> flywheel/replay
```

Human signals improve calibration but are not required.

### 12.3 Human Micro-Interaction

Example:

```text
User swipes left on claim:
"The user mainly wants cost reduction."
```

Flow:

```text
visual.interaction recorded
-> interpreter infers weak contest signal
-> review checks evidence for the claim
-> if weak, related state becomes contested
-> repair task verifies pain-point framing
-> synthesis avoids using the claim as fact
-> flywheel records whether this prevented rework
```

## 13. Evaluation Plan

### 13.1 Core Capability Metrics

Primary metrics:

- task success rate;
- repair/rework cost;
- held-out replay non-regression.

Secondary metrics:

- goal drift detection time;
- weak-evidence claims reaching synthesis;
- unresolved high-impact gaps at synthesis;
- number of irrelevant hand tasks;
- token/tool/latency cost;
- user text input volume;
- useful interaction consumption rate.

### 13.2 Interaction Metrics

Measure whether interaction improves productivity:

- percentage of visual interactions consumed by review/repair/replanning/synthesis;
- average interaction cost per useful correction;
- interruption count per episode;
- checkpoint acceptance/skipping rate;
- density preference stability across episodes.

### 13.3 Replay Metrics

For candidate harness edits:

- current harness vs candidate harness on replay set;
- held-out episode quality;
- cost delta;
- repair count delta;
- integrity/risk check result;
- regression by domain/task type.

## 14. Implementation Phases

### Phase 1: Minimal State-Aware Review Loop

Build only what proves capability improvement:

- extract claims/gaps/evidence from hand artifacts;
- create minimal environment state frame;
- make review state-aware;
- block contested/stale/weak-evidence states from uncaveated synthesis;
- create targeted repair tasks for high-impact gaps.

Success criterion:

```text
review/repair becomes more targeted and reduces weak-evidence synthesis.
```

### Phase 2: State-Aware Task Decomposition

- extend `AtomicTask`;
- include state/gap/rubric references in decomposition;
- add verification/refresh/resolve task intents;
- support exploratory tasks for unknown states.

Success criterion:

```text
fewer irrelevant hand tasks and higher gap closure rate.
```

### Phase 3: Visual Query and Checkpoint Deck

- implement bottleneck detector;
- compile only high-value bottlenecks into visual cards;
- record `VisualInteractionTrace`;
- wire `consumed_by` into review/repair/synthesis.

Success criterion:

```text
low user input cost with measurable reduction in goal drift or repair latency.
```

### Phase 4: Experience Graph and Replay

- build graph summaries from episode events;
- add replay evaluation harness;
- produce candidate harness edits;
- keep promotion manual or gated.

Success criterion:

```text
candidate edits can be evaluated without relying on single-episode anecdotes.
```

### Phase 5: Controlled Self-Evolution

- add shadow evaluation;
- add integrity checks;
- add versioned harness policies;
- promote only validated edits.

Success criterion:

```text
harness improves on replay/held-out sets without cost or integrity regression.
```

## 15. Risks and Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| state graph becomes structured logging | no capability improvement | require every state signal to affect plan/review/repair/synthesis or remain diagnostic |
| lifecycle fake precision | unreliable labels create bad control signals | require transition evidence and reversible status changes |
| weak gestures misinterpreted | user intent may be ambiguous | keep signals weak, confidence-scored, and never directly mutating |
| rubric explosion | prompt noise and slower agents | base rubric plus derived rubrics with source ids and expiry |
| over-constrained hand agents | less exploration | support exploratory tasks alongside state-bound tasks |
| user burden | visual surface becomes monitoring work | use interaction budget and checkpoint only high-value bottlenecks |
| self-evolution overfits | harness gets worse while scores look better | replay, held-out, cost, integrity, versioning, rollback |
| UI novelty without productivity | attractive but not useful | track `consumed_by` and downstream effect |

## 16. Research Novelty

The novelty should not be claimed as "state graph" or "interactive agent UI". Those are likely insufficient.

The stronger novelty is:

> Value-aware visual elicitation for long-horizon human-agent collaboration.

Core claim:

```text
Long-horizon agents fail because important uncertainty is discovered too late.
Loom detects epistemic bottlenecks during execution, decides whether each should
be asked of humans, verified by agents, deferred, or used, and compiles only
high-value human-addressable bottlenecks into low-cost visual interactions.
```

This highlights Loom's natural strengths:

- AI information visualization;
- real-time interaction;
- low-cost human calibration;
- agent-side verification and repair;
- replay-based harness improvement.

The research contribution is not that humans can provide feedback. It is the routing and compilation mechanism:

```text
bottleneck detection -> ask/verify/defer/use -> visual query -> state delta propagation
```

## 17. Acceptance Criteria

The design is considered implemented only when:

- state transitions are tied to concrete evidence;
- selected states influence Brain planning and hand decomposition;
- review can block or caveat unsafe state usage;
- high-impact gaps can produce targeted repair tasks;
- visual interactions are optional, low-cost, and reversible;
- consumed interactions show where they affected the harness;
- no human interaction is required for the harness to run;
- candidate harness edits are evaluated before promotion;
- productivity metrics show improvement beyond nicer visualization.

## 18. Minimal Version to Build First

The smallest useful version is:

```text
EnvironmentStateFrame
+ state-aware review gate
+ targeted repair task generation
+ minimal visual checkpoint for high-impact bottlenecks
+ flywheel recording of state transitions and repair outcomes
```

Do not start with full self-evolution, full dashboard, or broad visual interaction vocabulary. Prove the core claim first:

```text
Detecting and resolving epistemic bottlenecks earlier improves long-horizon agent performance.
```
