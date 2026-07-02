# P2 · 显影期：幽灵内容（Ghost Content）

> **目标**：hand 的计划不再被"说"出来，而是以半透明的幽灵 block 预先显影在它将要发生的位置。人批准的是未来，而不是审查过去。传统的"是否允许 agent 做 X"弹窗全部消失，变成"这个 ghost 需要你的 patch 才能凝固"——治理彻底空间化。
> **验收标准**：睡前看到明早盘前报告的幽灵轮廓，点掉其中一块不想要的；早上醒来，其余的都已凝固为正文。

---

## 1. 需求分析

### 1.1 本期解决的三个问题

1. **P1 遗留的黑箱感**：杀掉聊天框后，agent 的中长期计划失去了叙述出口。ghost 让"计划的可读性"从一份日志变成一个**排版问题**。
2. **权限疲劳**：弹窗式授权（allow once / always）打断心流且不携带上下文。ghost 把授权变成对具体未来内容的空间性操作。
3. **常驻化的入口**：P2 交付的调度器（trigger 机制）就是"从会话工具到守护进程"的第一块基建，Loom Fin 的盘前场景直接受益。

### 1.2 功能需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1 | ghost block：`state=ghost` 的 block，携带 trigger / eta / hand / budget / plan 元数据 | P0 |
| FR-2 | hand 产出计划 → 编译为 ghost patch 显影到目标位置（Plan Compiler） | P0 |
| FR-3 | ghost 三操作：**立即执行** / **refine 计划本身** / **驱散（dismiss）** | P0 |
| FR-4 | 批量手势："接受今晚全部计划"（fabric 级一键 seal） | P1 |
| FR-5 | `requires_human_seal` 标记：该 ghost 必须有 human patch 才允许凝固 | P0 |
| FR-6 | 调度器：cron / 事件 / 手动三类 trigger；到期起 run，产出 patch 替换 ghost（凝固） | P0 |
| FR-7 | 凝固动画与"昨夜发生了什么"摘要视图（回访时的差异汇总） | P1 |
| FR-8 | 失败态：run 失败的 ghost 转为 error 注记，保留计划便于重试 | P0 |
| FR-9 | ghost 的预算护栏：单个 ghost 与 fabric 级的 token/美元预算上限，超限拒绝调度 | P1 |
| FR-10 | P1 自然语言命令的"先显影再执行"模式：重命令（涉及删除/重构/花费超阈值）先生成 ghost 预览 | P1 |

### 1.3 非功能需求

- 调度精度：cron 触发偏差 ≤ 60s；事件触发（webhook/文件变化）≤ 5s。
- 无人值守可靠性：调度器进程崩溃重启后，从操作流恢复全部待触发 ghost（无独立状态文件）。
- ghost 的视觉密度上限：单屏 ghost 占比超过约 1/3 时自动聚拢为"计划抽屉"，防止文档被未来淹没。

## 2. 设计方案

### 2.1 数据模型（复用 P0，零新表）

ghost 就是一个 block，其元数据放在 block content 的保留字段中；生命周期全部由 patch 表达：

```jsonc
// hand 显影一个 ghost（block.insert，state=ghost）
{ "type": "block.insert", "target": "blk_ghost1", "parent": "blk_sec_market", "index": 0,
  "block": {
    "block_type": "ghost",
    "state": "ghost",
    "ghost": {
      "plan": "开盘后基于持仓数据更新本节收益归因",
      "render_hint": "table",                    // 凝固后的预期形态，用于占位排版
      "trigger": { "kind": "cron", "spec": "30 9 * * 1-5", "tz": "America/Los_Angeles" },
      // 或 { "kind": "event", "topic": "positions.updated" } / { "kind": "manual" }
      "eta": "2026-07-03T09:30-07:00",
      "hand_id": "hand_position",
      "budget": { "usd": 0.50 },
      "requires_human_seal": false
    }
  } }

// 人的三操作，全部是普通 patch：
// 立即执行:  block.command { target: blk_ghost1, verb: "materialize" }
// refine:   block.command { target: blk_ghost1, verb: "refine", text: "只看科技板块" }  // 改的是计划
// 驱散:      block.delete  { target: blk_ghost1 }（软删，历史可见"人否决过这个计划"）
// 盖章:      block.state   { target: blk_ghost1, state_flag: "sealed" }（human 来源才有效）
```

**凝固（materialize）**：run 成功后，hand 以一组普通 patch 替换 ghost（delete ghost + insert 正文块），
新块的 provenance 指向原 ghost 的 patch_id——未来与结果在历史上链接，可追问"当初的计划是什么"。

### 2.2 调度器（Scheduler）

