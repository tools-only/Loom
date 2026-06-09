# LPH Proposal v2 — Harness Factoring Necessity Theorem 与 Brain-Hand 架构

**作者:** Loom Core research thread
**日期:** 2026-06-08
**版本:** Proposal v2（基于 v1 + debate-20260608-brhd 辩论结论的重大修订）
**形态:** *研究提案*——问题域形式化 → 必要性定理 → LPH 构造 → 实验设计 → 诚实优劣分析

> **v1 → v2 核心变化：**
> v1 的定位是"LPH 是一种好设计"（充分性）。
> v2 的核心主张是"**有类型分解是结构转移不变性的必要条件**"（必要性）——
> 即 Harness Factoring Necessity Theorem（HFNT，定理 0）。
> 这把贡献从"提出一个方案"升级为"证明这是唯一可行的方案类"。

---

## 1. 问题陈述

### 1.1 什么是 Harness（不是 Personalization）

本提案的核心对象是 **LLM Harness**：wrap 一个 base LLM 的 scaffolding，使其在以下三个维度上具备持久不变性：

1. **跨 domain 元规律**：用户在多个 domain 上累积的"偏好怎么更新、locked belief 怎么解冲突、新 domain 怎么 bootstrap"
2. **Lock 不变性**：用户显式 lock 的声明（立场、隐私边界、必要约束）在任意 online update 下不被静默修改
3. **跨 model / 跨 vendor 不变量**：更换底座 LLM 时，harness 的行为契约保持稳定

**关键区分——架构 vs 应用：**
- *Personalization*（个性化）是基于 harness 架构的 **一个具体适用点**
- 本提案关注的是架构本身：Brain 和 Hand 作为独立可剥离的类型化服务，能否被任意重新组合并迁移到不同用户

可迁移的 harness 服务是架构；personalization 只是该架构上的实例化。

### 1.2 当前 Harness 的两类形式化失败

**F-comp（跨域组合泛化失败）：**
用户在 K 个 domain 上累积的元规律被缠绕在 domain-specific prompt 中。K+1 个 domain 到来时必须从零重学，而不能从已有元规律中冷启动。

**F-lock（在线更新下的 lock 保存失败）：**
用户 lock 的声明（"AAPL bullish until Q3"、"必须引用 reversal_condition"）仅存于 prompt 字符串，无类型保护。Vendor system-prompt 升级、RLHF 漂移、长 context 截断均可静默改写 lock 内容。

这两类失败是 **类型安全问题**，不是质量问题。增量改进现有方法无法解决——原因见 §4（HFNT）。

### 1.3 形式化标准：Brain.meta vs Hand.manifest vs Locked-belief

这是 v2 相比 v1 的关键新增。

**定义（领域不变性准则）：**

> `h ∈ Brain.meta`（元策略）**当且仅当** `h(signal, state)` 对所有活跃 Hand 产生相同的策略结果——即 h 是 *用户专属、领域无关* 的。

> `h ∈ Hand.manifest`（领域程序）**当且仅当** `h(task, context)` 对所有 Brain 实例产生相同的程序输出——即 h 是 *领域专属、用户无关* 的。

> `h ∈ Brain.state.Locked-belief`（锁定信念）**当且仅当** h 同时依赖特定用户 **且** 特定领域——即跨积类型，不可化约到前两者。

**为什么三分类是必要的：**
把 Brain.meta 和 Hand.manifest 混入同一个 blob（如 CLAUDE.md），会使"从 blob 中自动提取领域无关成分"等价于一般信号函数的 domain-agnosticity 判定，后者对一般程序不可判定（undecidable）。类型化分解将这个问题转移到 **编写时**（Hand 作者声明 DomainID），而非 **推理时**（harness 从 blob 中动态识别）。

---

## 2. 八个 Focus Dimensions

把"harness 想解决什么"分解为 8 个 **正交** focus dimension。任何方法可以在某一维满分而在另一维零分。

