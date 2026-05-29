# Loom Core / Loom Fin Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **Status:** Superseded by `docs/superpowers/plans/2026-05-29-loom-python-core-fin-split.md`. The original plan assumed new Core packages would be implemented in Node/CommonJS. The current architecture directive is Python-first Core, with JavaScript reserved for Electron/webview and local service gateway compatibility.

**Goal:** Separate Loom Core from Loom Fin without breaking the existing interaction loop, CSS templates, UI design, color system, or concrete product functions.

**Architecture:** Use a compatibility-first modular monolith. First introduce domain-pack metadata and adapter/protocol boundaries while all existing routes and files keep working. Only after behavior is covered by tests should finance-specific code move behind `domains/loom-fin`.

**Tech Stack:** Node.js CommonJS runtime, vanilla webview JavaScript/CSS, Electron shell, JSON manifests, Node built-in test runner.

---

## Ground Rules

- Do not rewrite UI styling as part of this split.
- Do not change `data-anc`, `data-handles`, patch semantics, or existing route behavior.
- Do not move working finance files until compatibility imports or route adapters exist.
- Commit only files touched for the current task.
- Run focused verification after each task.

## Task 1: Add Loom Fin Domain Manifest

**Files:**
- Create: `domains/loom-fin/manifest.json`
- Create: `domains/loom-fin/README.md`
- Test: `mcp/domain-manifest.test.cjs`

**Step 1: Write the failing manifest test**

Create `mcp/domain-manifest.test.cjs`:

```js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const manifestPath = path.join(ROOT, 'domains', 'loom-fin', 'manifest.json');

test('loom-fin domain manifest declares current finance routes and capabilities', () => {
  assert.equal(fs.existsSync(manifestPath), true);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

  assert.equal(manifest.id, 'loom-fin');
  assert.equal(manifest.runtime, 'local-desktop-single-user');
  assert.deepEqual(manifest.compatibility.preserveExistingExperience, true);

  for (const route of ['overview', 'market', 'target', 'sentiment', 'position', 'trading.private']) {
    assert.ok(manifest.routes.includes(route), `missing route ${route}`);
  }

  for (const capability of [
    'market.regime.review',
    'ticker.thesis.review',
    'sentiment.scan',
    'position.review',
    'thesis.debate'
  ]) {
    assert.ok(manifest.capabilities.includes(capability), `missing capability ${capability}`);
  }
});
```

**Step 2: Run test to verify it fails**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: FAIL because `domains/loom-fin/manifest.json` does not exist.

**Step 3: Create the manifest and README**

Create `domains/loom-fin/manifest.json`:

```json
{
  "id": "loom-fin",
  "name": "Loom Fin",
  "runtime": "local-desktop-single-user",
  "version": "0.1.0",
  "description": "Finance domain pack for market judgment, target thesis tracking, sentiment scanning, and personal position review.",
  "routes": [
    "overview",
    "market",
    "target",
    "sentiment",
    "position",
    "trading.private"
  ],
  "capabilities": [
    "market.regime.review",
    "ticker.thesis.review",
    "sentiment.scan",
    "position.review",
    "thesis.debate"
  ],
  "compatibility": {
    "preserveExistingExperience": true,
    "preserveCssTemplates": true,
    "preserveUiDesign": true,
    "preserveColorSystem": true,
    "preserveConcreteFunctions": true
  },
  "paths": {
    "legacyPythonBrain": "../../loom",
    "legacyConnectors": "../../mcp/connectors",
    "legacyTrading": "../../trading",
    "legacyBranchPrompts": "../../branches",
    "resources": "./resources",
    "policies": "./policies",
    "ui": "./ui",
    "harness": "./harness",
    "agents": "./agents"
  }
}
```

Create `domains/loom-fin/README.md` explaining that this domain pack currently references legacy paths through compatibility metadata and does not move working files yet.