```
ghost patches ──▶ GhostIndex（内存索引，从操作流重放构建）
                     │  到期 / 事件命中 / manual verb
                     ▼
              预算与 seal 校验 ──不通过──▶ 生成 system 注记（"等待盖章"/"超预算"）
                     │ 通过
                     ▼
              Router 起 run（复用 P1 通路）──▶ hand 产出 patch ──▶ 凝固
```

- 单进程事件循环即可（守护线程/独立 worker 均可），**唯一状态源是操作流**：启动时重放
  `state=ghost` 且未删除的 block 重建索引，天然满足崩溃恢复要求。
- 事件 trigger 的来源做成可插拔 `EventSource` 接口：首版提供 定时器、文件监视、HTTP webhook 三种；
  Loom Fin 的行情事件后续以插件接入。
- 并发控制：同一 hand 的 run 数上限、fabric 级并发上限，超限排队（复用 P1 的队列语义）。

### 2.3 重命令的"先显影"模式（FR-10）

Router 增加一个前置判断：命令若命中重操作规则（`restructure`、涉及 delete 的 NL 命令、
预估成本超阈值），不直接执行，而是要求 hand 先返回 plan，编译成 `requires_human_seal=true`
的 ghost 显影在受影响区域。用户点击 ghost 即批准。
——P1 的开放问题"NL 命令是否要预览确认"在此统一收口。

### 2.4 前端呈现

- ghost 样式：半透明 + 虚线边框 + 左上角 ETA 徽章（"今晚 21:00 · hand_market · ~$0.30"）；
  hover 展开完整 plan 文本与三操作按钮。
- 占位排版：按 `render_hint` 渲染骨架屏形态（表格/图表/段落），让"未来的版面"可预览。
- 凝固动画：ghost 渐变为实体（300ms），是本期的"魔法时刻"，值得打磨。
- **昨夜摘要**（FR-7）：回访时顶部横幅"你不在时：3 个 ghost 凝固、1 个失败、2 个仍在等待盖章"，
  点击逐项定位。数据 = 两次访问间的 patch 流按 run 聚合，纯查询无新状态。

### 2.5 与后续期的接口预留

- P3：系统 fabric 的变更提议（改配置、退役 hand）复用 ghost 管道——本期把 ghost 的
  target 校验器做成与 block_type 无关的通用机制。
- P5：生态的"繁殖/死亡提议"即 `requires_human_seal=true` 的 ghost；竞标失败者的
  speculative 产出可显影为可切换的 ghost 变体（本期不实现，但 ghost 元数据预留 `variant_of` 字段）。

## 3. 开发拆解

1. **M2.1** ghost block 类型 + 三操作 patch 语义 + 折叠器支持（0.5 周）
2. **M2.2** Plan Compiler：hand SDK `emit_plan(...)` → ghost patch（0.5 周）
3. **M2.3** Scheduler：GhostIndex 重放 + cron/manual 触发 + 凝固通路（1 周）
4. **M2.4** 事件 EventSource 接口 + 文件/webhook 两个实现（0.5 周）
5. **M2.5** 前端：ghost 渲染、三操作、批量 seal、凝固动画（1 周）
6. **M2.6** 重命令先显影 + 预算护栏 + 昨夜摘要（1 周）

## 4. 测试策略

- 调度器混沌测试：随机 kill 调度进程，断言重启后无 ghost 丢失、无重复触发（幂等以 ghost block_id 为锁）；
- 时区/DST 用例表（cron 的经典坑）；
- E2E：睡前-醒来剧本自动化（时钟 mock 快进）；
- 预算护栏边界：超限 ghost 必须留下可见注记而非静默失败。

## 5. 验收 Demo 脚本

1. 傍晚打开 Loom Fin fabric：明早的盘前报告以幽灵轮廓显影——市场综述（cron 6:00）、
   持仓归因（开盘事件触发）、一条标注"需要你确认"的重构提议；
2. hover 查看各 ghost 的计划与预算；驱散"宏观新闻综述"那块（今天不想看）；
3. 点"接受今晚全部计划"；
4. （快进）早上回访：横幅"你不在时：2 个凝固、1 个被你昨晚驱散"；正文已是成品，
   点开某段落出处，能回溯到昨晚那个 ghost 的原始计划。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| ghost 泛滥，文档被未来淹没 | 视觉密度上限 + 计划抽屉聚拢 + hand SDK 文档明确"少而准"的显影规范 |
| 用户不理解半透明块的含义 | 首次出现时的一次性 tooltip；ETA 徽章用自然语言（"今晚"而非 cron 表达式） |
| 定时任务与命令 run 抢占资源 | fabric 级并发上限 + 夜间批处理窗口（为 P4"睡眠与梦"预留同一调度窗口） |
| seal 语义与 lock 混淆 | 明确：seal 作用于 ghost（批准未来），lock 作用于实体（冻结现在）；UI 图标严格区分 |