| ID | Focus Dimension | 含义 | 理想行为 |
|----|----|----|-----|
| **F1** | Within-trajectory self-correction | 单次 agent run 内的迭代纠错 | 错一步 → reflect → 下一步纠正 |
| **F2** | Cross-session memory accumulation | 跨会话的持久记忆 | 上周说的偏好，今天还记得 |
| **F3** | Skill / procedure organization | 可复用命名能力的组织 | 各 domain 有独立可激活的"做法"模板 |
| **F4** | Context capacity management | 超出 context window 的状态管理 | 1M token 信息可被 paging / retrieve |
| **F5** | Cross-domain compositionality | 跨 domain 元规律的可组合泛化 | K 域的元规律自动迁到 K+1 域 |
| **F6** | User-lock preservation | 用户 lock 的不可变性 | 任意 online update 下 lock 不偏 |
| **F7** | Per-user privacy / state isolation | 个人状态本地、不池化 | 数据不进训练集，不跨用户共享 |
| **F8** | Intrinsic model capability | 模型本身的 tool-use / 规划能力 | tool-call 准，多步规划稳 |

**关键观察：** F5 和 F6 是 **结构上正交** 的维度——F5 要求元策略在跨域更新中稳定迁移，F6 要求 lock 在任意更新下不被改写。v2 新增贡献：**证明同时满足 F5+F6 要求 Brain×Hand 类型化分解（HFNT，定理 0）**。

---

## 3. 现有 10 类 Harness 方法调研

### M1 — Self-Critique / Reflexion / SELF-REFINE
单轨迹内自评→重做→收敛。
- **强项：** F1
- **弱项：** F2（无跨会话持久化）、F3、F5、F6
- **限制：** 把记忆等同于"上一次反思文本"，无结构

### M2 — Voyager / Skill Library
生成课程任务→完成后把代码入库→后续任务可调用。
- **强项：** F3（skill 库设计典范）、部分 F2
- **弱项：** F5（单域）、F6（无类型保护）、无 Brain 层
- **与 HFNT 的关系：** M2 是目前最接近 Hand.manifest.seed 的设计，但**完全没有 Brain 层**，也无 Pack routing → DomainID 传播。HFNT 的 I2（Lift 形式化）在 M2 中缺失。

### M3 — Kimi-K2 / Long-Context Agentic Models
1M-2M context + 原生 agent loop。记忆 = 放进 context window。
- **强项：** F4、F8
- **弱项：** F5（context 是 blob，无 typed factor）、F6（用户 lock 是字符串）
- **限制：** 长度规模不替代结构；context 越长 ≠ 元策略可分解

### M4 — Hermes / Fine-Tuned Agentic Models
fine-tune 让模型内化 agent 行为。
- **强项：** F8
- **弱项：** F2/F3/F5/F6/F7 全 ❌——纯模型，无 harness 层

### M5 — MemGPT / Hierarchical Memory
模拟操作系统 paging。
- **强项：** F4
- **弱项：** F3（page 是 text，非 skill）、F5/F6（无类型化分区）
- **限制：** 解决容量，不解决结构

### M6 — RAG + Vector Store
把记忆作为 embeddings 存储，查询时 retrieve top-k。
- **强项：** F2、F4
- **弱项：** F5/F6（embedding 无 typed factor；retrieval 是相似度，不是规则匹配）
- **限制：** meta-rule 无法 retrieve——它不是语义相似问题，是类型匹配问题

### M7 — Superpowers / Claude Skills / Cursor Rules
平铺 skill 注册表 + 触发时注入对应 markdown 到 system prompt。
- **强项：** F3、F7
- **弱项：** F5（每个 skill 独立，无跨 skill 类型化元规律）、F6（lock 是 markdown 文本）
- **与 HFNT 的关系：** M7 最接近 I1（有命名 skill，部分类型化），但 skill 触发是 **关键字匹配**，不是 Pack routing。DomainID 无法从触发的 skill 传播到后续信号处理（Lift 无形式化）。M7 满足 I1 的表面形式，但不满足 I2。

