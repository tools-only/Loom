# Loom Fin — Hand Agent 配置与挂载指南

Hand agent 是独立的 agent 进程，每个 hand 负责一个交易分析领域（market / sentiment / target / position）。  
Loom Core 通过 `ProcessAgentAdapter` 启动子进程、传入任务 envelope、接收 JSON 事件流。

---

## 1. 架构概览

```
POST /run  →  brain.py  →  AgentAdapterRegistry.find(runtime)
                                      │
                          ┌───────────┼───────────┐
                          ▼           ▼           ▼
                    cc adapter   codex adapter   sdk adapter
                    (claude -p)  (codex run)     (in-process)
                          │
                    stdin: task envelope JSON
                    stdout: {"type":"run.artifact","artifact":{...}}
```

每个 hand 有自己的工作目录 `hands/<id>/`，包含：

```
hands/market/
  CLAUDE.md            # 给 agent 看的 wiki schema + workflow 指令
  config.json          # 用户设定（关注板块、KOL 列表等）
  custom_resources.json
  wiki/
    index.md
    macro.md
    sectors.md
    tickers/
```

---

## 2. 支持的 Runtime 类型

| runtime 值 | 对应 adapter | 启动方式 |
|---|---|---|
| `cc` | `ClaudeCodeAdapter` | `claude -p <envelope>` |
| `codex` | `CodexAdapter` | `codex run <envelope>` |
| `openclaw` | `OpenclawAdapter` | `openclaw run <envelope>` |
| `sdk` | `InProcessAdapter` | Python 函数直接调用（legacy） |

---

## 3. 如何挂载一个 claude -p Hand Agent

### 3.1 配置 hand_registry.py

打开 `loom/hand_registry.py`，找到对应 hand，将 `runtime` 改为 `"cc"`：

```python
REGISTRY = {
    "market": {
        "label": "市场观察",
        "anchor_id": "loom-market",
        "runtime": "cc",          # ← 改这里（默认是 "sdk"）
        "wiki_dir": str(ROOT.parent / "hands" / "market" / "wiki"),
        "config_schema": { ... },
    },
    ...
}
```

### 3.2 确认 CLAUDE.md 已在工作目录

`hands/market/CLAUDE.md` 已预置好 wiki workflow 和输出格式。**不需要修改**，除非你想改变 agent 的分析策略。

关键要求：agent 的 stdout 最后一行必须是：
```json
{"type": "run.artifact", "artifact": { ... }}
```

### 3.3 触发运行

```bash
# 通过 Brain HTTP API 触发（Brain 在 port 3001）
curl -X POST http://127.0.0.1:3001/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id": "market", "task": "分析当前市场环境", "runtime": "cc"}'
```

Brain 会：
1. 构建 task envelope（含 `hand_dir`、`wiki_dir`、`resource_api`、`feedback_log`）
2. 启动 `claude -p <envelope>` 子进程，cwd = `hands/market/`
3. 接收 stdout 事件流，提取 `run.artifact`
4. patch webview anchor `loom-market`

---

## 4. 如何挂载一个 codex Hand Agent

### 4.1 配置 runtime

```python
# loom/hand_registry.py
"market": {
    ...
    "runtime": "codex",
}
```

### 4.2 准备 CLAUDE.md（适配 codex 格式）

`hands/market/CLAUDE.md` 是给 claude 格式的 agent 看的。如果用 codex，你可能需要调整格式，但输出协议相同：stdout 最后一行必须是 `run.artifact` 事件 JSON。

### 4.3 触发

```bash
curl -X POST http://127.0.0.1:3001/run \
  -d '{"hand_id": "market", "task": "...", "runtime": "codex"}'
```

---

## 5. 如何挂载一个自定义 agent

任何能从 stdin 读取 JSON、向 stdout 写 JSON 事件的进程都可以挂载。

### 5.1 注册自定义 adapter

在 `loom_core/agent_adapters/providers/` 下新建文件，例如 `my_agent.py`：

```python
from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter

def create_my_agent():
    return {
        "id": "my-agent",
        "instance": ProcessAgentAdapter(
            adapter_id="my-agent",
            command=["path/to/my-agent", "--stdin"],
            capabilities=["market.analysis"],
        )
    }
```

在 `loom_core/agent_adapters/providers/__init__.py` 的 `create_providers()` 中注册：

```python
from .my_agent import create_my_agent

def create_providers():
    providers = {}
    ...
    try:
        p = create_my_agent()
        providers[p["id"]] = p
    except Exception:
        pass
    return providers
```

### 5.2 配置 hand 使用它

```python
"market": {
    "runtime": "my-agent",   # ← adapter_id
    ...
}
```

### 5.3 Agent 协议（stdout 事件流）

你的 agent 进程必须遵守以下协议：

**输入**（stdin，单行 JSON）：
```json
{
  "task": "用户任务描述",
  "context": {},
  "hand_id": "market",
  "hand_dir": "D:/ai-native chrome/hands/market",
  "wiki_dir": "D:/ai-native chrome/hands/market/wiki",
  "resource_api": "http://127.0.0.1:3001/resources",
  "feedback_log": "D:/ai-native chrome/logs/feedback.jsonl"
}
```

