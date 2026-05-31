# Loom Fin — 使用手册

Loom Fin 是一套面向个人投研的 AI 手代理框架。四个 **hand agent**（market / sentiment / target / position）各司一域，共享同一套个性化文件体系，并支持本地 CLI、远端 HTTP、SDK 三类部署形式。

---

## 目录

1. [服务架构一览](#1-服务架构一览)
2. [快速上手（5 分钟）](#2-快速上手5-分钟)
3. [个性化配置 — `personal/` 文件](#3-个性化配置--personal-文件)
4. [三类研究维度](#4-三类研究维度)
5. [Hand Agent 部署方式](#5-hand-agent-部署方式)
6. [Brain API 参考](#6-brain-api-参考)
7. [路线图（Stage 2–6）](#7-路线图stage-26)

---

## 1. 服务架构一览

```
浏览器 / curl
     │
     ▼
Anchor Service  (port 3000)  ── WebSocket ──► Claude Code MCP
     │
     ▼
Loom Brain      (port 3002)
     │
     ├─ POST /run  ──► Hand Agent (market / sentiment / target / position)
     │                      │
     │                      ├─ runtime=sdk          (in-process Python)
     │                      ├─ runtime=cc/codex/…   (local CLI subprocess)
     │                      ├─ runtime=xxx-mounted  (http × openai)
     │                      └─ runtime=cloud-xxx    (http × loom)
     │
     └─ GET  /resources/{id}  ──► Connector (FRED / Reuters / …)
```

所有运行时路径都读取同一套 `hands/<id>/personal/` 文件——个性化配置与 agent 部署形式无关。

---

## 2. 快速上手（5 分钟）

### 2.1 启动服务

**Windows**

```bat
scripts\start-anchor.bat
```

**Linux / WSL**

```bash
bash scripts/start-anchor.sh
```

启动后：
- Anchor Service → `http://localhost:3000`
- Loom Brain → `http://localhost:3002`

### 2.2 确认 Brain 在运行

```bash
curl http://127.0.0.1:3002/hands
# 期望返回：{"market":{"runtime":"sdk",...},"sentiment":...}
```

### 2.3 发起第一次分析

```bash
curl -X POST http://127.0.0.1:3002/run \
  -H "Content-Type: application/json" \
  -d '{"hand_id":"market","task":"今日大盘研判"}'
```

返回格式：

```json
{
  "artifact": {
    "metadata": {
      "confidence": 0.75,
      "key_claims": ["..."],
      "gaps": ["..."]
    },
    "narrative": "..."
  }
}
```

### 2.4 写入个人背景后再次运行

```bash
# 告诉 market hand 你关注的主题
cat >> hands/market/personal/themes.md << 'EOF'

### 进行中
- AI 算力 capex 持续性
- 美债期限溢价与 QT 节奏
EOF

# 再次调用，narrative 将主动引用上述主题
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"当前市场对 AI 投资节奏有何反应？"}'
```

---

## 3. 个性化配置 — `personal/` 文件

每个 hand 下都有一套 `hands/<id>/personal/` 文件。Brain 在每次调用时将这些文件 inline 进 agent 的系统提示（SDK 路径）或通过 envelope 传递（本地 CLI / 远端 API 路径）。

### 文件说明

| 文件 | 作用 | 示例内容 |
|------|------|---------|
| `profile.md` | 研究风格、时间视域、风险偏好 | "中线持仓为主，不做日内。风险容忍度：最大回撤 15%。" |
| `themes.md` | 当前关注的宏观/行业主题 | "AI capex、期限溢价、中美科技脱钩" |
| `watchlist.md` | Ticker 清单 + 关注原因 | `NVDA — AI 算力核心，看期权 IV 与 COT 变化` |
| `sources.md` | 信任的 KOL / 媒体 / 自定义 RSS | "Lyn Alden（宏观）、Odd Lots（Fed）" |
| `learned-notes.md` | 累积的经验散文（append-only） | "2025-11 FOMC 会后：CME FedWatch 与实际路径偏差 …" |

### 快速编辑

```bash
# 添加主题
echo "- 印度科技出口加速" >> hands/market/personal/themes.md

# 添加 watchlist 条目
echo "| TSM  | 台积电；观察台海溢价与 AI 需求节奏 |" \
  >> hands/market/personal/watchlist.md

# 记录一条经验笔记
cat >> hands/market/personal/learned-notes.md << 'EOF'

## 2026-05-31

FOMC 后技术股反弹被 VIX 快速收敛消化，单日 VIX 下行 ≥3 点时不应追多，
等待次日广度确认（adv/dec > 2:1）再评估。
EOF
```

### 新鲜上下文快照

若连接器（connector）写入了近期宏观快照，Brain 会自动读取（< 24h 内有效）：

```
hands/<id>/context/regime-snapshot.md
```

可手动写入：

```bash
echo "# Regime snapshot ($(date -u +%FT%TZ))
Risk-off。VIX 22，HYG 破位，信用利差扩张 +25bp。" \
  > hands/market/context/regime-snapshot.md
```

---

## 4. 三类研究维度

Loom Fin 把市场分析分成三个可独立参考的散文维度，收录于 `skills/investment-research-framework/references/`。Agent 通过 SKILL.md 索引按需打开。

### 4.1 基本盘 + 大资金流向 (`regime.md`)

关注：
- **指数与广度**：SPX / NDX / RUT / 等权重；A/D 比率；50/200 DMA 占比
- **波动率**：VIX、VVIX、put/call 比、gamma 敞口
- **信用信号**：HY OAS、HYG / LQD 走势、CDX
- **流动性**：Fed 资产负债表、TGA 余额、RRP 规模
- **估值**：fwd PE 与 ERP；FCF yield
- **资金流向**：ETF flow、CFTC COT、机构持仓变化

何时算 regime 切换：多维同向（价格 + 广度 + 信用）持续 ≥ 5 日，而非单日跳变。

### 4.2 板块热度 + 上下游产业链 (`sector-and-chains.md`)

关注：
- **板块轮动**：11 个 GICS 板块相对强度、ETF flows、EPS 修正方向
- **产业链分析**：上游（原材料 / 设备）→ 中游（制造 / 半导体）→ 下游（品牌 / 应用）→ 政策敏感度
- **候选标的筛选**：流动性（ADV > $50M）、纯度（pure-play vs 综合企业）、催化剂日历、估值分位、与 `themes.md` 对齐

产业链地图参考：`skills/investment-research-framework/references/industry-chain-map.md`

### 4.3 政策层 6 维度 (`policy.md`)

| 维度 | 关注点 |
|------|--------|
| **货币政策** | Fed 利率路径、QT 节奏、各大央行相对立场 |
| **财政政策** | 预算赤字、税改、债务上限、国债供给 |
| **监管** | SEC / FTC / DOJ / EPA / FDA 行动、行业规则变化 |
| **地缘** | 制裁、贸易战、供应链脱钩、海运通道 |
| **选举** | 关键民调、政纲行业影响、议席更迭 |
| **国际宏观** | 欧 / 日 / 中央行、汇率、跨境资本流动 |

传导路径（需追踪全链条）：宣布 → 提案 → 规则制定 → 实施 → 营收影响

---

## 5. Hand Agent 部署方式

Brain 支持四条运行时路径，可在 `loom/hand_registry.py` 里按 hand 设置。

### 5.1 SDK（默认，无需配置）

```python
# loom/hand_registry.py（默认）
"market": { "runtime": "sdk", ... }
```

Brain 在 Python 进程内直接调用 Anthropic SDK，每次调用时新鲜读取 `personal/` 文件。

```bash
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判"}'
```

编辑 `personal/*.md` 后下次调用立即生效，无需重启。

---

### 5.2 本地 CLI Agent（process × loom）

支持 `cc`（Claude Code CLI）、`codex`（OpenAI Codex CLI）、`herms`、`opencode`。

**设置 runtime：**

```python
# loom/hand_registry.py
"market": { "runtime": "cc", ... }
```

或在请求时一次性指定：

```bash
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判","runtime":"cc"}'
```

Agent 收到的 stdin JSON 包含：

```json
{
  "task": "...",
  "hand_id": "market",
  "hand_dir": "/abs/path/to/hands/market",
  "personal": {
    "skill_index": "...",
    "personal/profile.md": "...",
    "personal/themes.md": "...",
    "personal/watchlist.md": "...",
    "personal/sources.md": "...",
    "personal/learned-notes.md": "...(tail 4000 chars)"
  },
  "context": { "__personal__": { ... } }
}
```

Agent 的 CWD 被设为 `hands/market/`，可以用 `Read("personal/themes.md")` 直接访问文件。

**前提条件：**

| runtime | 需要 |
|---------|------|
| `cc` | `claude` CLI 已安装并认证 |
| `codex` | `npm i -g @openai/codex` |
| `herms` | `herms` 在 PATH |
| `opencode` | `opencode` CLI 已安装 |

---

### 5.3 远端 HTTP Agent（http × openai）

任何兼容 OpenAI ChatCompletion 的端点都可以挂载为 hand agent。系统提示在挂载时一次性构建，包含当前 `personal/` 内容。

**挂载：**

```bash
curl -X POST http://127.0.0.1:3002/hand/mount \
  -H "Content-Type: application/json" \
  -d '{
    "hand_id":    "market",
    "endpoint":   "https://api.openai.com/v1/chat/completions",
    "auth_token": "sk-...",
    "description": "GPT-4o market analyst",
    "timeout_s":  90
  }'
```

挂载信息持久化到 `loom/mounts.json`，Brain 重启后自动恢复。

**运行：**

```bash
# 挂载后自动优先使用（market-mounted 优先级高于 sdk）
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判"}'
```

**编辑 personal/ 文件后需重新挂载：**

```bash
# 卸载
curl -X DELETE http://127.0.0.1:3002/hand/market/mount

# 重新挂载（Brain 重读 personal/ 并重建系统提示）
curl -X POST http://127.0.0.1:3002/hand/mount -d '{ ...同上... }'
```

**Agent 响应格式**（必须在 content 中返回一行 NDJSON）：

```json
{"type":"run.artifact","artifact":{"metadata":{"confidence":0.75,"key_claims":[...],"gaps":[...]},"narrative":"..."}}
```

可选地，在 artifact 行之前加 `wiki.write` 事件写回 wiki：

```json
{"type":"wiki.write","path":"macro.md","content":"..."}
{"type":"run.artifact","artifact":{...}}
```

---

### 5.4 云端 Loom Agent（http × loom）

部署在云端、说 Loom NDJSON 流协议的 agent。通过 `hands/<id>/cloud.json` 注册。

**`hands/market/cloud.json` 示例：**

```json
{
  "endpoint":               "https://your-cloud-agent.example.com/run",
  "auth_token":             "...",
  "timeout_s":              120,
  "include_wiki_snapshot":  true,
  "prefetch_resources":     ["fred", "reuters-rss"]
}
```

Brain 通过 `_build_snapshot` 把 `context.__personal__` 转发给云端 agent。Agent 收到完整快照：

```json
{
  "task": "...",
  "hand_id": "market",
  "context": {
    "__personal__": {
      "skill_index": "...",
      "personal/themes.md": "...",
      "personal/watchlist.md": "...",
      "personal/sources.md": "...",
      "personal/profile.md": "...",
      "personal/learned-notes.md": "...(tail)",
      "context/regime-snapshot.md": "..."
    }
  },
  "wiki_snapshot": { "analysis.md": "..." },
  "config": {},
  "feedback_recent": []
}
```

**运行：**

```bash
curl -X POST http://127.0.0.1:3002/run \
  -d '{"hand_id":"market","task":"今日大盘研判","runtime":"<cloud-adapter-id>"}'
```

---

### 运行时路径汇总

| 路径 | runtime 值 | personal/ 传递方式 | 适用场景 |
|------|-----------|------------------|---------|
| SDK（in-process） | `sdk` | `_assemble_prompt` 每次 inline | 默认；零配置；最快 |
| 本地 CLI | `cc` / `codex` / `herms` / `opencode` | stdin JSON `envelope["personal"]` + CWD | 本地 CLI 安装时首选 |
| 远端 HTTP（openai 兼容） | `<id>-mounted` | mount 时 bake 进系统提示 | 任意 OpenAI 兼容 API |
| 云端 Loom 流协议 | 注册的 cloud adapter id | `context.__personal__` 快照转发 | 云部署自研 agent |

---

## 6. Brain API 参考

Brain 运行在 `http://127.0.0.1:3002`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/hands` | 列出已注册的 hand + 当前 runtime |
| `POST` | `/run` | 触发一次 hand 分析（见下） |
| `POST` | `/hand/mount` | 挂载远端 HTTP agent |
| `DELETE` | `/hand/{id}/mount` | 卸载挂载 |
| `GET` | `/resources` | 列出可用 resource connector |
| `POST` | `/feedback` | 提交反馈（Stage 5.5 后自动写入 learned-notes） |

### `POST /run` 请求体

```json
{
  "hand_id": "market",
  "task":    "今日大盘研判",
  "runtime": "cc",
  "context": {
    "prior_thesis": "...",
    "position_data": [...]
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `hand_id` | ✓ | `market` / `sentiment` / `target` / `position` |
| `task` | ✓ | 自然语言任务描述 |
| `runtime` | — | 不填则使用 `hand_registry.py` 中的默认值 |
| `context` | — | 补充上下文（持仓数据、先前 thesis 等） |

---

## 7. 路线图（Stage 2–6）

本期（Stage 1）已完成最小骨架：SKILL.md 重写、三类维度 references、personal/ 文件体系、SDK 和全 adapter 路径个性化传递。

| Stage | 内容 | 预计收益 |
|-------|------|---------|
| **2** | `references/team.md` + `synthesis.md` + `push-decision.md`；SKILL.md team-aware | 引入 scout/main agent 协作合同 |
| **3** | `scouts/<id>/`、`outbox/`、`team.yaml` 文件脚手架 | 团队文件结构就位 |
| **4** | SDK `_assemble_prompt` 读 `scouts/*/digest.md` tail | SDK fallback 升级为 main agent |
| **5.1** | Scheduler 驱动 scout cycle（cron / brain-internal） | 7×24 自动分析 |
| **5.2** | Outbox drainer → `patch_webview` | 分析结果自动推送到 UI |
| **5.5** | `POST /feedback` 自动写入 `personal/learned-notes.md` | 反馈自动累积 |
| **5.6** | Connector 写入 `context/regime-snapshot.md` | 宏观快照自动更新 |
| **6** | `config/default.yaml` 清理 `driver_weights`；`_buildCcPrompt` 中性化 | 技术债清理 |

---

*Loom Fin Stage 1 · 2026-05-31*
