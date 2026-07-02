# Loop / Dynamic Workflow / Harness / Self-Evolve 对比笔记

日期：2026-06-30

## 一句话总览

`loop/dynamic workflow` 是任务形态，`swarm` 是执行策略，`sandbox` 是试运行与隔离机制，`harness` 是本地适配与评价系统；`recursive self-evolve` 是系统级自进化，`OPD/OPSD/in-place TTT` 是模型层适配，`verbal feedback` 是连接用户、本地 harness 和模型训练的反馈接口。

更适合 Loom 的整体定位可以写成：

> 一个面向个人用户的 Local Adaptive Loop Harness：动态调用多个 domain harness 的能力，并把稳定行为逐步 offload 成低成本执行单元。

## 分层关系

```text
Personal / Local Harness
  - 用户偏好
  - 本地资源
  - 权限边界
  - 历史反馈
  - domain rubrics

Loop IR / Dynamic Workflow
  - 任务闭环结构
  - 动态步骤
  - 稳定步骤
  - 风险等级
  - offload target

Capability Fabric
  - 跨 domain 能力注册
  - 输入/输出 contract
  - 费用、延迟、信任等级
  - evaluator contract

Swarm / Tool Runtime
  - 多 hand 并行探索
  - 工具调用
  - artifact 写入 shared blackboard

Sandbox Evaluation
  - 新能力试运行
  - 新 workflow 对比
  - offload 结果验证

Promotion / Offload / Memory Update
  - 晋升为正式 loop 能力
  - 编译为规则、模板、脚本、小模型
  - 更新用户 memory / domain memory
```

## 关键概念解释

### Loop

Loop 不是普通 workflow。普通 workflow 假设步骤稳定；loop 假设任务会反复发生、每轮会产生反馈、下一轮会被改进。

Loop 更关心：

- 触发条件是什么
- 输入来自哪里
- 哪些步骤稳定，哪些步骤动态
- 哪些判断需要人
- 哪些判断可以交给 agent
- 哪些结果可以被评估
- 下一轮如何变好

### Dynamic Workflow

Dynamic workflow 是 loop 的运行时形态。它不固定写死流程，而是在每次执行时根据目标、上下文、风险、可用能力、用户偏好动态选择路径。

在 Loom 里，它应该从“固定 fanout 到几个 hand”升级为：

```text
goal -> capability query -> hand/tool selection -> artifact synthesis -> eval -> repair/offload
```

### Personal / Local Harness

当前很多 loop 太通用，只回答“一个任务怎么形成闭环”。真正有价值的是本地化 harness：

> 对这个用户、这个领域、这些资源、这些偏好、这些历史反馈，这个 loop 应该如何执行和评估？

Local harness 负责：

- 用户风格和偏好
- 风险承受和决策习惯
- 本地文件、笔记、仓位、代码库等资源
- domain-specific rubrics
- 哪些信息源可信
- 哪些动作需要确认
- 哪些经验可以沉淀为 memory

### Domain Harness

Domain harness 封装某个领域的能力、资源、评价标准。它不只是一个 agent prompt，而应该发布能力卡：

```text
capability: evaluate_market_sentiment
domain: finance.sentiment
input: ticker, time_window, sources
output: sentiment_score, drivers, contradictions
cost: medium
latency: 30s
trust_tier: B
requires:
  - news_sources
  - social_sources
eval_contract:
  - freshness
  - source diversity
  - contradiction coverage
sandbox_required_when:
  - new source added
  - high-stakes trade decision
```

### Capability Fabric

Capability Fabric 是跨 domain 能力共享层。Loop runtime 不应该知道每个 domain 的内部细节，只需要问：

- 当前步骤需要什么能力？
- 哪些 domain harness 能提供？
- 输入/输出格式是什么？
- 成本、延迟、风险是多少？
- 结果如何验收？
- 是否需要 sandbox？

这使得一个交易分析 loop 可以同时调用：

- market trend
- company fundamentals
- social sentiment
- technical signals
- portfolio risk
- counter-thesis
- report rendering
- notification / publishing

### Swarm

Swarm 适合 loop 中的高不确定环节。它不是让一堆 agent 聊天，而是让多个能力单元并行产生结构化 artifact，然后由 synthesis 层汇总、冲突识别和评分。

适合使用 swarm 的场景：

- 市场研判
- 多方案架构设计
- 高风险决策前的反方观点生成
- 跨 domain 信息收集
- 结果评估中的多维度打分

不适合全局滥用 swarm。稳定步骤应该 offload，而不是每次都 fanout。

### Shared Blackboard

Shared blackboard 是 swarm 的中间 artifact space。每个 hand 不直接互相依赖，而是写入结构化结果：

- claim
- evidence
- confidence
- source
- contradiction
- risk
- missing information

最终 synthesis 从 blackboard 读取结果，而不是从一堆自由文本里硬抽结论。

### Sandbox

Sandbox 是试运行、隔离和晋升前验证机制。

主要用途：

