# P4 · 凝视期：文档反过来看你

> **目标**：注意力成为输入。停留、滚动、跳过、回访、圈选都是隐式反馈；被长期忽略的区块自动收拢成一行摘要，被反复凝视的区块加深展开，hand 从阅读行为中学习口味。
> **核心设计决定**：注意力推断**不直接驱动行为**，而是先落成 wiki 里可见、可点击、可反驳的认知条目，hand 引用这些认知来调整文档。惊悚问题由 P3 的"可点击记忆"结构性化解：文档对你的全部了解，你都看得到、改得掉、删得干净。
> **验收标准**：打开"注意力透镜"，看到文档上叠加的热力层，然后看到它据此把自己重新折叠了一遍。

---

## 1. 需求分析

### 1.1 边界（先说不做什么）

- 不采集：摄像头/眼动、键击内容、Loom 之外的任何行为；
- 不上传：全部信号本地处理与存储，不进入任何云端 runtime 的上下文（进入上下文的只有蒸馏后、
  用户可见的 wiki 认知）；
- 不默认开启：全局默认关，按 fabric 粒度显式开启；
- 不静默行动：任何由注意力驱动的文档变化都带可见标记与一键还原。

### 1.2 功能需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1 | 信号采集 SDK（前端）：块级视口停留、滚动速度、跳过、回访计数、圈选/点击密度 | P0 |
| FR-2 | 会话聚合：原始事件在本地聚合为块级会话统计，原始事件保留 ≤ 7 天 | P0 |
| FR-3 | 推断器：规则引擎 + 可选本地小模型，输出**候选认知**（附证据与置信度） | P0 |
| FR-4 | 候选认知落 `sys:wiki` 的独立分区（`attention` 来源标注），经 P3 管道可 refine/lock/delete | P0 |
| FR-5 | 折叠行为 v1：连续 N 次会话被忽略的块 → 自动收拢为一行摘要，带"Loom 折叠了这里"标记 + 一键还原 | P0 |
| FR-6 | 展开行为 v1：高关注块的 hand 在后续 run 中加深、扩写（通过读取 wiki 认知实现，非硬编码） | P1 |
| FR-7 | 注意力透镜：热力叠加层可视化（按块着色 + 数值 tooltip） | P0 |
| FR-8 | 隐私控制台：per-fabric 开关、数据用量展示、一键清除全部注意力数据 | P0 |
| FR-9 | 反馈闭环：用户还原被折叠的块 = 强负反馈，推断器必须消费（撤销/降权相应认知） | P0 |
| FR-10 | 夜间蒸馏任务：会话统计 → 认知候选的批处理跑在 P2 调度器的夜间窗口（"睡眠与梦"的第一小步） | P1 |

### 1.3 非功能需求

- 采集开销：滚动帧率不受影响（事件采样 + requestIdleCallback 批处理），事件缓冲本地 flush；
- 冷启动纪律：单 fabric 累计 < 5 个阅读会话时，推断器保持沉默（防学噪声）;
- 可解释：每条 attention 认知必须能展开证据（"过去 12 次会话你平均 1.2s 内滚过本节"）。

## 2. 设计方案

### 2.1 管道总览

```
前端 AttentionSDK（采样事件）
   │ 本地批量 flush
   ▼
attention_events（本地 SQLite，≤7天滚动）
   │ 会话结束 / 夜间窗口
   ▼
会话聚合 attention_stats（block_id × 会话 的统计行，长期保留）
   │ 推断器（规则 + 可选本地小模型）
   ▼
候选认知 ──▶ sys:wiki 的 attention 分区（普通 wiki.entry block，source=attention）
                │ 人可 refine / lock / delete（P3 机制，零新开发）
                ▼
hand 在 run 中读取（与其他 wiki 认知同一协议）──▶ 折叠/加深等文档行为（patch，可还原）
```

关键点：**行为层与推断层解耦**。折叠/展开都是 hand（或专职的 `hand_curator`）读了认知后
发出的普通 patch——注意力系统本身从不直接改文档。

### 2.2 信号与统计定义

```sql
CREATE TABLE attention_stats (
  fabric_id TEXT, block_id TEXT, session_id TEXT,
  dwell_ms INTEGER,        -- 块在视口 ≥50% 面积的累计毫秒
  scroll_v REAL,           -- 经过该块时的平均滚动速度（px/s）
  skipped INTEGER,         -- 本会话是否 <800ms 掠过（0/1）
  revisits INTEGER,        -- 本会话内回访次数
  interactions INTEGER,    -- 圈选/点击/handle 次数
  ts TEXT,
  PRIMARY KEY (fabric_id, block_id, session_id)
);
```

