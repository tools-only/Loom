# Loom Core / Loom Fin Architecture Design

## Goal

Restructure Loom from a mixed prototype into two clear layers:

- **Loom Core**: a local-first human-agent interaction and harness framework.
- **Loom Fin**: a finance domain pack for market judgment, thesis tracking, and personal position management.

The first implementation target is a **local desktop single-user product**. The architecture should not introduce cloud collaboration, multi-tenant auth, remote sync, or distributed infrastructure in this phase.

The core code framework is **Python-first**. JavaScript should be used only where it is the right boundary technology: Electron, browser/webview interaction, static asset serving, and local HTTP/WebSocket gateway compatibility.

## Non-Goal

This redesign must not break the basic interaction capability that already works today.

It must also preserve the existing CSS templates, UI design language, color system, and concrete product functions. Architecture cleanup is only successful if the current user-facing experience continues to feel and behave like the current Loom.

The migration is not a big-bang rewrite. Existing webview rendering, anchor operations, patching, workspace interaction, and agent feedback loops must remain runnable while the boundaries are being separated.

## Current Problem

The current repository mixes several different responsibilities:

- Core interaction runtime: webview, workspace, anchor operations, patching, WebSocket updates.
- Agent runtime: in-process LLM loop, Claude/Codex-style agent execution, MCP bridge behavior.
- Finance domain logic: market, target, sentiment, position flows.
- Finance data layer: SEC, FRED, Yahoo, Reuters, CNBC, Reddit, StockTwits, COT, AAII, NAAIM, and other connectors.
- UI kits, generated artifacts, domain pages, resource previews, historical branches, and local runtime logs.

This makes the name "Loom" ambiguous. The current `loom/` directory is mostly a finance-specific Brain/Hands prototype and should be treated as **Loom Fin**, not Loom Core.

## Core Definition

Loom Core is an interface and harness framework for human-agent collaboration.

For humans, it provides:

- A directly rendered interactive workspace produced by agent artifacts.
- Fast operations on generated content: ask, refine, expand, annotate, branch, edit, review.
- Visible context, history, feedback, and workspace state.

For agents, it provides:

- Structured human intent, selection, annotation, and feedback events.
- Workspace context and relevant rendered artifacts.
- Harness signals from user behavior and explicit feedback.
- A stable artifact protocol for returning patches, blocks, claims, evidence, and follow-up questions.

Core is not a finance analyst, not a market data collector, and not a direct LLM API wrapper.

## Recommended Architecture

Use a **Local-first Modular Monolith + Domain Pack** architecture.

This keeps development fast inside one repository while drawing real module boundaries.

```text
apps/
  desktop/
    Electron shell and local launcher
  webview/
    browser-side interactive workspace UI

services/
  web-gateway/
    JavaScript HTTP/WebSocket gateway for Electron/webview compatibility

loom_core/
  runtime/
    Python local daemon, orchestration, process manager
  workspace/
    files, rendered artifacts, history, anchor index
  interaction_protocol/
    human intent envelope, selection snapshot, op schema, feedback schema
  render_protocol/
    HTML/block/patch contracts for agent-rendered workspaces
  harness/
    event log, replay, feedback compiler, eval ledger, claim/evidence primitives
  agent_adapters/
    adapters for cc, codex, openclaw, herms, opencode, and local command workers
  domain_sdk/
    APIs for registering domain routes, panels, agents, resources, and policies
  storage/
    SQLite/JSONL local persistence

domains/
  loom-fin/
    manifest.json
    agents/
    connectors/
    resources/
    policies/
    ui/
    harness/
    prompts-or-skills/
```

## Runtime Shape

The first version remains local and single-user:

```text
Electron Desktop App
  -> JavaScript webview gateway
  -> Python Loom Core daemon
  -> Local workspace/event stores
  -> Python agent adapter process manager
  -> External agent CLI workers
  -> Agent artifacts
  -> Render/patch stream
  -> Interactive webview
```

No remote service is required.

## Boundary: Loom Core

Loom Core owns:

- Python local daemon lifecycle.
- WebSocket patch/event stream.
- Workspace files, rendered artifacts, anchor history, and current document state.
- Human intent capture: operations, selections, annotations, feedback, review requests.
- Generic context manifest: memories, skills, resources, subagents, domain capabilities.
- Agent task envelope creation.
- Agent adapter invocation and cancellation.
- Generic event log and replay model.
- Generic claim/evidence/feedback data model.
- Generic harness signals and feedback compiler.

The JavaScript gateway may forward HTTP/WebSocket traffic, serve the webview, and preserve legacy `/op`, `/patch`, `/html`, workspace, and domain routes during migration. New core behavior should be implemented in Python unless it is browser/Electron/gateway-specific.

Loom Core must not own:

