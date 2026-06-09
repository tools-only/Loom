# LPH Proposal v3 — Brain-Hand 分层作为两级推理架构

**作者:** Loom Core research thread
**日期:** 2026-06-08
**版本:** Proposal v3（基于 v2 的方向性收口 + Loom 实际架构锚定）
**形态:** *研究提案*——架构原语 → 痛点结构性诊断 → Loom 作为存在性证明 → 与现有方法对比

> **v2 → v3 核心变化：**
> v2 把贡献押在 HFNT 形式化必要性定理 + F5/F6 两个形式化失败模式上。
> v3 收口为：**Brain-Hand 分层的结构性新意，不是"两个文件夹"，而是引入两个现有 in-context harness 无法拥有的架构原语 —— 外置化 Brain state + Brain 侧 meta-inference 循环**。
> 这是 Loom 现有架构（Brain 跑在 agent 主进程上承担 harness offload，Hand agents 完成具体内容交付）的形式化陈述。
> **删除：** F5 跨域 K+1 泛化、F6 lock preservation、HFNT 类型论证明、O(√(d·log K/K)) PAC-VC 界、Theorem 1/2 的形式证明、M9+ 对抗性实验。
> **保留：** Brain × Hand × Locked-belief 三分概念脚手架；Pack / Lift / Evolve 词汇；M1–M10 对比基准。
> **新增：** 五个 Brain-Hand 特异痛点（2, 3, 4, 5, 7）；Loom 代码层级锚定；"两级推理架构"作为中心论点。

---

## TL;DR

**论点（待 ICLR 接收）：**

> Harness 组件的**可分离性**（Brain 跨 base model 迁移、Hand 跨用户分发）依赖于两个结构性条件：**(a) 持久外置化的 harness 状态**，**(b) Brain 侧的 meta-inference 循环**。所有 in-context harness 设计（CLAUDE.md、Skills、MemGPT、RAG、长上下文 agentic model 等）都缺少 (b)，因此在结构上无法把"人格维护"与"技能编排"解耦——两者都被压扁到 base LLM 的单次推理里。

**架构新意不是 prompt 工程，是推理拓扑。**

---

## 1. 问题陈述（Layer 1）

### 1.1 什么是 Harness（不是 Personalization）

Harness = wrap 一个 base LLM 的 scaffolding，使其在多次会话、多个领域、多个 base model 切换下具备稳定的行为契约。

**关键区分——架构 vs 应用：**

- *Personalization*（个性化）是基于 harness 架构的一个具体适用点
- 本提案关注架构本身：**Brain 与 Hand 作为独立可剥离的服务，能否被任意重新组合并迁移到不同用户**

可迁移的 harness 服务是架构；personalization 只是该架构上的一个实例化。

### 1.2 Brain-Hand 分层能结构性解决的六个痛点

| # | 痛点 | 现状（in-context harness） |
|---|------|---------------------------|
| **P1** | 业务级**跨 Hand 整合推理**无法委派给单 Hand —— 用户的 alpha 不在 Hand 的事实抓取里，而在"用什么策略把多个事实关联起来" | 把整合也塞进 base LLM 同一次推理：用户策略 + 多 Hand 数据 + 任务请求 一锅烩；策略漂移、整合质量不可控、能力无法独立演化 |
| **P2** | 切底层模型（base LLM）需要重做 harness | 人格行为依赖特定模型对特定 .md 文本的解读；换模型行为漂移 |
| **P3** | 增加能力会污染人格 | 新加的 skill .md 与人格 .md 在同一次推理里被 base LLM 同时消化；语义干扰是结构性的 |
| **P4** | 反馈归因不明 | 用户反馈"刚才那段不好"只能 append 到某个 blob；没有一个分类器判断这是关于"我的说话风格"还是"这次产出流程" |
| **P5** | Hand 难以打包分发 | 单存储 harness 里 skill 与用户专属内容缠绕，无法剥离一个 Hand 给另一个用户使用 |
| **P6** | **能力蒸馏路径缺失** —— 用户在交互中体现出的策略 / 偏好 / KOL 蒸馏内容，无法被持续吸收到 main agent 自身的推理能力里 | 用户教 agent 的内容散落在历次 prompt 或反馈 append 里，没有结构化的"main agent 能力增长"路径 |
| **P7** | 演化轨迹混叠 | 人格漂移、技能漂移、流程漂移都压在同一个 .md 文件里复合演化 |

