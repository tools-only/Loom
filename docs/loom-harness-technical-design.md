# Loom Harness 技术设计文档

**版本**: v0.1 | **日期**: 2026-05-28

---

## 1. 整体架构概览

Loom 的核心是一个 **Brain + Hands** 分层架构，运行在独立于 Anchor 主服务的 Python 进程中。

```
浏览器
  │  用户在 /loom 控制面板点击 Hand 按钮
  ▼
server.cjs (Node.js, port 3000)          ← Anchor 主服务，已有
  │  POST /loom/run  （axios 代理）
  ▼
brain.py (Python FastAPI, port 3001)     ← Loom Brain
  │  1. 计算 resource_menu（渐进披露）
  │  2. 同步调用 hand.run(task, context, resource_menu)
  ▼
hands/base.py (BaseHand)                 ← Loom Hand（LLM 推理层）
  │  Anthropic Messages API (claude-haiku-4-5)
  │  tool-use 循环：fetch_resource 工具
  │         │
  │         ▼
  │  bridge.get_connector_data()
  │         │  GET /data/:connector_id
  │         ▼
  │  server.cjs → inbox.list()           ← 复用已有 connector 数据
  │
  │  返回 artifact { metadata, narrative }
  ▼
brain.py
  │  1. bridge.patch_webview()  POST /patch → WebSocket → 浏览器
  │  2. harness/eval_log.append_signal()
  ▼
日志 logs/loom-eval-log.jsonl            ← 渐进披露的学习数据
```

---

## 2. Brain 是什么

**Brain 是一个 Python FastAPI HTTP 服务，本身不是 LLM agent。**

`brain.py` 的职责是**协调**，不是推理：

```python
# brain.py — /run 端点的核心逻辑
async def run(req: RunRequest):
    hand = HANDS.get(req.hand_id)          # 取出对应的 Hand 实例
    resource_menu = get_menu_for_hand(...)  # 计算本次应展示哪些资源
    artifact = await hand.run(...)          # 调用 Hand（LLM 推理在这里发生）
    await patch_webview(anchor_id, html)    # 将结果 patch 到浏览器
    append_signal(...)                      # 记录资源使用情况
    return {"ok": True, "artifact": artifact}
```

Brain 没有任何 LLM 调用，没有 system prompt，没有 tool-use loop。它是一个**路由 + 副作用管理器**：

| 职责 | 实现 |
|------|------|
| 路由请求到正确的 Hand | `HANDS` 字典，Python 直接函数调用 |
| 计算资源菜单 | `resource_disclosure.get_menu_for_hand()` |
| 渲染 HTML artifact | `_render_artifact()` — 纯字符串模板 |
| 推送结果到浏览器 | `bridge.patch_webview()` → `POST /patch` |
| 记录 eval signal | `harness/eval_log.append_signal()` |

---

## 3. Hands 是什么，基于什么实现

**Hands 直接调用 Anthropic Python SDK，不经过 Claude Code，不经过 MCP。**

每个 Hand 是一个**独立的 Messages API 会话**，使用 `anthropic.AsyncAnthropic()` 客户端：

```python
# hands/base.py
_aclient = anthropic.AsyncAnthropic()   # 直接用 Anthropic SDK

async def run(self, task, context, resource_menu):
    resp = await _aclient.messages.create(
        model="claude-haiku-4-5-20251001",   # Hand 用 Haiku 推理
        max_tokens=4096,
        system=self._load_prompt(),           # hands/prompts/{hand_id}.md
        tools=[FETCH_RESOURCE_TOOL],          # 唯一工具
        messages=messages,
    )
```

Hand 的模型选择：**claude-haiku-4-5**（不是 Claude Code 使用的 Sonnet/Opus）。原因：
- Hand 是专职单一任务的分析 agent，任务边界清晰
- Haiku 速度快、成本低，适合日频调用
- 复杂推理由 system prompt 的分析框架约束，不依赖模型规模

Hand 的 LLM context 与 Anchor 主流程（inproc-agent.cjs）**完全隔离**：不共享 session、不共享 token 计数、不共享工具集。

### Hand 的结构

每个 Hand 遵循**固定 workflow + LLM 推理**的模式，不是自由 agent：

```
固定输入端：
  task (string)          ← Brain 传入的分析任务
  context (dict)         ← 附加上下文（ticker、prior_thesis 等）
  resource_menu (list)   ← 渐进披露系统计算的资源列表

LLM 推理（tool-use loop，最多 10 轮）：
  system: hands/prompts/{hand_id}.md    ← 分析纪律约束
  tool:   fetch_resource(resource_id)   ← 唯一工具，拉 connector 数据
  → 循环直到 stop_reason = "end_turn"

固定输出端：
  artifact {
    metadata: { confidence, gaps, key_claims, resources_shown, resources_used, resources_ignored }
    narrative: string                    ← 完整自然语言分析
  }
```

