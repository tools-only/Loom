# P1 · 弑君期：杀掉聊天框

> **目标**：彻底移除全局 prompt bar。所有意图表达溶解进文档内部——任意位置直接打字、圈选下命令、`@` 某个 hand、页边评论。聊天降级为锚定在元素上的评论线程。
> **一句发布文案**：聊天框没有被删除，它被溶解了——**每个元素都是它自己的 prompt bar**。
> **验收标准**：从空白 fabric 出发织出一个完整 dashboard，全程画面中不出现任何全局输入框。

---

## 1. 需求分析

### 1.1 为什么必须"杀"而不是"藏"

只要聊天框还在，用户就会退回旧范式，click-to-refine 永远只是"附加功能"，差异化无法成立。
本期同时要诚实面对代价：用户被聊天范式训练了三年；杀掉聊天框后失去的最大东西不是输入框，
而是 agent 的**进度叙述流**（"我正在做 X，接下来做 Y"）。该缺口由两处补偿：
① 本期的元素级运行状态呈现（§2.5）；② P2 的幽灵内容（计划直接显影在将要发生的位置）。
**因此 P1 与 P2 必须连续交付。**

### 1.2 交互歧义的裁决原则（本期最重要的产品决定）

**不做意图识别去猜"打字是内容还是命令"，歧义一律交给显式手势：**

| 手势 | 语义 | 落成的 patch |
|---|---|---|
| 在 block 内直接打字 / 编辑 | 内容编辑 | `block.update`（source=human） |
| 圈选文本 / 选中 block → 浮出命令面板 | 对目标下命令 | `block.command`（verb=handle 或自然语言） |
| 输入 `/` | 块级插入与命令菜单（Notion 式救生索） | 按选择生成 insert 或 command |
| `@hand_name` | 将命令显式路由给指定 hand | command.mentions 填充 |
| 页边点击 → 评论 | 讨论，不触发执行 | `comment.add`（可再升级为命令） |
| 空白 fabric 的第一个块 | 整块 fabric 的初始 prompt | 对 root block 的 command |
| 选中 root（标题区）下命令 | 全局命令 | target = root block 的 command |

### 1.3 功能需求

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1 | 移除全局 prompt bar；空白 fabric 首块即 prompt | P0 |
| FR-2 | Selection Manager：文本圈选与 block 选中（含多选）的统一选区模型 | P0 |
| FR-3 | 命令面板：浮动于选区，含 8 个 handle 快捷键 + 自然语言输入 + `@` 补全 | P0 |
| FR-4 | `/` 菜单：块插入（文本/图表/表格/hand 产物占位）与常用命令 | P0 |
| FR-5 | 页边评论线程：锚定 block，thread 本身是 block 子树；评论可一键"升级为命令" | P1 |
| FR-6 | 元素级运行状态：被命令的 block 显示接单 hand、阶段、可中断按钮 | P0 |
| FR-7 | 出处面板：任意 block 一键查看 provenance（P0 数据的 UI 化） | P1 |
| FR-8 | 命令路由器：消费 `block.command` patch，分派 hand，run 产出 patch 回流 | P0 |
| FR-9 | 旧聊天会话迁移：历史对话渲染为挂在 root 上的评论线程（只读） | P2 |
| FR-10 | 遥测：命令入口分布（圈选/斜杠/@/评论升级）、任务完成率、无所适从率（进入后 60s 无任何 patch） | P1 |

### 1.4 非功能需求

- 命令面板呼出 ≤ 100ms；从下达命令到目标 block 出现运行态 ≤ 500ms（不含模型时延）。
- 全键盘可达：选中 block → 快捷键直达 8 个 handle（例：`R` refine、`B` branch、`L` lock）。
- 移动端降级方案：长按代替圈选，命令面板改为底部抽屉（本期出设计稿，可后置实现）。

## 2. 设计方案

### 2.1 总体数据流

```
人（浏览器）                         服务端                         hand runtime
  │ 圈选/打字/@                        │                              │
  ├─ block.command patch ───────────▶ │ 追加进操作流                  │
  │                                   ├─ Router 消费 command ─────────▶ 起 run（携带上下文包）
  │ ◀─ SSE: tree diff ─────────────── │ ◀── emit_patch(...) ──────────┤
  │  (目标 block 进入 running 徽章)    │   run 的产出 patch 回流折叠      │
```

意图即 patch（P0 的 `block.command`）带来的直接收益：命令可审计、可重放、可归因，
且"命令排队/取消"就是操作流上的普通状态管理。

### 2.2 Selection Manager（前端核心模块）

- 统一选区模型：`{ kind: 'text'|'block'|'multi-block', anchor_block, range?, block_ids[] }`；
- 文本圈选跨 block 时，向上归一到共同祖先并降级为 multi-block；
- 选区序列化进 command patch（`target` + 可选 `text_range`），使 hand 精确知道"圈的是哪半句"；
- 依赖 P0 投影输出的稳定 `data-block-id` 锚点。

