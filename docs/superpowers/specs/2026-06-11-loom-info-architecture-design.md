# Loom 信息数据架构设计

**日期**: 2026-06-11  
**状态**: 已批准，待实现  
**方案**: B — Tiered Layer Schema

---

## 背景与问题

当前 Loom card 展开内容有限，仅展示 LLM 提炼后的 `narrative` + `sections` + `evidence`。用户无法看到：

1. **meta 层** — hand agent 抓取的原始数据（connector JSON、URL 内容、web search、推文、博客）
2. **完整 summary 层** — hand/brain 对原始信息的归纳分析结构
3. **targeted abstract** — Brain 基于 goal/flywheel/intent-wiki 状态管理的重点推理

---

## 设计目标

- **L0 原始素材**：execution 层捕获 + LLM 语义标注，都落入 artifact
- **L1 Hand 归纳**：现有 sections/evidence，迁移到 layers 结构
- **L2 Brain 状态推理**：独立 State Engine 卡，纯状态读取，不增加 LLM 调用
- **密度 level 系统**：L0/L1/L2 预设 + 用户自由组合，持久化到 localStorage
- **不改 UI 风格**：复用 Bloom Design System，仅在现有 overlay 结构内扩展

---

## Section 1 — Artifact Schema

### 完整结构

```json
{
  "metadata": {
    "confidence": 0.85,
    "key_claims": [{"claim": "...", "source": "FRED", "tier": "A", "freshness": "2026-06-10"}],
    "gaps": ["..."],
    "source_notes": [{"source": "...", "tier": "A", "freshness": "...", "note": "..."}],
    "resources_shown": [],
    "resources_used": [],
    "resources_ignored": []
  },
  "narrative": "2-4句可见摘要",

  "raw_sources": [
    {
      "resource_id": "fred",
      "fetched_at": "2026-06-11T10:23:00Z",
      "content_type": "json",
      "summary": "10Y Treasury 4.52%...",
      "raw": {}
    },
    {
      "resource_id": "fetch_url",
      "url": "https://...",
      "fetched_at": "...",
      "content_type": "html",
      "raw": "stripped text..."
    }
  ],

  "raw_items": [
    {
      "item_type": "news",
      "title": "Fed holds rates...",
      "source": "Reuters",
      "url": "...",
      "tier": "C",
      "published_at": "2026-06-10",
      "summary": "首句或LLM摘要",
      "relevance": "directly supports rate regime assessment"
    },
    {
      "item_type": "tweet",
      "author": "@NickTimiraos",
      "text": "原文",
      "source": "web_search",
      "tier": "E",
      "published_at": "...",
      "relevance": "sentiment signal"
    },
    {
      "item_type": "data_point",
      "label": "10Y Treasury",
      "value": "4.52%",
      "source": "FRED",
      "tier": "A",
      "freshness": "2026-06-10",
      "relevance": "rate regime anchor"
    }
  ],

  "layers": [
    {
      "layer_id": "summary",
      "layer_type": "summary",
      "title": "高层判断",
      "summary": "...",
      "items": [{"claim": "...", "source": "...", "tier": "A"}]
    },
    {
      "layer_id": "evidence",
      "layer_type": "evidence",
      "title": "Evidence and data",
      "items": [{"claim": "...", "support": "...", "source": "...", "source_tier": "A", "freshness": "..."}]
    },
    {
      "layer_id": "analysis",
      "layer_type": "analysis",
      "title": "深度分析",
      "items": []
    },
    {
      "layer_id": "gaps",
      "layer_type": "gaps",
      "title": "Coverage gaps",
      "items": []
    }
  ],

  "sections": [],
  "evidence": []
}
```

`sections` 和 `evidence` 由 backward-compat shim 自动从 `layers` 生成，供旧渲染路径使用。

### item_type 枚举

| item_type | 来源 | 渲染方式 |
|-----------|------|---------|
| `data_point` | FRED/Finnhub/SEC | key-value 数字卡 |
| `news` | Reuters/CNBC/MarketWatch | 标题 + 摘要 |
| `blog` | KOL RSS | 标题 + 首段 |
| `tweet` | StockTwits/Reddit | 原文卡片 |
| `filing` | SEC EDGAR | 章节摘要 |
| `search_snippet` | web_search | 标题 + snippet |
| `[custom]` | 用户定义 | 通用 key-value |