- 新能力试运行：新 hand、新资源、新策略先在沙箱跑，不污染长期 memory。
- offload 验证：把 agent 重复做的事编译成规则、模板、脚本或小模型后，先与 agent 版本对比。
- 多方案竞争：多个 workflow/swarm 策略同时跑，用 evaluator 决定哪一个晋升。
- 安全隔离：避免不可信能力直接写入长期 harness 或执行高风险动作。

### Offload Engine

Offload Engine 观察 agent 执行轨迹，把稳定行为逐步编译成低成本执行单元。

典型规则：

```text
Agent repeatedly does same formatting
-> compile to template

Agent repeatedly applies same classification
-> compile to rule table or small classifier

Agent repeatedly asks same clarification
-> compile to intake form/schema

Agent repeatedly searches same sources
-> compile to source connector + freshness policy

Agent repeatedly writes same output structure
-> compile to renderer

Agent repeatedly rejects same bad pattern
-> compile to validator
```

核心问题是：

> 这次 Agent 做的事情，下次能不能不让 Agent 做？

### Recursive Self-Evolve

Recursive self-evolve 是系统级自进化。它不是让模型一次回答变好，而是让系统自己提出改造、在沙箱里测试、用 evaluator 选择，再把有效改造晋升为长期能力。

它可能更新：

- prompt
- skill library
- workflow graph
- agent graph
- tool route
- evaluator
- offload rule
- domain capability

它通常不更新基础模型权重。重点是系统 scaffold、能力库和编排策略的递归改进。

相关代表：

- STOP：用 LLM-infused scaffolding program 改进自身。
- Voyager：在 Minecraft 中通过反馈改进代码技能，并积累 skill library。
- GPTSwarm：把 language agents 表示为可优化图，优化节点 prompt 和边连接。

### OPD

OPD 可以理解为 On-Policy Distillation。它是模型训练层方法。

核心做法：

- student 按自己的 policy 采样轨迹
- teacher 对这些 student 实际会走到的状态给 token-level 分布监督
- 训练 student 贴近 teacher

它解决的问题是 off-policy distillation 的分布错配：如果 student 训练时只看 teacher 轨迹，推理时一旦走到自己的错误状态，就缺少监督。

OPD 侧重：

- teacher -> student 能力转移
- 训练稳定性
- 分布匹配
- token-level supervision

适合放在离线或周期训练阶段，不是 runtime harness 的默认能力。

### OPSD

OPSD 是 On-Policy Self-Distillation。它把 OPD 中的 teacher/student 改成同一个模型的不同上下文角色。

常见设定：

- teacher role：看到 privileged context，比如 verified reasoning trace、答案、成功轨迹总结、persona guidance
- student role：只看到普通问题
- student 采样自己的轨迹
- teacher 在同一轨迹上提供分布监督
- student 学会在没有 privileged context 时表现得更好

OPSD 侧重：

- 内化训练期额外上下文
- 减少外部 teacher 依赖
- 降低部分训练成本
- 把 skill / reasoning trace 压进模型行为

在 Loom 语境中，OPSD 更像是把长期 harness 中稳定有效的 domain guidance 周期性蒸馏进模型，而不是每次 runtime 都加载大量上下文。

### Verbal Feedback

Verbal feedback 是自然语言反馈。它不是只给 reward 分数，而是告诉系统：

- 哪里错
- 为什么错
- 哪个假设不成立
- 哪个信息源不可信
- 下次应该如何改
- 用户实际偏好是什么

它可以有两种落点：

1. 不更新权重：写入 episodic memory / harness memory，例如 Reflexion。
2. 更新权重：作为 RL 或蒸馏信号，让模型内化反馈，例如 DITTO 一类方法。

在个人本地 harness 中，verbal feedback 很关键，因为用户最自然提供的往往不是标量 reward，而是：

> 这个判断太激进；下次要多看反方逻辑。

或：

> 这个 KOL 不可信，别把它当作强信号。

### In-Place TTT

In-place TTT 是 In-Place Test-Time Training，属于推理期模型参数适配。

核心思想：

- 推理时更新模型的一小部分 fast weights
- 论文中选择 MLP block 的 final projection matrix 作为可适配参数
- 目标对齐到自回归语言模型的 next-token prediction
- 支持在当前上下文流中即时适应

它侧重：

- 当前任务流的即时模型适配
- 长上下文和连续信息流
- 参数层的 test-time adaptation

它比 harness/memory 更底层，也更敏感。对 Loom 这样的本地 agent 系统来说，它可以是高级能力，但不应该是 MVP 的核心依赖。

## 总对比表

