# Loom Agent-Native VibeOS Shift Implementation Plan（中文）

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 Loom 从“带 AI 按钮的软件”转向“以 agent 能力为原生系统原语的工作空间”，让 Capability、Loomlet、Agent Kernel、Permission Envelope 成为产品和架构的一等概念。

**Architecture:** 保留现有 Brain / Hand / Adapter 栈，在其上增加 agent-native capability plane。Brain 从传统“路由 + 编排服务”升级为 Agent Kernel：把用户意图编译为能力计划，通过权限信封约束执行，再把结果投影为可交互 Loomlet，而不是预先写死的页面模块。

**Tech Stack:** Python 3.11 `dataclasses` / `unittest`，`loom/brain.py` FastAPI 路由，`loom_core/agent_adapters/*` 现有 agent runtime，`loom_core/agents/core_agent.py` Brain 编排，`bridge/webview/*` vanilla JS/CSS，Node `node:test`。

---

## 1. 背景与启发

参考对象：https://vibeos.sh/

这份计划不是要把 Loom 变成一个真正的桌面操作系统，也不是复制 VibeOS 的外壳。真正值得吸收的是它的产品范式：

- Agent 不是插件，而是系统的主要交互层和执行层。
- 用户不是先打开固定 app，再找 AI 功能；用户直接表达意图，系统围绕这个意图生成可操作界面。
- 工具、浏览器、MCP、文件、权限、状态都应该成为 agent 可发现、可调用、可审计的系统能力。
- Prompt 可以即时变成屏幕上的 workspace / app / view。
- 沙箱和权限不应该藏在设置里，而应该是每次能力调用的显式合同。

Loom 的方向应该是：面向投研、工作流和可视化生成的 agent-native workspace。固定页面、固定 domain、固定设置面板都只是投影，不再是系统边界。

---

## 2. 当前 Loom 的基础

Loom 已经有一些非常接近 agent-native 的能力：

- `loom_core/agent_adapters/registry.py` 已经有 adapter registry 和 capability lookup。
- `loom_core/agent_service.py` 可以运行不受 Hand artifact contract 限制的 full agent session。
- `loom/brain.py` 已经注册 SDK、process、Codex、cloud、dynamic adapter。
- `docs/loom-social-and-agent-adapters.md` 已经描述 direct-agent execution 和 adapter registration。
- `loom_core/agents/core_agent.py` 事实上已经接近 Brain agent：解析 workflow、拆任务、调度 Hands、review、synthesize、记录 episode。
- `bridge/webview/anchor-client.js` 已经能接收 agent event，并 patch 生成页面。
- 之前的计划 `docs/plans/2026-07-01-loom-clickable-card-home-detail-pages.md` 已经为“卡片首页 -> 页面级浮窗 -> 分层内容”提供了视觉骨架。

但当前体验仍然太传统：

- 能力散落在 route、adapter、Hand、connector、prompt handler、settings panel、domain page 里。
- Agent runtime 更像基础设施配置，而不是 Loom 原生能力。
- 页面大多是固定 shell 调用 agent，而不是 agent 生成的 workspace 自己声明需要什么能力。
- Brain / Hand artifact 仍被当成最终产品输出，而不是 agent-native state 的一种投影。
- 权限和沙箱是 runtime 设置，不是用户可见的能力合同。

---

## 3. 核心产品判断

Loom 应该少一些“软件工程模块感”，多一些“agent-native 系统感”。

旧模型：

```text
用户选择 route
  -> 固定页面加载
  -> 页面调用 Brain / Hand
  -> 返回卡片
  -> 用户再通过按钮 refine / patch / route
```

新模型：

```text
用户表达意图
  -> Agent Kernel 编译 capability plan
  -> Permission Envelope 约束可读/可写/可执行范围
  -> agent 通过 adapter / Hand / tool / resource 执行
  -> Loom 渲染 Loomlet
  -> Loomlet 暴露动作、状态、证据、后续 agent 能力
```

关键变化：