### Backward-compat shim（`_normalize_artifact()` 扩展）

- 若有 `sections` 但无 `layers` → 按 section.id 映射 `layer_type`（summary/evidence/analysis/gaps）
- 若有 `layers` → 反向填充 `sections`/`evidence` 供旧渲染路径
- `raw_sources` / `raw_items` 缺失时默认空数组

---

## Section 2 — Hand 执行层改造

### `BaseHand.run()` 新增 raw_sources 捕获

```python
raw_sources: list[dict] = []

# fetch_resource 分支
raw_sources.append({
    "resource_id": rid,
    "fetched_at": datetime.utcnow().isoformat() + "Z",
    "content_type": "json",
    "summary": BaseHand._summarize_raw(data),
    "raw": data,
})

# fetch_url 分支
raw_sources.append({
    "resource_id": "fetch_url",
    "url": url,
    "fetched_at": datetime.utcnow().isoformat() + "Z",
    "content_type": "html",
    "raw": content,
})

# web_search: Anthropic built-in，无法拦截 → 由 LLM 在 raw_items 自报

# end_turn 后合并
artifact["raw_sources"] = raw_sources
```

### `_summarize_raw()` 辅助函数

```python
@staticmethod
def _summarize_raw(data) -> str:
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return text[:200].rstrip() + ("…" if len(text) > 200 else "")
```

### Output contract 新增 raw_items 要求

在发给 LLM 的 output contract 末尾追加：

```
"raw_items": [
  {
    "item_type": "news|tweet|blog|data_point|filing|search_snippet|[custom]",
    "title": "标题或label",
    "source": "来源名",
    "tier": "A|B|C|D|E|F|G",
    "published_at": "YYYY-MM-DD或空字符串",
    "summary": "首句或简短摘要（≤120字符）",
    "relevance": "此素材为何相关（≤60字符）",
    "url": "(可选)",
    "value": "(data_point专用)",
    "author": "(tweet/blog专用)"
  }
]
最低密度：至少5条 raw_items，覆盖本次用到的信息来源；
data_point 必须有 value；所有条目必须有 relevance。
```

### 密度校验扩展

```python
if len(artifact.get("raw_items", [])) < 5 and used_resources:
    gaps.append("raw_items density low: fewer than 5 annotated raw items despite resource usage")
```

---

## Section 3 — Brain State Engine 卡

### 定位

第五张独立卡，与四张 hand 卡平行，渲染在 brain-synthesis 之后。纯状态读取，不增加 LLM 调用。

### `state_engine` 数据结构

```python
def _build_state_engine(goal, fw_record, synthesis, intent_activation, reward_report) -> dict:
    return {
        "goal": {
            "goal_id": goal.goal_id,
            "title": goal.title,
            "episode_count": len(goal.episode_ids),
            "stance_history": [
                {"ts": s.ts[:10], "stance": s.stance, "confidence": s.confidence}
                for s in goal.synthesis_snapshots[-5:]
            ],
            "latest_reversal": goal.latest_reversal_condition(),
        },
        "flywheel": {
            "episode_id": fw_record.episode_id,
            "domain": fw_record.domain,
            "confidence_delta": _confidence_delta(goal),
        },
        "intent_focus": {
            "active_nodes": [
                {"label": n.label, "zone": n.zone, "confidence": n.confidence}
                for n in (intent_activation.active_nodes[:4] if intent_activation else [])
            ],
            "decision_context": intent_activation.decision_context if intent_activation else "",
        },
        "reward": {
            "latest_score": reward_report.overall_reward if reward_report else None,
            "diagnosis": reward_report.diagnosis if reward_report else "",
            "top_policies": [
                {"label": p.label, "weight": p.weight}
                for p in (reward_report.top_policies[:3] if reward_report else [])
            ],
        },
        "targeted_abstract": {
            "focus_variables": synthesis.get("key_drivers", [])[:3],
            "regime_relevance": synthesis.get("regime_relevance", ""),
            "watch_conditions": synthesis.get("watch_conditions", []),
            "priority_signal": synthesis.get("priority_signal", ""),
        },
    }
```

