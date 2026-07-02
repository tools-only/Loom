# P0 · 地基期：一切皆 patch

> **目标**：把 Loom 的真理源从"HTML 文件"替换为 append-only 的 patch 操作流；HTML 降级为对 patch 流的一次折叠（投影）。
> **用户可见产出**：无。本期是使能层，决定后续每一期是"实现功能"还是"和自己的数据模型搏斗"。
> **验收唯一标准**：任意时刻可将整块 fabric 拖回任意历史点，并从那里分叉。

---

## 1. 需求分析

### 1.1 现状问题

当前架构（假设）：hand 直接读写 HTML 文档，文档即状态。由此产生的结构性缺陷：

- 无法回答"这个元素是谁、在什么时候、基于什么改的"（无出处）；
- 无法时间旅行与分叉（branch handle 只能靠复制文件模拟）；
- 多个 hand 并发写同一文档需要文件锁或串行化，天然排斥并行织造；
- 后续所有规划（幽灵内容、生态度量、fork/merge）都需要各自重新发明状态管理。

### 1.2 功能需求（FR）

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1 | 所有 fabric 状态变化以 patch 形式追加写入操作流，禁止原地修改 | P0 |
| FR-2 | 折叠器（reducer）可从任意 seq 重放出块树，并投影为 HTML | P0 |
| FR-3 | block 拥有状态机：`molten / committed / ghost / locked / conflict` | P0 |
| FR-4 | 每条 patch 携带出处：source（human/hand/system）、run_id、成本与模型元数据 | P0 |
| FR-5 | 分支：从任意 seq fork 出新 branch；同一 fabric 可有多个 head | P0 |
| FR-6 | 合并：block 级 3-way merge，冲突物化为 `conflict` 状态的 block 交给人 | P1 |
| FR-7 | 快照：每 N 条 patch 固化一次块树快照，加速重放 | P1 |
| FR-8 | hand 适配层：hand 的输出从"改写 HTML"改为"提交 patch"；提供 HTML-diff→patch 过渡转换器 | P0 |
| FR-9 | 现有 HTML 文档一键导入为初始 patch 序列（迁移工具） | P1 |
| FR-10 | 时间旅行 API：`checkout(seq)`（只读视图）与 `fork(seq)`（新分支） | P0 |

### 1.3 非功能需求（NFR）

- **性能**：10 万条 patch 的 fabric，冷启动折叠 ≤ 2s（借助快照应 ≤ 200ms）；单条 patch 追加 ≤ 10ms。
- **并发**：多个 hand 并发提交 patch 不丢失、不阻塞（append-only 天然支持，冲突延迟到折叠期处理）。
- **可恢复**：进程崩溃后从 log 完整恢复；log 是唯一必须备份的文件。
- **明确不做**：CRDT / 多端实时协同（P6 课题）、跨 fabric 事务、patch 压缩加密。

## 2. 设计方案

### 2.1 存储模型（SQLite）

```sql
-- 操作流：系统唯一真理源
CREATE TABLE patches (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 全局单调序号
  patch_id    TEXT NOT NULL UNIQUE,               -- uuid，用于跨库引用
  fabric_id   TEXT NOT NULL,
  branch_id   TEXT NOT NULL DEFAULT 'main',
  source_type TEXT NOT NULL CHECK(source_type IN ('human','hand','system')),
  source_id   TEXT NOT NULL,                      -- user_id 或 hand_id
  run_id      TEXT,                               -- hand 一次运行的归因锚点
  op          TEXT NOT NULL,                      -- JSON，见 2.2
  meta        TEXT,                               -- JSON：model, cost_usd, tokens, inputs 等
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_patches_fabric ON patches(fabric_id, branch_id, seq);
CREATE INDEX idx_patches_run    ON patches(run_id);

-- 分支登记
CREATE TABLE branches (
  branch_id       TEXT PRIMARY KEY,
  fabric_id       TEXT NOT NULL,
  name            TEXT,
  forked_from_seq INTEGER,          -- 分叉点；main 为 NULL
  created_at      TEXT NOT NULL
);

-- 快照：纯缓存，可随时删除重建
CREATE TABLE snapshots (
  fabric_id  TEXT NOT NULL,
  branch_id  TEXT NOT NULL,
  seq        INTEGER NOT NULL,      -- 截止到该 seq 的折叠结果
  tree       TEXT NOT NULL,         -- 块树 JSON
  PRIMARY KEY (fabric_id, branch_id, seq)
);
```