- Hand 不再是产品模块边界，而是 capability provider。
- Route 不再是主要入口，而是 Loomlet projection。
- Connector 不再只是数据接口，而是 `resource.query` 等能力来源。
- Settings 不再是能力配置中心，而是 capability dock / permission envelope 的底层支撑。
- 生成内容不再只是 HTML，而是带 manifest、state、actions、permissions 的 Loomlet。

---

## 4. 新系统原语

### Capability

Capability 是 agent 可以发现和调用的系统能力。

例子：

- `agent.run`
- `workspace.patch`
- `ui.render`
- `resource.query`
- `browser.open`
- `mcp.invoke`
- `portfolio.read`
- `episode.replay`
- `social.reply`

每个 Capability 至少包含：

- `id`
- `label`
- `description`
- `provider`
- `safety`
- `intent_verbs`
- `tags`
- `input_schema`
- `output_schema`
- `render_hint`

### Permission Envelope

Permission Envelope 是能力调用前必须生成的权限合同。

它回答：

- 能否写 workspace？
- 能否访问网络？
- 能否调用外部工具？
- 是否需要用户确认？
- workspace root 是哪里？
- 数据范围是什么？
- 审计标签是什么？

### Loomlet

Loomlet 是 agent 生成的小型工作空间 / app surface。

它不是普通 HTML 片段，而是：

- `id`
- `title`
- `intent`
- `required_capabilities`
- `state`
- `html`
- `actions`
- `update_policy`

### Agent Kernel

Agent Kernel 是 Brain 面向 agent-native 体验的核心运行层。

职责：

- 将用户意图编译为 capability plan。
- 给每个 capability 分配 permission envelope。
- 选择 adapter / Hand / tool / resource。
- 生成 Loomlet。
- 观察用户交互。
- 将结果写入 episode / flywheel / workspace state。

### Capability Dock

Capability Dock 是用户看到 Loom 当前能做什么的界面。

它不是传统设置页，而是一个运行态能力面板：

- 当前有哪些 agent runtime。
- 当前有哪些 Hands。
- 当前有哪些 resource / connector。
- 哪些能力需要确认。
- 哪些能力能直接读。
- 哪些能力能 patch workspace。

### State Frame

State Frame 是 agent 可读的当前环境状态。

包括：

- 用户当前意图。
- 当前 Loomlet。
- 选中的内容。
- 页面锚点。
- 已完成/折叠内容。
- 当前 workspace 文件/资源。
- 最近 episode。
- 当前权限状态。

---

## 5. 非目标

本计划不做这些事：

- 不重写整个 Loom。
- 不删除现有 Brain / Hand / adapter。
- 不把 Loom 变成真实桌面 OS。
- 不让 agent 获得无限文件和网络权限。
- 不允许 generated UI 任意执行脚本。
- 不把 VibeOS 只当视觉风格来模仿。

本计划的重点是：先把 agent-native 的运行时原语放进去，然后逐步把现有页面和模块迁移成 projection。

---

## 6. 实施任务

### Task 1: 记录 agent-native 架构决策

**Files:**

- Create: `docs/architecture/adr-2026-07-02-agent-native-loom.md`

**Step 1: 创建 ADR**

写入：