### M8 — Agentic RL (RLVR / ReSTEM)
合成 trajectory 训练 reward，让模型在 agentic benchmark 上表现更好。
- **强项：** F8
- **弱项：** F6（权重 RLHF 漂移可静默改 user-locked 行为）、F7（训练数据池化）

### M9 — Active Lessons-Learned Notepad（CLAUDE.md / ChatGPT memory）
用户告诉 agent"下次不要这样"，agent 把这条写进 notepad，下次注入。
- **强项：** F2、F7、即时部署
- **弱项：** F5（notes 是 fact，不是 meta-rule；K 域需 K 份 note，无组合）、F6（string lock 可被后续 prompt 覆盖）
- **限制：** 失败是结构性的——fact / meta-rule / lock 全塞进同一个字符串 blob

### M10 — Constitutional AI / RLHF Constitution
文本 constitution + RLHF reward model 训练，让模型内化 alignment 规则。
- **强项：** F6（alignment-time 约束，部分对抗权重漂移）、F8
- **弱项：** F5（单一 constitution，非跨域）、F7（population-level，非 per-user）

---

## 4. HFNT — Harness Factoring Necessity Theorem（核心定理）

这是 v2 相比 v1 最重要的新增内容。

### 4.1 理想属性定义（I1–I4）

在陈述定理之前，先定义目标架构需满足的四个理想属性：

**I1（有类型可分离性）：**
Brain 导出 `Schema_B = {meta_policy_family: FiniteHypothesisClass[Φ], state_graph: TypedCIRGraph}`；Hand 导出 `Schema_H = {seed_manifest: ProcedureLibrary, brain_dependencies: Schema_B → bool}`。Pack 函数当且仅当 `brain_dependencies(Brain.state) = true` 时有类型——即 Brain×Hand 的组合是一个可机器检查的 schema 校验，而非手工审查。

**I2（Lift 形式化——Pack 路由的 DomainID 来源）：**
`Lift: Interaction × Workspace → Signal`，每个 Signal 携带 `domain_tag: Option[DomainID]`。
类型规则：
```
若 active_hand ≠ null 则 signal.domain_tag = Some(active_hand.domain_id)
否则 signal.domain_tag = None
```
**关键架构动作：** DomainID 在 Hand seed **编写时**（由领域专家）声明，而非在推理时从信号内容中推断。Pack 选择 Hand → Hand 携带 DomainID → Lift 继承 DomainID。领域分类是路由的结构性属性，不是语义解读问题。

**I3（两层迁移不变性）：**
- *L1（结构层，类型级别）：* 任意满足 schema contract 的 Brain×Hand 对无类型错误地组合。可通过对 Pack 类型检查 `(Schema_B, Schema_H)` 来证明。对所有兼容对成立。这是架构的形式保证。
- *L2（行为层，运行时）：* 组合后的 Brain×Hand 对目标 domain 产生语义有用的输出。由定理 2（O(log K/K) 冷启动界）刻画——不是类型级保证，是统计学习保证。

**I4（Audit 机制——生命周期迁移不变性）：**
每 K 次交互后：`Audit(Brain.state.mutable_nodes) → {retain: domain_agnostic, demote: domain_specific}`。一个节点是 `domain_agnostic` 当且仅当其信号溯源携带 `domain_tag = None`（由 Lift 类型规则保证）。具有领域特异性的可变节点（`domain_tag ≠ None`）被降级到 `Hand.manifest.evolved`，使 Brain 在整个生命周期内保持可迁移性——而非只在初始化时。

**Audit 正确性：** 由 Lift 的类型规则（结构性，非语义性）保证。DomainID 来源于 Pack 路由，对格式良好的调用不会出错。

### 4.2 定理 0（HFNT）