### 2.2 op 协议（patch 的载荷）

```jsonc
// op.type 枚举与载荷。target 一律为 block_id。
{ "type": "block.insert",  "target": "blk_x", "parent": "blk_p", "index": 3,
  "block": { "block_type": "chart", "content": {...}, "state": "molten" } }

{ "type": "block.update",  "target": "blk_x", "content_patch": {...} }   // 内容的结构化 diff
{ "type": "block.move",    "target": "blk_x", "parent": "blk_p2", "index": 0 }
{ "type": "block.delete",  "target": "blk_x" }                            // 软删：折叠后不可见，历史可见
{ "type": "block.state",   "target": "blk_x", "state": "locked" }         // 状态机迁移
{ "type": "block.command", "target": "blk_x", "verb": "refine",
  "text": "改成滚动12个月趋势", "mentions": ["hand_market"] }             // 意图也是 patch（P1 主用）
{ "type": "comment.add",   "target": "blk_x", "thread": "th_1", "text": "..." }
{ "type": "fabric.meta",   "kv": { "title": "盘前分析" } }
```

设计要点：
- **command 是 patch 而不是 API 调用**。意图进入操作流后才被路由器消费，天然获得审计、重放与归因。
- `block.update` 的 `content_patch` 按 block_type 定义各自的 diff 格式（文本用 unified diff 或直接整段替换；
  结构化块用 JSON merge patch）。首版允许整段替换，diff 精细化留给后续优化。

### 2.3 block 状态机

```
            ┌─────────────┐  seal/verify   ┌───────────┐
  insert ─▶ │   molten    │ ─────────────▶ │ committed │ ──▶ lock ──▶ locked
            │ (即兴,可变) │ ◀───── melt ── │  (已定稿) │ ◀── unlock ─┘
            └─────────────┘                └───────────┘
   ghost（P2 引入，凝固后进入 molten/committed）
   conflict（merge 产物，人工消解后回到 molten）
```

状态迁移只能通过 `block.state` patch 完成；`locked` 的 block 拒绝除 `unlock` 外的一切 patch
（折叠器层面强制，返回被拒 patch 的错误块）。

### 2.4 折叠器（reducer）与投影

```
patches (seq ≤ N, branch B)
   │  replay，纯函数：fold(tree, patch) -> tree
   ▼
BlockTree（内存中的块树，含状态与出处索引）
   │  projector（可插拔）
   ├──▶ HTML 投影（现有渲染层，本期唯一投影）
   └──▶ (预留) Agent 视图 / JSON 导出
```

实现要求：
- `fold` 必须是**纯函数**且**全量确定**：同一 patch 序列在任何机器上折叠出完全相同的树（禁止读取时钟、随机数）。
- 非法 patch（目标不存在、锁定拒写）不 crash，折叠为一个 `system` 来源的 error 注记 block，保证流永远可重放。
- 每个 block 在树上携带 `provenance` 聚合：最后修改者、创建者、关联 run_id 列表——供 P1 的出处 UI 直接读取。

### 2.5 分支与合并

- `fork(seq)`：在 branches 表登记新 branch，`forked_from_seq = seq`；此后新 patch 写入新 branch_id。
- 折叠某 branch = 重放 `main` 上 `seq ≤ forked_from_seq` 的 patch，再叠加本 branch 的 patch（递归支持从分支再分叉）。
- `merge(src → dst)`（FR-6，P1 优先级）：以分叉点为 base 做 **block 级 3-way**——
  仅一侧动过的 block 直接采用；两侧都动过的 block 生成 `conflict` block（并排呈现两个版本 + base），
  由人通过 handle 消解。**不做文本级自动合并**，冲突显式化本身就是"验证优先"的体现。

### 2.6 hand 适配层（本期最大的存量改造）

```
旧协议:  hand ──(改写 HTML 文件)──▶ 文档
新协议:  hand ──(POST /fabrics/{id}/patches, 批量)──▶ 操作流 ──折叠──▶ HTML
```