```markdown
# ADR 2026-07-02: Agent-Native Loom

## Status

Proposed

## Context

Loom 已经拥有 Brain orchestration、Hand agents、runtime adapters、social ingress、
generated cards 和 webview patching。但产品表达仍然像传统软件：固定 route、固定
domain page、settings panel、connector UI 和 adapter 配置散落各处。

VibeOS 展示了更强的 AI-native 姿态：agent 是系统的原生交互层，用户用 prompt
直接生成和操作界面。Loom 应该吸收这种范式，但聚焦在投研和工作空间，而不是变成通用 OS。

## Decision

Loom 增加 agent-native capability plane：

- Capability 是 typed、discoverable、permissioned 的系统能力。
- Brain 成为 Agent Kernel，负责把 intent 编译为 capability plan。
- UI surface 以 Loomlet 形式生成，带 manifest、state、actions 和 permission。
- 固定 domain page 变成 projection，而不是系统边界。
- Permission envelope 和 audit trail 成为用户可见的运行时状态。

## Alternatives

1. 继续增加固定 domain page 和 settings panel。
   - Rejected：这会延续传统 app 模式，隐藏 agent 能力。

2. 重写 Loom 为桌面 OS shell。
   - Rejected：范围过大，风险高，也不符合 Loom 的工作空间定位。

3. 只做一个 VibeOS 风格首页。
   - Rejected：没有 runtime 原语支撑，只是视觉模仿。

## Consequences

Positive:

- 用户可以要求“生成一个工作空间”，而不是先选择模块。
- Agent 可以通过 typed capability catalog 选择工具和资源。
- 生成 UI 更安全，因为它显式声明所需能力和权限。
- 现有 Hands 和 adapters 会升级为 capability providers。

Negative:

- 运行时状态需要更多可视化和审计。
- Generated UI 需要更严格的隔离和测试。
- Brain 需要稳定的 intent -> capability -> Loomlet 中间表示。

## Guardrails

- 没有 permission envelope，不执行写入或外部操作。
- Generated UI 不允许任意 script。
- 网络、文件、外部工具访问必须显式。
- 迁移期间保留现有 Brain / Hand 流程。
```

**Step 2: 验证文件**

Run:

```powershell
Get-Item docs/architecture/adr-2026-07-02-agent-native-loom.md
```

Expected: 文件存在。

**Step 3: Commit**

```bash
git add docs/architecture/adr-2026-07-02-agent-native-loom.md
git commit -m "docs: record agent-native Loom architecture direction"
```

---

### Task 2: 增加 Capability Catalog 测试

**Files:**

- Create: `tests/test_agent_native_capabilities.py`
- Create later: `loom_core/agent_native/__init__.py`
- Create later: `loom_core/agent_native/capabilities.py`

**Step 1: 写失败测试**

测试目标：

- 内置能力包含 `agent.run`、`ui.render`、`workspace.patch`、`resource.query`、`episode.replay`。
- 现有 adapter 可以投影为 capability。
- 写入和执行类能力需要确认。
- 可以根据用户意图选择相关能力。

测试骨架：

```python
import unittest

from loom_core.agent_native.capabilities import (
    BUILTIN_CAPABILITIES,
    CapabilityCatalog,
    CapabilityPolicy,
)
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

        self.assertEqual(cap.provider, "codex-app-server")
        self.assertIn("runtime.hand", cap.tags)
        self.assertIn("workspace.patch", cap.tags)

    def test_policy_requires_confirmation_for_write_and_execute(self):
        policy = CapabilityPolicy.default()

        self.assertFalse(policy.requires_confirmation("resource.query"))
        self.assertTrue(policy.requires_confirmation("workspace.patch"))
        self.assertTrue(policy.requires_confirmation("agent.run"))
        self.assertTrue(policy.requires_confirmation("mcp.invoke"))
```

**Step 2: 验证失败**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
```

Expected: FAIL，因为 `loom_core.agent_native` 还不存在。

**Step 3: Commit**

```bash
git add tests/test_agent_native_capabilities.py
git commit -m "test: define agent-native capability catalog"
```

---

### Task 3: 实现 Capability Catalog

**Files:**

- Create: `loom_core/agent_native/__init__.py`
- Create: `loom_core/agent_native/capabilities.py`
- Test: `tests/test_agent_native_capabilities.py`

**Step 1: 创建 package**

`loom_core/agent_native/__init__.py`：

```python
"""Agent-native runtime primitives for Loom."""

from .capabilities import Capability, CapabilityCatalog, CapabilityPolicy