### Brain output contract 追加字段

```
"regime_relevance": "当前 regime 为何使本次问题权重异常（≤80字符）",
"watch_conditions": ["需要持续监控的变量或事件，2-3条"],
"priority_signal": "本次分析的最高优先级信号，一句话"
```

### State Engine 卡渲染结构

```
[State Engine 卡]
  pills: [Brain 状态] [goal.title]
  h2: 状态推理

  targeted_abstract:
    priority_signal（insight-box，大字）
    regime_relevance
    watch_conditions（ul）

  <aside anc-detail hidden>
    Tab: Goal Track
      stance_history 时间线（ts → stance → confidence）
      latest_reversal
      confidence_delta（↑↓箭头）

    Tab: Intent Focus
      active_nodes grid（label / zone / confidence bar）
      decision_context

    Tab: Reward & Policy
      latest_score 大数字
      diagnosis
      top_policies list（label + weight bar）

    Tab: Flywheel
      episode_id / domain
      本次 hand_artifacts 摘要（各 hand 最高 tier + confidence）
  </aside>
```

### 触发时机

```python
# brain.py /analyze 末尾
state_engine = _build_state_engine(
    goal, fw_record, synthesis,
    _brain_harness._last_intent_activation,
    _brain_harness._last_reward_report,
)
state_engine_html = _render_state_engine(state_engine)
await patch_webview("brain-state-engine", state_engine_html)
```

`panel.html` 预置占位：
```html
<section data-anc="brain-state-engine" data-handles="refine,expand">
  <!-- 初始占位，Brain 分析后 patch 填充 -->
</section>
```

---

## Section 4 — 密度 Level 系统

### 预设 level 定义

| Level | 可见 layer_type |
|-------|----------------|
| L0    | raw_source, raw_item |
| L1    | summary, evidence, analysis, gaps |
| L2    | state_engine |

用户可在任意预设基础上额外勾选/取消单个 layer_type，形成自定义组合。

### overlay 交互结构

```
┌─────────────────────────────────────────────────────┐
│ [←] Market Hand       [L0] [L1] [L2]   [自定义 ▾]   │
├─────────────────────────────────────────────────────┤
│ 自定义展开:                                           │
│ ☑ 原始数据  ☑ 媒体/推文  ☑ Hand归纳                  │
│ ☑ 证据行    ☑ 深度分析   ☐ Brain分析                 │
├─────────────────────────────────────────────────────┤
│ [Detail] [Sources] [Hand Eval] ← 现有 tabs，按 level 过滤 │
└─────────────────────────────────────────────────────┘
```

### layer_type → 渲染方式

| layer_type | 默认 level | 渲染 |
|------------|-----------|------|
| `raw_source` | L0 | resource_id badge + summary + 可展开 raw |
| `raw_item:data_point` | L0 | `anc-kpi--arctic` 数字卡 |
| `raw_item:news/blog` | L0 | 标题 + 摘要 + tier pill + 时间戳 |
| `raw_item:tweet` | L0 | author + 原文 + tier pill |
| `raw_item:search_snippet` | L0 | 标题 + snippet + url chip |
| `summary` | L1 | 现有 sections 渲染 |
| `evidence` | L1 | 现有 evidence 表 |
| `analysis` | L1 | 现有 sections 渲染 |
| `gaps` | L1 | gaps ul |
| `state_engine` | L2 | State Engine detail tabs |
| `[custom]` | 用户定义 | 通用 key-value list |

### 持久化 schema

```json
{
  "loom.density.level": "L1",
  "loom.density.overrides": {
    "raw_source": true,
    "state_engine": false
  },
  "loom.density.custom_layers": [
    { "layer_type": "macro_regime", "label": "宏观制度", "default_level": "L0" }
  ]
}
```

### 前端扩展 API

```javascript
LoomDensity.registerLayer({
  layer_type: "macro_regime",
  label: "宏观制度",
  default_level: "L0"
});
```

### overlay JS 改动范围