### 2.3 推断器 v1（规则先行）

首版只上三条高置信规则，全部输出为**候选**认知：

1. **忽略**：近 K(=8) 次会话中 skipped 率 ≥ 80% 且 interactions=0 →
   候选："用户似乎不关注〈块摘要〉一类内容"（confidence=中）；
2. **偏好**：dwell 与 interactions 在 fabric 内 z-score ≥ +1.5 持续 K 次 →
   候选："用户高度关注〈主题〉"；
3. **节奏**：工作日早间会话集中于某 section →
   候选："早间阅读聚焦〈section〉，其余可后置"。

本地小模型（可选，feature flag）：仅用于把块内容归纳成认知文本里的〈主题〉短语，
不参与判定。规则的 K、阈值全部进 `sys:config`（吃 P3 狗粮）。

### 2.4 折叠行为 v1（唯一的自动行为）

- 执行者：内置 `hand_curator`（一个极简 hand，只做视图级整理，无内容生成权限）；
- 折叠 = 一条 `block.state` patch（新增视图态 `folded`，折叠器渲染为单行摘要 + 标记图标），
  **不删除不移动任何内容**；
- 还原按钮 = `block.state → normal` 的 human patch，同时 SDK 上报强负反馈事件，
  推断器将对应认知置为 `disputed`（hand 不再引用，等待人处置或衰减删除）。

### 2.5 注意力透镜与隐私控制台

- 透镜：开关后按 dwell 分位数给块叠加冷暖色层，tooltip 显示原始统计；同屏展示当前生效的
  attention 认知列表（点击即跳 wiki 条目）——**看到数据、看到推断、看到出口**，三样在同一视图；
- 隐私控制台入口固定在 fabric 菜单：开关、事件量/统计量、一键清除（连带删除 attention 分区认知，
  以 patch 形式留下"用户清除了注意力数据"的系统注记，数据本体物理删除）。

### 2.6 与 P5 的接口

attention 认知是竞标路由器可选的打分特征之一（"该用户在此类块上偏好 hand_x 的产出风格"），
本期只保证认知的机器可读结构（`subject / predicate / evidence / confidence` 四字段 JSON），
不实现消费方。

## 3. 开发拆解

1. **M4.1** AttentionSDK：块级视口观测（IntersectionObserver）+ 采样 + 本地落库（1 周）
2. **M4.2** 会话聚合 + attention_stats + 7 天滚动清理（0.5 周）
3. **M4.3** 推断器 v1（三规则）+ 候选认知写入 wiki attention 分区（1 周）
4. **M4.4** hand_curator + folded 视图态 + 还原与负反馈闭环（0.5 周）
5. **M4.5** 注意力透镜 + 隐私控制台 + per-fabric 开关（1 周）
6. **M4.6** 夜间蒸馏迁移到调度器窗口 + 阈值进 config（0.5 周）

## 4. 测试策略

- 采集正确性：录制的滚动剧本回放 → dwell/skip 统计与人工标注误差 ≤ 10%；
- 冷启动纪律：< 5 会话时推断器零输出（硬断言）；
- 负反馈闭环 E2E：折叠 → 还原 → 断言认知进入 disputed 且下一夜不再产生同类折叠；
- 隐私：一键清除后全库 grep 无残留事件/统计/认知；关闭开关后 SDK 零事件发出（网络层断言）。

## 5. 验收 Demo 脚本

1. 在 Loom Fin fabric 开启注意力采集，正常使用一周（或用回放脚本模拟 10 次会话：
   每次都掠过"宏观新闻"、细读"持仓归因"）；
2. 打开注意力透镜：热力层显示"持仓归因"炽热、"宏观新闻"冰冷；侧栏出现两条候选认知；
3. 次日回访："宏观新闻"已被收拢为一行摘要，带折叠标记；"持仓归因"的晨间 ghost 计划变得更深入
   （hand 引用了偏好认知）；
4. 点击折叠标记还原 → 展开 wiki 看到对应认知被标记为 disputed；
5. 进隐私控制台一键清除，透镜变空白——**它看你的一切，你都能看到并抹掉**。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 从魔法滑向惊悚 | 默认关 + 空间可见（透镜）+ 认知可反驳（P3）+ 一键清除；营销与文档口径统一为"本地、可见、可撤销" |
| 学到噪声（访客代看、临时任务） | 冷启动纪律 + 会话去重 + disputed 机制兜底 |
| 折叠错关键内容引发不信任 | v1 只折叠、绝不删改；折叠标记醒目；连续两次被还原的块列入永不折叠名单 |
| 采集拖慢前端 | 采样 + idle 批处理 + 性能预算纳入 CI（滚动 FPS 回归测试） |