**定理 0（Harness Factoring Necessity Theorem）：**
任何满足 I2（来自 Pack 路由的结构性 `domain_tag` 来源）的 Harness，必须让 Pack 从**预类型化的 Hand 服务**（具有编写时声明的 DomainID）中进行选择。

**证明结构：**

**引理（DomainID 稳定性）：** I2 要求 `H_d.DomainID` 在状态存储更新下稳定（否则 Lift 无法稳定继承 `domain_tag`）。若 `H_d` 是由运行时分区函数 `C` 从共享存储 S 中识别的子集，则 `H_d.DomainID` 由 C 的输出决定，而 C 的输出随 S 变化而改变。∴ `H_d.DomainID` 不稳定。DomainID 稳定性要求编写时声明——即 Hand 必须是预类型化服务。

**Pack 对称性推导：** Pack 的签名为 `Pack(Brain.state, Hand.manifest, Task) → TaskEnvelope`。若 `Hand.manifest` 必须是类型化服务（由引理），则 `Brain.state` 也必须是类型化实体，才能使 Pack 的类型签名格式良好（函数不能在某些参数有类型而其他参数是无类型 blob 的情况下良好定义）。∴ Brain 也必须是预类型化的。

**推论（存在性）：** LPH 满足 I1+I2+I3+I4，建立 HFNT 的存在性（即 Brain×Hand 类型化分解是可构造的）。

### 4.3 负面结果——类型化注释不足以满足 I2

**M9+（带类型前置信息的 CLAUDE.md）：** 在 M9 中每个条目标记 `{type: brain|hand, domain_id: Option[DomainID]}`。M9+ 在语法上满足 I1（条目有标签）。但：M7/M9 中的 skill/hand 选择是**关键字匹配**，不是 Pack routing。"活跃 Hand"由触发的 skill 决定——而 skill 是同一文件中的内容 blob，不是具有稳定 DomainID 的独立类型化服务。因此 M9+ **在结构上不满足 I2**：DomainID 无法从带标签的内容传播到 Lift（没有 Pack routing）。

差距不在于注释质量——而在于 **Pack routing 的缺失**。给 M9 加 routing table，等价于重新实现 LPH 的 Hand 架构；"单存储"的标签在那时已名存实亡。

---

## 5. LPH 设计（v2 更新版）

### 5.1 核心分解（类型化分解）

**Brain 侧**——跨 domain、跨 model swap 持久：

- `Brain.meta`：类型化元策略族（FiniteHypothesisClass[Φ]）= `{rubric_update, lock_resolve, new_domain_bootstrap, schema_evolution, routing_decay, presentation_pref, cross_domain_rule}`
- `Brain.state`：类型化 CIR 图，节点类型 = `{Rubric-weight, Locked-belief, Routing-rule, Cross-domain-rule, Preference}`
  - `Locked-belief` 节点：类型保护，Evolve 的类型签名禁止写入

**Hand 侧**——domain-specific，可 product-shipped 或 user-evolved：

- `Hand.manifest.seed`：product-shipped = `{procedure, tools, output_schema, resource_catalog, domain_id: DomainID}`
  - **DomainID 是 seed 的 declared 属性，在编写时由领域专家确定**
- `Hand.manifest.evolved`：用户累积的领域精化（Brain.state 中被 Audit 降级的节点写入这里）

### 5.2 三个纯函数（v2 形式化版）

```
Pack   : (Brain.state, Hand.manifest, Task) → TaskEnvelope
         约束: brain_dependencies(Brain.state) = true（schema 校验）
         效果: 选择 Hand → TaskEnvelope 中包含 Hand.domain_id

Lift   : (Interaction, Workspace) → Signal
         类型规则: active_hand ≠ null → signal.domain_tag = Some(Hand.domain_id)
         效果: DomainID 从 Pack 路由传播到信号，不依赖信号内容

Evolve : (Brain.meta, Signal, Brain.state, Hand.evolved) → (Δstate, Δevolved)
         类型约束: Δstate 不包含 Locked-belief 或 seed 节点
         效果: domain-agnostic 信号更新 Brain.state.mutable_nodes；
               domain-specific 信号（domain_tag ≠ None）更新 Hand.evolved
```

