# Loom Python Core / Loom Fin Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Loom 重构为 Python-first 的本地单用户 Core + 独立 Loom Fin task pack，并通过 adapter/interface 把 Fin 任务路由到具体外部 agent，同时不破坏现有交互、UI、配色和具体功能。

**Architecture:** Core 只负责 human-agent 交互协议、task routing、workspace/render/harness 和本地服务生命周期；同时在 Core 内部预留一个可选的 Loom Core Agent 层，用于异步、高阶、推理类能力，但它不能阻塞主路径。Fin 只声明任务、路由和领域约束，不承载 Core 实现。JavaScript 只保留 Electron/webview/gateway 兼容层。所有新增能力先落在 Python，现有可用交互路径必须保持可运行，迁移期间以兼容层和回归测试为主，不做大爆炸重写。

**Tech Stack:** Python 3.11+, SQLite/JSONL 本地存储, unittest, Node.js 兼容层, existing `bridge/` + `mcp/` gateway, current webview assets and styles.

---

### Task 1: Freeze compatibility contracts and protect the current experience

**Files:**
- Modify: `tests/test_domain_registry.py`
- Modify: `tests/test_task_routing.py`
- Modify: `tests/test_interaction_protocol.py`
- Modify: `tests/test_agent_adapters.py`
- Modify: `mcp/domain-manifest.test.cjs`
- Modify: `bridge/webview/styles.regression.test.cjs`

**Step 1: Write the failing regression tests**

Add checks for the contract we must not break:
- `domains/loom-fin/manifest.json` must keep `interface: "loom-agent-adapter"`.
- `agentTasks` must still map finance tasks to concrete agents and adapters.
- `HumanIntentEnvelope` must still normalize the current ops and anchor-related fields.
- Adapter registry must resolve by id and capability.
- The existing CSS templates, color system, and `data-anc` / `data-handles` semantics must remain unchanged.

**Step 2: Run the focused tests**

Run:
```powershell
D:\conda\python.exe -m unittest tests.test_domain_registry tests.test_task_routing tests.test_interaction_protocol tests.test_agent_adapters -v
node --test mcp/domain-manifest.test.cjs
node --test bridge/webview/styles.regression.test.cjs
```

Expected: the tests either fail on missing coverage or pass only after the required contract checks are in place.

**Step 3: Tighten assertions only, do not widen behavior**

Keep these tests focused on compatibility and routing. Do not add new product behavior here.

**Step 4: Commit**

Commit message:
```bash
git add tests/test_domain_registry.py tests/test_task_routing.py tests/test_interaction_protocol.py tests/test_agent_adapters.py mcp/domain-manifest.test.cjs bridge/webview/styles.regression.test.cjs
git commit -m "test: lock loom core fin compatibility contracts"
```

---

### Task 2: Build the Python local Core runtime

**Files:**
- Create: `loom_core/runtime/app.py`
- Create: `loom_core/runtime/http_api.py`
- Create: `loom_core/runtime/state.py`
- Create: `loom_core/agents/core_agent.py`
- Create: `loom_core/storage/__init__.py`
- Create: `loom_core/storage/sqlite_store.py`
- Create: `loom_core/storage/event_log.py`
- Create: `loom_core/runtime/core_agent_bridge.py`
- Modify: `loom_core/runtime/__init__.py`
- Modify: `loom_core/README.md`
- Test: `tests/test_runtime_bootstrap.py`
- Test: `tests/test_storage.py`
- Test: `tests/test_core_agent_reserve.py`

**Step 1: Write failing tests for startup and storage**

Cover these behaviors:
- The Core runtime can boot locally without a remote service.
- The runtime exposes a minimal health/status surface.
- Local storage can append interaction events and reload them.
- The runtime can load domain manifests and expose them to the rest of Core.
- The Core runtime exposes a non-blocking hook for an internal Loom Core Agent, but the runtime must still work when the agent is absent.