__all__ = ["Capability", "CapabilityCatalog", "CapabilityPolicy"]
```

**Step 2: 实现 Capability 数据模型**

`loom_core/agent_native/capabilities.py` 需要包含：

- `Capability`
- `BUILTIN_CAPABILITIES`
- `CapabilityCatalog`
- `CapabilityPolicy`

内置能力先保持小而稳定：

```python
BUILTIN_CAPABILITIES = (
    Capability(id="agent.run", ...),
    Capability(id="ui.render", ...),
    Capability(id="workspace.patch", ...),
    Capability(id="resource.query", ...),
    Capability(id="episode.replay", ...),
    Capability(id="mcp.invoke", ...),
)
```

`CapabilityCatalog.from_adapter_registry(registry)` 要把现有 adapter 变成：

```text
agent.adapter.<adapter_id>
```

例如：

```text
agent.adapter.codex-app-server
```

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_capabilities.py
git commit -m "feat: add agent-native capability catalog"
```

---

### Task 4: 在 Brain 暴露 Capability API

**Files:**

- Modify: `loom/brain.py`
- Create: `tests/test_brain_agent_native_routes.py`

**Step 1: 写 route 测试**

测试目标：

- `GET /agent-native/capabilities` 返回能力列表。
- `GET /agent-native/policy` 返回哪些能力需要确认。

测试示例：

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

**Step 2: 验证失败**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes
```

Expected: FAIL，路由不存在。

**Step 3: 实现路由**

在 `loom/brain.py` 引入：

```python
from loom_core.agent_native.capabilities import CapabilityCatalog, CapabilityPolicy
```

增加 helper：

```python
def _agent_native_catalog() -> CapabilityCatalog:
    return CapabilityCatalog.from_adapter_registry(_adapter_registry)


def _agent_native_policy() -> CapabilityPolicy:
    return CapabilityPolicy.default()
```

增加路由：

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

**Step 4: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities tests.test_brain_agent_native_routes
```

Expected: PASS。

**Step 5: Commit**

```bash
git add loom/brain.py tests/test_brain_agent_native_routes.py
git commit -m "feat: expose agent-native capability APIs"
```

---

### Task 5: 定义 Loomlet 作为生成 UI 原语

**Files:**

- Create: `loom_core/agent_native/loomlet.py`
- Modify: `loom_core/agent_native/__init__.py`
- Create: `tests/test_agent_native_loomlet.py`

**Step 1: 写测试**

测试目标：

- Loomlet 可以序列化 manifest、state、actions。
- 默认拒绝 `<script>` 和 inline event handler。
- Loomlet 必须声明 `ui.render`。

测试示例：

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

**Step 2: 实现 Loomlet**

`loom_core/agent_native/loomlet.py`：

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

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_loomlet tests.test_agent_native_capabilities
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_loomlet.py
git commit -m "feat: add Loomlet generated UI primitive"
```

---

### Task 6: 实现最小 Agent Kernel 编译器

**Files:**

- Create: `loom_core/agent_native/kernel.py`
- Create: `tests/test_agent_native_kernel.py`
- Modify: `loom_core/agent_native/__init__.py`

**Step 1: 写测试**

测试目标：

- 输入 intent，输出 capability plan 和 Loomlet。
- 写入能力带 confirmation 标记。
- 输出 HTML 包含 `data-loomlet-root`。

测试示例：

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

**Step 2: 实现确定性编译器**

`AgentKernel.compile_intent()` 第一版不要调用 LLM。先做确定性规则：

- intent 包含 `create/build/analyze/track/research` -> 加 `agent.run`
- intent 包含 `market/target/portfolio/sentiment/source/data/research` -> 加 `resource.query`
- intent 包含 `patch/modify/edit/update` -> 加 `workspace.patch`
- 永远加 `ui.render`

输出：

```json
{
  "ok": true,
  "intent": "...",
  "capability_plan": [...],
  "loomlet": {...}
}
```

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_kernel tests.test_agent_native_loomlet tests.test_agent_native_capabilities
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_kernel.py
git commit -m "feat: compile intent into Loomlet plans"
```

---

### Task 7: 在 Brain 暴露 intent compile API

**Files:**

- Modify: `loom/brain.py`
- Modify: `tests/test_brain_agent_native_routes.py`

**Step 1: 增加测试**

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

