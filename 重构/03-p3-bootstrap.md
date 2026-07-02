# P3 · 照镜期：自举一期（Loom 本身就是一块 fabric）

> **目标**：把系统自身的三样内部状态——**配置、hand 注册表、wiki**——渲染为 fabric，用同一套 handle 读写。改一个超时参数 = refine 一句话；禁用一个 hand = lock 它的注册条目；纠正 agent 的一条认知 = 点击那条 wiki。
> **范围纪律**：只做这三样（一期）。日志/运行轨迹 fabric 化（二期）、Loom 用 Loom 开发自己（三期）明确不在本期。
> **验收标准**：全程不打开任何设置页/配置文件，在文档里把系统改了。

---

## 1. 需求分析

### 1.1 为什么排在 P3，以及它偷来的三样东西

1. **对 P1 的压力测试**：团队被迫每天用 in-document 交互改配置——新范式若有手感缺陷，自己先疼。
2. **白捡的差异化**：wiki 的 fabric 化顺手实现了"可点击的记忆"——用编辑文档的方式编辑 agent 的心智，
   与一切"记忆=黑盒向量库"的方案拉开身位。
3. **为 P5 铺床**：注册表成为 fabric 后，hand 的采纳率/成本等生态度量直接作为元素长在注册条目上。

### 1.2 功能需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1 | 三块系统 fabric：`sys:config`、`sys:registry`、`sys:wiki/<hand_id>`，可从全局导航进入 | P0 |
| FR-2 | 双向投影器：内部状态 → blocks（读）；patch → 状态变更（写，经校验） | P0 |
| FR-3 | handle 语义映射表（§2.3）：八个 handle 在系统 fabric 上的确定性语义 | P0 |
| FR-4 | Schema 校验器：非法 patch 不落地为状态变更，物化为 error/conflict 注记 block | P0 |
| FR-5 | 危险变更走 ghost：删除 hand、改权限类配置 → `requires_human_seal` 的 ghost（复用 P2） | P1 |
| FR-6 | wiki 条目 block 化：每条认知一个 block，provenance 指向产生它的 run | P0 |
| FR-7 | wiki 的 handle 语义：refine=修正认知、branch=并存假设、lock=固化为公理、delete=遗忘、annotate=人类批注 | P0 |
| FR-8 | hand 读取 wiki 时尊重状态：locked 认知不可被 hand 覆写；人工修正过的认知优先级高于自动习得 | P0 |
| FR-9 | 系统 fabric 的变更审计视图（就是 patch timeline，零开发，验证可用即可） | P2 |

### 1.3 非功能需求

- 投影一致性：内部状态与 fabric 投影的收敛延迟 ≤ 1s（含外部途径改动状态的场景，如 hand 自己写 wiki）;
- 安全：系统 fabric 的写 patch 仅接受 `source_type=human` 或白名单 system 流程；hand 不得直接 patch `sys:config` 与 `sys:registry`（hand 想改系统 → 只能通过 ghost 提议）；
- 失败必须可见：校验拒绝的 patch 在原位留下 error 注记（含原因），禁止静默丢弃。

## 2. 设计方案

### 2.1 双向投影器（本期核心构件）

```
                    read: project()
  内部状态源 ────────────────────────▶  system fabric（blocks）
  (config store /                       │
   hand registry /   ◀───────────────── │ write: apply(patch)
   wiki store)          经 Schema 校验    │
```

- 每类状态实现一个 `SystemProjector` 接口：
  `project(state) -> blocks`、`apply(patch, state) -> state | ValidationError`、`schema`；
- **真理源仍是内部状态**（不是 patch 流）——系统 fabric 的操作流是状态变更的**日志与界面**，
  投影器保证两者收敛。这与普通 fabric（patch 流即真理）刻意不同，理由：配置需要被非 Loom
  进程（启动脚本、hand runtime）直接读取，不能要求所有读者先学会折叠；
- 外部改动（如 hand 运行时写入 wiki 文件）通过状态源的变更通知 → 投影器生成 system 来源的
  patch 补录进流，保持时间线完整。

### 2.2 三块 fabric 的块结构

```
sys:config                          sys:registry                     sys:wiki/hand_market
├─ section: 运行时                   ├─ hand: hand_market             ├─ 认知: "美股盘前流动性低,
│   ├─ item: 默认runtime = cc        │   ├─ 字段: runtime=cc          │        信号噪声大" [locked]
│   ├─ item: run超时 = 300s          │   ├─ 字段: 权限=read_market     ├─ 认知: "用户只关心科技板块"
├─ section: 预算                     │   ├─ 度量占位(P5): 采纳率/成本   │        [由 run_1832 习得]
│   ├─ item: fabric日预算 = $5       │   └─ 状态: enabled              ├─ 假设(branch): "财报季应
└─ section: 调度                     ├─ hand: hand_sentiment           │        提高扫描频率" A/B 两支
    └─ item: 夜间窗口 = 01:00-05:00  └─ ...                            └─ 人类批注(annotate): ...
```