| 概念 | 做什么 | 主要侧重 | 更新对象 | 适合放在架构哪里 | 风险 / 注意点 |
|---|---|---|---|---|---|
| Loop | 把重复任务变成可运行、可反馈、可改进的闭环 | 任务结构 | loop state | 顶层工作单元 | 太通用会缺少个人价值 |
| Dynamic workflow | 每轮根据上下文动态选择路径 | 执行编排 | workflow route | Loop Runtime | 需要可解释 trace，否则难复盘 |
| Loop IR | 结构化表示 loop，标注动态性、风险、offload 目标 | 可分析、可编译 | 中间表示 | Loop Compiler 核心 | IR 过重会拖慢 MVP |
| Personal / Local Harness | 适配个人偏好、资源、历史反馈、权限 | 本地化 | 用户画像、rubric、memory | loop 入口层 | 隐私、权限和长期记忆污染 |
| Domain Harness | 封装某领域能力、资源、评价标准 | 专业能力 | domain capability / rubric | capability 提供方 | domain contract 不清会导致跨域混乱 |
| Capability Fabric | 让多个 domain harness 共享即时能力 | 跨域调度 | capability registry | loop 与 domain 之间 | 需要标准化输入输出和 evaluator |
| Swarm | 多个 hand/agent 并行探索同一问题不同面向 | 高不确定性探索 | 多 agent artifacts | dynamic step 的执行策略 | 成本高、噪音高，不适合稳定步骤 |
| Shared Blackboard | 聚合多 agent 产物、证据、冲突和置信度 | 协作记忆 | artifact space | swarm 中间层 | 需要结构化 schema |
| Sandbox | 隔离试跑新策略、新能力、新 offload | 验证与安全 | temporary run state | promotion 前置层 | 沙箱结果需要可比较 evaluator |
| Offload Engine | 把稳定行为编译成规则、模板、脚本、小模型 | 降低 agent 成本 | runtime / tool / template | loop 优化层 | 过早 offload 会固化错误模式 |
| Recursive self-evolve | 让系统改进自己的 loop、agent graph、skill、prompt | 系统级进化 | architecture / skill / workflow | meta-loop | 必须有 sandbox、eval、rollback |
| OPD | teacher 监督 student 自己采样到的轨迹 | 稳定蒸馏 | model weights | 离线 / 周期训练 | 需要 teacher，训练成本较高 |
| OPSD | teacher role 用 privileged context 指导 student role | 内化隐性指导 | model weights | domain skill 内化 | 要防止答案泄漏和过拟合 |
| Verbal feedback | 用自然语言反馈解释错误和改进方向 | 人类可读反馈 | memory 或 weights | harness eval / 用户反馈 | 反馈可能主观、矛盾、噪声大 |
| In-place TTT | 推理时即时更新局部 fast weights | 当前任务快速适应 | model fast weights | 高级 runtime 能力 | 安全、可控性和成本边界更敏感 |

## 与 Loom 的组合方式

一个更完整的 Loom 版本可以这样运作：

```text
1. 用户提出任务
   -> Personal Harness 读取用户偏好、权限、历史反馈

2. Loop Miner / Loop IR
   -> 识别这是一次性任务、重复 loop，还是已有 loop 的新一轮

3. Dynamic Workflow Planner
   -> 判断哪些步骤稳定、哪些步骤动态、哪些需要 swarm

4. Capability Fabric
   -> 查询 finance、research、coding、writing、portfolio 等 domain harness

5. Swarm / Tool Runtime
   -> 并行执行高不确定步骤，结果写入 Shared Blackboard

6. Synthesis + Domain Eval + Personal Eval
   -> 评估是否满足目标、领域标准和用户偏好

7. Sandbox / Repair
   -> 对新能力、新 offload、新 workflow 先隔离验证

8. Promotion / Offload
   -> 稳定行为沉淀为模板、规则、脚本、小模型或 persistent capability

9. Verbal Feedback
   -> 用户用自然语言纠偏，写回 harness memory，必要时进入周期训练数据

10. Recursive Self-Evolve
   -> 系统周期性提出 loop / skill / capability / evaluator 改造，并通过 sandbox 晋升
```

## 最重要的区分

```text
harness / loop / swarm / sandbox / offload
  = 系统层自适应

OPD / OPSD / in-place TTT
  = 模型层适应

verbal feedback
  = 连接用户、本地 harness、系统进化和模型训练的反馈接口
```

## 参考

- Self-Taught Optimizer (STOP): Recursively Self-Improving Code Generation: https://arxiv.org/abs/2310.02304
- Voyager: An Open-Ended Embodied Agent with Large Language Models: https://arxiv.org/abs/2305.16291
- Language Agents as Optimizable Graphs / GPTSwarm: https://arxiv.org/abs/2402.16823
- Reflexion: Language Agents with Verbal Reinforcement Learning: https://arxiv.org/abs/2303.11366
- Self-Distilled Reasoner: On-Policy Self-Distillation for Large Language Models: https://arxiv.org/abs/2601.18734
- A Brief Overview: On-Policy Self-Distillation In Large Language Models: https://arxiv.org/abs/2605.18141
- In-Place Test-Time Training: https://arxiv.org/abs/2604.06169
- Reinforcing Human Behavior Simulation via Verbal Feedback / DITTO: https://arxiv.org/abs/2605.20506