**Step 2: 实现 endpoint**

在 `loom/brain.py`：

```python
class AgentNativeCompileRequest(BaseModel):
    intent: str
    state_frame: dict = {}


@app.post("/agent-native/compile")
async def agent_native_compile(req: AgentNativeCompileRequest):
    kernel = AgentKernel(
        catalog=_agent_native_catalog(),
        policy=_agent_native_policy(),
    )
    return kernel.compile_intent(req.intent, req.state_frame)
```

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes tests.test_agent_native_kernel
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom/brain.py tests/test_brain_agent_native_routes.py
git commit -m "feat: expose agent-native intent compilation"
```

---

### Task 8: 增加 Agent-Native 首页 / 路由

**Files:**

- Create: `bridge/webview/agent-native-home.js`
- Create: `bridge/webview/agent-native-home.css`
- Create: `bridge/webview/agent-native-home.test.cjs`
- Modify: `bridge/webview/index.html`
- Modify: `bridge/webview/anchor-client.js`

**Step 1: 写静态测试**

测试目标：

- `index.html` 引入 agent-native CSS / JS。
- `anchor-client.js` 支持 `#agent-native` route。
- 页面 JS 调用 `/agent-native/capabilities` 和 `/agent-native/compile`。
- 页面包含 Capability Dock 和 Loomlet Preview。

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
```

**Step 2: 实现 webview 路由**

在 `index.html` 添加：

```html
<link rel="stylesheet" href="agent-native-home.css">
<script src="agent-native-home.js"></script>
```

在 `anchor-client.js` 的 route 分支中添加：

```js
} else if (route === 'agent-native') {
  this._showRouteShell(route);
  if (window.AgentNativeHome) window.AgentNativeHome.renderInto(this);
  this._updateToolbarTabs(route);
```

**Step 3: 实现页面**

`agent-native-home.js` 第一版包含：

- Intent input。
- Compile button。
- Capability Dock。
- Loomlet Preview。
- 调用 `http://localhost:3002/agent-native/capabilities`。
- 调用 `http://localhost:3002/agent-native/compile`。

**Step 4: CSS**

风格要求：

- 不做 landing hero。
- 第一屏就是可操作工作台。
- 卡片半径控制在 8px。
- Capability Dock 和 Loomlet Preview 并列。
- 移动端堆叠。

**Step 5: 跑测试**

Run:

```powershell
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS。

**Step 6: Commit**

```bash
git add bridge/webview/agent-native-home.js bridge/webview/agent-native-home.css bridge/webview/agent-native-home.test.cjs bridge/webview/index.html bridge/webview/anchor-client.js
git commit -m "feat: add agent-native Loom home route"
```

---

### Task 9: 增加 Permission Envelope

**Files:**

- Create: `loom_core/agent_native/permissions.py`
- Modify: `loom_core/agent_native/kernel.py`
- Create: `tests/test_agent_native_permissions.py`

**Step 1: 写测试**

测试目标：

- `resource.query` 默认 `read-only`，不需要确认。
- `workspace.patch` 默认 `workspace-write`，需要确认。
- `agent.run` 默认 `workspace-write`，需要确认。

```python
import unittest

from loom_core.agent_native.permissions import PermissionEnvelope


class AgentNativePermissionTests(unittest.TestCase):
    def test_permission_envelope_defaults_to_read_only_workspace(self):
        envelope = PermissionEnvelope.for_capability("resource.query")

        self.assertEqual(envelope.sandbox, "read-only")
        self.assertFalse(envelope.requires_confirmation)

    def test_permission_envelope_requires_confirmation_for_workspace_patch(self):
        envelope = PermissionEnvelope.for_capability("workspace.patch")

        self.assertEqual(envelope.sandbox, "workspace-write")
        self.assertTrue(envelope.requires_confirmation)

    def test_permission_envelope_requires_confirm_for_agent_run(self):
        envelope = PermissionEnvelope.for_capability("agent.run")

        self.assertEqual(envelope.sandbox, "workspace-write")
        self.assertTrue(envelope.requires_confirmation)
```

**Step 2: 实现权限信封**

`PermissionEnvelope` 字段：

- `capability_id`
- `sandbox`
- `data_scope`
- `network_scope`
- `requires_confirmation`
- `audit_tags`

在 `AgentKernel.compile_intent()` 输出的每个 capability plan item 中加入：

```python
"permission": PermissionEnvelope.for_capability(cap.id).to_json()
```

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_permissions tests.test_agent_native_kernel
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom_core/agent_native tests/test_agent_native_permissions.py tests/test_agent_native_kernel.py
git commit -m "feat: add permission envelopes to capability plans"
```

---

### Task 10: 将现有 Hands 投影为 Capabilities

**Files:**

- Modify: `loom_core/agent_native/capabilities.py`
- Modify: `loom/brain.py`
- Modify: `tests/test_agent_native_capabilities.py`
- Modify: `tests/test_brain_agent_native_routes.py`

**Step 1: 增加测试**

```python
    def test_catalog_can_register_hand_capabilities(self):
        catalog = CapabilityCatalog(BUILTIN_CAPABILITIES)

        catalog.register_hand("market", {"label": "Market", "capabilities": ["web_search", "market_data"]})

        cap = catalog.get("hand.market")
        self.assertEqual(cap.provider, "hand:market")
        self.assertIn("market_data", cap.tags)
        self.assertIn("analyze", cap.intent_verbs)
```

**Step 2: 实现 `register_hand`**

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

**Step 3: Brain catalog 合并当前 REGISTRY**

```python
def _agent_native_catalog() -> CapabilityCatalog:
    catalog = CapabilityCatalog.from_adapter_registry(_adapter_registry)
    for hand_id, info in REGISTRY.items():
        catalog.register_hand(hand_id, info if isinstance(info, dict) else {})
    return catalog
```

**Step 4: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities tests.test_brain_agent_native_routes
```

Expected: PASS。

**Step 5: Commit**

```bash
git add loom_core/agent_native/capabilities.py loom/brain.py tests/test_agent_native_capabilities.py tests/test_brain_agent_native_routes.py
git commit -m "feat: project Hands into agent-native capabilities"
```

---

### Task 11: 支持 Loomlet Action 的确认执行

**Files:**

- Modify: `loom/brain.py`
- Modify: `bridge/webview/agent-native-home.js`
- Create: `tests/test_agent_native_action_execution.py`

**Step 1: 写后端测试**

目标：

- 未确认的 execute / write action 拒绝。
- read-only action 可以直接返回 preview。

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

**Step 2: 实现 endpoint**

`loom/brain.py`：

```python
class AgentNativeActionRequest(BaseModel):
    capability_id: str
    intent: str = ""
    payload: dict = {}
    confirmed: bool = False


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

第一版不要真正执行任意 agent process。先建立确认和 action plumbing。

**Step 3: 前端确认**

在 `agent-native-home.js` 中：

- 对 `requires_confirmation` 的 action 使用 `window.confirm`。
- 调用 `/agent-native/actions/run`。
- 将结果追加到 Loomlet Preview。

**Step 4: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_action_execution tests.test_brain_agent_native_routes
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS。

**Step 5: Commit**

```bash
git add loom/brain.py bridge/webview/agent-native-home.js tests/test_agent_native_action_execution.py
git commit -m "feat: add confirmed Loomlet capability actions"
```

---

### Task 12: 把固定 Domain 页面标记为 Loomlet Projection

**Files:**

- Modify: `bridge/webview/anchor-client.js`
- Create: `bridge/webview/loomlet-projection.test.cjs`

**Step 1: 写静态测试**

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

  assert.match(client, /data-loomlet-projection/);
  assert.match(client, /_renderDomainLoomletProjection/);
});
```

**Step 2: 增加 helper**

在 `anchor-client.js`：

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
}
```