每个 config item / registry 字段 / wiki 条目 = 一个 block，`block_type` 分别为
`sys.config_item`、`sys.registry_field`、`wiki.entry`，content 中携带 `schema_ref` 供校验器寻址。

### 2.3 handle 语义映射表（写给 hand 与前端的契约）

| handle | sys:config | sys:registry | sys:wiki |
|---|---|---|---|
| refine | 修改值（经类型/范围校验） | 修改字段（如 runtime cc→codex） | 修正认知内容 |
| edit | 同 refine（直接编辑） | 同 refine | 同 refine |
| expand | 展开该项的说明与影响面 | 展开 hand 详情/历史 | 展开认知的证据链（关联 run） |
| shorten | N/A（拒绝并提示） | 折叠详情 | 压缩为更简认知（蒸馏） |
| annotate | 加运维备注 | 加备注 | 人类批注（hand 必读的边注） |
| branch | N/A（拒绝） | N/A | 认知分叉为并存假设 |
| restructure | 重排分组（仅视图） | 重排（仅视图） | 认知重组/合并（危险，走 ghost） |
| lock | 冻结配置项（防误改与防 hand 提议） | **禁用该 hand** | 固化为公理（hand 不可覆写） |
| delete | 恢复默认值（软） | 移除 hand（走 ghost + seal） | **遗忘**该认知（软删，历史可见） |

拒绝语义统一：不适用的 handle 返回带原因的轻量 toast，不产生 patch。

### 2.4 校验与危险变更

- Schema 用 JSON Schema 表达（config 与 registry 字段各一份），校验失败 → error 注记 block
  （原值不动），注记含失败原因与"改成合法值"的快捷入口；
- 危险清单（首版写死）：删除/新增 hand、改权限字段、改预算上限——命中即转 ghost
  （`requires_human_seal=true`），复用 P2 管道，无新机制。

### 2.5 wiki：可点击的记忆（本期的对外亮点）

- 存量 wiki（Markdown 文件）迁移：按条目切分为 `wiki.entry` block，无法自动切分的整页
  作为单块导入，后续由 shorten/restructure 渐进整理；
- hand 侧读取协议升级：`wiki.query()` 返回条目携带状态标志，SDK 强制规则——
  `locked` 条目注入 system 段（不可违背），`annotate` 批注随条目一起注入，人工 `refine`
  过的条目在冲突时覆盖自动习得版本；
- 出处贯通：hand 写入新认知时必带 run_id，前端"证据链"入口从认知直接跳到当次 run 的
  patch 时间线——用户可以审计"你凭什么这么认为"。

## 3. 开发拆解

1. **M3.1** `SystemProjector` 接口 + config 投影器（读+写+校验）（1 周）
2. **M3.2** registry 投影器 + 危险变更 ghost 化（0.5 周）
3. **M3.3** wiki 存储条目化改造 + 迁移脚本 + wiki 投影器（1 周）
4. **M3.4** handle 语义映射接线（前端按 block_type 裁剪命令面板）+ hand SDK 的 wiki 状态协议（0.5 周）
5. **M3.5** 团队狗粮周：全员一周内禁止直接编辑配置文件，问题清单反哺 P1 手感（0.5 周，穿插）

## 4. 测试策略

- 投影器往返性质测试：`apply(project(state) 上的合法 patch)` 后再 project，状态与视图收敛；
- 校验器矩阵：每个 schema 字段的非法值 → 必须产生 error 注记且状态不变；
- 越权测试：hand 直接 patch sys:config/registry → 拒绝并留痕；
- wiki 语义测试：locked 认知在 hand 的下一次 run 中确实进入不可违背段（对 runtime 适配层做契约断言）。

## 5. 验收 Demo 脚本

1. 打开 `sys:config`，圈选"run 超时 = 300s"→ refine →"改成 600"→ 原地生效，出处显示"你，刚刚"；
2. 打开 `sys:registry`，选中 hand_sentiment → `L`（lock）→ 该 hand 即刻禁用，正文中它的运行徽章消失；
3. 尝试删除一个 hand → 出现需要盖章的 ghost 提议，而非直接执行；
4. 打开 `sys:wiki/hand_market`，点击认知"用户只关心科技板块"→ refine 为"用户关心科技与能源板块"
   → 展开证据链看到它源自哪次 run；再 lock 一条盘前流动性公理；
