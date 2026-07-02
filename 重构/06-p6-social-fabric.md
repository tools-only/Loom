# P6 · 出海期：fabric 是社会对象

> **目标**：fabric 像 repo 一样可 fork / merge，hands 随 fabric 迁徙，"织谱"（pattern）成为可分享的声明式工作流。你可以 fork 一位分析师公开的盘前 fabric——连同它积累的 wiki 认知一起继承。个人助理的终局不是一个更聪明的单体，而是一个可继承、可交换认知的网络。
> **最大的雷**：分享一块 fabric ≈ 分享一个 agent 对你的了解。导出必须经过 **wiki 消毒**，而消毒界面本身又是一块 fabric——用 handle 圈选哪些认知随布出海。
> **分三步**：织谱导出/导入 → 公开 fabric 的 fork → 带认知的继承。风险递增，按序上线。

---

## 1. 需求分析

### 1.1 三个可分享单元（严格区分，风险分级）

| 单元 | 含什么 | 不含什么 | 风险 |
|---|---|---|---|
| **织谱 pattern** | hand 编排（角色/权限/预算/trigger）、文档骨架（section 结构 + ghost 计划模板）、handle 配置 | 任何数据、任何 wiki、任何历史 | 低 |
| **公开 fabric** | 某分支在某 seq 的折叠内容 + 自该点起的公开历史 | 私有分支、注意力数据、wiki | 中 |
| **认知包 legacy** | 经消毒的 wiki 条目子集（可附证据摘要） | 未圈选条目、attention 分区（默认） | 高 |

### 1.2 功能需求

**S1 织谱**

| 编号 | 需求 |
|---|---|
| FR-1 | `pattern.yaml` 导出：从现有 fabric 提取声明式织谱（§2.1），本地文件 + 可发布到 git repo |
| FR-2 | 导入：织谱 → 实例化空 fabric（hands 按需映射到本地注册表；缺失 hand 生成"需要结晶/安装"的 ghost 提示） |
| FR-3 | 织谱签名：导出时附作者签名（P0 预留的 sig 字段落地）；导入时校验并展示来源 |
| FR-4 | 权限声明消减原则：导入的织谱申请的权限以显式清单呈现，逐项批准（默认全拒） |

**S2 公开 fork**

| 编号 | 需求 |
|---|---|
| FR-5 | 发布：选择分支 + seq，生成公开快照（folded tree + 后续公开 patch 流），静态可托管（单文件 bundle） |
| FR-6 | fork：导入公开 bundle 为本地新 fabric，保留原出处链（provenance 指向源 fabric 的 patch_id） |
| FR-7 | 上游更新：源 fabric 发布新快照时，fork 方可见"上游有 N 个新 patch"，选择性 merge（复用 P0 3-way + conflict block） |
| FR-8 | 身份最小实现：keypair 本地生成，公钥即身份；不做账号系统（分发靠 URL/git，验证靠签名） |

**S3 认知继承**

| 编号 | 需求 |
|---|---|
| FR-9 | 消毒 fabric：导出流程强制经过一块临时 fabric，全部候选 wiki 条目铺开，**默认全不选**；用 handle 圈选出海条目（annotate 可加脱敏批注，refine 可现场改写泛化） |
| FR-10 | 泛化助手：可选的 hand 辅助改写（"用户只关心科技与能源" → "本织谱默认聚焦科技与能源板块"），人终审 |
| FR-11 | 导入侧隔离：继承的认知进入 wiki 的 `inherited/<来源>` 分区，默认不 locked，与本地认知冲突时并存为 branch 假设，由使用中的采纳数据自然分出胜负（P5 机制） |
| FR-12 | 撤销出海：本地一键吊销已发布 bundle 的后续更新（已扩散的副本无法追回——文档与 UI 必须诚实说明这一点） |

### 1.3 非功能需求

- 导出物完全自包含（单文件 `.loom` bundle = zip：manifest + patches + snapshots + assets），离线可导入；
- 消毒不可绕过：代码层面不存在"导出含 wiki 的 fabric"的非消毒路径（安全评审项）；
- 隐私红线自动扫描：导出前对内容跑本地敏感信息扫描（密钥格式、邮箱、账号数字模式），命中即阻断并定位到 block。

## 2. 设计方案

### 2.1 织谱格式（示意）

```yaml
# pattern.yaml —— 声明式、无数据、可 diff、可 PR
pattern: premarket-desk
version: 3
author: pk:9f3a…            # 公钥身份
description: 盘前分析工作台（四手协作）
hands:
  - role: market            # 角色名，导入时映射/结晶为本地 hand
    caps: [read_market_data]
    budget: {usd_per_run: 0.4}
    heartbeat: {cron: "0 6 * * 1-5", tz: local}
  - role: sentiment
    caps: [read_news]
skeleton:
  - section: 市场综述   {ghost: {hand: market, trigger: heartbeat}}
  - section: 情绪扫描   {ghost: {hand: sentiment, trigger: heartbeat}}
  - section: 持仓归因   {ghost: {hand: position, trigger: {event: positions.updated}}}
handles:
  locked_sections: [免责声明]
requires:
  events: [positions.updated]     # 导入时提示需要接入的数据源
```