在 domain page render 中包一层：

```js
const projectedCardsHtml = this._renderDomainLoomletProjection(domain, cardsHtml);
```

这一步不改变行为，只改变语义：固定 route 变成 Loomlet projection。

**Step 3: 跑测试**

Run:

```powershell
node --test bridge/webview/loomlet-projection.test.cjs
```

Expected: PASS。

**Step 4: Commit**

```bash
git add bridge/webview/anchor-client.js bridge/webview/loomlet-projection.test.cjs
git commit -m "feat: mark domain pages as Loomlet projections"
```

---

### Task 13: 在 UI 中展示 Kernel Trace 与 Permission 状态

**Files:**

- Modify: `bridge/webview/agent-native-home.js`
- Modify: `bridge/webview/agent-native-home.css`
- Modify: `bridge/webview/agent-native-home.test.cjs`

**Step 1: 扩展测试**

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

**Step 2: 增加 Kernel Trace**

Agent Native Home 应显示：

- 被选中的 capabilities。
- 每个 capability 的 provider。
- 每个 capability 的 sandbox。
- 是否需要 confirmation。
- render hint。

前端结构：

```html
<section class="agent-kernel-trace" data-agent-kernel-trace>
  <h2>Kernel Trace</h2>
  <p>Compile an intent to see selected capabilities and permissions.</p>
</section>
```