**这六个痛点不是质量问题，是结构问题。** §1.3 给出结构性诊断。

> **P1 + P6 是 v3 相对 v2 新增加的核心痛点。** 它们指向 main agent 作为**业务级推理器**的角色——不是 router，不是 dispatcher，而是承载用户 alpha 的 reasoner。没有这个角色，main agent 在业务面前是"无所事事"的，分层架构就退化为"两个文件夹"。

### 1.3 为什么这些失败是结构性的

In-context harness（CLAUDE.md / Skills / MemGPT 等）的本质是 **smarter context loading**：根据当前任务选择正确的 .md 拼接进 base LLM 的 context window，然后由 base LLM 一次推理出结果。

这个范式有一个**不可消除的结构性限制**：

> **storage 之上没有 LLM 推理层。**
> harness 状态在文件系统里，但任何使用、分类、路由、归因都必须**塞进 base LLM 的同一次推理里**完成——这就把人格维护、技能调用、反馈分类、领域识别全部压扁到了一次推理。

这就是为什么"渐进式披露 .md 文件"无法替代 Brain-Hand 分层：渐进式披露只控制**哪些 .md 出现在 base LLM 的 context 里**，它没有引入第二个推理层。

---

## 2. 理想架构（Layer 2）—— 三个原语

### 2.1 原语 A：外置化 Brain state

**Brain state lives outside any single LLM session.**

- Brain 侧的 harness 状态（rubric、preference、locked-belief、routing-rule、**用户策略 / 蒸馏 skill** 等）持久化在**本地存储**里
- 由长期运行的 **Brain agent 主进程** 维护、查询、更新
- **不通过"塞进 context window"被使用**——而是由 Brain 主进程主动地、显式地从持久层中读取并写入

**对比 in-context harness：** CLAUDE.md 表面上也是"在磁盘上"，但它实际上每次 session 都被全文拼接进 LLM context——它的"状态"等价于 "上次 LLM 是怎么解读这段文本的"。换 base LLM 后，同样的文本会被新模型以不同方式解读——状态实际上**绑定在 LLM 的解读能力上**，不是真正外置化。

### 2.2 原语 B：Brain 侧的 agentic 推理层

**Brain 自带一层独立的 LLM 推理，operating on the externalized state.**

Brain agent 主进程不是被动的存储——它会主动发起自己的 LLM 调用。这一层推理服务**两类用途**：

#### B-internal：harness 内部操作（对架构稳定性必要）

- **反馈分类**：用户反馈进来，Brain 自己跑一次推理判断"这是关于人格的，还是关于流程的"，然后决定 update 写入哪里
- **Hand 派发决策**：根据任务上下文 + Brain.state 决定派发哪些 Hand、传递什么上下文
- **Audit / 维护**：定期对 Brain.state 跑 meta-policy 推理（哪些条目过时、哪些被升格为元规律）

#### B-business：业务级整合推理（对用户价值必要）

这是 v2 完全缺失、v3 必须补上的核心：

- **跨 Hand 结果整合**：多个 Hand 各自交付事实快照（事件、数据、新闻、情绪指标），Brain 主进程跑一次独立推理把它们关联成业务结论
- **应用用户策略**：把 Brain.state 中持久化的**用户策略 / KOL 蒸馏 skill**（例如"DCF + 8.5% WACC for utility stocks"、"VIX > 25 时拒绝增加 beta exposure"）作为推理 prompt 的核心，让多 Hand 输出按用户的方法论被解读
- **生成 reasoning 输出**：包含解读、决策、reversal condition 的最终业务回答

**关键：B-business 不是路由，是真正的业务级 agentic 工作。** 它产生的是用户最看重的 reasoning 输出，本质上 = 单个 Hand 不能独立完成的部分。

**对比 in-context harness：** 单层 harness 没有这个独立推理层——所有"整合"必须在 base LLM 同一次推理里完成，用户策略、多 Hand 数据、任务请求被一锅烩。结果：策略难以持久化、整合质量不可控、能力无法独立演化。

### 2.3 原语 C：能力蒸馏路径（用户 → Brain）

**Brain 必须能从用户交互中持续吸收新的 reasoning skill 到 Brain.state，且这些 skill 直接增强 B-business。**

具体机制：