设计要点：织谱引用**角色**而非具体 hand_id——导入时经"映射向导"绑定本地 hand，
或触发 P5 结晶管道生成新 hand。这使织谱天然跨环境、跨 runtime。

### 2.2 公开 bundle 与 fork/merge

```
.loom bundle
├─ manifest.json      // fabric_id, 快照 seq, 作者公钥, 签名, 内容哈希
├─ snapshot.json      // 折叠树（发布点）
├─ patches.jsonl      // 发布点之后的公开 patch（增量更新用）
└─ assets/            // 图片等静态资源
```

- fork = 本地建 fabric，初始 patch 为"import snapshot"，出处链保留源 patch_id 映射表；
- 上游 merge 复用 P0 的 block 级 3-way：base = 上次同步点快照。fork 后本地大改的块与上游
  更新冲突时物化 conflict block——**社会化合并与单机合并是同一机制**，这是 P0 投资的回报；
- 分发不自建平台：bundle 可放任意静态托管 / git repo；`loom import <url>` 即可。
  社区目录（awesome-patterns 式的 git 仓库）作为运营动作而非产品功能。

### 2.3 消毒流程（S3 的核心）

```
点击「发布含认知的织谱」
  ▼
生成临时 sanitize fabric：
  ├─ 左栏：全部候选 wiki 条目（默认灰=不出海），attention 分区默认隐藏且需二次展开
  ├─ 圈选条目 → 变绿（出海）；refine → 现场泛化改写；annotate → 附导出说明
  ├─ 顶部常驻红线扫描结果与「以接收者视角预览」按钮
  ▼
确认 → 只有绿色条目进入 bundle 的 legacy 分区（每条附消毒记录：原文哈希 + 改写人）
```

「以接收者视角预览」是本流程的良心开关：完整渲染对方导入后将看到的一切，
包括每条认知会出现在哪个 wiki 分区。

### 2.4 导入侧的信任呈现

- 导入向导四屏：来源与签名 → 权限清单（逐项批准，默认拒）→ 继承认知列表（可逐条剔除）
  → hand 映射；
- 一切导入产物带来源标记：inherited wiki 条目、织谱实例化的 ghost、fork 的块，
  出处面板均可回溯到源 bundle 与作者公钥。

## 3. 开发拆解

1. **M6.1** bundle 格式 + 导出/导入 + 签名验证（1 周）
2. **M6.2** 织谱提取器（fabric → pattern.yaml）+ 导入映射向导（1 周）
3. **M6.3** 公开发布 + fork + 上游增量 merge（1 周，依赖 P0 的 FR-6 merge 已完成）
4. **M6.4** 消毒 fabric + 红线扫描 + 接收者视角预览（1.5 周）
5. **M6.5** inherited 分区 + 冲突并存机制接线（0.5 周）
6. **M6.6** 安全评审（消毒不可绕过、红线扫描覆盖率）+ 文档与吊销诚实性检查（0.5 周）

## 4. 测试策略

- 往返测试：导出 → 导入 → 再导出，bundle 内容哈希稳定；
- 消毒不可绕过：对代码路径做安全测试（不存在含 wiki 的非消毒导出 API）；红线扫描用
  含 fake 密钥/邮箱的种子集，召回率 100% 为硬门槛（宁可误报）；
- fork-merge 冲突矩阵：上游改/本地改/双改 × 内容/结构/状态 的组合用例；
- 跨环境导入：在无任何已注册 hand 的干净环境导入织谱，映射向导必须给出完整的结晶/安装路径。

## 5. 验收 Demo 脚本

1. 把 Loom Fin 的盘前 fabric 一键提取为 `premarket-desk` 织谱，推到 GitHub；
2. 在另一台干净机器 `loom import <url>`：签名校验 → 权限逐项批准 → 缺失的 sentiment 角色
   触发结晶 ghost → 批准后空 fabric 上显影出明早的全套幽灵计划；
3. 原作者发布含认知的进阶版：消毒 fabric 中圈选 6/40 条认知、refine 掉其中两条的个人色彩、
   预览接收者视角后发布；
4. 导入方在 wiki 的 inherited 分区看到 6 条认知（每条可溯源到作者），其中一条与本地认知
   冲突并存为两支假设；两周后（演示时用回放数据）P5 战绩显示继承认知胜出；
5. 展示吊销：作者停更后，fork 方收到"上游已停止发布"的诚实提示。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 隐私泄露（最大风险） | 默认全不选 + 红线扫描硬阻断 + 接收者视角预览 + 消毒不可绕过纳入安全评审 |
| 恶意织谱（权限走私、prompt 注入藏在骨架里） | 权限默认全拒逐项批准 + 骨架文本在导入预览中全量可见 + 导入的 ghost 首次执行强制 requires_human_seal |
| 上游投毒（增量 patch 注入） | 增量必须签名匹配 + merge 永远经人（conflict block），无静默自动合并 |
| 生态冷启动 | 官方先发 5–8 个高质量织谱（盘前、周报、论文速递…）；织谱 repo 化使分享零平台成本 |

**开放问题**：
- 多端实时协同（真 CRDT）：fork/merge 已覆盖异步协作，实时协同待用户需求验证后单独立项；
- 认知包的许可协议（继承的 wiki 算不算衍生作品）：发布前需要一份简明的默认许可文本，法务问题，工程侧只预留 manifest.license 字段。
