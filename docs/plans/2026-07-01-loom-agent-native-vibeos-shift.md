# Loom Agent-Native VibeOS Shift Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reframe Loom so agent capabilities become first-class system primitives, replacing fixed infrastructure-style modules with discoverable capabilities, generated Loomlets, and an agent-native home/workspace experience.

**Architecture:** Keep the existing Brain/Hand/adapters stack, but add an agent-native capability plane above it. Brain becomes an Agent Kernel that compiles user intent into capability plans, agents execute through permission envelopes, and UI surfaces are generated as Loomlets rather than predesigned route pages.

**Tech Stack:** Python 3.11 `dataclasses`/`unittest`, FastAPI routes in `loom/brain.py`, existing adapter runtime in `loom_core/agent_adapters/*`, existing Brain orchestration in `loom_core/agents/core_agent.py`, vanilla JS/CSS webview assets under `bridge/webview`, Node `node:test`.

---

## Source Inspiration

Reference reviewed: https://vibeos.sh/

Relevant ideas to translate, not copy:

- AI-native operating system: the agent is not a plugin bolted onto apps; it is the primary interaction and execution layer.
- Agent controls the computer directly: natural language can create, operate, and modify visible software surfaces.
- Prompted apps appear on screen immediately: the interface is generated around the user's intent.
- Tools/MCP/browser handoff become native OS-like capabilities, not separate setup chores.
- Privacy/sandboxing is part of the system contract, not a settings afterthought.

Loom should adapt these ideas for an AI-native research/workspace product. It should not try to become a real OS shell. The shift is: agent capabilities are native, fixed modules are projections.

## Current Loom Starting Point

Already useful:

- `loom_core/agent_adapters/registry.py` has an adapter registry with capability lookup.
- `loom_core/agent_service.py` can run full agent sessions outside the strict Hand artifact contract.
- `loom/brain.py` already registers SDK, process, Codex, cloud, and dynamic adapters.
- `docs/loom-social-and-agent-adapters.md` documents direct agent execution and adapter registration.
- `loom_core/agents/core_agent.py` already acts more like a Brain agent than the older docs suggest: it resolves workflows, decomposes tasks, dispatches Hands, reviews results, synthesizes, and records episodes.
- `bridge/webview/anchor-client.js` already receives agent events and can patch generated pages.
- The prior plan `docs/plans/2026-07-01-loom-clickable-card-home-detail-pages.md` can provide the visual hierarchy this plan needs.

Still too traditional:

- Capabilities are scattered across routes, adapters, Hands, connectors, prompt handlers, settings panels, and domain pages.
- Agent runtime is configured like infrastructure instead of experienced like native Loom power.
- Pages are mostly fixed UI shells that call agents, instead of agent-generated workspaces that declare their own capabilities.
- Brain/Hand artifacts are still treated as product output; they should become one possible projection of agent-native state.
- Permissions and sandboxing are runtime settings, not explicit capability contracts visible to the user.

## Core Product Thesis

Loom should feel less like "software with AI buttons" and more like "a workspace whose native units are agents, capabilities, and generated surfaces."

New primitives:

- **Capability:** A typed system ability available to agents, such as `workspace.patch`, `browser.open`, `resource.query`, `mcp.invoke`, `portfolio.read`, `episode.replay`, `social.reply`, or `ui.render`.
- **Permission Envelope:** The runtime contract for a capability call: sandbox, confirmation level, workspace root, data scope, network scope, and audit trail.
- **Loomlet:** A generated mini workspace/app surface. It has a manifest, state, required capabilities, rendered HTML, actions, and update policy.
- **Agent Kernel:** The Brain-facing runtime that compiles intent into capability plans, routes execution to adapters, renders Loomlets, observes user interaction, and records episode state.
- **Capability Dock:** The home/workspace UI where users see what Loom can do now and which agents/capabilities are active.
- **State Frame:** Agent-readable state containing user intent, active Loomlets, selected content, files/resources, permissions, and recent observations.

This plan does not delete existing Hands. It changes their role: a Hand is one capability provider among many, not the product module boundary.

---

### Task 1: Add An ADR For The Agent-Native Direction

**Files:**

- Create: `docs/architecture/adr-2026-07-01-agent-native-loom.md`

**Step 1: Write the ADR**

Create `docs/architecture/adr-2026-07-01-agent-native-loom.md`:

```markdown
# ADR 2026-07-01: Agent-Native Loom

## Status

Proposed

## Context

Loom already has Brain orchestration, Hand agents, runtime adapters, social ingress,
generated cards, and webview patching. The product still presents many capabilities
as traditional software modules: fixed routes, settings panels, hard-coded domain
pages, connector-specific UI, and adapter-specific configuration flows.

VibeOS demonstrates a stronger AI-native product posture: the agent is treated as
the native interaction layer and prompted software appears directly on screen.
Loom should adopt that posture for research/workspace workflows without becoming
a general-purpose operating system.

## Decision

Loom will introduce an agent-native capability plane:

- Capabilities are typed, discoverable, permissioned system abilities.
- Brain becomes the Agent Kernel that compiles intent into capability plans.
- UI surfaces are Loomlets generated from intent, capability results, and state.
- Fixed domain pages become projections or templates, not the system boundary.
- Permission envelopes and audit trails become first-class user-visible runtime state.

## Alternatives

1. Keep adding fixed domain pages and settings panels.
   - Rejected: this preserves the traditional app model and hides agent power.

2. Rewrite Loom as a desktop OS shell.
   - Rejected: too broad, high risk, and unnecessary for Loom's research workspace.

3. Add a VibeOS-inspired home UI only.
   - Rejected: visual inspiration without runtime primitives would be cosmetic.

## Consequences

Positive:

- Users can ask for workspaces instead of selecting prebuilt modules.
- Agents can select tools/resources directly through a typed capability catalog.
- Generated UI becomes safer because required capabilities and permissions are explicit.
- Existing adapters and Hands become more valuable as capability providers.

Negative:

- More runtime state must be audited and shown clearly.
- Generated UI needs stricter containment and deterministic tests.
- Brain needs a stable intermediate representation between intent and execution.

## Guardrails

- No arbitrary agent execution without permission envelopes.
- No generated UI with unrestricted script execution.
- No hidden external network or filesystem access.
- Existing Brain/Hand flows must continue to work during migration.
```

**Step 2: Verify the file exists**

Run:

```bash
Get-Item docs/architecture/adr-2026-07-01-agent-native-loom.md
```

Expected: file exists.

**Step 3: Commit**

```bash
git add docs/architecture/adr-2026-07-01-agent-native-loom.md
git commit -m "docs: record agent-native Loom architecture direction"
```

---

### Task 2: Add Agent-Native Capability Model Tests

**Files:**

- Create: `tests/test_agent_native_capabilities.py`
- Create later: `loom_core/agent_native/__init__.py`
- Create later: `loom_core/agent_native/capabilities.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_native_capabilities.py`:

```python
import unittest

from loom_core.agent_native.capabilities import (
    BUILTIN_CAPABILITIES,
    CapabilityCatalog,
    CapabilityPolicy,
)
from loom_core.agent_adapters.base import AgentAdapter
from loom_core.agent_adapters.registry import AgentAdapterRegistry


class _Adapter:
    id = "codex-app-server"
    capabilities = ["runtime.hand", "workspace.patch"]

    async def invoke(self, task):
        if False:
            yield task

    async def cancel(self, run_id):
        return None


class AgentNativeCapabilityTests(unittest.TestCase):
    def test_builtin_capabilities_include_agent_native_primitives(self):
        ids = {cap.id for cap in BUILTIN_CAPABILITIES}

        self.assertIn("workspace.patch", ids)
        self.assertIn("ui.render", ids)
        self.assertIn("resource.query", ids)
        self.assertIn("agent.run", ids)
        self.assertIn("episode.replay", ids)

    def test_catalog_projects_registered_agent_adapters(self):
        registry = AgentAdapterRegistry()
        registry.register(_Adapter())

        catalog = CapabilityCatalog.from_adapter_registry(registry)
        cap = catalog.get("agent.adapter.codex-app-server")

        self.assertEqual(cap.id, "agent.adapter.codex-app-server")
        self.assertEqual(cap.provider, "codex-app-server")
        self.assertIn("runtime.hand", cap.tags)
        self.assertIn("workspace.patch", cap.tags)

    def test_policy_requires_confirmation_for_write_and_execute(self):
        policy = CapabilityPolicy.default()

        self.assertFalse(policy.requires_confirmation("resource.query"))
        self.assertTrue(policy.requires_confirmation("workspace.patch"))
        self.assertTrue(policy.requires_confirmation("agent.run"))
        self.assertTrue(policy.requires_confirmation("mcp.invoke"))

    def test_catalog_can_select_by_intent_verb(self):
        catalog = CapabilityCatalog(BUILTIN_CAPABILITIES)

        matches = catalog.find_for_intent("create interactive workspace from prompt")
        ids = [cap.id for cap in matches]

        self.assertIn("ui.render", ids)
        self.assertIn("agent.run", ids)
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
```

Expected: FAIL because `loom_core.agent_native` does not exist.

**Step 3: Commit**

```bash
git add tests/test_agent_native_capabilities.py
git commit -m "test: define agent-native capability catalog"
```

---

### Task 3: Implement The Capability Catalog

**Files:**

- Create: `loom_core/agent_native/__init__.py`
- Create: `loom_core/agent_native/capabilities.py`
- Test: `tests/test_agent_native_capabilities.py`

**Step 1: Add the package init**

Create `loom_core/agent_native/__init__.py`:

```python
"""Agent-native runtime primitives for Loom."""

from .capabilities import Capability, CapabilityCatalog, CapabilityPolicy

__all__ = ["Capability", "CapabilityCatalog", "CapabilityPolicy"]
```

**Step 2: Implement the minimal model**

Create `loom_core/agent_native/capabilities.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    description: str
    provider: str = "loom"
    safety: str = "read"
    intent_verbs: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    render_hint: str = ""

    def matches_intent(self, text: str) -> bool:
        lowered = str(text or "").lower()
        return any(verb in lowered for verb in self.intent_verbs)


BUILTIN_CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="agent.run",
        label="Run Agent",
        description="Dispatch a task to a configured full agent runtime.",
        safety="execute",
        intent_verbs=("agent", "run", "do", "create", "build", "analyze", "inspect"),
        tags=("runtime.hand",),
        render_hint="live-agent",
    ),
    Capability(
        id="ui.render",
        label="Render Loomlet",
        description="Render a generated Loomlet into the webview.",
        safety="write",
        intent_verbs=("render", "show", "display", "workspace", "app", "page", "visual"),
        tags=("workspace.patch", "ui"),
        render_hint="loomlet",
    ),
    Capability(
        id="workspace.patch",
        label="Patch Workspace",
        description="Apply a bounded patch to the current Loom workspace.",
        safety="write",
        intent_verbs=("patch", "modify", "update", "edit", "replace"),
        tags=("workspace.patch",),
        render_hint="patch-preview",
    ),
    Capability(
        id="resource.query",
        label="Query Resource",
        description="Read connector, inbox, or resource data available to Loom.",
        safety="read",
        intent_verbs=("read", "query", "fetch", "search", "source", "data"),
        tags=("resource", "connector"),
        render_hint="source-list",
    ),
    Capability(
        id="episode.replay",
        label="Replay Episode",
        description="Replay or fork a prior Brain episode.",
        safety="read",
        intent_verbs=("replay", "fork", "history", "episode", "resume"),
        tags=("episode", "state"),
        render_hint="timeline",
    ),
    Capability(
        id="mcp.invoke",
        label="Invoke Tool",
        description="Invoke a registered external tool or MCP-like capability through Loom policy.",
        safety="execute",
        intent_verbs=("tool", "mcp", "browser", "open", "external"),
        tags=("tool", "external"),
        render_hint="tool-call",
    ),
)


class CapabilityCatalog:
    def __init__(self, capabilities: tuple[Capability, ...] | list[Capability] = ()) -> None:
        self._capabilities = {cap.id: cap for cap in capabilities}

    @classmethod
    def from_adapter_registry(cls, registry: Any) -> "CapabilityCatalog":
        catalog = cls(BUILTIN_CAPABILITIES)
        for adapter in registry.list():
            adapter_id = str(adapter.id)
            tags = tuple(str(item) for item in getattr(adapter, "capabilities", []) or [])
            catalog.register(
                Capability(
                    id=f"agent.adapter.{adapter_id}",
                    label=f"Agent Adapter: {adapter_id}",
                    description="Configured agent runtime adapter.",
                    provider=adapter_id,
                    safety="execute",
                    intent_verbs=("agent", "run", "delegate", adapter_id.lower()),
                    tags=tags,
                    render_hint="agent-adapter",
                )
            )
        return catalog

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.id] = capability

    def get(self, capability_id: str) -> Capability:
        return self._capabilities[capability_id]

    def list(self) -> list[Capability]:
        return sorted(self._capabilities.values(), key=lambda cap: cap.id)

    def find_for_intent(self, text: str) -> list[Capability]:
        matches = [cap for cap in self.list() if cap.matches_intent(text)]
        return matches or [self.get("agent.run"), self.get("ui.render")]

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "id": cap.id,
                "label": cap.label,
                "description": cap.description,
                "provider": cap.provider,
                "safety": cap.safety,
                "intent_verbs": list(cap.intent_verbs),
                "tags": list(cap.tags),
                "render_hint": cap.render_hint,
                "input_schema": cap.input_schema,
                "output_schema": cap.output_schema,
            }
            for cap in self.list()
        ]


class CapabilityPolicy:
    def __init__(self, confirm_safety: set[str]) -> None:
        self._confirm_safety = set(confirm_safety)

    @classmethod
    def default(cls) -> "CapabilityPolicy":
        return cls({"write", "execute", "external"})

    def requires_confirmation(self, capability_or_safety: str | Capability) -> bool:
        safety = capability_or_safety.safety if isinstance(capability_or_safety, Capability) else ""
        if not safety:
            by_id = {cap.id: cap.safety for cap in BUILTIN_CAPABILITIES}
            safety = by_id.get(str(capability_or_safety), "execute")
        return safety in self._confirm_safety
```

**Step 3: Run the tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
```

Expected: PASS.

**Step 4: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_capabilities.py
git commit -m "feat: add agent-native capability catalog"
```

---

### Task 4: Add Capability API Endpoints To Brain