**Step 2: Run the new tests and confirm the missing implementation**

Run:
```powershell
D:\conda\python.exe -m unittest tests.test_runtime_bootstrap tests.test_storage -v
```

**Step 3: Implement the smallest working runtime**

Start with:
- config loading
- manifest loading
- local storage initialization
- health endpoint or status function
- no UI changes yet

**Step 4: Re-run tests**

Run:
```powershell
D:\conda\python.exe -m unittest tests.test_runtime_bootstrap tests.test_storage -v
D:\conda\python.exe -m unittest discover tests -v
```

Expected: runtime bootstrap, storage, and Core Agent reserve tests pass; existing tests remain green.

**Step 5: Commit**

```bash
git add loom_core/runtime/app.py loom_core/runtime/http_api.py loom_core/runtime/state.py loom_core/agents/core_agent.py loom_core/storage/__init__.py loom_core/storage/sqlite_store.py loom_core/storage/event_log.py loom_core/runtime/core_agent_bridge.py loom_core/runtime/__init__.py loom_core/README.md tests/test_runtime_bootstrap.py tests/test_storage.py tests/test_core_agent_reserve.py
git commit -m "feat: add python loom core runtime foundation"
```

---

### Task 3: Implement the agent adapter boundary

**Files:**
- Modify: `loom_core/agent_adapters/base.py`
- Modify: `loom_core/agent_adapters/registry.py`
- Create: `loom_core/agent_adapters/process_adapter.py`
- Create: `loom_core/agent_adapters/providers/__init__.py`
- Create: `loom_core/agent_adapters/providers/codex.py`
- Create: `loom_core/agent_adapters/providers/cc.py`
- Create: `loom_core/agent_adapters/providers/openclaw.py`
- Create: `loom_core/agent_adapters/providers/herms.py`
- Create: `loom_core/agent_adapters/providers/opencode.py`
- Test: `tests/test_agent_process_adapter.py`
- Test: `tests/test_agent_provider_registry.py`

**Step 1: Write failing tests for adapter selection and invocation**

Add tests for:
- resolving an adapter by explicit id
- resolving an adapter by capability when id is absent
- rejecting unknown adapters cleanly
- streaming agent events from a fake external process adapter

**Step 2: Run the focused adapter tests**

Run:
```powershell
D:\conda\python.exe -m unittest tests.test_agent_process_adapter tests.test_agent_provider_registry -v
```

**Step 3: Implement the generic adapter wrapper first**

Build a single process-based adapter abstraction that can:
- launch an external agent worker
- pass the task envelope through stdin or a temp file
- stream events back into Core
- cancel the run

Only after the generic adapter works, add thin provider wrappers for `codex`, `cc`, `openclaw`, `herms`, and `opencode`.

**Step 4: Re-run all Python tests**

Run:
```powershell
D:\conda\python.exe -m unittest discover tests -v
```

**Step 5: Commit**

```bash
git add loom_core/agent_adapters/base.py loom_core/agent_adapters/registry.py loom_core/agent_adapters/process_adapter.py loom_core/agent_adapters/providers/__init__.py loom_core/agent_adapters/providers/codex.py loom_core/agent_adapters/providers/cc.py loom_core/agent_adapters/providers/openclaw.py loom_core/agent_adapters/providers/herms.py loom_core/agent_adapters/providers/opencode.py tests/test_agent_process_adapter.py tests/test_agent_provider_registry.py
git commit -m "feat: add external agent adapter boundary"
```

---

### Task 4: Route Loom Fin tasks to concrete external agents

**Files:**
- Modify: `domains/loom-fin/manifest.json`
- Modify: `domains/loom-fin/README.md`
- Modify: `loom_core/runtime/task_router.py`
- Modify: `loom_core/domain_sdk/registry.py`
- Test: `tests/test_domain_registry.py`
- Test: `tests/test_task_routing.py`

**Step 1: Write routing tests that reflect the real model**