### 2.3 命令面板（Command Palette）

- 布局：第一行 8 个 handle 图标（快捷键提示）；第二行自然语言输入（占位符随选区类型变化，
  如选中图表时提示"改成滚动 12 个月趋势…"）；输入 `@` 触发 hand 补全（数据来自注册表）。
- handle 点击 = 立即发出 `verb=<handle>` 的 command；自然语言 = `verb=nl`。
- **routing 缺省规则**（P5 竞标器的前身，本期写死为简单策略）：
  ① mentions 非空 → 指定 hand；② block 的 provenance 上有"惯常负责 hand" → 沿用；③ 否则走默认通用 hand。
  该策略实现为独立的 `Router` 接口，P5 将整体替换其实现。

### 2.4 `/` 菜单与空白 fabric

- `/` 菜单项来自两个源：静态块类型 + 注册表中各 hand 声明的"可插入产物"（如 `/盘前报告`）。
- 空白 fabric：渲染一个居中的 molten 首块，占位文案即引导语；用户输入的第一段文字
  自动包装为对 root 的 command——**空白画布本身就是 prompt**。

### 2.5 元素级运行状态（进度叙述流的替代品·其一）

- block 徽章状态：`queued → running(hand 头像 + 阶段短语) → done/failed`；
- hand SDK 增加 `emit_status(block_id, phrase)` 轻量通道（不落 patch 流，仅 SSE 转发；
  阶段短语示例："正在拉取持仓数据"）；
- 运行中的 block 支持 **中断**（发送 `block.command verb=cancel`，Router 终止 run）与
  **排队查看**（同一 block 的命令按序执行）。

### 2.6 评论线程

- thread 是挂在目标 block 下的特殊子树（`block_type=comment_thread`），天然获得历史与出处；
- hand 可以被 `@` 进线程参与讨论（其回复是 comment patch，不改动正文）；
- "升级为命令"按钮：把该条评论文本包装成对宿主 block 的 command——这是从"聊天肌肉记忆"
  到新范式的最重要滑轨。

### 2.7 视觉语言（配合 frontend 设计）

- molten block：微弱的呼吸边框；committed：无装饰；locked：角标锁；running：hand 头像徽章；
- 出处面板：hover 角标 → 浮层显示 创建者 / 最后修改 / run 链 / 成本；
- 所有装饰必须可通过"安静模式"一键收敛，避免文档变成圣诞树。

## 3. 开发拆解

1. **M1.1** Selection Manager + block 锚点接线（1 周）
2. **M1.2** 命令面板（handle + NL + @补全）+ command patch 通路（1 周）
3. **M1.3** Router v0（写死策略）+ run 生命周期 + SSE tree-diff 推送（1 周）
4. **M1.4** 元素级运行状态徽章 + 中断/排队（0.5 周）
5. **M1.5** `/` 菜单 + 空白 fabric 首块（0.5 周）
6. **M1.6** 评论线程 + 升级为命令（1 周）
7. **M1.7** 移除全局 prompt bar（feature flag 灰度）+ 遥测埋点 + 出处面板（0.5–1 周）

灰度策略：内部先行（配合 P3 自举吃自己的狗粮）→ 新用户默认无聊天框 → 存量用户切换，
每一步观察遥测中的"无所适从率"与任务完成率。

## 4. 测试策略

- 交互 E2E（Playwright）：七种手势 × 命令通路 × 中断/排队的全矩阵；
- Router 契约测试：command patch 进 → run 起 → patch 回流 → 折叠可见，全链路 ≤ 500ms（mock runtime）；
- 可用性测试（非自动化）：5 名未接触过 Loom 的用户，任务"做一个个人理财周报"，
  观察指标：首个命令发出耗时、是否寻找聊天框、`/` 菜单发现率。

## 5. 验收 Demo 脚本（对外主 demo，同时是 P1 的 DoD）

1. 空白 fabric，首块打字："给我一个 Q4 SaaS 营收 dashboard"——文档原地长出来；
2. 圈选某 KPI 卡片 → 命令面板 → 输入"改成滚动 12 个月趋势"→ 卡片原地改写，**镜头里没有聊天框**；
3. 选中另一区块按 `B`（branch）→ 并排出现变体；
4. 页边 `@sentiment` hand 提问 → 它在评论线程里回答 → 点"升级为命令"让它把结论写进正文；
5. hover 该段落角标 → 出处面板：哪个 hand、哪次 run、花了多少钱。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 用户流失（找不到入口） | 退路不是加回聊天框，而是修 affordance：`/` 菜单常驻提示、首次进入的 20 秒手势引导、评论线程"长得像聊天" |
| 进度叙述流缺口造成黑箱感 | 元素级状态徽章（本期）+ P2 幽灵内容连续交付；P2 未就绪前不向存量用户全量 |
| "对整份文档说话"的需求无处安放 | root 命令 + `/` 菜单全局项；遥测验证是否够用 |
| handle 快捷键与浏览器/输入法冲突 | 快捷键仅在 block 选中态生效，文本编辑态一律不劫持 |