三者均为**纯函数，无外部副作用**——这是后续形式证明的基础。

### 5.3 工作循环（10 步）

```
Task
  → Pack(Brain.state, Hand.manifest, task) → TaskEnvelope（含 Hand.domain_id）
  → Hand 执行（不见 Brain.state 全貌）
  → artifact → workspace
  → 用户交互 → Lift(interaction, workspace) → Signal（domain_tag 由 Pack routing 确定）
  → Evolve(meta, signal, state, evolved) → (Δstate, Δevolved)
  → 应用 Δ → 下次 Pack 输出不同 envelope
  → 每 K 次交互后：Audit(Brain.state.mutable_nodes) → 领域特异节点降级到 Hand.evolved
```

### 5.4 为什么 HFNT 蕴含 F5+F6

**F5（跨域组合泛化）：**
- Brain.meta 是类型化的 FiniteHypothesisClass[Φ]，VC 维有界
- K 个 domain 交互 → Brain.meta 收敛；第 K+1 域冷启动时元规律已具备
- **定理 2：** `L(meta_K, d_{K+1}) − L(meta_oracle, d_{K+1}) ≤ C · √(d · log K / K)`，其中 d = VC dim(Φ)
- Audit 机制确保这一泛化在生命周期内持续成立（Brain 不因领域使用而退化为 domain-specific）

**F6（lock 保存）：**
- Brain.state.Locked-belief 是**类型图节点**，不是字符串
- Evolve 的类型签名**结构性禁止**写 Locked-belief 节点
- 唯一可改 lock 的路径：lock_resolve meta-policy + 用户显式触发
- **定理 1：** 在任意遵循 Evolve 类型签名的 online signal 序列下，所有原有 lock 的 value 不变
- 这是**类型级**不变性——不可被字符串 blob 方法功能替代（HFNT 的必要性部分）

---

## 6. 综合对比表（v2 更新——增加 I1/I2 列）

> **图例：** ✅ = 设计目标且充分实现；⚠️ = 部分覆盖或依赖手工配置；❌ = 不在设计目标内或结构性缺失

| 方法 | F1 | F2 | F3 | F4 | **F5** | **F6** | F7 | F8 | **I1** | **I2** |
|---|---|---|---|---|---|---|---|---|---|---|
| M1 Reflexion | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | ⚠️ | ❌ | ❌ |
| M2 Voyager | ⚠️ | ⚠️ | ✅ | ❌ | ❌ | ❌ | n/a | ⚠️ | ⚠️ | ❌ |
| M3 Kimi-K2 | ⚠️ | ⚠️ | ❌ | ✅ | ❌ | ❌ | ⚠️ | ✅ | ❌ | ❌ |
| M4 Hermes | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| M5 MemGPT | ❌ | ⚠️ | ❌ | ✅ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ |
| M6 RAG | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | ❌ |
| M7 Skills/Superpowers | ❌ | ⚠️ | ✅ | ❌ | ❌ | ❌ | ✅ | ⚠️ | ⚠️ | ❌ |
| M8 Agentic RL | ⚠️ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ✅ | ❌ | ❌ |
| M9 Notepad/CLAUDE.md | ❌ | ✅ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ⚠️ | ❌ | ❌ |
| M9+ (typed CLAUDE.md) | ❌ | ✅ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ⚠️ | ⚠️ | ❌ |
| M10 Constitutional AI | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ✅ | ❌ | ❌ |
| **LPH（本提案）** | ❌ | ✅ | ✅ | ⚠️ | **✅** | **✅** | ✅ | ❌ | **✅** | **✅** |

### 关键观察

**Gap 1（F5 列）：** 没有任何已有方法 ✅——所有 10 个方法在跨域组合泛化上结构性失败。