- Finance-specific connector logic.
- Market, ticker, thesis, sentiment, or position analysis.
- Finance-specific safety policy.
- SEC/FRED/Yahoo/Reuters/Reddit/etc. source definitions.
- Direct dependence on a single LLM API provider.
- Hardcoded domain routes such as `market`, `target`, `sentiment`, `position`, or `trading.private`.

## Boundary: Loom Fin

Loom Fin is a domain pack loaded by Loom Core.

Loom Fin owns:

- Finance domain manifest.
- Market, target, sentiment, position, thesis, and private trading capabilities.
- Finance data connectors.
- Finance source registry and trust tiers.
- Financial source policy and safety boundaries.
- Finance-specific UI panels, tabs, cards, dashboards, and settings.
- Finance-specific harness rules.
- Thesis, position, and source-quality ledgers.
- Agent definitions for market judgment, target tracking, sentiment analysis, position review, and thesis debate.

Loom Fin may use Core services, but Core should not import Fin implementation details.

## Agent Model

Specific scenario agents should be independent and swappable workers, not built-in LLM API calls.

Supported agent families should include:

- Claude Code / cc
- Codex
- OpenClaw
- Herms
- Opencode
- Local command agents
- Future provider-specific wrappers

Core only sees a Python adapter contract:

```python
class AgentAdapter(Protocol):
    id: str
    capabilities: list[str]

    async def invoke(self, task: AgentTaskEnvelope) -> AsyncIterator[AgentEvent]:
        ...

    async def cancel(self, run_id: str) -> None:
        ...
```

The adapter translates Loom's structured task into the target agent's native execution model.

## Core Protocols

### Human Intent

```ts
type HumanIntentEnvelope = {
  eventId: string;
  workspaceId: string;
  fileId?: string;
  targetAnchor?: string;
  op: "ask" | "refine" | "expand" | "shorten" | "edit" | "annotate" | "branch" | "review";
  instruction: string;
  selection?: SelectionSnapshot;
  domain?: string;
  createdAt: string;
};
```

### Agent Task

```ts
type AgentTaskEnvelope = {
  taskId: string;
  domain?: string;
  capability: string;
  intent: HumanIntentEnvelope;
  contextRefs: string[];
  artifactContract: "html_patch" | "workspace_block" | "claim_bundle" | "mixed";
  constraints: {
    preserveAnchors: boolean;
    preserveClasses: boolean;
    requireEvidence?: boolean;
  };
};
```

### Agent Artifact

```ts
type AgentArtifact = {
  taskId: string;
  patches?: WorkspacePatch[];
  blocks?: RenderBlock[];
  claims?: Claim[];
  evidence?: Evidence[];
  feedbackRequests?: FeedbackRequest[];
  metadata: {
    agentId: string;
    adapter: string;
    runId: string;
    confidence?: number;
    sources?: SourceUsage[];
  };
};
```

## Local Storage

Use local files and SQLite-style stores. Do not design for multi-user cloud storage yet.

```text
data/
  workspace.sqlite
    files
    anchors
    artifacts
    claims
    evidence
    feedback

  events.jsonl
    append-only human/agent/harness event stream

  runs/
    agent run transcripts and artifacts

  domains/
    loom-fin/
      thesis.sqlite or thesis.jsonl
      positions.sqlite or positions.jsonl
      source-scores.json
```

JSONL is acceptable for early migration when append-only auditing matters more than query performance. SQLite should be introduced where relationships become important, especially workspace, claim, evidence, and feedback records.

## Domain Pack Manifest

Each domain pack registers itself with Core:

```json
{
  "id": "loom-fin",
  "name": "Loom Fin",
  "version": "0.1.0",
  "routes": ["market", "target", "sentiment", "position", "trading.private"],
  "capabilities": [
    "market.regime.review",
    "ticker.thesis.review",
    "sentiment.scan",
    "position.review",
    "thesis.debate"
  ],
  "agents": "./agents",
  "connectors": "./connectors",
  "resources": "./resources",
  "policies": "./policies",
  "ui": "./ui",
  "harness": "./harness"
}
```

Core reads the manifest and mounts the domain. Domain code can register routes and UI panels through the domain SDK, but Core does not hardcode the domain.

## Migration Strategy

The migration must preserve behavior at every step.

### Phase 1: Name the Existing Finance Layer

Move or alias current finance-specific code under `domains/loom-fin/` while preserving existing imports through compatibility modules.

Candidates:

- `loom/hands/*`
- `loom/harness/*`
- `loom/resource_library.json`
- `loom/hand_registry.py`
- `mcp/connectors/*`
- `trading/*`
- `branches/market`
- `branches/target`
- `branches/sentiment`
- `branches/position`
- `skills/market-news-analysis`
- finance-specific routes and rendering inside `bridge/webview/anchor-client.js`

The first pass may use wrappers rather than physical moves if direct movement risks breaking startup.

### Phase 2: Extract Protocols

Extract current op envelope, patch, selection, feedback, and render contracts into Python modules under `loom_core/interaction_protocol` and `loom_core/render_protocol`.