**输出**（stdout，每行一个 JSON 事件）：
```
{"type": "run.started", ...}         ← 可选
{"type": "run.artifact", "artifact": {"metadata": {...}, "narrative": "..."}}  ← 必须
{"type": "run.completed", ...}       ← 可选
```

只有 `run.artifact` 是必须的。stderr 输出会被捕获记录，不影响流程。

---

## 6. 访问 Core 提供的数据

### 6.1 资源 API

从 `resource_api` 获取市场数据（agent 进程内调用）：

```bash
curl "http://127.0.0.1:3001/resources/fred"
curl "http://127.0.0.1:3001/resources/finnhub?ticker=NVDA"
curl "http://127.0.0.1:3001/resources/reuters-rss"
```

返回格式：`{"ok": true, "resource_id": "...", "data": {...}}`

### 6.2 用户反馈

读取历史反馈（python 示例）：

```python
import json
with open(feedback_log) as f:
    events = [json.loads(l) for l in f if l.strip()]
my_feedback = [e for e in events if e.get("hand_id") == hand_id]
```

或通过 HTTP：
```bash
curl "http://127.0.0.1:3001/feedback?hand_id=market&since=1748000000"
```

### 6.3 用户设定

```bash
curl "http://127.0.0.1:3001/hand/market/config"
# → {"ok":true,"config":{"watched_sectors":["科技","能源"],"kol_feeds":[...]}}
```

---

## 7. 用户在 Webview 配置 Hand

每个 hand section 右上角有一个齿轮按钮（⚙），点击展开设置面板：

| Hand | 可配置项 |
|---|---|
| market | 关注板块、KOL RSS 列表、宏观主题 |
| sentiment | Reddit 社区、关注标的 |
| target | 目标标的列表 |
| position | 仓位数据、风险偏好 |

设置保存后立即写入 `hands/<id>/config.json`，下次 hand agent 运行时自动读取。

每个 hand artifact 底部有反馈控件（👍/👎 + 备注），提交后写入 `logs/feedback.jsonl`。

---

## 8. 验证挂载是否成功

```bash
# 1. 启动 Brain（如未运行）
cd loom && uvicorn brain:app --port 3001

# 2. 检查 adapters 已注册
curl http://127.0.0.1:3001/health
# → {"adapters": ["cc", "codex", "sdk-market", ...]}

# 3. 触发一次运行（sdk 模式，快速验证）
curl -X POST http://127.0.0.1:3001/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id":"market","task":"市场概况","runtime":"sdk"}'

# 4. 切换为 cc 模式，验证 claude -p 路径
curl -X POST http://127.0.0.1:3001/run \
  -d '{"hand_id":"market","task":"市场概况","runtime":"cc"}'
```

Brain 返回 `{"ok":true,"artifact":{...}}` 表示成功；webview 中对应 `loom-market` 区域会被 patch 更新。

---

## 9. 故障排查

| 症状 | 原因 | 解法 |
|---|---|---|
| `"unknown runtime adapter: cc"` | cc adapter 注册失败（claude CLI 未安装）| `which claude` 验证；检查 `create_providers()` 日志 |
| `"adapter returned no artifact"` | agent stdout 没有 `run.artifact` 行 | 检查 CLAUDE.md 输出格式；运行 `claude -p '{"task":"test","hand_id":"market","hand_dir":"..."}' < /dev/null` 手动测试 |
| agent 找不到 wiki/ | cwd 不对 | 确认 `hand_registry.py` 的 `wiki_dir` 是绝对路径 |
| 设置面板空白 | Brain 未启动 | `curl http://127.0.0.1:3001/health` |

---

## 10. 云端 Agent 接入概览

云端 agent（如 openclaw cloud、自托管 HTTP 服务）无法访问 `127.0.0.1` 或本地文件系统。Loom 使用 **Inline 快照 + 写回事件** 模式解决这个问题：

```
POST /run  →  brain.py  →  HttpAgentAdapter
                                │
                  (1) 构建自包含快照 envelope：
                       wiki_snapshot / config / feedback_recent / resources
                                │
                  (2) POST https://cloud-agent/run
                       Authorization: Bearer <token>
                                │
                  (3) 流式读取 NDJSON 响应：
                       wiki.write    → 本地落盘（agent 不可见）
                       feedback.signal → feedback_store.append
                       run.artifact  → yield 给 brain.py（同本地 adapter）
```

**优点：**
- Loom Core 始终绑定 `127.0.0.1`，零公网暴露面
- 云端 agent 无需访问 localhost
- brain.py 感知不到差异 — 代码路径与本地 adapter 完全相同

**约束：**
- 云端 agent 不能中途动态请求新资源（须在 `hands/<id>/cloud.json` 预声明 prefetch_resources）
- v1 不支持 cancel（一旦触发运行，等待超时或完成）

---