**Gap 2（F6 列）：** 没有任何已有方法 ✅——所有 lock 都是字符串或权重，无类型保护。

**Gap 3（I2 列）：** 没有任何已有方法 ✅——M9+ 加了类型注释后满足 I1 的表面形式，但仍不满足 I2（Pack routing 缺失）。**这是 v2 新增的核心观察。**

**HFNT 的意义：** I2 是 F5+F6 的必要条件。因为没有方法满足 I2，所以没有方法能够同时满足 F5+F6——这不是质量差距，是架构的结构性缺失。

---

## 7. 形式贡献（三项，ICLR 定位）

### C1 — HFNT（定理 0，必要性）

**主张：** 任何满足 I2（结构性 domain_tag 来源）的 harness，必须实现类型化 Brain×Hand 分解。

**证明结构：** DomainID 稳定性引理 → Hand 必须是预类型化服务 → Pack 对称性 → Brain 也必须是预类型化服务 → 类型化 Brain×Hand 分解对 I2 是必要的。

**定位：** 这不是"提出一种好设计"，而是"证明这是唯一可行的设计类"。类比：
- 端到端论证（Saltzer, Reed & Clark 1984）：某些正确性保证只能在特定架构层实现
- 类型安全必要性（Pierce, TAPL 2002）：某些安全属性需要类型化接口，而非惯例

**负面结果（M9+）：** 给 CLAUDE.md 添加类型注释在语法上满足 I1，但在结构上不满足 I2——差距不在注释质量，而在 Pack routing 的缺失。明确关闭"增量改进现有方法"这一反驳路径。

### C2 — LPH 构造（定理 0 的存在性 + 形式规范）

**主张：** LPH 满足 I1-I4，建立类型化分解的存在性。

**形式证明（四个）：**
1. **Pack 良型性：** `Pack: Schema_B × Schema_H × Task → TaskEnvelope` 当 `brain_dependencies(Brain.state) = true` 时类型检查通过
2. **Lift domain_tag 来源：** 类型规则 `active_hand → domain_tag = Some(DomainID)` 由 Pack 路由结构性保证，不依赖信号内容
3. **Evolve 更新隔离：** Locked-belief 和 seed 节点不在 Evolve 写域（类型签名保证）
4. **Audit 正确性：** 由 Lift 的类型规则推导——domain_tag 来源是结构性的，不是语义性的

**附属定理：**

> **定理 1（Lock 保存）：** 在任意遵循 Evolve 类型签名的 online signal 序列下，所有 `Brain.state.Locked-belief` 的值不变。
> *证明：* Evolve 的类型签名将 Locked-belief 排除在写域之外。

> **定理 2（冷启动界）：** 令 d = VC dim(Brain.meta 的 FiniteHypothesisClass[Φ])，K 个先前 domain 交互后，对第 K+1 个 domain 的泛化误差满足：
> `L(meta_K, d_{K+1}) − L(meta_oracle, d_{K+1}) ≤ C · √(d · log K / K)`
> *证明：* 将标准 PAC-VC 定理（Blumer et al. 1989）应用于以 FiniteHypothesisClass[Φ] 为假设类的 Brain.meta。

### C3 — 实验验证（三个实验）

**（a）对抗 lock 违反实验（验证定理 1）：**
- 1000 条对抗性 update 序列，设计为最大化 Locked-belief 节点的改变压力
- 度量：违反率（lock 被改变的序列百分比）
- 基线：M7 Skills（有命名 skill 但无类型保护的 lock）
- 预期：LPH 0% 违反；M7 >0% 违反

**（b）K-domain 冷启动实验（验证定理 2）：**
- K = 2, 4, 6, 8 个 domain holdout；度量 Brain.meta 在 held-out domain 上的冷启动性能
- 将实验曲线拟合到理论预测 `O(log K / K)`
- 基线：独立 per-domain 精调（无跨域迁移）
- 预期：LPH 拟合 O(log K/K)；基线不随 K 改善