**Files:**

- Modify: `loom/brain.py`
- Create: `tests/test_brain_agent_native_routes.py`
- Test: `tests/test_brain_agent_native_routes.py`

**Step 1: Write route tests**

Create `tests/test_brain_agent_native_routes.py`:

```python
import unittest

from fastapi.testclient import TestClient

from loom.brain import app


class BrainAgentNativeRoutesTests(unittest.TestCase):
    def test_capabilities_endpoint_exposes_builtin_and_adapter_capabilities(self):
        client = TestClient(app)

        response = client.get("/agent-native/capabilities")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        ids = {item["id"] for item in body["capabilities"]}
        self.assertIn("agent.run", ids)
        self.assertIn("ui.render", ids)
        self.assertIn("workspace.patch", ids)

    def test_capability_policy_endpoint_marks_confirmation_required(self):
        client = TestClient(app)

        response = client.get("/agent-native/policy")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["requires_confirmation"]["agent.run"])
        self.assertTrue(body["requires_confirmation"]["workspace.patch"])
        self.assertFalse(body["requires_confirmation"]["resource.query"])
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes
```

Expected: FAIL with 404 routes.

**Step 3: Implement endpoints**

In `loom/brain.py`, import:

```python
from loom_core.agent_native.capabilities import CapabilityCatalog, CapabilityPolicy
```

Add helpers near other control-plane helpers:

```python
def _agent_native_catalog() -> CapabilityCatalog:
    return CapabilityCatalog.from_adapter_registry(_adapter_registry)


def _agent_native_policy() -> CapabilityPolicy:
    return CapabilityPolicy.default()
```

Add routes near adapter/runtime routes:

```python
@app.get("/agent-native/capabilities")
async def agent_native_capabilities():
    catalog = _agent_native_catalog()
    return {"ok": True, "capabilities": catalog.to_json()}


@app.get("/agent-native/policy")
async def agent_native_policy():
    catalog = _agent_native_catalog()
    policy = _agent_native_policy()
    return {
        "ok": True,
        "requires_confirmation": {
            cap.id: policy.requires_confirmation(cap)
            for cap in catalog.list()
        },
    }
```

**Step 4: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities tests.test_brain_agent_native_routes
```

Expected: PASS.

**Step 5: Commit**

```bash
git add loom/brain.py tests/test_brain_agent_native_routes.py
git commit -m "feat: expose agent-native capability APIs"
```

---

### Task 5: Define Loomlet Specs As Generated UI Primitives

**Files:**

- Create: `loom_core/agent_native/loomlet.py`
- Modify: `loom_core/agent_native/__init__.py`
- Create: `tests/test_agent_native_loomlet.py`

**Step 1: Write the failing tests**

Create `tests/test_agent_native_loomlet.py`:

```python
import unittest

from loom_core.agent_native.loomlet import LoomletAction, LoomletSpec


class AgentNativeLoomletTests(unittest.TestCase):
    def test_loomlet_serializes_manifest_state_and_actions(self):
        spec = LoomletSpec(
            id="loomlet.market-brief",
            title="Market Brief",
            intent="Build a market brief workspace",
            required_capabilities=("agent.run", "resource.query", "ui.render"),
            state={"ticker": "NVDA"},
            html="<section data-loomlet-root>Market Brief</section>",
            actions=(
                LoomletAction(id="refresh", label="Refresh", capability="agent.run"),
                LoomletAction(id="patch", label="Patch Workspace", capability="workspace.patch"),
            ),
        )

        data = spec.to_json()

        self.assertEqual(data["id"], "loomlet.market-brief")
        self.assertEqual(data["title"], "Market Brief")
        self.assertEqual(data["state"]["ticker"], "NVDA")
        self.assertIn("resource.query", data["required_capabilities"])
        self.assertEqual(data["actions"][0]["capability"], "agent.run")

    def test_loomlet_rejects_script_tags_by_default(self):
        with self.assertRaises(ValueError):
            LoomletSpec(
                id="loomlet.unsafe",
                title="Unsafe",
                intent="render unsafe script",
                required_capabilities=("ui.render",),
                html="<script>alert(1)</script>",
            ).validate()
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_loomlet
```

Expected: FAIL because `loomlet.py` does not exist.

**Step 3: Implement Loomlet model**

Create `loom_core/agent_native/loomlet.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LoomletAction:
    id: str
    label: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "capability": self.capability,
            "payload": self.payload,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class LoomletSpec:
    id: str
    title: str
    intent: str
    required_capabilities: tuple[str, ...]
    state: dict[str, Any] = field(default_factory=dict)
    html: str = ""
    actions: tuple[LoomletAction, ...] = ()
    update_policy: str = "agent-patch"

    def validate(self) -> "LoomletSpec":
        lowered = self.html.lower()
        if "<script" in lowered:
            raise ValueError("loomlet html cannot include script tags")
        if " onerror=" in lowered or " onclick=" in lowered:
            raise ValueError("loomlet html cannot include inline event handlers")
        if "ui.render" not in self.required_capabilities:
            raise ValueError("loomlet requires ui.render capability")
        return self

    def to_json(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "title": self.title,
            "intent": self.intent,
            "required_capabilities": list(self.required_capabilities),
            "state": self.state,
            "html": self.html,
            "actions": [action.to_json() for action in self.actions],
            "update_policy": self.update_policy,
        }
```

Update `loom_core/agent_native/__init__.py`:

```python
from .loomlet import LoomletAction, LoomletSpec

__all__ = [
    "Capability",
    "CapabilityCatalog",
    "CapabilityPolicy",
    "LoomletAction",
    "LoomletSpec",
]
```

**Step 4: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_loomlet tests.test_agent_native_capabilities
```

Expected: PASS.

**Step 5: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_loomlet.py
git commit -m "feat: add Loomlet generated UI primitive"
```

---

### Task 6: Add A Minimal Intent-To-Loomlet Compiler

**Files:**

- Create: `loom_core/agent_native/kernel.py`
- Create: `tests/test_agent_native_kernel.py`
- Modify: `loom_core/agent_native/__init__.py`

**Step 1: Write failing tests**

Create `tests/test_agent_native_kernel.py`:

```python
import unittest

from loom_core.agent_native.capabilities import BUILTIN_CAPABILITIES, CapabilityCatalog, CapabilityPolicy
from loom_core.agent_native.kernel import AgentKernel


class AgentNativeKernelTests(unittest.TestCase):
    def test_compile_intent_returns_capability_plan_and_loomlet(self):
        kernel = AgentKernel(
            catalog=CapabilityCatalog(BUILTIN_CAPABILITIES),
            policy=CapabilityPolicy.default(),
        )

        result = kernel.compile_intent("Create an interactive NVDA target tracker")

        self.assertEqual(result["ok"], True)
        capability_ids = [item["id"] for item in result["capability_plan"]]
        self.assertIn("agent.run", capability_ids)
        self.assertIn("ui.render", capability_ids)
        self.assertEqual(result["loomlet"]["update_policy"], "agent-patch")
        self.assertIn("data-loomlet-root", result["loomlet"]["html"])

    def test_write_capabilities_are_marked_for_confirmation(self):
        kernel = AgentKernel(
            catalog=CapabilityCatalog(BUILTIN_CAPABILITIES),
            policy=CapabilityPolicy.default(),
        )

        result = kernel.compile_intent("Patch this workspace")
        by_id = {item["id"]: item for item in result["capability_plan"]}

        self.assertTrue(by_id["workspace.patch"]["requires_confirmation"])
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_kernel
```

Expected: FAIL because `kernel.py` does not exist.

**Step 3: Implement minimal deterministic compiler**

Create `loom_core/agent_native/kernel.py`:

```python
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityCatalog, CapabilityPolicy
from .loomlet import LoomletAction, LoomletSpec