Cover the model the user already corrected:
- Fin tasks are declared in the task pack.
- Core resolves a task to a concrete agent and adapter.
- Core does not mount or import Fin implementation code.
- The task route must keep the existing finance capability names stable.

**Step 2: Run routing tests**

Run:
```powershell
D:\conda\python.exe -m unittest tests.test_domain_registry tests.test_task_routing -v
```

**Step 3: Implement task resolution and validation**

Keep the manifest-driven routing simple:
- load task pack manifest
- resolve task id
- resolve adapter id
- validate the contract before dispatch
- return a normalized route object for the runtime

**Step 4: Re-run the full Python suite**

Run:
```powershell
D:\conda\python.exe -m unittest discover tests -v
```

**Step 5: Commit**

```bash
git add domains/loom-fin/manifest.json domains/loom-fin/README.md loom_core/runtime/task_router.py loom_core/domain_sdk/registry.py tests/test_domain_registry.py tests/test_task_routing.py
git commit -m "feat: route loom fin tasks through concrete agents"
```

---

### Task 5: Shrink JavaScript to a compatibility gateway only

**Files:**
- Modify: `mcp/server.cjs`
- Modify: `bridge/server.js`
- Modify: `bridge/webview/anchor-client.js`
- Modify: `mcp/shim.cjs`
- Test: `mcp/domain-manifest.test.cjs`

**Step 1: Add regression coverage before changing gateway code**

Protect the existing browser/webview paths, anchor behavior, and manifest exposure.

**Step 2: Move new behavior out of JS**

Keep JS limited to:
- serving the existing webview
- preserving current routes
- forwarding to Python Core
- compatibility for `/op`, `/patch`, `/html`, and workspace-related traffic

Do not reintroduce finance logic into `mcp/server.cjs`.

**Step 3: Verify Node compatibility**

Run:
```powershell
node --test mcp/domain-manifest.test.cjs
node --check mcp/server.cjs
```

**Step 4: Commit**

```bash
git add mcp/server.cjs bridge/server.js bridge/webview/anchor-client.js mcp/shim.cjs mcp/domain-manifest.test.cjs
git commit -m "refactor: reduce js layer to compatibility gateway"
```

---

### Task 6: End-to-end smoke test the migrated boundary

**Files:**
- Modify: `docs/superpowers/specs/2026-05-29-loom-core-fin-architecture-design.md`
- Modify: `docs/plans/2026-05-29-loom-python-core-fin-split.md` if the implementation deviates in a controlled way
- Modify: `loom_core/README.md`
- Modify: `domains/loom-fin/README.md`
- Test: any end-to-end smoke test you add for the local runtime

**Step 1: Verify the current UI still behaves the same**

Check at least:
- existing webview loads
- current CSS templates still render
- existing workspace interactions still work
- anchor/patched content still updates
- finance task routing still reaches a concrete adapter

**Step 2: Run the full verification set**

Run:
```powershell
D:\conda\python.exe -m unittest discover tests -v
node --test mcp/domain-manifest.test.cjs
node --check mcp/server.cjs
```

**Step 3: Only after all checks pass, mark the migration slice complete**

Do not claim completion until the runtime, routing, gateway, and regression checks are all green.

**Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-29-loom-core-fin-architecture-design.md docs/plans/2026-05-29-loom-python-core-fin-split.md loom_core/README.md domains/loom-fin/README.md
git commit -m "docs: finalize loom core fin migration plan"
```

---

## Execution Rules

- 每个 task 先写测试，再补实现。
- 每次只改一个边界层，不同时改 Core、Fin、gateway 和 UI。
- 不改变现有配色、组件风格和具体交互行为。
- 任何 Fin 逻辑都必须通过 adapter/interface 进入 Core，不能反向依赖 Core 内部实现。
- 每个 task 完成后都跑最小验证，再跑全量回归。
- 每个阶段都保留可回滚的提交点。