- 为 hand SDK 增加 `emit_patch(op, meta)` 与 `emit_patches([...])`；run 开始/结束由适配层自动登记 run_id。
- **过渡转换器**：对尚未迁移的 hand，适配层接收其输出的整份 HTML，与折叠出的当前 HTML 做结构 diff
  （按 block 的 `data-block-id` 锚点对齐），自动转换为 patch 序列提交。允许老 hand 零改动跑在新地基上，
  但转换产生的 patch 出处标记 `via_legacy_diff: true`，作为迁移完成度的度量。
- 渲染层要求：HTML 投影为每个 block 输出稳定的 `data-block-id`，这是过渡转换器与 P1 交互层共同的锚点。

### 2.7 对外 API（内部服务边界）

```
POST /fabrics/{fid}/patches          批量提交 patch（原子追加）
GET  /fabrics/{fid}/tree?seq=&branch= 折叠结果（默认 head）
GET  /fabrics/{fid}/html?seq=&branch= HTML 投影
POST /fabrics/{fid}/branches         fork(seq)
POST /fabrics/{fid}/merge            merge(src, dst)  [FR-6]
GET  /fabrics/{fid}/timeline         patch 元数据流（时间轴 UI 数据源）
```

## 3. 开发拆解（建议顺序）

1. **M0.1** patches/branches/snapshots 表 + 追加写接口 + patch 校验（1 周）
2. **M0.2** 折叠器纯函数 + 块树 + 状态机强制 + error block（1 周）
3. **M0.3** HTML 投影接入现有渲染层（block_id 锚点化）（0.5–1 周）
4. **M0.4** hand SDK `emit_patch` + 过渡转换器（HTML diff→patch）（1 周）
5. **M0.5** fork / checkout / timeline API + 快照（0.5 周）
6. **M0.6** 迁移工具（存量 HTML → 初始 patch 序列）+ 回归测试（0.5 周）
7. **M0.7**（可后置）block 级 3-way merge 与 conflict block

## 4. 测试策略

- **性质测试（property-based）**：随机生成合法 patch 序列，断言 ①折叠是确定的 ②任意前缀可折叠
  ③快照折叠 ≡ 全量重放。这是本期最重要的测试投入。
- 并发测试：N 个 writer 并发追加，断言无丢失、seq 无空洞。
- 兼容测试：Loom Fin 现有全部 hand 通过过渡转换器跑通原有场景，产出 HTML 与旧架构一致（golden file 对比）。

## 5. 验收 Demo 脚本

1. 打开一块由 Loom Fin hands 织出的盘前分析 fabric；
2. 拖动时间轴滑块回到 3 小时前，文档随之回放（只读）；
3. 在该历史点点击 **fork**，得到新分支，对某图表下达 refine（走过渡期的任意入口）；
4. 切回 main head，展示两个分支并存；
5. 打开任一元素的出处面板：创建者、最后修改的 hand、run、成本，一目了然。

## 6. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 贪心引入 CRDT 拖垮工期 | 明令禁止；单机 append-only log + 服务端串行 seq 已满足 P6 前所有需求 |
| 过渡转换器 diff 质量差，patch 碎片化 | block_id 锚点对齐 + 允许整块替换；碎片化只影响历史可读性，不影响正确性 |
| 折叠性能随 patch 增长退化 | 快照 + 每 fabric patch 量监控；超阈值提示归档 |
| content_patch 格式过度设计 | 首版允许整段替换，diff 精细化按 block_type 渐进补充 |

**开放问题**（进入 P1 前需拍板）：
- block 粒度的下限：一个段落是一个 block，那一个句子呢？建议以"handle 可作用的最小单元"为准，首版 = 现有渲染组件粒度。
- patch 是否需要签名（为 P6 的跨用户信任预留）：本期在 meta 中预留 `sig` 字段，不实现验签。


## 7. 代码架构与开发指导

### 7.1 模块结构

```
loom/core/            ├ ops.py  store.py  tree.py  reducer.py  branch.py  api.py
loom/projection/      ├ base.py  html.py
loom/handsdk/         ├ session.py  legacy.py
frontend/timeline.js
```

`core` 是全系统唯一地基，**禁止 import loom 内任何其他包**（见 ARCHITECTURE.md 红线）。

### 7.2 关键类与函数