## 11. 挂载云端 openclaw Agent（示例）

### 步骤 1 — 声明 endpoint

编辑 `config/cloud-agents.json`（该文件可入 git，不含 token）：

```json
{
  "openclaw-cloud": {
    "endpoint": "https://api.openclaw.ai/v1/run",
    "capabilities": ["market.analysis", "sentiment.scan"],
    "timeout_s": 120,
    "token_env": "OPENCLAW_CLOUD_TOKEN",
    "require_auth": true
  }
}
```

### 步骤 2 — 设置 token

在项目根目录创建 `.env`（已在 `.gitignore` 中）：

```bash
echo "OPENCLAW_CLOUD_TOKEN=your-actual-token" >> .env
```

Brain 启动时通过 `python-dotenv` 或系统环境变量读取。若使用系统环境变量：

```bash
# Windows PowerShell
$env:OPENCLAW_CLOUD_TOKEN = "your-actual-token"
```

### 步骤 3 — 将 hand 的 runtime 指向云端 adapter

编辑 `loom/hand_registry.py`，将对应 hand 的 `runtime` 改为你在 `cloud-agents.json` 中声明的 key：

```python
"market": {
    ...
    "runtime": "openclaw-cloud",   # ← 从 "sdk" 或 "cc" 改为 cloud adapter id
    ...
}
```

### 步骤 4 — 声明 prefetch 资源（可选）

若云端 agent 需要读取特定 connector 数据，在 `hands/market/cloud.json` 中声明：

```json
{
  "include_wiki_snapshot": true,
  "prefetch_resources": ["fred", "reuters-rss"]
}
```

这些资源由 Loom Core 本地预取后打包进 envelope，云端 agent 直接从 body 读取。

### 步骤 5 — 验证

```bash
# 重启 Brain
cd loom && uvicorn brain:app --port 3001

# 检查 cloud adapter 已注册
curl http://127.0.0.1:3001/health
# → {"adapters": [..., "openclaw-cloud"]}

# 触发运行
curl -X POST http://127.0.0.1:3001/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id":"market","task":"分析当前市场环境"}'
```

---

## 12. 自托管云端 Agent 协议参考

任何能接收 HTTPS POST + 返回 NDJSON 流的服务都可以作为云端 hand agent。

### 12.1 请求格式（Loom Core → 云端 agent）

```
POST <endpoint>
Authorization: Bearer <token>
Content-Type: application/json

{
  "task": "用户任务描述",
  "context": {},
  "hand_id": "market",
  "wiki_snapshot": {
    "index.md": "...",
    "macro.md": "..."
  },
  "config": {
    "watched_sectors": ["科技"],
    "kol_feeds": [...]
  },
  "feedback_recent": [
    {"hand_id": "market", "vote": "down", "note": "情绪判断不准", "ts": 1748000000}
  ],
  "resources": {
    "fred": { ... },
    "reuters-rss": { ... }
  }
}
```

### 12.2 响应格式（云端 agent → Loom Core）

响应必须是 NDJSON（每行一个 JSON 对象），使用 chunked 编码或普通响应体（逐行）。

**必须**的事件（至少输出一个）：

```json
{"type": "run.artifact", "artifact": {"metadata": {...}, "narrative": "..."}}
```

**可选**事件（按需输出）：

| 事件 | 作用 |
|---|---|
| `{"type":"run.started","run_id":"..."}` | 可选，标记开始 |
| `{"type":"wiki.write","path":"macro.md","content":"..."}` | 写回本地 wiki 文件 |
| `{"type":"feedback.signal","event":{"hand_id":"market","note":"..."}}` | 写入 feedback store |
| `{"type":"run.completed","exit_code":0}` | 可选，标记完成 |
| `{"type":"run.error","message":"..."}` | 标记运行失败（brain.py 返回错误） |

**`wiki.write` 路径规则：**
- 相对路径，相对于 `hands/<id>/wiki/`
- 不允许 `..` 路径段（会被丢弃）
- 不允许绝对路径

### 12.3 错误码

| HTTP 状态码 | Loom 行为 |
|---|---|
| 2xx | 正常处理 NDJSON 流 |
| 4xx / 5xx | 立即返回 `run.error`，body 前 500 字节作为 message |
| 连接失败 / 超时 | 返回 `run.error`，message 描述异常 |

---

## 13. 安全提示

1. **Token 仅放 `.env`** — 永远不要把 token 提交到 git。`.env` 已在 `.gitignore` 中。
2. **必须 HTTPS** — 生产云端 endpoint 必须使用 HTTPS；HTTP 仅用于本地开发测试。
3. **Core 不暴露公网** — Loom Core 始终绑定 `127.0.0.1:3001`。不要用 `--host 0.0.0.0` 启动 Brain。
4. **路径穿越防护** — `wiki.write` 中包含 `..` 的路径会被静默拒绝，wiki 目录之外的文件不会被写入。
5. **require_auth 默认 true** — 若云端 endpoint 没有 token，设置 `"require_auth": false`，但仅用于本地受信任网络环境。