**开放问题**：
- 多人同时圈选下命令的选区冲突（P6 前单人使用，暂记录不解决）；
- 自然语言命令是否需要"预览将执行的计划"再确认——倾向于交给 P2 的 ghost 机制统一解决。


## 7. 代码架构与开发指导

### 7.1 模块结构

```
frontend/  selection.js  palette.js  slashmenu.js  comments.js  badges.js  provenance.js
loom/router/  router.py  runs.py  stream.py
loom/handsdk/session.py（增补 emit_status）
```

前端不引入框架也能实现（现有 HTML 投影 + 事件委托）；若引入，限定在这六个模块内部。

### 7.2 关键类与函数

**selection.js — SelectionManager（前端地基，先写它）**
```js
class SelectionManager {
  current()            // -> {kind:'text'|'block'|'multi-block', anchorBlock, range?, blockIds[]}
  normalize(domSel)    // DOM Selection → 统一选区模型；跨块文本选区向上归一为 multi-block
  serialize()          // -> command patch 需要的 {target, text_range?}；依赖 data-block-id 锚点
  onChange(cb)         // palette / slashmenu 的订阅入口
}
```

**palette.js — CommandPalette**
```js
class CommandPalette {
  openFor(selection)               // 定位浮层；按 selection 与 block_type 裁剪可用 handle
  submitHandle(verb)               // -> postCommand({verb})            八个 handle 按钮/快捷键
  submitNL(text, mentions)         // -> postCommand({verb:'nl', text, mentions})
  attachMentionCompleter(input)    // '@' 触发；候选来自 GET /system/registry 缓存
}
function postCommand({target, verb, text, mentions, text_range}) 
  // 唯一出口：包装成 block.command patch → POST /fabrics/{id}/patches
```

**slashmenu.js / comments.js**
```js
class SlashMenu { itemsFor(blockCtx) }   // 静态块类型 + 注册表声明的"可插入产物"两个来源
class CommentThread {
  mount(blockId)                          // 线程 = comment_thread 子树的渲染器
  promoteToCommand(commentId)             // "升级为命令"：评论文本 → 对宿主块的 command patch
}
```

**badges.js — 运行状态（进度叙述流替代品）**
```js
class RunBadgeController {
  connect()                    // 订阅 GET /stream (SSE)
  onRunEvent(e)                // queued/running(phrase)/done/failed → 更新块徽章
  requestCancel(blockId)       // -> block.command {verb:'cancel'}
}
```

**router/router.py — 命令消费（后端核心）**
```python
class Router(Protocol):
    def route(self, cmd: Patch, tree: BlockTree) -> RouteDecision   # -> (hand_id, reason)
class RouterV0(Router):
    """写死策略：mentions 短路 → provenance 惯常 hand → 默认通用 hand。
    P5 的 BiddingRouter 将整体替换本实现——接口即契约，不要在别处旁路调用 hand。"""
class CommandConsumer:
    def start(self):
        """订阅 store.on_appended；过滤 block.command → 去重/排队 → Router.route → RunManager.start。
        cancel verb 在此拦截，不进路由。"""
```

**router/runs.py — RunManager**
```python
class RunManager:
    def start(self, decision, cmd) -> run_id   # 创建 HandSession，注入上下文包（目标块+邻域+wiki 摘要）
    def cancel(self, run_id) / def enqueue(...)  # 同一 block 串行队列；fabric 级并发上限
    def on_status(self, run_id, phrase)          # 转发到 stream.py，不落 patch
```

**router/stream.py**
```python
class TreeDiffStream:
    """SSE 端点。订阅 on_appended，把折叠后的增量（块级 diff）与 run 状态事件推给前端。
    前端只做'按 block_id 替换 DOM 节点'，不理解 patch。"""
```

### 7.3 编码顺序（与 M1.x 对应）

1. `selection.js`（含序列化单测，用 fixture DOM）→ 2. `postCommand` 通路 + `palette.js` 骨架 →
3. 后端 `CommandConsumer + RouterV0 + RunManager`（mock hand 先跑通闭环）→
4. `stream.py + badges.js`（此时才有"活"的感觉，团队内 demo 点）→
5. `slashmenu.js` + 空白 fabric 首块 → 6. `comments.js` + 升级为命令 →
7. 拔掉全局 prompt bar（feature flag）+ `provenance.js` + 遥测。

**纪律**：所有前端意图出口收敛到 `postCommand` 一个函数（遥测与灰度都挂它）；Router 是接口
不是类——P5 要换实现，任何绕过 Router 直呼 hand 的代码都是未来的债。
