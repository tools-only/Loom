# Loom Python Core / Loom Fin Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move Loom toward a Python-first Core framework that connects finance tasks to concrete external agents through Loom adapters/interfaces while preserving the existing webview interaction, CSS templates, UI design, color system, and concrete product functions.

**Architecture:** Python owns Core runtime, harness, protocol models, task registry, storage, and agent adapters. JavaScript remains the Electron/webview/gateway layer for serving UI, forwarding HTTP/WebSocket messages, and preserving legacy routes during migration. Loom Fin tasks are not mounted into Core; each Fin task is assigned to a concrete cc/codex/openclaw/herms/opencode agent and connected to Loom through an adapter/interface.

**Tech Stack:** Python 3, standard-library dataclasses/typing/json/pathlib/unittest, optional FastAPI later for the Python daemon, existing Node/Electron/webview JavaScript only as compatibility service and UI shell.

---

## Ground Rules

- New Loom Core framework code goes under `loom_core/` in Python.
- Fin-specific work enters Loom as task envelopes routed to concrete external agents.
- Do not add Fin business logic to `loom_core/`.
- JavaScript changes are allowed only for gateway compatibility, Electron/webview UI, or preserving existing routes.
- Do not rewrite CSS templates, UI kits, spacing, typography, color tokens, or component treatments.
- Do not change existing `data-anc`, `data-handles`, patch semantics, or current route behavior.
- Do not move working finance files until compatibility wrappers and focused tests exist.
- Commit only files touched for the current task. Avoid `git commit --only` for files that already have unrelated working-tree changes.

## Task 1: Keep Loom Fin Task Manifest

**Files:**
- Existing: `domains/loom-fin/manifest.json`
- Existing: `domains/loom-fin/README.md`
- Existing: `mcp/domain-manifest.test.cjs`

**Purpose:** The Loom Fin manifest remains valid as a compatibility boundary. It records current Fin routes/capabilities and declares agent-routable tasks without moving working code into Core.

**Verification:**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: PASS.

## Task 2: Add Python Domain Registry

**Files:**
- Create: `loom_core/__init__.py`
- Create: `loom_core/domain_sdk/__init__.py`
- Create: `loom_core/domain_sdk/registry.py`
- Test: `tests/loom_core/test_domain_registry.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from loom_core.domain_sdk.registry import load_domain_manifests, build_domain_manifest_response


def test_loads_loom_fin_manifest():
    root = Path(__file__).resolve().parents[2]
    manifests = load_domain_manifests(root)
    loom_fin = next(item for item in manifests if item["id"] == "loom-fin")

    assert loom_fin["runtime"] == "local-desktop-single-user"
    assert loom_fin["compatibility"]["preserveExistingExperience"] is True
    assert "market.regime.review" in loom_fin["capabilities"]


def test_public_response_omits_manifest_path():
    root = Path(__file__).resolve().parents[2]
    response = build_domain_manifest_response(load_domain_manifests(root))

    assert response["ok"] is True
    loom_fin = next(item for item in response["domains"] if item["id"] == "loom-fin")
    assert "manifest_path" not in loom_fin
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.loom_core.test_domain_registry`

Expected: FAIL because `loom_core.domain_sdk.registry` does not exist.

**Step 3: Implement minimal Python registry**

`load_domain_manifests(root_dir)` should:

- Read `domains/*/manifest.json`.
- Return parsed dictionaries.
- Attach internal `manifest_path` for Core use.
- Ignore directories without manifests.

`build_domain_manifest_response(manifests)` should:

- Return `{ "ok": True, "domains": [...] }`.
- Remove internal `manifest_path` from public output.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.loom_core.test_domain_registry`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- loom_core tests/loom_core/test_domain_registry.py
git commit -m "feat: add python domain registry"
```

## Task 3: Add Python Interaction Protocol Models

**Files:**
- Create: `loom_core/interaction_protocol/__init__.py`
- Create: `loom_core/interaction_protocol/envelope.py`
- Test: `tests/loom_core/test_interaction_protocol.py`

**Step 1: Write failing tests**

Test that a human intent envelope:

- Requires `op`.
- Preserves `workspace_id`, `target_anchor`, `instruction`, `domain`, and `selection`.
- Supports current operation names used by the webview.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.loom_core.test_interaction_protocol`

Expected: FAIL because the module does not exist.

**Step 3: Implement minimal dataclass and normalizer**

Create a Python dataclass for `HumanIntentEnvelope` and a `normalize_human_intent_envelope(raw)` helper.

Do not route production traffic through it yet.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.loom_core.test_interaction_protocol`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- loom_core/interaction_protocol tests/loom_core/test_interaction_protocol.py
git commit -m "feat: add python interaction protocol models"
```

## Task 4: Add Python Agent Adapter Contract

**Files:**
- Create: `loom_core/agent_adapters/__init__.py`
- Create: `loom_core/agent_adapters/base.py`
- Create: `loom_core/agent_adapters/registry.py`
- Test: `tests/loom_core/test_agent_adapters.py`

**Step 1: Write failing registry tests**

Test that a registry can:

- Register an adapter with capabilities.
- List registered adapters.
- Resolve adapters by capability.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.loom_core.test_agent_adapters`

Expected: FAIL because the modules do not exist.

**Step 3: Implement minimal Protocol and registry**

Use Python `typing.Protocol` for `AgentAdapter`.

The registry should not spawn any external agents yet.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.loom_core.test_agent_adapters`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- loom_core/agent_adapters tests/loom_core/test_agent_adapters.py
git commit -m "feat: add python agent adapter contract"
```

## Task 5: Add Python Core README

**Files:**
- Create: `loom_core/README.md`

Document:

- Python owns Core.
- JS is gateway/UI compatibility only.
- Loom Fin is a task pack whose tasks are routed to concrete external agents.
- Existing behavior and visual design are protected.

**Verification:**

Run all Python tests:

```bash
python -m unittest discover tests
```

Expected: PASS.