**开放问题**：
- 多人共用一台设备的会话污染：P6 身份系统就绪前，提供"访客模式"暂停采集作为权宜；
- 注意力认知是否参与跨 fabric 泛化（"你在所有 fabric 都跳过宏观新闻"）：诱人但危险，留待 P4 数据成熟后单独评审。

## 7. 代码架构与开发指导

### 7.1 模块结构

```
frontend/  attention.js  lens.js
loom/attention/  store.py  aggregate.py  infer.py  writer.py  privacy.py
loom/hands/hand_curator.py
```

依赖关系刻意做成"只出不进"：attention 包产出 wiki 条目后即止步——**折叠等文档行为由
hand_curator（普通 hand）消费认知后发普通 patch 完成**，attention 包自身没有任何改文档的能力。

### 7.2 关键类与函数

**frontend/attention.js — AttentionSDK**
```js
class AttentionSDK {
  enable(fabricId) / disable(fabricId)     // per-fabric 开关；disable 后零事件（网络层断言）
  observe(root)        // IntersectionObserver 注册全部 block；threshold [0, .5, 1]
  sample()             // requestIdleCallback 批采样：dwell/scrollV/skip/revisit/interactions
  flush()              // 本地批量 POST /attention/events；页面隐藏时 sendBeacon 兜底
}
```

**store.py / aggregate.py**
```python
class AttentionStore:      # attention_events(≤7天滚动) 与 attention_stats 两表
    def purge_expired(self) / purge_all(fabric_id)
def aggregate_session(events) -> list[StatRow]
    """会话结束或夜间窗口触发；产出 §2.2 定义的块级统计行。纯函数，可回放测试。"""
```

**infer.py — 推断器 v1**
```python
class Rule(Protocol):
    def evaluate(self, stats_window, fabric_ctx) -> list[CandidateInsight]
class IgnoreRule(Rule): ...      # skipped≥80% × K次 × 零交互
class PreferenceRule(Rule): ...  # dwell/interactions z-score ≥ +1.5 持续 K 次
class RhythmRule(Rule): ...      # 时段 × section 聚集
class RuleEngine:
    def run(self, fabric_id) -> list[CandidateInsight]
        """冷启动纪律在此硬编码：会话数 <5 直接返回 []。阈值 K 等全部读 sys:config。"""
@dataclass
class CandidateInsight:   # subject/predicate/evidence(统计摘要+样本会话)/confidence —— P5 机读四字段
```

**writer.py**
```python
def write_candidates(insights) -> None
    """经 WikiStore 写入 attention 分区（source=attention）。含去重与更新逻辑：
    同 subject 已存在 → 更新 evidence；已被人 disputed/deleted → 永不复写（负反馈的持久化）。"""
def on_restore_feedback(block_id):
    """用户还原折叠块的强负反馈：定位对应认知 → status=disputed。"""
```

**hands/hand_curator.py（唯一的自动行为执行者）**
```python
class HandCurator:
    """极简内置 hand：无内容生成权限，只发 block.state(folded/normal) patch。
    def decide(self, insights, tree) -> list[Op]:
        只消费 confidence≥阈值 且非 disputed 的忽略类认知 → folded patch（带认知引用进 meta）；
        连续两次被还原的块进 never_fold 名单（存 sys:config）。跑在 P2 夜间调度窗口。"""
```

**lens.js / privacy.py**
```js
class AttentionLens {
  toggle()             // GET /attention/stats?fabric= → dwell 分位数冷暖着色叠加层
  tooltip(blockId)     // 原始统计 + 当前生效认知列表（点击跳 wiki 条目）
}
```
```python
class PrivacyConsole:  # usage() / purge_all()：物理删除 + 留系统注记 patch；接 UI 三件套
```

### 7.3 编码顺序（与 M4.x 对应）

1. `attention.js`（滚动剧本回放的采集正确性测试先写）→ 2. `store + aggregate`（含 7 天滚动清理）→
3. `RuleEngine` 三规则 + `writer`（冷启动与去重的硬断言）→
4. `hand_curator` + folded 视图态（reducer 增补）+ 还原负反馈闭环 →
5. `lens.js + privacy` → 6. 阈值迁入 sys:config + 夜间窗口接线。

**纪律**：attention 包 import loom.core.store 即违规（它只许经 WikiStore 说话）；
任何新增自动行为必须走 hand_curator 且可一键还原——"推断"与"行动"的隔离是本期的安全带。