**Step 3: 跑测试**

Run:

```powershell
node --test bridge/webview/agent-native-home.test.cjs
```

Expected: PASS。

**Step 4: Commit**

```bash
git add bridge/webview/agent-native-home.js bridge/webview/agent-native-home.css bridge/webview/agent-native-home.test.cjs
git commit -m "feat: show agent-native kernel trace"
```

---

### Task 14: 更新 Brain Presentation Contract

**Files:**

- Modify: `loom_core/agents/core_agent.py`
- Modify: `tests/test_brain_presentation.py`

**Step 1: 增加测试**

在 `tests/test_brain_presentation.py` 增加：

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

**Step 2: 更新 contract**

在 `loom_core/agents/core_agent.py` 的 `_build_presentation_spec()["ui_contract"]` 中加入：

```python
"agent_native": {
    "capability_plan": "Brain selects typed capabilities before rendering or execution.",
    "loomlet": "User-facing surfaces are generated workspace units with manifest, state, actions, and required capabilities.",
    "permission_envelope": "Write, execute, external, and filesystem operations must carry explicit confirmation and audit metadata.",
    "state_frame": "Hands receive enough selected state to contribute raw material without owning the final UI.",
},
```

**Step 3: 跑测试**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_presentation
```

Expected: PASS。

**Step 4: Commit**

```bash
git add loom_core/agents/core_agent.py tests/test_brain_presentation.py
git commit -m "feat: add agent-native presentation contract"
```

---

### Task 15: 增加中文架构说明文档

**Files:**

- Create: `docs/agent-native-loom.zh.md`

**Step 1: 写说明文档**

内容：

```markdown
# Agent-Native Loom

Loom 正在从固定 app 模块转向 agent-native primitives。

## 旧模型

- 用户选择 route。
- route 加载固定页面。
- 页面调用 Brain 或 Hand。
- 结果渲染为卡片。
- 设置面板配置基础设施。

## 新模型

- 用户表达 intent。
- Agent Kernel 编译 capability plan。
- Permission Envelope 显式约束权限。
- Agents 通过 adapters 和 Hands 执行。
- Loom 渲染 Loomlet：一个带 actions 和 state 的生成工作空间。
- 固定 route 成为 projection，而不是系统边界。

## 新原语

- Capability
- Permission Envelope
- Loomlet
- Agent Kernel
- Capability Dock
- State Frame

## 迁移规则

新增 Loom 行为时，不要先加 route 或 settings panel。先问：