Hand 对数据源**没有硬编码知识**。它只知道"有一批可用资源"（资源菜单），由 `fetch_resource` 工具自主决定用哪些。

---

## 4. Brain 与 Hands 的关联方式

Brain 和 Hands 的关联是**Python 进程内的直接函数调用**，不是 HTTP、不是消息队列、不是 MCP。

```python
# brain.py
HANDS = {                       # 进程启动时初始化，全生命周期持有
    "market":    MarketHand(),
    "sentiment": SentimentHand(),
    "target":    TargetHand(),
    "position":  PositionHand(),
}

# 调用时
artifact = await hand.run(req.task, req.context, resource_menu)
# ↑ 这是普通的 Python async 函数调用
# Brain 等待 Hand 完成（包括 Hand 内部的所有 Anthropic API 调用）后继续
```

关联的关键属性：

| 属性 | 描述 |
|------|------|
| **同步性** | Brain 调用 `await hand.run()`，等待完整 artifact 才继续 |
| **隔离性** | 每次 Hand 调用是独立的 LLM 会话，不积累跨调用状态 |
| **单向性** | Brain → Hand，Hand 不回调 Brain；artifact 是唯一返回值 |
| **注册表** | `hand_registry.py` 维护 Hand 元数据（anchor_id、label、prompt 路径），Brain 用它做路由和渲染 |

---

## 5. 数据流：connector 数据如何进入 Hand

connector 数据不直接注入 Hand。Hand 通过 `fetch_resource` 工具**按需拉取**：

```
Hand (LLM) 决定调用 fetch_resource("fred")
    │
    ▼
hands/base.py: tool_use handler
    │  await get_connector_data("fred")
    ▼
bridge.py
    │  GET http://localhost:3000/data/fred
    ▼
server.cjs: GET /data/:connector_id
    │  inbox.list({}).filter(i => i.source === "fred")
    ▼
返回最新的 inbox 条目（connector 推送的原始数据）
```

**关键点**：connector 实现只存在一份（`mcp/connectors/*.cjs`），Python 侧没有任何 connector 代码。Python 通过 HTTP 消费 JS connector 已经推送进 inbox 的数据。

---

## 6. 渐进披露机制

渐进披露是指 Hand 每次调用看到的**资源菜单排序会随使用历史自动优化**。

### 数据流

```
每次 Hand 调用结束
    │
    ▼
brain.py → append_signal(hand_id, resources_shown, resources_used)
    │
    ▼
logs/loom-eval-log.jsonl
  { hand_id, resources_shown: [...], resources_used: [...], resources_ignored: [...], ts }

下次调用前
    │
    ▼
resource_disclosure.get_menu_for_hand(hand_id)
    │  读取近 30 天 signals
    │  计算每个资源的使用率：used / (used + ignored)
    │  按使用率降序排序
    ▼
resource_menu（最多 10 条）注入 Hand 的 user message
```

### 使用率算法

```python
def score(rid: str) -> float:
    used    = usage_count[rid]
    ignored = ignore_count[rid]
    total   = used + ignored
    return 0.5 if total == 0 else used / total   # 冷启动默认 50%
```

**冷启动**：第一次调用时所有资源得分相同（0.5），按 `resource_library.json` 的顺序展示。随着使用积累，高价值资源会浮到前面，被频繁忽略的资源沉到后面。

---

## 7. 四个 Hand 的差异点

所有 Hand 继承 `BaseHand`，差异只在两个地方：

### market / sentiment
无任何扩展，完全用 BaseHand 行为：

```python
class MarketHand(BaseHand):
    def __init__(self):
        super().__init__("market")
```

### target（增量 thesis 持久化）
在父类 `run()` 前后各做一次 I/O：

```python
async def run(self, task, context, resource_menu):
    # 读：注入上次 thesis 到 context
    prior = await get_thesis(ticker)
    if prior:
        context = {**context, "prior_thesis": prior}

    artifact = await super().run(task, context, resource_menu)

    # 写：追加新 thesis（Python 独占写，不经过 server.cjs）
    append_thesis(ticker, artifact)
    return artifact
```

Thesis store 是 Python 独占写的 `.jsonl` 文件。server.cjs 通过 `GET /loom/thesis/:ticker` 只读访问（供 webview 展示历史）。

### position（用户数据驱动）
不使用外部数据，传空的 resource_menu：

```python
async def run(self, task, context, resource_menu):
    return await super().run(task, context, [])  # 强制空菜单
```

位置信息由用户在控制面板直接输入，通过 `context.position_data` 字段传入。

---

## 8. Hand Prompt 的构成与来源

每个 Hand 有独立的 system prompt，存放在 `loom/hands/prompts/{hand_id}.md`。