`loom-detail-overlay.js` 新增两个函数，不修改现有逻辑：

```javascript
function _renderDensityBar(overlayEl, artifact) { ... }
function _filterSectionsByDensity(sections, density) { ... }
```

`open()` 末尾调用 `_renderDensityBar()`；`_filterSectionsByDensity()` 替换现有 section 遍历。

---

## Section 5 — 渲染层变更

### `_render_artifact()` 变更

现有渲染逻辑不动，在 `<aside anc-detail>` 里前置 L0 区块：

```python
raw_sources_html = _render_raw_sources(artifact)
raw_items_html   = _render_raw_items(artifact)

# aside 内容顺序:
# [L0] raw_sources_html + raw_items_html
# [L1] detail_sections_html + evidence_html + source_notes_html
# [hand-eval] 不变
```

### `_render_raw_sources(artifact)`

```
<section class="anc-detail-section anc-detail-section--raw"
         data-detail-section="raw-sources"
         data-detail-label="原始数据"
         data-layer-type="raw_source">
  每条 raw_source:
    resource_id badge + content_type + fetched_at
    summary 一行
    <details><summary>展开原始内容</summary>raw 截断到 2000 字</details>
</section>
```

### `_render_raw_items(artifact)`

```
<section class="anc-detail-section anc-detail-section--raw"
         data-detail-section="raw-items"
         data-detail-label="素材"
         data-layer-type="raw_item">
  按 item_type 分组:
    data_point   → anc-kpi--arctic: label + value
    news/blog    → 标题 + 摘要 + tier pill + published_at
    tweet        → author + 原文 + tier pill
    search_snippet → 标题 + snippet + url chip
  每条末尾: relevance（斜体，muted 色）
</section>
```

### 全局数据流

```
Browser Query
     │
     ▼
POST /analyze
     │
     ├─► WorkflowResolver → 决定 hands[]
     │
     ├─► parallel hand.run() × N
     │        ├─ execution: raw_sources[] 捕获
     │        ├─ LLM loop: fetch_resource / fetch_url / web_search
     │        ├─ LLM output: narrative + layers[] + raw_items[]
     │        └─ _normalize_artifact(): shim → sections/evidence 同步
     │
     ├─► BrainHarness.synthesize()
     │        ├─ 读 goal/intent-wiki/flywheel/reward
     │        ├─ LLM: synthesis + regime_relevance + watch_conditions
     │        └─ _build_state_engine() → state_engine{}
     │
     ├─► patch_webview("brain-synthesis", brain_html)
     ├─► patch_webview("brain-state-engine", state_engine_html)   ← 新增
     └─► patch_webview(hand.anchor_id, _render_artifact(art))     ← 含 L0

Browser overlay
     ├─ hover/click → open(target)
     ├─ _renderDensityBar() → [L0][L1][L2][自定义▾]
     ├─ _filterSectionsByDensity() → 按 data-layer-type 过滤
     └─ 用户切换 level → localStorage 持久化 → 重过滤
```

---

## 改动文件清单

| 文件 | 变更内容 |
|------|---------|
| `loom/hands/base.py` | `run()` 追加 raw_sources 捕获；output contract 新增 raw_items；density 校验 |
| `loom/brain.py` | `_render_artifact()` 插入 L0；新增 `_render_raw_sources/items()`、`_build_state_engine()`、`_render_state_engine()`；`/analyze` patch state-engine |
| `loom/brain_harness/base.py` | Brain output contract 追加 regime_relevance / watch_conditions / priority_signal |
| `bridge/webview/loom-detail-overlay.js` | 新增 `_renderDensityBar()` + `_filterSectionsByDensity()`；`open()` 末尾调用 |
| `loom/panel.html` | 预置 `brain-state-engine` anchor 占位 |

---

## 约束

- 不改 UI 风格（Bloom Design System、现有 card/pill/kpi 样式不动）
- `sections`/`evidence` 字段继续存在（backward compat shim 维护同步）
- State Engine 卡不增加 LLM 调用（纯状态读取）
- web_search raw 内容依赖 LLM 自报（Anthropic built-in 工具无法拦截）