1. 这暴露了什么 Capability？
2. 哪个 agent 能使用它？
3. 它需要什么 Permission Envelope？
4. 它应该渲染成什么 Loomlet 或 workspace projection？
5. 哪些 state 需要可观察、可回放、可审计？
```

**Step 2: 验证文件**

Run:

```powershell
Get-Item docs/agent-native-loom.zh.md
```

Expected: 文件存在。

**Step 3: Commit**

```bash
git add docs/agent-native-loom.zh.md
git commit -m "docs: explain agent-native Loom primitives in Chinese"
```

---

## 7. 推荐实施顺序

1. 先写 ADR，统一产品和架构语言。
2. 增加 Capability Catalog。
3. 在 Brain 暴露 capability / policy API。
4. 增加 Loomlet 数据模型。
5. 增加确定性 Agent Kernel compiler。
6. 增加 Agent Native Home route。
7. 增加 Permission Envelope。
8. 将 Hands 和 adapters 投影为 capabilities。
9. 支持 Loomlet action 的确认执行。
10. 将固定 domain page 标记为 Loomlet projection。
11. 在 UI 中展示 Kernel Trace 和权限状态。
12. 更新 Brain presentation contract。
13. 写中文架构说明。

---

## 8. 风险与约束

### Generated UI 安全

Loomlet HTML 必须被限制。第一阶段不允许：

- `<script>`
- inline event handler
- 任意远程资源注入
- 未声明 capability 的 action

### 权限混乱

用户必须看得懂：

- 为什么这个操作需要确认。
- 这个操作会读什么。
- 这个操作会写什么。
- 这个操作是否会调用外部工具或网络。

### Adapter 越权

`agent.run` 不能成为无限制执行入口。

必须保持：

- 默认 sandbox。
- workspace root。
- confirmation。
- audit trail。

### 抽象过早

第一版 Agent Kernel 不要上 LLM planner。先用确定性规则建立中间表示、API、UI 和测试，再逐步替换为 Brain 规划。

### 与现有功能兼容

以下功能不能被破坏：

- `market`
- `position`
- `target`
- `sentiment`
- 现有 Brain / Hand 分析。
- 现有 generated cards。
- 现有 adapter runtime settings。

---

## 9. 验证命令

Focused Python tests：

```powershell
D:\conda\python.exe -m unittest tests.test_agent_native_capabilities
D:\conda\python.exe -m unittest tests.test_agent_native_loomlet
D:\conda\python.exe -m unittest tests.test_agent_native_kernel
D:\conda\python.exe -m unittest tests.test_agent_native_permissions
D:\conda\python.exe -m unittest tests.test_brain_agent_native_routes
D:\conda\python.exe -m unittest tests.test_agent_native_action_execution
```

Focused webview tests：

```powershell
node --test bridge/webview/agent-native-home.test.cjs
node --test bridge/webview/loomlet-projection.test.cjs
```

Broad regression：

```powershell
D:\conda\python.exe -m unittest discover tests
node --test bridge/webview/*.test.cjs
```

---

## 10. 手动验收

1. 启动 Loom。
2. 打开 `#agent-native` route。
3. Capability Dock 能从 Brain 加载 capabilities。
4. 输入 `Create an interactive NVDA target tracker`。
5. 点击 compile。
6. 页面出现 Loomlet Preview。
7. Kernel Trace 显示 capability plan。
8. 每个 capability 显示 permission / sandbox / confirmation 状态。
9. read-only action 不需要确认。
10. write / execute action 需要确认。
11. 现有 `market`、`position`、`target`、`sentiment` route 仍能工作。
12. 生成内容和详情层级仍能打开。

---

## 11. Definition Of Done

- 有中文 ADR 记录 agent-native 方向。
- 有 `loom_core/agent_native` 包。
- Brain 暴露 `/agent-native/capabilities`、`/agent-native/policy`、`/agent-native/compile`。
- 有 `CapabilityCatalog`、`CapabilityPolicy`、`PermissionEnvelope`、`LoomletSpec`、`AgentKernel`。
- Webview 有 Agent Native route。
- UI 显示 Capability Dock、Loomlet Preview、Kernel Trace。
- Hands 和 adapters 能出现在 capability catalog 中。
- Loomlet action 执行有确认边界。
- Domain routes 被标记为 Loomlet projections。
- 相关 Python / Node tests 通过。