**Step 4: Run test to verify it passes**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- domains/loom-fin/manifest.json domains/loom-fin/README.md mcp/domain-manifest.test.cjs
git commit --only domains/loom-fin/manifest.json domains/loom-fin/README.md mcp/domain-manifest.test.cjs -m "feat: register loom fin domain manifest"
```

## Task 2: Add Domain Manifest Loader

**Files:**
- Create: `mcp/lib/domain-registry.cjs`
- Modify: `mcp/domain-manifest.test.cjs`

**Step 1: Extend test for loader behavior**

Add assertions that `loadDomainManifests()` returns the `loom-fin` manifest and preserves compatibility flags.

**Step 2: Run test to verify it fails**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: FAIL because `mcp/lib/domain-registry.cjs` does not exist.

**Step 3: Implement minimal loader**

Create a CommonJS module that:

- Reads `domains/*/manifest.json`.
- Parses valid JSON manifests.
- Ignores folders without manifests.
- Exposes `loadDomainManifests(rootDir)`.
- Does not mount routes or change server behavior yet.

**Step 4: Run test to verify it passes**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- mcp/lib/domain-registry.cjs mcp/domain-manifest.test.cjs
git commit --only mcp/lib/domain-registry.cjs mcp/domain-manifest.test.cjs -m "feat: add local domain manifest loader"
```

## Task 3: Surface Domain Metadata Without Changing Existing Routes

**Files:**
- Modify: `mcp/server.cjs`
- Test: `mcp/domain-manifest.test.cjs`

**Step 1: Add route contract test**

Add a test for a pure helper in `domain-registry.cjs`, such as `buildDomainManifestResponse(manifests)`, to avoid starting the server.

**Step 2: Run test to verify it fails**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: FAIL because the helper does not exist.

**Step 3: Add helper and mount read-only route**

Add a read-only route to `mcp/server.cjs`:

```text
GET /domains -> { ok: true, domains: [...] }
```

This route must not replace current finance routes.

**Step 4: Run focused tests**

Run: `node --test mcp/domain-manifest.test.cjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- mcp/lib/domain-registry.cjs mcp/server.cjs mcp/domain-manifest.test.cjs
git commit --only mcp/lib/domain-registry.cjs mcp/server.cjs mcp/domain-manifest.test.cjs -m "feat: expose registered loom domains"
```

## Task 4: Add Interaction Protocol Package Skeleton

**Files:**
- Create: `packages/interaction-protocol/index.cjs`
- Create: `packages/interaction-protocol/README.md`
- Test: `packages/interaction-protocol/interaction-protocol.test.cjs`

**Step 1: Write tests for envelope validation**

Test that `normalizeHumanIntentEnvelope()` preserves known fields and rejects missing `op`.

**Step 2: Run test to verify it fails**

Run: `node --test packages/interaction-protocol/interaction-protocol.test.cjs`

Expected: FAIL because the module does not exist.

**Step 3: Implement minimal normalizer**

Create a small helper only. Do not route production traffic through it yet.

**Step 4: Run test to verify it passes**

Run: `node --test packages/interaction-protocol/interaction-protocol.test.cjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- packages/interaction-protocol
git commit --only packages/interaction-protocol -m "feat: add interaction protocol package skeleton"
```

## Task 5: Add Agent Adapter Contract Skeleton

**Files:**
- Create: `packages/agent-adapters/index.cjs`
- Create: `packages/agent-adapters/README.md`
- Test: `packages/agent-adapters/agent-adapters.test.cjs`

**Step 1: Write adapter registry tests**

Test registering a `legacy-inproc` adapter with capabilities and resolving it by capability.

**Step 2: Run test to verify it fails**

Run: `node --test packages/agent-adapters/agent-adapters.test.cjs`

Expected: FAIL because the module does not exist.

**Step 3: Implement registry only**

Create `createAdapterRegistry()` with `register(adapter)`, `list()`, and `findByCapability(capability)`.

Do not replace `mcp/inproc-agent.cjs` yet.

**Step 4: Run test to verify it passes**

Run: `node --test packages/agent-adapters/agent-adapters.test.cjs`

Expected: PASS.

**Step 5: Commit**

```bash
git add -- packages/agent-adapters
git commit --only packages/agent-adapters -m "feat: add agent adapter registry skeleton"
```

## Task 6: Compatibility Verification

**Files:**
- No source changes unless a regression is found.

**Step 1: Run focused tests**

Run:

```bash
node --test mcp/domain-manifest.test.cjs
node --test packages/interaction-protocol/interaction-protocol.test.cjs
node --test packages/agent-adapters/agent-adapters.test.cjs
node --test bridge/webview/styles.regression.test.cjs
node --test mcp/test-envelope.cjs
```

Expected: all available tests pass.

**Step 2: Run build if dependencies are installed**

Run: `npm run build`

Expected: build exits 0. If dependencies are missing in the current workspace, install or report the blocker before claiming build verification.

**Step 3: Manual smoke check if server dependencies are available**

Start server with existing command and confirm:

- Webview loads.
- Existing handles appear.
- Existing finance routes still render.
- `/domains` returns `loom-fin`.

**Step 4: Commit any verification-only doc update if needed**

Only commit if verification reveals a necessary docs clarification.