**开放问题**：
- ghost 之间的依赖（B 的计划依赖 A 的产出）：首版用 event trigger 串联（A 凝固发事件触发 B），
  显式 DAG 编排推迟到 P5 织谱化时再考虑；
- 驱散是否应告知 hand 原因以供学习：接口预留 dismiss reason 字段，学习闭环归 P4/P5。


## 7. 代码架构与开发指导

### 7.1 模块结构

```
loom/scheduler/  ghost_index.py  triggers.py  loop.py  budget.py
loom/handsdk/session.py（增补 emit_plan）
frontend/ghost.js
```

调度器是独立 worker 进程/线程，与 API 进程通过同一 SQLite 库 + on_appended 钩子通信，
**自身无任何持久状态文件**。

### 7.2 关键类与函数

**handsdk — Plan Compiler（hand 侧唯一新接口）**
```python
class HandSession:
    def emit_plan(self, *, parent_block, plan: str, trigger: Trigger,
                  render_hint="paragraph", budget=None, requires_seal=False, eta=None) -> block_id:
        """把 hand 的计划编译为 state=ghost 的 block.insert patch。
        hand 不需要理解 ghost 生命周期——显影之后的一切归调度器。"""
```

**scheduler/ghost_index.py**
```python
class GhostIndex:
    def rebuild(self, store) -> None
        """启动时重放全部 fabric 的操作流，收集 state=ghost 且未删除的块。
        崩溃恢复 = 重新 rebuild，这就是'唯一状态源是操作流'的全部含义。"""
    def on_patch(self, patch)         # 增量维护：ghost 新增/驱散/凝固/盖章
    def due(self, now) -> list[GhostRef]          # cron 到期
    def on_event(self, topic, payload) -> list[GhostRef]   # 事件命中
```

**scheduler/triggers.py**
```python
class EventSource(Protocol):
    def subscribe(self, topic: str, cb: Callable) -> None
class CronSource(EventSource):     # croniter 驱动；DST 用例表必须过
class FileWatchSource(EventSource) # watchdog
class WebhookSource(EventSource)   # 复用 api 进程的 POST /events/{topic}
```

**scheduler/loop.py 与 budget.py**
```python
class SchedulerLoop:
    def tick(self):
        """due()/on_event 命中 → gate() → RunManager.start(materialize run)。
        materialize run 的 HandSession 携带 ghost 上下文；成功回调 finalize()。"""
    def gate(self, ghost) -> GateResult:
        """三关：requires_seal 未盖章 → 留 system 注记'等待盖章'；
        BudgetGuard 超限 → 注记'超预算'；hand 并发上限 → 排队。"""
    def finalize(self, ghost, run_result):
        """成功：delete ghost + insert 正文（provenance 指向 ghost patch_id）；
        失败：ghost → error 注记（保留 plan 供重试）。全部经 store.append，无私有状态。"""
class BudgetGuard:
    def check(self, ghost) -> bool     # 单 ghost 与 fabric 日预算（读 sys:config）
```

**Router 增补（重命令先显影，FR-10）**
```python
class HeavyCommandGate:   # 挂在 CommandConsumer 与 Router 之间
    def intercept(self, cmd, tree) -> bool
        """命中重操作规则（restructure/含删除的 NL/预估超阈值）→ 改派 hand 走 emit_plan
        产出 requires_seal=True 的 ghost，而非直接执行。规则表进 sys:config。"""
```

**frontend/ghost.js**
```js
class GhostRenderer {
  render(block)              // 半透明 + ETA 徽章 + render_hint 骨架屏
  actions(blockId)           // materialize / refine / dismiss 三操作 → postCommand
  sealAll(fabricId)          // 批量盖章手势
  densityGuard()             // 单屏 ghost >1/3 → 聚拢为计划抽屉
}
function nightSummaryBanner(sinceSeq)  // "你不在时…"：GET /timeline?after= 按 run 聚合，纯查询
```

### 7.3 编码顺序（与 M2.x 对应）

1. ghost 的 op 语义进 reducer（state=ghost 的折叠 + 三操作）+ `emit_plan` →
2. `GhostIndex`（rebuild + 增量，混沌测试同步写）→ 3. `CronSource + loop.tick + finalize`
（时钟 mock 快进跑通睡前-醒来剧本）→ 4. `budget.py + gate()` → 5. `ghost.js` 全套 →
6. `HeavyCommandGate` + 昨夜摘要。

**纪律**：调度器代码里出现任何"写文件保存状态"即违规——状态只能长在操作流上；
finalize 的幂等锁以 ghost block_id 为键（混沌测试会专门打这里）。