| 蒸馏入口 | 触发 | 沉淀对象 |
|---------|-----|---------|
| **显式策略注入** | 用户说"以后这类问题，先看 X 再看 Y，权重按 Z" | Brain.state.strategy/* |
| **反馈触发的策略更新** | 用户对 Brain 输出说"这次低估了财报 guide 的重要性" | Brain meta-inference 推理 → 修订 strategy 中的权重 / 因子 |
| **KOL / 文本蒸馏** | 用户上传 KOL 文章、研报、自己的笔记 | Brain 跑一次蒸馏推理 → 抽取 reasoning pattern → 写入 Brain.state.distilled_skill |
| **隐式纠正** | 用户多次修改 Brain 的整合结论 | 周期性 audit → 识别模式 → 升格为新 strategy |

**蒸馏的关键点：** 沉淀目标是 **Brain.state**（用户专属）而**不是** Hand（跨用户的 product-shipped 服务）。这就保证了：
- 用户的 alpha 留在用户自己的 Brain 里，不会被打包随 Hand 分发
- Hand 仍然可以干净地跨用户分发（Hand 是抓数据 / 跑工具，用户策略不污染 Hand）
- 同一份 Hand 配合不同用户的 Brain，会产生**结构性不同的整合结论**——这正是 personalization 的真正出处

**对比 in-context harness：** 蒸馏在单层架构里只能表现为"把蒸馏内容 append 到 .md 文件"。但这没有"蒸馏推理"步骤——你只是堆积原文，base LLM 在下次任务里去自己重新解读。蒸馏成果不可累积、不可结构化、不可与 strategy 的其他部分一起被 B-business 引用。

### 2.4 三个原语之间的关系

```
        ┌─────────────────────────────────────────┐
        │  Brain agent 主进程（长期运行）          │
        │                                          │
        │   ┌─────────┐      ┌──────────────┐    │
        │   │ B 推理  │ ──→  │ Brain.state  │    │
        │   │  层     │ ←──  │（持久化）    │    │
        │   └────┬────┘      └──────┬───────┘    │
        │        │                  │             │
        │        │ B-internal       │ 原语 A      │
        │        │ B-business       │ 外置化      │
        │        │ C-distill        │             │
        └────────┼──────────────────┼─────────────┘
                 │                  │
                 │ envelope         │ 不进入任何
                 ▼                  │ LLM session
        ┌──────────────┐            │ context
        │ Hand agents  │            │
        │（独立服务）  │            ▼
        └──────────────┘    (本地磁盘)
```

- 原语 A 让 state 不被 LLM session 持有
- 原语 B 是"独立 LLM 推理层"——既维护架构（B-internal）又产生业务价值（B-business）
- 原语 C 是 B 的一个长期模式：用户交互 → state 持续增长

### 2.5 Loom 作为存在性证明

Loom 现有架构正是 (A) + (B) + (C) 的具体实现：

| Loom 组件 | 对应原语 |
|----------|---------|
| Brain agent 主进程（FastAPI 服务，port 3001） | Brain 主进程：长期运行，处理交互工作空间 |
| Brain 侧的持久存储（Brain.state、Brain.meta、用户策略 / 蒸馏 skill）落盘到本地 | 原语 A：外置化状态 |
| Brain 主进程内的独立 LLM 调用，做 dispatch、feedback routing、跨 Hand 整合 | 原语 B：内含 B-internal + B-business 两类用途 |
| 用户交互工作空间（loom-human-ag 分支的 canvas 等）：用户在交互中持续输入策略、纠正、上传文本 | 原语 C 的蒸馏入口 |
| `loom/hands/base.py` 的 `BaseHand` 模式 | Hand 作为接受 envelope 的独立服务 |
| `loom_core/agent_adapters/adapter.py` 的 transport × protocol 矩阵 | Hand dispatch 的 typed 接口 |

#### 业务案例：市场研判中的 Brain B-business 推理

用户问："AAPL 还能买吗？"——Loom 实际工作流程：

1. **Brain 主进程 B-internal 推理**：决定派发哪些 Hand
   - `macro-hand`：抓取美联储利率路径、CPI、9 月议息预期
   - `earnings-hand`：拉取 AAPL Q3 财报 + management guidance
   - `sentiment-hand`：VIX、AAPL 持仓变化、Fear & Greed
   - `news-hand`：AAPL 近 30 天的重大新闻
2. **Hand agents 并行执行**：每个 Hand 只返回**自己 domain 的事实快照**，不做任何整合
3. **Brain 主进程 B-business 推理**：
   - 加载 Brain.state.strategy（用户的投研策略：例如"科技股按 forward P/E + 增长率组合估值；macro tightening 时拒绝增 beta"）
   - 加载 Brain.state.distilled_skill（从用户上传 KOL 蒸馏出的"看财报 guide 的方法论"）
   - 把 4 个 Hand 的快照 + 上述 strategy 一起塞进推理 prompt
   - **输出业务结论**：包含估值结论 + reversal condition + 关键风险点
4. **用户反馈**："这次你低估了 guide 的重要性"
5. **Brain B-internal + 原语 C**：触发蒸馏推理 → 修订 strategy.weighting.earnings_guide → 沉淀到 Brain.state

**这一过程展示：**
- Hand 是"事实抓取层"——可跨用户分发
- Brain 是"业务整合层"——承载用户 alpha 和持续学习
- 整合本身是 Brain 的独立推理调用——**不是把所有信息塞给一个大 LLM 一次解决**

**这就是"两级推理架构"的业务化具体形态。**

---

## 3. Gap 分析（Layer 3）—— 为什么"两个文件夹"不算分层

### 3.1 通用失败模式：缺少原语 B

所有 in-context harness 方法在原语层面是这样的：

```
[文件系统：persona.md, skills/*.md, memory.md]
         |
         | (smart context loading: 选择哪些 .md 进 context)
         |
         v
[base LLM 单次推理：人格 + skill + 用户输入 + base capabilities 同时消化]
```

它们的差异只在"smart context loading 的策略"层面：

- M1 Reflexion：基于 reflect 文本选择
- M5 MemGPT：基于 paging 算法选择
- M6 RAG：基于 embedding 相似度选择
- M7 Skills/Superpowers：基于 keyword/trigger 选择
- M9 CLAUDE.md：全部固定加载

**没有任何一个方法在 storage 与 base LLM 之间引入第二个 LLM 推理层。**

### 3.2 "两个文件夹"的反例

假设有人把 CLAUDE.md 拆成 `brain.md` 和 `hand.md`，并用渐进式披露策略——这**仍然不是 Brain-Hand 分层**，原因如下：

| 测试 | 两个文件夹方案 | 真正的 Brain-Hand 分层 |
|------|--------------|----------------------|
| 切 base model 后人格是否稳定 | ❌（解读改变）| ✅（state 外置化）|
| 加新 skill 是否会让旧人格的表现漂移 | ❌（同一次推理消化）| ✅（Brain.state 与 Hand 注册解耦）|
| 用户反馈进来时是否有归因决策 | ❌（无第二推理层）| ✅（Brain meta-inference 分类）|
| Hand 能否独立打包分发 | ❌（与用户专属内容缠绕）| ✅（envelope I/O 边界清晰）|
| 人格漂移与技能漂移是否独立 | ❌（同源 .md）| ✅（不同存储 + 不同推理操作）|

**关键诊断：渐进式披露解决的是"哪些 .md 进入 base LLM context"——它没有引入 storage 之上的推理组件，所以无法做归因、无法做隔离、无法做独立演化。**

### 3.3 重新审视 M1–M10

| 方法 | A 外置化 | B-internal | **B-business** | **C 蒸馏** | P1 | P2 | P3 | P4 | P5 | P6 | P7 |
|------|---------|-----------|---------------|-----------|-----|-----|-----|-----|-----|-----|-----|
| M1 Reflexion | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| M2 Voyager | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ⚠️ | ⚠️ | ❌ |
| M3 Kimi-K2 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| M4 Hermes | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| M5 MemGPT | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| M6 RAG | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ |
| M7 Skills | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ |
| M8 Agentic RL | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| M9 CLAUDE.md | ⚠️ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ❌ |
| M10 Constitutional AI | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **LPH (Loom)** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** | **✅** |

**核心 Gap：**
- 没有任何已有方法同时满足原语 A + B + C
- 特别是 **B-business（业务级整合推理层）** 和 **C（持续蒸馏到 main agent 的路径）** 在所有方法里都缺失
- 这不是质量差距，是架构层面的结构性缺失

---

## 4. 策略（Layer 4）—— LPH 作为最小可工作架构

### 4.1 LPH 的最小架构契约

一个满足 Brain-Hand 分层定义的 harness 必须包含：

1. **Brain 主进程**：长期运行的 agent process，提供与用户的交互界面
2. **Brain.state 持久层**：本地存储，可被 Brain 主进程读写，**不被任何 LLM session 持有**
3. **Brain meta-inference**：Brain 主进程对 Brain.state 进行 LLM 推理的能力（用于反馈分类、Hand dispatch、audit）
4. **Hand agents**：接受 typed envelope 的独立服务，完成具体内容交付
5. **Pack / Lift / Evolve 接口**：Brain 与 Hand 间的纯函数接口（envelope 流入 + signal 流出 + state 更新）

LPH 是该契约的最小存在性实现——Loom 是已经在跑的具体实例。

### 4.2 五个痛点的结构性解决路径

| 痛点 | 结构性解 |
|------|---------|
| **P2 切模型** | Brain.state 在持久层；换 Brain 主进程的底层 LLM 时，state 完全保留；人格行为不依赖某个特定模型的文本解读 |
| **P3 能力扩展** | 新 Hand = 在 Hand registry 注册新服务；Brain.state 完全不动；新 Hand 的 procedure 永远不会出现在 Brain meta-inference 的 prompt 里 |
| **P4 反馈归因** | 反馈到达 Brain 主进程后触发一次独立 meta-inference 推理，输出 `{target: brain_state | hand_evolved, classification: persona|procedure|...}`；写入由分类结果决定 |
| **P5 Hand 打包** | Hand 接收的 envelope 与产出的 signal 是已定义的接口；可以打包 `loom/hands/finance/` 这样的目录给另一个用户的 Brain 调用 |
| **P7 独立演化** | Brain.state 由 Brain meta-inference 更新；Hand.evolved 由 Hand 自身在任务中积累；两者落盘到不同位置，无 cross-write |

### 4.3 验证方案

**实验 E1 — Base model 切换稳定性（P2）**
- 在 Loom Brain 主进程上分别使用 Claude Sonnet 4.6 / GPT-5 / Gemini Pro 2.5 作为底层 LLM
- 给定相同的 Brain.state，让 Brain 处理相同的一组用户请求
- 度量：Hand dispatch 决策一致率、反馈分类一致率
- **基线（in-context harness）：** 同样的 CLAUDE.md，三个模型上的行为漂移率
- **预期：** LPH 显著降低 cross-model 行为漂移；in-context 高漂移

**实验 E2 — 能力扩展不污染人格（P3）**
- 给 Brain 注册新 Hand（如"金融分析 Hand"），不修改 Brain.state
- 度量：Brain 在与 Hand 无关任务上的输出表征（embedding 距离 vs Hand 加入前）
- **基线：** 把同样内容加进 CLAUDE.md
- **预期：** LPH 表征无显著漂移；in-context 出现可测漂移

**实验 E3 — 反馈归因正确率（P4）**
- 构造 100 条混合反馈（50 条关于人格、50 条关于流程）
- 度量：Brain meta-inference 分类的 precision / recall
- **基线：** 把反馈 append 到 CLAUDE.md 后由 base LLM 在下一次任务中"自然吸收"——通过下游表现间接评估
- **预期：** LPH 显式分类可达 >85% accuracy，in-context 无法度量

**实验 E4 — Hand 跨用户迁移可行性（P5）**
- 用户 A 用 Loom 训练出 `finance/` Hand
- 把 `finance/` 打包给用户 B 的 Brain
- 度量：用户 B 在该 domain 上的冷启动表现 vs 自己从零开始
- **基线：** 把用户 A 的 CLAUDE.md 给用户 B 用（隐私问题 + 用户专属内容 + skill 混杂）
- **预期：** LPH Hand 可干净迁移；in-context 方案出现隐私泄露或人格混淆

---

## 5. 与现有方法的诚实对比

### 5.1 LPH 的劣势（必须诚实承认）

- **F1（trajectory 内自纠错）：** LPH 不专门提升单 trajectory 内的 reflexion 能力。M1 Reflexion 在这一维上更强。LPH 设计目标不覆盖这里。
- **F4（context capacity）：** LPH 的 Brain.state 是结构化的图，不解决 1M+ token 长上下文问题。M3 / M5 在这一维上更强。
- **F8（intrinsic capability）：** LPH 是 wrapper，不能让 base LLM 本身的 tool-use 或 planning 能力变强。M4 / M8 是 model-level 工作。

LPH 的设计目标是 **架构可分离性**，不是"做一个全能 agent"。

### 5.2 与"渐进式 .md 披露"的特别对比

很多 in-context harness 实现使用渐进式披露策略（claude code skills、cursor rules 等）：根据上下文动态选择把哪些 .md 加进 context。

**这与 Brain-Hand 分层的区别：**

| 渐进式 .md 披露 | Brain-Hand 分层 |
|----------------|----------------|
| storage 之上无推理层 | Brain 主进程是独立推理层 |
| 触发逻辑 = keyword / embedding | 触发逻辑 = Brain meta-inference 推理 |
| 状态更新 = 文件 append | 状态更新 = meta-inference 输出 → 持久层 |
| 反馈处理 = 把反馈塞进下次 context | 反馈处理 = meta-inference 分类 → 路由到对应 store |
| 能否被"上面再加一层 LLM"补救 | — | 这就是分层做的事 |

**结论：渐进式 .md 披露与 Brain-Hand 分层不是连续光谱上两个点——它们之间有结构性鸿沟，即"storage 之上是否有 LLM 推理层"。**

---

## 6. ICLR-Level 论点小结

**主张：** Harness 组件可分离性的充分条件是**外置化持久状态 + Brain 侧 meta-inference 循环**。

**为什么重要：**
- 它把 harness 设计从 "prompt 工程问题" 推到 "推理拓扑问题"——这是定性变化
- 它给出可证伪的实验路径（E1–E4），不是哲学论证
- 它对应到 Loom 这样的已经跑起来的具体架构，不是 vaporware

**与文献的关系：**
- 类比"系统调用 vs 应用程序代码"的分离：harness 与任务执行属于不同抽象层
- 类比"控制平面 vs 数据平面"：Brain 是控制平面（meta-inference），Hand 是数据平面（任务执行）
- 与 LLM-as-OS 工作（如 MemGPT）的差别：MemGPT 把 LLM 当 process，但没有独立的"OS-level LLM"做 meta 决策——本质上仍是单层

**这是 ICLR 级别的论点，因为它定义了一个新的设计 axis（"storage 之上是否有 LLM 推理层"），并且证明现有所有方法都在 axis 同侧。**

---

## 7. 局限性与下一步

### 7.1 LPH 不解决什么

- 不解决 base LLM 本身能力不足（intrinsic capability）
- 不解决长上下文窗口管理（capacity）
- 不解决单 trajectory 内 reflexion 质量（self-correction）

### 7.2 v3 相比 v2 删除的内容

- F5（跨域 K+1 泛化）—— 太远，先不考虑
- F6（lock preservation）—— 工程细节，不在架构主张内
- HFNT 形式化必要性定理 —— 类型论形式化超出范围
- Theorem 1 / 2 形式证明 —— 一并删除
- M9+ 对抗实验 —— 与 F5 绑定

### 7.3 v3 保留的概念脚手架

- Brain × Hand × Locked-belief 三分作为概念锚
- Pack / Lift / Evolve 作为接口词汇
- M1–M10 作为对比基准

### 7.4 投稿目标

- **主目标：** ICLR 2027 main track（系统 + ML 交叉）
- **次目标：** COLM 2026
- **副产品：** 一个 ablation study 论文（在 LPH 框架下分别去掉 A 或 B，度量退化程度）可走 EMNLP 或 NeurIPS workshop

---

## 8. 参考与代码锚定

| 概念 | Loom 代码位置 |
|------|--------------|
| Brain 主进程 | `mcp/server.cjs` + Brain FastAPI (port 3001) |
| Brain.state 持久层 | `output/`、`logs/` 下的 session 持久化 |
| Hand 接口 | `loom/hands/base.py`（`BaseHand` 类） |
| Hand dispatch | `loom_core/agent_adapters/adapter.py`（transport × protocol matrix） |
| Pack envelope | `loom/` 任务派发的 JSON envelope schema |
| 对比文献 | M1–M10 见 §3.3 表格；详见 v2 附录 |

---

*v3 由 v2 收口而来，方向性变化已在文首记录。主要架构论点：Brain-Hand 分层是"两级推理架构"，不是"两个文件夹"。Loom 是已运行的存在性证明。*