@dataclass
class AgentKernel:
    catalog: CapabilityCatalog
    policy: CapabilityPolicy

    def compile_intent(self, intent: str, state_frame: dict[str, Any] | None = None) -> dict[str, Any]:
        text = str(intent or "").strip()
        if not text:
            return {"ok": False, "error": "intent is required"}

        selected = self._select_capabilities(text)
        required = tuple(dict.fromkeys([cap.id for cap in selected] + ["ui.render"]))
        title = self._title_from_intent(text)
        loomlet = LoomletSpec(
            id=self._loomlet_id(title),
            title=title,
            intent=text,
            required_capabilities=required,
            state={"intent": text, **(state_frame or {})},
            html=self._render_placeholder(title, text, selected),
            actions=tuple(self._actions_for(selected)),
        )

        return {
            "ok": True,
            "intent": text,
            "capability_plan": [
                {
                    "id": cap.id,
                    "label": cap.label,
                    "provider": cap.provider,
                    "safety": cap.safety,
                    "requires_confirmation": self.policy.requires_confirmation(cap),
                    "render_hint": cap.render_hint,
                }
                for cap in selected
            ],
            "loomlet": loomlet.to_json(),
        }

    def _select_capabilities(self, intent: str):
        selected = self.catalog.find_for_intent(intent)
        by_id = {cap.id: cap for cap in selected}
        if any(word in intent.lower() for word in ("create", "build", "analyze", "track", "research")):
            by_id["agent.run"] = self.catalog.get("agent.run")
        if any(word in intent.lower() for word in ("data", "source", "market", "target", "portfolio", "sentiment", "research")):
            by_id["resource.query"] = self.catalog.get("resource.query")
        if any(word in intent.lower() for word in ("patch", "modify", "edit", "update")):
            by_id["workspace.patch"] = self.catalog.get("workspace.patch")
        by_id["ui.render"] = self.catalog.get("ui.render")
        return [by_id[key] for key in sorted(by_id)]

    @staticmethod
    def _title_from_intent(intent: str) -> str:
        words = re.sub(r"[^a-zA-Z0-9 ]+", " ", intent).strip().split()
        title = " ".join(words[:6]) or "Agent Workspace"
        return title.title()

    @staticmethod
    def _loomlet_id(title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "workspace"
        return f"loomlet.{slug}"

    @staticmethod
    def _render_placeholder(title: str, intent: str, capabilities) -> str:
        caps = "".join(
            f'<li data-capability="{html.escape(cap.id)}">{html.escape(cap.label)}</li>'
            for cap in capabilities
        )
        return (
            f'<section class="loomlet" data-loomlet-root>'
            f'<header class="loomlet-header"><h2>{html.escape(title)}</h2></header>'
            f'<p>{html.escape(intent)}</p>'
            f'<ul class="loomlet-capability-list">{caps}</ul>'
            f'</section>'
        )

    def _actions_for(self, capabilities):
        actions = []
        for cap in capabilities:
            if cap.id in {"agent.run", "workspace.patch", "resource.query"}:
                actions.append(
                    LoomletAction(
                        id=cap.id.replace(".", "-"),
                        label=cap.label,
                        capability=cap.id,
                        requires_confirmation=self.policy.requires_confirmation(cap),
                    )
                )
        return actions
```

Update `loom_core/agent_native/__init__.py`:

```python
from .kernel import AgentKernel
```

**Step 4: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_kernel tests.test_agent_native_loomlet tests.test_agent_native_capabilities
```

Expected: PASS.

**Step 5: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_kernel.py
git commit -m "feat: compile intent into Loomlet plans"
```

---

### Task 7: Expose Intent Compilation Through Brain

**Files:**

- Modify: `loom/brain.py`
- Modify: `tests/test_brain_agent_native_routes.py`

**Step 1: Extend route test**

Add to `tests/test_brain_agent_native_routes.py`:

```python
    def test_compile_intent_endpoint_returns_loomlet_plan(self):
        client = TestClient(app)

        response = client.post(
            "/agent-native/compile",
            json={"intent": "Create an interactive NVDA target tracker"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("capability_plan", body)
        self.assertIn("loomlet", body)
        self.assertIn("data-loomlet-root", body["loomlet"]["html"])
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes
```

Expected: FAIL with 404.

**Step 3: Implement endpoint**

In `loom/brain.py`, import:

```python
from pydantic import BaseModel
from loom_core.agent_native.kernel import AgentKernel
```

If `BaseModel` is already imported, only add `AgentKernel`.

Add request model:

```python
class AgentNativeCompileRequest(BaseModel):
    intent: str
    state_frame: dict = {}
```

Add route:

```python
@app.post("/agent-native/compile")
async def agent_native_compile(req: AgentNativeCompileRequest):
    kernel = AgentKernel(
        catalog=_agent_native_catalog(),
        policy=_agent_native_policy(),
    )
    return kernel.compile_intent(req.intent, req.state_frame)
```

**Step 4: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes tests.test_agent_native_kernel
```

Expected: PASS.

**Step 5: Commit**

```bash
git add loom/brain.py tests/test_brain_agent_native_routes.py
git commit -m "feat: expose agent-native intent compilation"
```

---

### Task 8: Add Agent-Native Home Route And Static Tests

**Files:**

- Create: `bridge/webview/agent-native-home.js`
- Create: `bridge/webview/agent-native-home.css`
- Create: `bridge/webview/agent-native-home.test.cjs`
- Modify: `bridge/webview/index.html`
- Modify: `bridge/webview/anchor-client.js`

**Step 1: Write failing static tests**

Create `bridge/webview/agent-native-home.test.cjs`:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('agent-native home assets are wired into the webview', () => {
  const index = read('bridge/webview/index.html');
  const client = read('bridge/webview/anchor-client.js');

  assert.match(index, /agent-native-home\.css/);
  assert.match(index, /agent-native-home\.js/);
  assert.match(client, /route === 'agent-native'/);
  assert.match(client, /AgentNativeHome\.renderInto\(this\)/);
});

test('agent-native home renders capability dock and Loomlet preview hooks', () => {
  const page = read('bridge/webview/agent-native-home.js');
  const css = read('bridge/webview/agent-native-home.css');

  assert.match(page, /window\.AgentNativeHome/);
  assert.match(page, /agent-native\/capabilities/);
  assert.match(page, /agent-native\/compile/);
  assert.match(page, /data-agent-capability/);
  assert.match(page, /data-loomlet-preview/);
  assert.match(css, /\.agent-native-shell/);
  assert.match(css, /\.capability-dock/);
  assert.match(css, /\.loomlet-preview/);
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: FAIL because assets/routes do not exist.

**Step 3: Add CSS include and JS include**

In `bridge/webview/index.html`, add near existing CSS:

```html
<link rel="stylesheet" href="agent-native-home.css">
```

Add near existing scripts:

```html
<script src="agent-native-home.js"></script>
```

**Step 4: Wire route**

In `bridge/webview/anchor-client.js`, inside `_routeHash(hash)`, add before the domain route branch:

```js
    } else if (route === 'agent-native') {
      this._showRouteShell(route);
      if (window.AgentNativeHome) window.AgentNativeHome.renderInto(this);
      this._updateToolbarTabs(route);
```

If the toolbar has a suitable place for a button, add a compact button in `index.html`:

```html
<button id="anchor-agent-native-btn" class="toolbar-icon-btn" type="button" title="Agent native workspace">
  <i class="ph-bold ph-sparkle"></i>
</button>
```

Wire it in `_initHomeNav()`:

```js
const agentNativeNav = document.getElementById('anchor-agent-native-btn');
agentNativeNav?.addEventListener('click', (e) => {
  e.preventDefault();
  this._navigateToRoute('agent-native');
});
```

**Step 5: Add minimal page JS**

Create `bridge/webview/agent-native-home.js`:

```js
(function () {
  'use strict';

  const API_BASE = 'http://localhost:3002';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, options || {});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  function shellHtml() {
    return [
      '<section class="agent-native-shell" data-anc="agent-native.home" data-detail-disabled="true">',
      '  <header class="agent-native-header">',
      '    <div>',
      '      <p class="agent-native-kicker">Agent-native Loom</p>',
      '      <h1>Prompt a workspace, not a module.</h1>',
      '    </div>',
      '    <button class="agent-native-refresh" type="button" data-agent-native-refresh title="Refresh capabilities"><i class="ph-bold ph-arrows-clockwise"></i></button>',
      '  </header>',
      '  <div class="agent-native-command">',
      '    <input data-agent-native-intent type="text" placeholder="Create a target tracker, inspect a portfolio, replay an episode...">',
      '    <button type="button" data-agent-native-compile title="Compile intent"><i class="ph-bold ph-arrow-right"></i></button>',
      '  </div>',
      '  <div class="agent-native-grid">',
      '    <section class="capability-dock" data-capability-dock></section>',
      '    <section class="loomlet-preview" data-loomlet-preview></section>',
      '  </div>',
      '</section>',
    ].join('');
  }

  function renderCapabilities(root, capabilities) {
    const dock = root.querySelector('[data-capability-dock]');
    if (!dock) return;
    dock.innerHTML = [
      '<h2>Capability Dock</h2>',
      '<div class="capability-list">',
      capabilities.map((cap) => [
        '<article class="capability-card" data-agent-capability="' + esc(cap.id) + '">',
        '  <div class="capability-card-head">',
        '    <strong>' + esc(cap.label) + '</strong>',
        '    <span data-safety="' + esc(cap.safety) + '">' + esc(cap.safety) + '</span>',
        '  </div>',
        '  <p>' + esc(cap.description) + '</p>',
        '  <small>' + esc((cap.tags || []).join(' / ')) + '</small>',
        '</article>',
      ].join('')).join(''),
      '</div>',
    ].join('');
  }

  function renderLoomlet(root, loomlet) {
    const preview = root.querySelector('[data-loomlet-preview]');
    if (!preview) return;
    if (!loomlet) {
      preview.innerHTML = '<h2>Loomlet Preview</h2><p>Compile an intent to generate a workspace surface.</p>';
      return;
    }
    preview.innerHTML = [
      '<h2>' + esc(loomlet.title) + '</h2>',
      '<div class="loomlet-surface">' + (loomlet.html || '') + '</div>',
      '<div class="loomlet-actions">',
      (loomlet.actions || []).map((action) => (
        '<button type="button" data-loomlet-action="' + esc(action.id) + '">' +
        esc(action.label) +
        (action.requires_confirmation ? '<span>Confirm</span>' : '') +
        '</button>'
      )).join(''),
      '</div>',
    ].join('');
  }

  async function loadCapabilities(root) {
    const data = await fetchJson(API_BASE + '/agent-native/capabilities');
    renderCapabilities(root, data.capabilities || []);
  }

  async function compileIntent(root) {
    const input = root.querySelector('[data-agent-native-intent]');
    const intent = (input && input.value || '').trim();
    if (!intent) return;
    const data = await fetchJson(API_BASE + '/agent-native/compile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent })
    });
    renderLoomlet(root, data.loomlet);
  }

  window.AgentNativeHome = {
    async renderInto(anchor) {
      anchor.container.innerHTML = shellHtml();
      const root = anchor.container.querySelector('.agent-native-shell');
      renderLoomlet(root, null);
      root.querySelector('[data-agent-native-refresh]')?.addEventListener('click', () => loadCapabilities(root).catch(console.error));
      root.querySelector('[data-agent-native-compile]')?.addEventListener('click', () => compileIntent(root).catch(console.error));
      root.querySelector('[data-agent-native-intent]')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') compileIntent(root).catch(console.error);
      });
      await loadCapabilities(root);
    }
  };
})();
```

**Step 6: Add minimal CSS**

Create `bridge/webview/agent-native-home.css`:

```css
.agent-native-shell {
  width: min(1180px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 14px;
  color: var(--fg-1);
}

.agent-native-header,
.agent-native-command,
.capability-dock,
.loomlet-preview {
  border: 1px solid rgba(18, 24, 38, 0.10);
  border-radius: 8px;
  background: rgba(255,255,255,0.86);
}

.agent-native-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
}

.agent-native-kicker {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 760;
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: 0;
}

.agent-native-header h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.08;
  letter-spacing: 0;
}

.agent-native-refresh,
.agent-native-command button,
.loomlet-actions button {
  min-width: 34px;
  height: 34px;
  border: 1px solid rgba(18, 24, 38, 0.10);
  border-radius: 8px;
  background: rgba(255,255,255,0.84);
  color: var(--fg-1);
  cursor: pointer;
}

.agent-native-command {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 10px;
}

.agent-native-command input {
  min-width: 0;
  border: 0;
  background: transparent;
  font: inherit;
  outline: none;
}

.agent-native-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.82fr) minmax(420px, 1.18fr);
  gap: 14px;
}

.capability-dock,
.loomlet-preview {
  min-width: 0;
  padding: 14px;
}

.capability-dock h2,
.loomlet-preview h2 {
  margin: 0 0 12px;
  font-size: 15px;
}

.capability-list {
  display: grid;
  gap: 8px;
}

.capability-card {
  border: 1px solid rgba(18, 24, 38, 0.08);
  border-radius: 8px;
  padding: 10px;
  background: rgba(255,255,255,0.70);
}

.capability-card-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.capability-card p {
  margin: 6px 0;
  color: var(--fg-2);
  font-size: 12px;
  line-height: 1.45;
}

.capability-card small {
  color: var(--fg-3);
  font-size: 11px;
}

.loomlet-surface {
  border: 1px solid rgba(18, 24, 38, 0.08);
  border-radius: 8px;
  padding: 14px;
  background: rgba(255,255,255,0.72);
}

.loomlet-actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 900px) {
  .agent-native-grid {
    grid-template-columns: 1fr;
  }
}
```

**Step 7: Run tests**

Run:

```bash
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS.

**Step 8: Commit**

```bash
git add bridge/webview/agent-native-home.js bridge/webview/agent-native-home.css bridge/webview/agent-native-home.test.cjs bridge/webview/index.html bridge/webview/anchor-client.js
git commit -m "feat: add agent-native Loom home route"
```

---

### Task 9: Add Permission Envelopes To Agent-Native Plans

**Files:**

- Create: `loom_core/agent_native/permissions.py`
- Modify: `loom_core/agent_native/kernel.py`
- Create: `tests/test_agent_native_permissions.py`

**Step 1: Write failing tests**

Create `tests/test_agent_native_permissions.py`:

```python
import unittest

from loom_core.agent_native.permissions import PermissionEnvelope


class AgentNativePermissionTests(unittest.TestCase):
    def test_permission_envelope_defaults_to_read_only_workspace(self):
        envelope = PermissionEnvelope.for_capability("resource.query")

        self.assertEqual(envelope.capability_id, "resource.query")
        self.assertEqual(envelope.sandbox, "read-only")
        self.assertFalse(envelope.requires_confirmation)

    def test_permission_envelope_requires_confirmation_for_workspace_patch(self):
        envelope = PermissionEnvelope.for_capability("workspace.patch")

        self.assertEqual(envelope.sandbox, "workspace-write")
        self.assertTrue(envelope.requires_confirmation)
        self.assertIn("workspace.patch", envelope.audit_tags)

    def test_permission_envelope_requires_confirm_for_agent_run(self):
        envelope = PermissionEnvelope.for_capability("agent.run")

        self.assertEqual(envelope.sandbox, "workspace-write")
        self.assertTrue(envelope.requires_confirmation)
        self.assertIn("agent.run", envelope.audit_tags)
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_permissions
```

Expected: FAIL because `permissions.py` does not exist.

**Step 3: Implement permission envelopes**

Create `loom_core/agent_native/permissions.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionEnvelope:
    capability_id: str
    sandbox: str
    data_scope: str = "current-workspace"
    network_scope: str = "default"
    requires_confirmation: bool = False
    audit_tags: tuple[str, ...] = ()

    @classmethod
    def for_capability(cls, capability_id: str) -> "PermissionEnvelope":
        cid = str(capability_id)
        if cid in {"resource.query", "episode.replay"}:
            return cls(
                capability_id=cid,
                sandbox="read-only",
                network_scope="none",
                requires_confirmation=False,
                audit_tags=(cid,),
            )
        if cid in {"workspace.patch", "ui.render"}:
            return cls(
                capability_id=cid,
                sandbox="workspace-write",
                network_scope="none",
                requires_confirmation=True,
                audit_tags=(cid,),
            )
        return cls(
            capability_id=cid,
            sandbox="workspace-write",
            network_scope="default",
            requires_confirmation=True,
            audit_tags=(cid,),
        )

    def to_json(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "sandbox": self.sandbox,
            "data_scope": self.data_scope,
            "network_scope": self.network_scope,
            "requires_confirmation": self.requires_confirmation,
            "audit_tags": list(self.audit_tags),
        }
```

Update `kernel.py` so each capability plan item includes:

```python
from .permissions import PermissionEnvelope
```

Inside the capability plan dict:

```python
"permission": PermissionEnvelope.for_capability(cap.id).to_json(),
```

**Step 4: Add a kernel assertion**

Update `tests/test_agent_native_kernel.py`:

```python
        self.assertEqual(by_id["workspace.patch"]["permission"]["sandbox"], "workspace-write")
```

**Step 5: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_permissions tests.test_agent_native_kernel
```

Expected: PASS.

**Step 6: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_permissions.py tests/test_agent_native_kernel.py
git commit -m "feat: add permission envelopes to capability plans"
```

---

### Task 10: Project Existing Hands And Connectors Into Capabilities

**Files:**

- Modify: `loom_core/agent_native/capabilities.py`
- Modify: `loom/brain.py`
- Modify: `tests/test_agent_native_capabilities.py`
- Modify: `tests/test_brain_agent_native_routes.py`

**Step 1: Add tests for Hands as capability providers**

Extend `tests/test_agent_native_capabilities.py`:

```python
    def test_catalog_can_register_hand_capabilities(self):
        catalog = CapabilityCatalog(BUILTIN_CAPABILITIES)

        catalog.register_hand("market", {"label": "Market", "capabilities": ["web_search", "market_data"]})

        cap = catalog.get("hand.market")
        self.assertEqual(cap.provider, "hand:market")
        self.assertIn("market_data", cap.tags)
        self.assertIn("analyze", cap.intent_verbs)
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
```

Expected: FAIL because `register_hand` does not exist.

**Step 3: Implement hand registration**

In `CapabilityCatalog`, add:

```python
    def register_hand(self, hand_id: str, info: dict[str, Any]) -> None:
        label = str(info.get("label") or hand_id)
        tags = tuple(str(item) for item in (info.get("capabilities") or info.get("tools") or []))
        self.register(
            Capability(
                id=f"hand.{hand_id}",
                label=f"Hand: {label}",
                description=f"Run the {hand_id} Hand as an agent-native capability.",
                provider=f"hand:{hand_id}",
                safety="execute",
                intent_verbs=("analyze", "research", "review", hand_id),
                tags=tags,
                render_hint="hand-run",
            )
        )
```

**Step 4: Add Brain helper to register current Hands**

In `loom/brain.py`, update `_agent_native_catalog()`:

```python
def _agent_native_catalog() -> CapabilityCatalog:
    catalog = CapabilityCatalog.from_adapter_registry(_adapter_registry)
    for hand_id, info in REGISTRY.items():
        catalog.register_hand(hand_id, info if isinstance(info, dict) else {})
    return catalog
```

**Step 5: Extend API test**

In `tests/test_brain_agent_native_routes.py`, assert:

```python
        self.assertTrue(any(item["id"].startswith("hand.") for item in body["capabilities"]))
```

**Step 6: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities tests.test_brain_agent_native_routes
```

Expected: PASS.

**Step 7: Commit**

```bash
git add loom_core/agent_native/capabilities.py loom/brain.py tests/test_agent_native_capabilities.py tests/test_brain_agent_native_routes.py
git commit -m "feat: project Hands into agent-native capabilities"
```

---

### Task 11: Make Loomlets Executable Through Confirmed Actions

**Files:**

- Modify: `loom/brain.py`
- Modify: `loom_core/agent_native/kernel.py`
- Create: `tests/test_agent_native_action_execution.py`
- Modify: `bridge/webview/agent-native-home.js`

**Step 1: Write backend action test**

Create `tests/test_agent_native_action_execution.py`:

```python
import unittest

from fastapi.testclient import TestClient

from loom.brain import app


class AgentNativeActionExecutionTests(unittest.TestCase):
    def test_unconfirmed_execute_action_is_rejected(self):
        client = TestClient(app)

        response = client.post(
            "/agent-native/actions/run",
            json={
                "capability_id": "agent.run",
                "intent": "Inspect workspace",
                "confirmed": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "confirmation required")

    def test_resource_query_action_can_return_preview_without_confirmation(self):
        client = TestClient(app)

        response = client.post(
            "/agent-native/actions/run",
            json={
                "capability_id": "resource.query",
                "intent": "List available resources",
                "confirmed": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["capability_id"], "resource.query")
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_action_execution
```

Expected: FAIL with missing endpoint.

**Step 3: Add action request model and endpoint**

In `loom/brain.py`:

```python
class AgentNativeActionRequest(BaseModel):
    capability_id: str
    intent: str = ""
    payload: dict = {}
    confirmed: bool = False
```

Route:

```python
@app.post("/agent-native/actions/run")
async def agent_native_action_run(req: AgentNativeActionRequest):
    catalog = _agent_native_catalog()
    policy = _agent_native_policy()
    try:
        cap = catalog.get(req.capability_id)
    except KeyError:
        return {"ok": False, "error": f"unknown capability: {req.capability_id}"}
    if policy.requires_confirmation(cap) and not req.confirmed:
        return {"ok": False, "error": "confirmation required", "capability_id": cap.id}

    # First iteration: only read/preview capabilities execute directly.
    if cap.id == "resource.query":
        return {
            "ok": True,
            "capability_id": cap.id,
            "result": {
                "message": "Resource query preview is available through existing resource endpoints.",
                "payload": req.payload,
            },
        }
    return {
        "ok": True,
        "capability_id": cap.id,
        "queued": True,
        "message": "Capability accepted for the agent-native runtime.",
    }
```

Do not run arbitrary agent processes in this task. The purpose is to establish confirmation and action plumbing.

**Step 4: Wire frontend actions**

In `bridge/webview/agent-native-home.js`, add action click handling after render:

```js
  async function runAction(root, action) {
    const confirmed = !action.requires_confirmation || window.confirm(action.label + ' requires confirmation. Continue?');
    const data = await fetchJson(API_BASE + '/agent-native/actions/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        capability_id: action.capability,
        intent: root.querySelector('[data-agent-native-intent]')?.value || '',
        payload: action.payload || {},
        confirmed
      })
    });
    const preview = root.querySelector('[data-loomlet-preview]');
    preview?.insertAdjacentHTML('beforeend', '<pre class="agent-native-action-result">' + esc(JSON.stringify(data, null, 2)) + '</pre>');
  }
```

In `renderLoomlet`, after setting `preview.innerHTML`, bind buttons by passing actions or store the latest loomlet on the root:

```js
    root.__latestLoomlet = loomlet;
```

After `renderLoomlet(root, data.loomlet)` in `compileIntent`, bind:

```js
    root.querySelectorAll('[data-loomlet-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = (root.__latestLoomlet?.actions || []).find((item) => item.id === btn.dataset.loomletAction);
        if (action) runAction(root, action).catch(console.error);
      });
    });
```

**Step 5: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_action_execution tests.test_brain_agent_native_routes
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS.

**Step 6: Commit**

```bash
git add loom/brain.py bridge/webview/agent-native-home.js tests/test_agent_native_action_execution.py
git commit -m "feat: add confirmed Loomlet capability actions"
```

---

### Task 12: Move From Fixed Route Thinking To Generated Loomlet Projections

**Files:**

- Modify: `bridge/webview/anchor-client.js`
- Modify: `bridge/webview/agent-native-home.js`
- Modify: `loom_core/agent_native/kernel.py`
- Create: `bridge/webview/loomlet-projection.test.cjs`

**Step 1: Add static projection tests**

Create `bridge/webview/loomlet-projection.test.cjs`:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('domain routes can be represented as Loomlet projections', () => {
  const client = read('bridge/webview/anchor-client.js');
  const home = read('bridge/webview/agent-native-home.js');

  assert.match(client, /data-loomlet-projection/);
  assert.match(client, /_renderDomainLoomletProjection/);
  assert.match(home, /Loomlet Preview/);
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test bridge/webview/loomlet-projection.test.cjs
```

Expected: FAIL.

**Step 3: Add route projection helper**

In `bridge/webview/anchor-client.js`, add a helper near domain render functions:

```js
  _renderDomainLoomletProjection(domain, cardsHtml) {
    return [
      '<section class="domain-loomlet-projection" data-loomlet-projection="' + _escHtml(domain) + '">',
      '  <header class="domain-loomlet-header">',
      '    <span>Generated Loomlet</span>',
      '    <strong>' + _escHtml(domain) + '</strong>',
      '  </header>',
      '  <div class="domain-loomlet-body">',
      cardsHtml,
      '  </div>',
      '</section>',
    ].join('');
  },
```

In `_renderBlogPage` or the equivalent domain page render, wrap `cardsHtml`:

```js
const projectedCardsHtml = this._renderDomainLoomletProjection(domain, cardsHtml);
```

Then render `projectedCardsHtml` instead of raw `cardsHtml`.

This does not change behavior yet. It creates a semantic bridge: fixed routes become Loomlet projections.

**Step 4: Run tests**

Run:

```bash
node --test bridge/webview/loomlet-projection.test.cjs bridge/webview/agent-native-home.test.cjs
```

Expected: PASS.

**Step 5: Commit**

```bash
git add bridge/webview/anchor-client.js bridge/webview/loomlet-projection.test.cjs
git commit -m "feat: mark domain pages as Loomlet projections"
```

---

### Task 13: Add Agent Runtime Observability To The UI

**Files:**

- Modify: `bridge/webview/agent-native-home.js`
- Modify: `bridge/webview/agent-native-home.css`
- Modify: `bridge/webview/agent-native-home.test.cjs`

**Step 1: Extend static test**

Add:

```js
test('agent-native home exposes live kernel and permission state', () => {
  const page = read('bridge/webview/agent-native-home.js');
  const css = read('bridge/webview/agent-native-home.css');

  assert.match(page, /data-agent-kernel-trace/);
  assert.match(page, /permission/);
  assert.match(css, /\.agent-kernel-trace/);
  assert.match(css, /\.permission-chip/);
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: FAIL.

**Step 3: Add trace panel markup**

In `shellHtml()` add inside `.agent-native-grid`:

```html
<section class="agent-kernel-trace" data-agent-kernel-trace>
  <h2>Kernel Trace</h2>
  <p>Compile an intent to see selected capabilities and permissions.</p>
</section>
```

In `compileIntent()`, after receiving data:

```js
renderKernelTrace(root, data.capability_plan || []);
```

Add:

```js
  function renderKernelTrace(root, plan) {
    const trace = root.querySelector('[data-agent-kernel-trace]');
    if (!trace) return;
    trace.innerHTML = [
      '<h2>Kernel Trace</h2>',
      '<ol>',
      plan.map((item) => [
        '<li>',
        '<strong>' + esc(item.label || item.id) + '</strong>',
        '<span class="permission-chip">' + esc(item.permission?.sandbox || item.safety || '') + '</span>',
        item.requires_confirmation ? '<span class="permission-chip permission-chip--confirm">confirm</span>' : '',
        '</li>',
      ].join('')).join(''),
      '</ol>',
    ].join('');
  }
```

**Step 4: Add CSS**

```css
.agent-kernel-trace {
  grid-column: 1 / -1;
  border: 1px solid rgba(18, 24, 38, 0.10);
  border-radius: 8px;
  background: rgba(255,255,255,0.78);
  padding: 14px;
}

.agent-kernel-trace h2 {
  margin: 0 0 10px;
  font-size: 15px;
}

.agent-kernel-trace ol {
  margin: 0;
  padding-left: 20px;
}

.permission-chip {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  margin-left: 8px;
  padding: 0 7px;
  border-radius: 8px;
  background: rgba(18,24,38,0.06);
  color: var(--fg-3);
  font-size: 11px;
}

.permission-chip--confirm {
  color: #8a4b00;
  background: rgba(244, 158, 11, 0.16);
}
```

**Step 5: Run tests**

Run:

```bash
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS.

**Step 6: Commit**

```bash
git add bridge/webview/agent-native-home.js bridge/webview/agent-native-home.css bridge/webview/agent-native-home.test.cjs
git commit -m "feat: show agent-native kernel trace"
```

---

### Task 14: Update Brain Presentation Contract For Agent-Native Output

**Files:**

- Modify: `loom_core/agents/core_agent.py`
- Modify: `tests/test_brain_presentation.py`

**Step 1: Add test expectations**

Open `tests/test_brain_presentation.py` and add an assertion to the existing presentation spec test, or create one:

```python
    def test_presentation_spec_names_agent_native_primitives(self):
        spec = LoomCoreAgent._build_presentation_spec(
            "Create a target tracker",
            {"domain": "target", "hands": ["target"]},
            {},
        )

        self.assertIn("agent_native", spec["ui_contract"])
        self.assertIn("capability_plan", spec["ui_contract"]["agent_native"])
        self.assertIn("loomlet", spec["ui_contract"]["agent_native"])
        self.assertIn("permission_envelope", spec["ui_contract"]["agent_native"])
```

**Step 2: Run test to verify it fails**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_brain_presentation
```

Expected: FAIL.

**Step 3: Add agent-native contract**

In `loom_core/agents/core_agent.py`, inside `_build_presentation_spec()["ui_contract"]`, add:

```python
"agent_native": {
    "capability_plan": "Brain selects typed capabilities before rendering or execution.",
    "loomlet": "User-facing surfaces are generated workspace units with manifest, state, actions, and required capabilities.",
    "permission_envelope": "Write, execute, external, and filesystem operations must carry explicit confirmation and audit metadata.",
    "state_frame": "Hands receive enough selected state to contribute raw material without owning the final UI.",
},
```

**Step 4: Run tests**

Run:

```bash
D:\conda\python.exe -m unittest tests.test_brain_presentation
```

Expected: PASS.

**Step 5: Commit**

```bash
git add loom_core/agents/core_agent.py tests/test_brain_presentation.py
git commit -m "feat: add agent-native presentation contract"
```

---

### Task 15: Document Migration From Traditional Modules To Agent-Native Primitives

**Files:**

- Create: `docs/agent-native-loom.md`

**Step 1: Write user-facing architecture doc**

Create:

```markdown
# Agent-Native Loom

Loom is moving from fixed app modules toward agent-native primitives.

## Old Model

- User chooses a route.
- Route loads a fixed page.
- Page calls Brain or a Hand.
- Result is rendered into a card.
- Settings panels configure infrastructure.

## New Model

- User states an intent.
- Agent Kernel compiles a capability plan.
- Permission envelopes make access explicit.
- Agents execute through adapters and Hands.
- Loom renders a Loomlet: a generated workspace surface with actions and state.
- Fixed routes become reusable projections, not product boundaries.

## Primitives

- Capability
- Permission Envelope
- Loomlet
- Agent Kernel
- Capability Dock
- State Frame

## Migration Rule

When adding new Loom behavior, do not start by adding a route or settings panel.
Start by asking:

1. What capability does this expose?
2. Which agent can use it?
3. What permission envelope does it require?
4. What Loomlet or workspace projection should show the result?
5. What state should be observable and replayable?
```

**Step 2: Verify doc exists**

Run:

```bash
Get-Item docs/agent-native-loom.md
```

Expected: file exists.

**Step 3: Commit**

```bash
git add docs/agent-native-loom.md
git commit -m "docs: explain agent-native Loom primitives"
```

---

## Design Decisions

### ADR: Capability Plane Over Rewrite

Use a capability plane over the current Brain/Hand runtime rather than rewriting Loom as a full OS shell.

Rationale:

- Existing adapters already provide the execution substrate.
- Existing generated cards already provide a rendering substrate.
- Existing social/direct-agent paths already prove agents can be direct executors.
- A rewrite would delay the product shift and increase safety risk.

### ADR: Loomlet Instead Of App Plugin

Use Loomlet manifests instead of app plugins.

Rationale:

- A plugin model recreates traditional software engineering boundaries.
- A Loomlet can be generated, patched, replayed, and scoped by permission envelopes.
- Existing fixed pages can be wrapped as Loomlet projections during migration.

### ADR: Confirmation At Capability Boundary

Ask for confirmation at the capability boundary, not inside each adapter.

Rationale:

- Users need one consistent mental model.
- Agents should receive already-scoped permissions.
- Adapters can still enforce lower-level sandboxing.

## Implementation Order

1. Record the architectural decision.
2. Add capability catalog model and tests.
3. Expose capability APIs in Brain.
4. Add Loomlet model.
5. Add deterministic intent compiler.
6. Add agent-native home route.
7. Add permission envelopes.
8. Project Hands into the capability catalog.
9. Wire confirmed Loomlet actions.
10. Wrap domain pages as Loomlet projections.
11. Show kernel trace and permissions in the UI.
12. Update Brain presentation contract and docs.

## Verification

Run focused tests after each task:

```bash
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
D:\conda\python.exe -m unittest tests.test_agent_native_loomlet
D:\conda\python.exe -m unittest tests.test_agent_native_kernel
D:\conda\python.exe -m unittest tests.test_agent_native_permissions
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes
node --test bridge/webview/agent-native-home.test.cjs
node --test bridge/webview/loomlet-projection.test.cjs
```

Run the broader regression set before finishing:

```bash
D:\conda\python.exe -m unittest discover tests
node --test bridge/webview/*.test.cjs
```

Manual verification:

- Open Loom.
- Navigate to the Agent Native route.
- Confirm the Capability Dock loads from Brain.
- Compile: `Create an interactive NVDA target tracker`.
- Confirm a Loomlet preview appears.
- Confirm Kernel Trace shows capabilities and permission envelopes.
- Confirm read-only capabilities run without confirmation.
- Confirm write/execute capabilities ask for confirmation.
- Confirm existing `market`, `position`, `target`, and `sentiment` routes still work.

## Risks

- **Generated UI safety:** Loomlet HTML must stay sanitized. No script tags or inline handlers in this phase.
- **Permission confusion:** Users must see exactly why a capability needs confirmation.
- **Adapter overreach:** `agent.run` must not become a backdoor to unrestricted filesystem/network access.
- **Route duplication:** Agent-native route should not become another dashboard. It must demonstrate intent-to-capability-to-Loomlet.
- **Over-abstracting too early:** Keep the first compiler deterministic and small; add LLM planning only after the catalog, permissions, and UI are stable.

## Definition Of Done

- Loom has an explicit agent-native ADR.
- Brain exposes capability and policy APIs.
- A deterministic Agent Kernel compiles intent into capability plans and Loomlet previews.
- The webview has an Agent Native route with Capability Dock, Loomlet Preview, and Kernel Trace.
- Existing Hands and adapters appear as capabilities.
- Permission envelopes are shown and enforced for Loomlet actions.
- Existing routes and generated cards continue to work.
- Tests listed above pass.