**（c）M9+ 负面结果实验（验证 G3）：**
- 对 CLAUDE.md 施加类型化注释（M9+），进行 domain-shift update 序列测试
- 度量：DomainID 稳定性（domain-shift 后 DomainID 是否仍指向正确的原始 Hand）
- 预期：M9+ 在 ≥80% 的 domain-shift 序列中 DomainID 不稳定；LPH 100% 稳定

---

## 8. LPH 优劣分析（诚实评估）

### 8.1 优势（F5、F6、F7、I1、I2）

| 优势 | 来源 | 是否可证 |
|---|---|---|
| 跨域组合泛化 | 类型化 Brain.meta + 有界 VC dim | ✅ 定理 2：O(√(d · log K / K)) 冷启动界 |
| User-lock 保存 | 类型化 Brain.state + Evolve 写域限制 | ✅ 定理 1：0% 违反 |
| Per-user 隐私 | Brain.state 本地类型图 | by design |
| 结构迁移不变性（L1） | Pack schema 校验 | ✅ 类型检查可机械验证 |
| 生命周期可迁移性 | Audit 机制（domain_tag 溯源） | ✅ 由 Lift 类型规则推导 |
| 可审计性 | 类型图 Δ 可可视化 | by design |

### 8.2 劣势（F1、F4、F8）

| 劣势 | 谁更强 | 缓解策略 |
|---|---|---|
| 无 within-trajectory 反思 | Reflexion / SELF-REFINE | Hand 内嵌 Reflexion-style loop |
| 无 context paging | MemGPT | Pack inject 阶段叠加 MemGPT |
| 不改 LLM 能力上限 | Kimi-K2 / Hermes / Agentic RL | 任意 model 作 Hand backend |
| 部署需基础设施 | Notepad / Skills 写 markdown 即用 | Phase A 提供最小类型化存储 |
| Brain.meta 收敛需 K≥3 域 | Notepad 第一次即生效 | 默认 seed library bootstrap |

### 8.3 LPH *不适用* 的场景

| 场景 | 推荐方法 |
|---|---|
| 单 domain、一次性任务 | Notepad / 直接 prompt |
| 不在意 lock，只要"差不多记得" | Notepad / ChatGPT memory |
| 需要 model 能力跃迁 | Agentic RL / 更强底座 |
| 单次复杂多步任务 | Reflexion + 强底座 |
| 容量受限（>200K context）| MemGPT 或叠加 |

---

## 9. 正交叠加图——LPH 如何与其他方法组合

LPH **不替代** M1-M10——它是**类型化分解层**，在其上提供不变性 + 跨域组合。

| LPH × | 叠加方式 | 收益 |
|---|---|---|
| × M1 Reflexion | Reflexion 嵌入 Hand 内的 LLM loop | F1 + F5 兼得 |
| × M2 Voyager | Voyager 课程作为 `new_domain_bootstrap` meta-policy | 自动课程能力被 LPH 跨域复用 |
| × M3 Kimi-K2 | Kimi 作 Hand backend（http×openai） | F4+F8 由 Kimi 承担，LPH 提供 F5+F6 |
| × M5 MemGPT | MemGPT 实现 Pack 的 context budget | F4 由 MemGPT 解决 |
| × M6 RAG | Vector store 作 routing-rule backing | F2 scalability 由 RAG 解决 |
| × M7 Skills/Superpowers | 每个 Skill → `Hand.manifest.seed`（含 DomainID 声明） | F3 由 Skills 解决，LPH 加跨 Skill 元规律 |
| × M9 Notepad | Notepad 作 Brain.state.Preference 初始化 seed；CLAUDE.md 内容平滑迁移到类型化状态 | 从 M9 渐进升级到 LPH |
| × M10 Constitutional AI | Constitution → 默认 Brain.meta 的固定子集 | 全局 alignment 与 per-user 不变性共存 |

**核心定位：** LPH = *不变性 + 分解层*。Capability / capacity / reflexion 层正交叠加。