Existing behavior should keep using the same JSON shapes until tests verify compatibility.

### Phase 3: Modularize Core Runtime

Move core runtime responsibilities into Python modules without changing endpoints. `mcp/server.cjs` should become a compatibility gateway rather than the place where new core behavior is added:

- core HTTP/WebSocket bootstrap
- workspace routes
- context manifest routes
- agent adapter routes
- event/session routes
- domain route mounting
- compatibility routes

Public routes should remain stable during the split.

### Phase 4: Modularize Webview

Split `bridge/webview/anchor-client.js` into:

- Core interaction client
- Workspace panel
- Context panel
- Timeline/history
- Generic render/patch handling
- Domain UI slots
- Loom Fin UI module

The visible interaction model should remain the same.

### Phase 5: Replace Direct LLM Hands With Agent Adapters

Keep the finance hands working through a legacy adapter first.

Then migrate each finance hand into an external agent definition that can be run through cc/codex/openclaw/herms/opencode adapters.

### Phase 6: Introduce Harness Ledger

Persist structured events:

- `human.intent.created`
- `workspace.selection.created`
- `agent.task.created`
- `agent.run.started`
- `agent.artifact.returned`
- `workspace.patch.applied`
- `claim.created`
- `evidence.attached`
- `human.feedback.created`
- `harness.signal.created`
- `domain.config.patch.proposed`
- `domain.config.patch.accepted`

These events form the data flywheel for later evaluation and adaptation.

## Compatibility Rules

During migration:

- Existing `/op`, `/envelope`, `/patch`, `/html`, workspace, WebSocket, and webview behavior must continue to work.
- Existing `data-anc`, `data-handles`, and anchor patch semantics must not change.
- Existing rendered HTML should remain patchable.
- Existing CSS templates, UI kits, spacing, typography, color tokens, component treatments, and visual style must not be rewritten as part of the architecture split.
- Existing concrete functions must keep their current behavior unless a later implementation plan explicitly scopes and verifies a product change.
- Current finance pages can continue to exist while they are moved behind `loom-fin`.
- Legacy routes can proxy into the new modules until the UI is fully migrated.
- No direct replacement of the working interaction loop should happen without a compatibility adapter and regression tests.

## Testing Strategy

Minimum verification for each migration phase:

- Server starts locally.
- Webview opens.
- Existing interaction handles appear.
- A generated section can be refined or patched.
- Workspace file switching still works.
- History still saves and restores.
- Loom Fin market/target/sentiment/position routes still render if enabled.
- Connector toggles still work inside Loom Fin.
- Event log records human intent and agent artifact events.

## Key Decisions

### Decision 1: Local-first modular monolith

Use one local runtime and one repository for now.

Rationale: the product is desktop single-user, and the project is still evolving quickly. A modular monolith gives clean boundaries without adding cloud or deployment complexity.

Trade-off: package boundaries rely on discipline until build tooling enforces them.

### Decision 2: Core calls adapters, not LLM APIs

Loom Core invokes agent adapters instead of directly calling Anthropic/OpenAI SDKs.

Rationale: scenario agents should be independent and swappable. Core should harness agent behavior, not become another provider-specific agent implementation.

Trade-off: adapters require a stable task/artifact protocol.

### Decision 3: Finance logic becomes a domain pack

All market, position, thesis, source, and connector logic belongs to Loom Fin.

Rationale: this keeps Loom Core reusable for non-finance workflows and makes the finance product easier to evolve independently.

Trade-off: some current files need compatibility wrappers during migration.

### Decision 4: Event log is the source of harness learning

Human interactions, agent calls, artifacts, claims, evidence, and feedback should be recorded as events.

Rationale: this enables replay, auditing, evaluation, feedback compilation, and future data flywheel behavior.

Trade-off: schemas need to be maintained carefully.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Migration breaks working interaction behavior | Loss of current product capability | Use compatibility routes and wrappers; split modules before changing protocols |
| Core remains polluted by Fin imports | Architecture separation fails | Domain manifest and SDK must be the only Core-to-Fin boundary |
| Agent adapters become too generic to be useful | Weak execution quality | Keep task/artifact contracts precise; allow adapter-specific metadata |
| Event log grows without clear use | Storage noise | Start with minimal event set tied to replay and feedback compilation |
| Fin UI still lives in generic webview | Core UI remains coupled | Add domain UI slots, then move Fin panels into `domains/loom-fin/ui` |

## Success Criteria

The architecture is successful when:

- A new non-finance domain can be registered without editing Core runtime internals.
- Loom Fin can be disabled without breaking the generic workspace.
- Existing interactive rendering and patching still work.
- Finance agents run through adapter contracts instead of direct Core-owned LLM calls.
- Human feedback and agent artifacts are recorded as replayable harness events.
- Core source files no longer hardcode market, target, sentiment, position, or trading-specific logic.