**内容来源**：从 `branches/{hand}/CLAUDE.md` 的第 1-3 节提取（数据纪律、叙事纪律、范围），**去掉** Anchor HTML Output Protocol 和 Bloom CSS 规范。

**新增内容**：输出格式要求——要求 Hand 返回 JSON artifact 而不是 HTML：

```
# 原 branch CLAUDE.md 包含（branches/market/CLAUDE.md）：
§1 数据纪律     → ✅ 保留
§2 叙事纪律     → ✅ 保留
§3 范围限制     → ✅ 保留
Anchor HTML 输出协议  → ❌ 删除
Bloom CSS 规范        → ❌ 删除

# 新增：
JSON 输出格式（metadata + narrative）  → ✅ 新增
```

这样 Hand 继承了 branch 的分析约束，但不会试图调用 `anchor_patch`（那是 Anchor inproc-agent 的职责，不属于 Hand）。

---

## 9. Loom 与 Anchor 主流程的关系

Loom 和 Anchor 是**并行的两个系统**，通过 server.cjs 连接，不直接交互：

```
用户浏览器
  ├─ Anchor 主流程（已有）
  │    用户对 HTML 做 refine/expand/edit op
  │    → server.cjs spawn claude -p
  │    → inproc-agent.cjs（Claude Code，Sonnet/Opus）
  │    → anchor_patch
  │
  └─ Loom 新流程
       用户在 /loom 面板触发分析
       → server.cjs POST /loom/run 代理
       → Python Brain（FastAPI，非 Claude Code）
       → Hand（Anthropic SDK，Haiku）
       → anchor_patch via /patch HTTP
```

| 维度 | Anchor inproc-agent | Loom Hand |
|------|---------------------|-----------|
| 实现语言 | JavaScript (Node.js) | Python |
| LLM 调用方式 | Claude Code (`claude -p`) / MCP | Anthropic Python SDK 直调 |
| 使用模型 | Claude Sonnet/Opus | Claude Haiku |
| 触发方式 | 用户在 webview 对 HTML 元素操作 | 用户在 /loom 控制面板点击 |
| 职责 | 修改现有 HTML 内容 | 生成新的市场分析 artifact |
| context 来源 | webview 的当前 HTML | connector inbox + 用户输入 |

---

## 10. 进程与端口

| 进程 | 启动方式 | 端口 | 职责 |
|------|----------|------|------|
| Anchor Server | `scripts/start-anchor.bat` | 3000 | HTTP + WebSocket 主服务 |
| Loom Brain | `cd loom && python main.py` | 3001 | FastAPI，接收 Loom 请求 |

两个进程通过 HTTP 通信：
- Brain → Server：`GET /data/:id`（拉数据）、`POST /patch`（推结果）、`GET /loom/thesis/:ticker`（读 thesis）
- Server → Brain：`POST /loom/run`（代理用户请求）

---

## 11. 文件结构速查

```
loom/
├── main.py                      启动入口（uvicorn + APScheduler）
├── brain.py                     FastAPI Brain 服务
├── bridge.py                    HTTP 客户端（连 server.cjs port 3000）
├── hand_registry.py             Hand 元数据注册表
├── resource_library.json        15 个数据源定义（Tier A-F）
├── resource_disclosure.py       渐进披露：按使用率排序资源菜单
├── panel.html                   浏览器测试控制面板（server 在 GET /loom 提供）
├── requirements.txt             fastapi / uvicorn / anthropic / httpx / apscheduler
├── TESTING.md                   UI-only 端到端测试手册
│
├── hands/
│   ├── base.py                  BaseHand（LLM tool-use loop）
│   ├── market.py                市场研判 Hand
│   ├── sentiment.py             情绪追踪 Hand
│   ├── target.py                标的 Thesis Hand（含 thesis 持久化）
│   ├── position.py              持仓管理 Hand（用户数据驱动）
│   └── prompts/
│       ├── market.md            market Hand system prompt
│       ├── sentiment.md         sentiment Hand system prompt
│       ├── target.md            target Hand system prompt
│       └── position.md          position Hand system prompt
│
└── harness/
    ├── eval_log.py              append/read loom-eval-log.jsonl
    ├── review.py                日报计算 + HTML 渲染 + patch 到 webview
    └── scheduler.py             APScheduler（每日 07:00 ET）

mcp/server.cjs（新增 4 个路由）
    GET  /data/:connector_id     Python 拉 connector 数据（从 inbox 过滤）
    GET  /loom/thesis/:ticker    读 thesis-store.jsonl（只读）
    POST /loom/run               代理到 Python Brain port 3001
    GET  /loom                   提供 loom/panel.html

logs/（运行时生成）
    loom-eval-log.jsonl          每次 Hand 调用的资源使用记录（渐进披露数据来源）
    thesis-store.jsonl           Target Hand 的历史 thesis（Python 独占写）
```