5. 触发一次盘前分析，展示 hand 的产出遵循了刚修正的认知——**全程没有打开过任何设置页**。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 双真理源（状态 vs 流）漂移 | 投影器收敛测试 + 定时对账任务（diff 状态与折叠视图，不一致即告警） |
| wiki 条目切分质量差 | 允许整页导入 + 渐进整理；切分器只处理有明确条目结构的文件 |
| 用户误 lock 关键 hand/config | lock 可随时 unlock（无副作用）；registry 的 lock 附带影响提示（"3 个 ghost 依赖此 hand"） |
| handle 语义表学习成本 | 命令面板按 block_type 只显示适用 handle，映射表对用户不可见、对开发是契约 |

**开放问题**：
- wiki 是否需要向量检索层：本期不需要（条目量小、hand 全量注入）；量级上来后在投影器后加检索索引，不影响本设计；
- 二期（日志/轨迹 fabric 化）的触发条件：P5 需要按 run 审计时再立项。

## 7. 代码架构与开发指导

### 7.1 模块结构

```
loom/system/  projector.py  config.py  registry.py  wiki.py  reconciler.py  guard.py  handle_map.py
loom/system/schema/  config.schema.json  registry.schema.json
loom/hands/（wiki 协议在 handsdk 侧的增补）
```

### 7.2 关键类与函数

**projector.py — SystemProjector（本期核心抽象）**
```python
class SystemProjector(Protocol):
    fabric_id: str                       # sys:config / sys:registry / sys:wiki/<hand>
    def project(self, state) -> list[Block]
        """内部状态 → 块列表。必须稳定：同一状态两次 project 产出相同 block_id（用状态键派生 id）。"""
    def apply(self, patch, state) -> ApplyResult
        """patch → 状态变更。返回 ok(new_state) | rejected(reason)。
        rejected 由框架物化为 error 注记 block，原状态不动。"""
    def schema(self, block) -> dict | None   # 校验器寻址

class SystemFabricHost:
    """把 Projector 挂进 patch 流的框架：
    on_appended(sys patch) → guard.check → projector.apply → 成功则更新状态并触发 re-project；
    状态源变更通知 → reconciler 补录 system patch。所有 Projector 共用，写一次。"""
```

**guard.py**
```python
def check(patch, fabric_id) -> bool
    """sys:config / sys:registry 只接受 source=human 或白名单 system 流程；
    hand 想改系统 → 只能 emit_plan 出 ghost 提议。违规即拒 + 留痕。"""
```

**config.py / registry.py**
```python
class ConfigStore:        # get/set/watch；文件或表存储，供非 Loom 进程直读
class ConfigProjector(SystemProjector):
    # project: section → sys.config_item blocks；apply: refine/edit → JSON Schema 校验 → set
class RegistryProjector(SystemProjector):
    # apply 的特例：lock=禁用 hand（联动 Router 候选集）；delete/新增/改权限 → 转 ghost（复用 P2）
    # 预留 metric_blocks(hand_id) 挂点 —— P5 在此追加指标块，不改本类其余代码
```

**wiki.py**
```python
class WikiEntry:          # id, text, status(auto|refined|locked|disputed), source_run, annotations[]
class WikiStore:
    def entries(self, hand_id) / upsert(entry) / migrate_markdown(path) -> list[WikiEntry]
class WikiProjector(SystemProjector):
    """handle 语义按 §2.3 映射表实现：refine→修正+status=refined；lock→公理；
    branch→并存假设（两条 entry 共享 hypothesis_group）；delete→软删=遗忘。"""
```

**handsdk 侧 wiki 协议**
```python
class HandSession:
    def wiki(self) -> WikiView
        """run 上下文注入规则（SDK 强制，hand 不可选择性无视）：
        locked 条目 → system 段（不可违背）；annotations 随条目注入；
        refined 条目在与 auto 条目冲突时覆盖后者。"""
```

**handle_map.py + 前端**
```python
HANDLE_MAP: dict[(block_type, verb) -> handler | Rejected(reason)]
# 前端 palette.js 读 GET /system/handle-map 按 block_type 裁剪按钮——映射表只维护一份
```

### 7.3 编码顺序（与 M3.x 对应）

1. `SystemFabricHost + guard`（框架先行，用假 Projector 过契约测试）→
2. `ConfigProjector`（最简单，验证读写闭环 + 校验 + error 注记）→
3. `RegistryProjector`（含 ghost 化危险变更）→ 4. `WikiStore 条目化 + 迁移脚本` →
5. `WikiProjector + handsdk wiki 协议`（对 runtime 适配层加契约断言）→
6. `handle_map` 接前端 + 狗粮周。

**纪律**：Projector 的 apply 绝不直接写 patch 流（框架负责补录），否则双真理源必漂移；
对账任务（reconciler 的 diff 告警）与功能同 PR 交付，不许"以后再加"。