**ops.py — op 协议**
```python
@dataclass(frozen=True)
class Patch:            # 一条已入库的操作（含 seq）；入库前为 PatchDraft
    seq: int; patch_id: str; fabric_id: str; branch_id: str
    source: Source      # (type: human|hand|system, id, run_id)
    op: Op; meta: dict; created_at: str

Op = BlockInsert | BlockUpdate | BlockMove | BlockDelete | BlockState | BlockCommand | CommentAdd | FabricMeta

def validate_op(op: Op, tree: BlockTree) -> None | OpError:
    """结构校验（目标存在性、locked 拒写、状态机合法迁移）。
    纯函数；被 store.append 与 reducer.fold 共用，保证写入与重放判定一致。"""
```

**store.py — PatchStore（唯一写入口）**
```python
class PatchStore:
    def append(self, drafts: list[PatchDraft]) -> list[int]:
        """原子批量追加，分配 seq。全库唯一的写路径——其余模块只能造 draft 交给它。"""
    def stream(self, fabric_id, branch_id, *, after: int = 0, until: int | None = None) -> Iterator[Patch]:
        """按 seq 升序流式读取；branch 读取自动拼接父分支前缀（递归到 main）。"""
    def save_snapshot(self, fabric_id, branch_id, seq, tree_json) / latest_snapshot(...):
        """快照纯缓存；latest_snapshot 返回 ≤seq 的最近快照供 materialize 加速。"""
    def on_appended(self, callback):  # 事件钩子：router/scheduler 等 consumer 的接入点
```

**tree.py — 块树与状态机**
```python
class Block:   # id, block_type, state, content, children, provenance(创建者/最后修改/run链)
class BlockTree:
    def get(self, block_id) -> Block | None
    def apply_structural(self, op) -> None      # insert/move/delete 的树操作
STATE_TRANSITIONS = {...}                        # molten/committed/ghost/locked/conflict 合法迁移表
def can_transition(cur: str, nxt: str) -> bool
```

**reducer.py — 折叠器（本期最重要的 200 行）**
```python
def fold(tree: BlockTree, patch: Patch) -> BlockTree:
    """纯函数、全量确定（禁时钟/随机）。非法 patch 不抛异常 → 物化 error 注记 block。"""
def materialize(store, fabric_id, branch_id, *, seq=None) -> BlockTree:
    """latest_snapshot + 增量重放；每 N(=500) 条 patch 顺手落新快照。所有读视图的唯一入口。"""
```

**branch.py**
```python
def fork(store, fabric_id, from_branch, seq, name) -> branch_id
def checkout(store, fabric_id, branch_id, seq) -> BlockTree     # 只读历史视图 = materialize 的别名
def merge3(base: BlockTree, ours: BlockTree, theirs: BlockTree) -> MergeResult:
    """block 级 3-way：单侧改动直取；双侧改动生成 conflict block（携带三版本）。
    返回 patch 草稿列表，由调用方 append——merge 本身不写库。"""
```

**projection/html.py**
```python
class HtmlProjector(Projector):
    def render(self, tree: BlockTree) -> str
    """每个 block 输出稳定 data-block-id 与 data-state 属性——P1 交互层与 legacy 转换器共同的锚点。
    按 block_type 分发到渲染函数注册表（后续期新增 block_type 只需注册，不改本文件）。"""
```

**handsdk/session.py 与 legacy.py**
```python
class HandSession:      # 适配层为每次 run 创建；自动注入 run_id 与成本 meta
    def emit_patch(self, op: Op, **meta) / emit_patches(self, ops)
class LegacyDiffAdapter:
    def convert(self, old_html: str, new_html: str) -> list[Op]:
        """按 data-block-id 对齐做结构 diff → patch 序列；未对齐块整块替换。
        产出 meta 标记 via_legacy_diff=True（迁移完成度度量）。"""
```

### 7.3 编码顺序（与 M0.x 对应）

1. `ops.py`（数据类 + validate_op + 单测）→ 2. `store.py`（append/stream，先不做快照）→
3. `tree.py` + `reducer.py`（fold + materialize 全量重放版；此时性质测试框架必须就位）→
4. `projection/html.py` 接现有渲染层 → 5. `handsdk`（session 后 legacy）→
6. `branch.py`（fork/checkout；merge3 可后置）→ 7. 快照优化 + `api.py` + 迁移工具。

**给程序员的三条纪律**：写任何模块前先写它的契约测试；reducer 的确定性用 property-based
测试守住（随机 patch 序列 × 任意前缀可折叠 × 快照≡全量重放）；除 store.append 外任何地方
出现 SQL 写语句即架构违规。