---

## 10. 与 Loom Codebase 的关系

**复用已有：**
- `loom_core/agent_adapters/adapter.py`：7-provider 抽象 → 直接作 Hand backend layer
- `loom_core/runtime/app.py`（`LoomCoreRuntime`）：feedback_store / hand_config_store → Lift 信号采集与 Evolve 状态写回
- `loom/hands/base.py`（`BaseHand`）：继续作 Hand 内部执行循环；envelope 改为 TaskEnvelope 形态
- `loom/brain.py` FastAPI `/run`：Pack/Lift/Evolve 接入点

**新增独立目录：** `loom_core/lph/`（当前不存在）
- `brain_state.py` / `brain_meta.py` / `hand_manifest.py` — 类型化 schema
- `pack.py` / `lift.py` / `evolve.py` — 三纯函数
- `audit.py` — Audit 机制
- `meta_policies/` — 默认元策略库

**双协议并行：** 旧 `task+context` envelope 保留（兼容性）；新 `task_envelope` 走 LPH；feature flag 切换。不动 `anchor-client.js`、`styles.css`、`loom-fin`。

---

## 11. 实施 Outline

| Phase | 内容 | 周期 |
|---|---|---|
| A | 类型化存储骨架（brain_state.py, brain_meta.py, hand_manifest.py）+ JSON Schema 导出 | 2–3 周 |
| B | Pack/Lift/Evolve + Audit + 默认元策略库 | 3–4 周 |
| C | 定理 1 实验框架：1000 对抗信号，lock 违反率度量 | 3–4 周 |
| D | 定理 2 实验：6–8 domain holdout + O(√(d log K/K)) 拟合 | 5–6 周 |
| E | M9+ 负面结果实验：DomainID 稳定性测试 | 2–3 周 |
| F | 用户研究（N=50，迁移摩擦 vs 传统 skill 系统） | 4–5 周 |
| G | 理论证明 paper（C、D、E 并行） | 6–8 周 |

**目标投稿：** ICLR 2027 main / COLM 2026 main / NeurIPS 2026 main

---

## 12. 参考文献

- Shinn et al. "Reflexion" (2023); Madaan et al. "Self-Refine" (2023)
- Wang et al. "Voyager" (2023); Park et al. "Generative Agents" (2023)
- Moonshot AI "Kimi-K2 Technical Report" (2025); Nous Research "Hermes 3/4"
- Packer et al. "MemGPT" (2023); Lewis et al. "RAG" (2020)
- DeepSeek-AI "DeepSeek-R1" (2025); AI2 "Tülu 3" (2024)
- Bai et al. "Constitutional AI" (2022, Anthropic)
- Finn et al. "MAML" (2017); Nichol et al. "Reptile" (2018)
- Vapnik & Chervonenkis (1971); Blumer et al. "Learnability and the VC dimension" (1989)
- Saltzer, Reed & Clark "End-to-end arguments in system design" (1984)
- Pierce "Types and Programming Languages" (2002); Wadler "Linear types can change the world" (1990)
- Moggi "Notions of computation and monads" (1991)

---

## 一句话总结（v2）

> 当前所有 LLM harness 设计（M1-M10）在同时满足 F5（跨域组合泛化）和 F6（lock 保存）上结构性失败，根因是它们都违反了 **Harness Factoring Necessity Theorem（HFNT）**：任何实现结构迁移不变性（I2）的 harness，必须将 Brain（领域无关元策略族 + 类型化状态图）和 Hand（领域专属 seed manifest，编写时声明 DomainID）分解为独立类型化服务，通过 Pack/Lift/Evolve 类型化接口连接。LPH 是满足此要求的最小构造，并通过 Audit 机制将 structural Transfer Invariance 从初始化时扩展到整个生命周期。贡献：**HFNT（必要性） + LPH（存在性） + 两个定理 + 三个实验**。可迁移的 harness 是架构；personalization 是该架构上的一个实例化点。
