# Loom/Anchor 实时性与功能完整性修复方案

**Debate date:** 2026-05-26  
**Status:** CONVERGED (4 rounds, all layers committed)

---

## Layer 1 — Problem Definition

### 利益相关方
使用 Anchor webview 进行内容迭代的用户。每次点击 anchor block 操作按钮（refine/expand/edit/annotate 等）都需要等待结果；inbox 面板的消息提醒不可靠。

### 问题 1：op 处理延迟过高

**当前路径**：`browser op → pendingOps[] → spawnCCProcessor() → claude -p 子进程`

子进程需要：启动 Node.js 进程 + 加载 MCP shim + 建立 WebSocket 连接 + 完成 MCP 握手。仅冷启动开销约 5–15 秒，之后才进入 LLM 推理（Sonnet 4.6 约 3–8 秒）。

**已有但未使用的解法**：`mcp/inproc-agent.cjs` 已实现完整的工具调用循环（直接调 Anthropic SDK，无子进程），但 `server.cjs` 中无任何 `require('./inproc-agent.cjs')` 引用。

**使该断言失效的条件**：若 `processorPool` 中始终有 idle WebSocket 连接，则无冷启动，延迟主要来自 LLM 推理本身（inproc-agent 对 LLM 推理延迟无影响）。

### 问题 2：agent 生成完整 HTML 而非局部 patch

**当前 prompt**：`buildProcessorPrompt()` 正确要求只生成目标 anchor 的 outerHTML，但 `claude -p` 以交互模式运行，CC 会话初始化逻辑可能忽视 `-p` prompt 中的约束。

`inproc-agent.cjs` 的 TOOL_DEFS 只暴露 `anchor_patch`，不暴露 `anchor_render`，从工具层面物理隔离全 HTML 生成问题。

**使该断言失效的条件**：若 `relevant_subtree.target_html` 未被正确填充（server 传了 `currentHtml` fallback），则根本原因在数据层而非 prompt 层。

### 问题 3：annotate 功能缺失

UI handle 按钮已有，op 正确路由到 server，但 `anchor-client.js` 零实现：无 annotation 存储 API、无 overlay 渲染代码、无 patch 后重挂载逻辑。`anc-annotation-pill` CSS 类名在 CLAUDE.md 中有定义，但 `styles.css` 未实现对应样式。

### 问题 4：inbox 面板列表不自动刷新

`anchor-client.js` 约 830 行：`case 'inbox_updated':` 只调用 `InboxPanel.applyServerCounts()`（更新角标），未调用 `InboxPanel._fetchItems()`（刷新列表）。新消息角标更新，但打开面板看不到新消息，须手动关闭再打开。

### 已锁定约束

- **C1**：不修改 CSS/视觉层（颜色、主题、样式）
- **C2**：兼容现有 anchor op 路由协议（envelope → pendingOps → patch）
- **C3**：annotate 架构：客户端 overlay（不走 LLM），在 Layer 2 中锁定

---

## Layer 2 — Ideal State

- **I1**：用户点击 anchor block op 后，≤ 3s 看到首字符（需 streaming）；≤ 10s 完成完整 patch
- **I2**：LLM 只生成目标 anchor 的 outerHTML；工具层面物理不可能调用 `anchor_render`（全页替换）
- **I3**：annotate = 客户端 overlay。注解不修改目标 anchor DOM 结构；以 `anc-annotation-pill` 形式附着在元素旁；存储于独立的 `annotations.json`（`data-anc` 关联）；`anchor_patch` 后自动重挂载
- **I4**：`inbox_updated` 同时触发 badge + 列表刷新；用户可在 inbox 面板内阅读消息详情（payload 全文）

---

## Layer 3 — Gap Analysis

| Gap | 影响的理想态 | 根本原因 |
|-----|------------|---------|
| **G1**：`inproc-agent.cjs` 未集成到 `server.cjs` | I1, I2 | `server.cjs` 无 require；需确认 `ANTHROPIC_API_KEY` 在 server 进程中可用 |
| **G2**：无 streaming 支持 | I1 | `inproc-agent.cjs` 使用 `client.messages.create()`（非流式），全量等待后才 patch |
| **G3**：annotate 从零实现 | I3 | server 无 `/annotations` API；client 无拦截逻辑、无 overlay 渲染、无 patch 后重挂载 |
| **G4**：inbox 列表不刷新，无详情视图 | I4 | `inbox_updated` handler 缺 `_fetchItems()` 调用；inbox item 点击只跳转域名页 |

---

## Layer 4 — Strategy

### Phase 1：集成 inproc-agent，消除冷启动

**文件**：`mcp/server.cjs`

**做什么**：在 `spawnCCProcessor()` 调用路径之前，判断 `ANTHROPIC_API_KEY`：
- 若存在 → `require('./inproc-agent.cjs')` 初始化 `inprocAgent`（server 启动时懒加载），调用 `inprocAgent.enqueue(op)`，跳过 spawn
- 若不存在 → fallback 到现有 `spawnCCProcessor()`（完全后向兼容）

`inproc-agent.cjs` 的 `concurrency` 参数控制并发 LLM 调用数（建议设为 3）。

**KPI**：冷启动延迟 5–15s → <1s  
**风险**：server 进程内存增加（每个并发 op 约 4096 token 上下文）

---

### Phase 2：streaming，首 token 可见

**文件**：`mcp/inproc-agent.cjs`

**做什么**：
1. `client.messages.create()` 改为 `client.messages.stream()`
2. stream 期间，每收到 text delta，通过 WS 广播 `partial_render` 事件（已有 event type）：`{type: 'partial_render', payload: {target_anchor: id, html_fragment: accumulatedHtml}}`
3. stream 完成后，正式调用 `anchor_patch` 替换 DOM

**文件**：`bridge/webview/anchor-client.js`

4. 新增 `partial_render` 事件处理：在目标 anchor block 上方渲染 streaming overlay div（`pointer-events: none`，接受 malformed HTML）
5. 收到正式 `patch` 广播后，移除 overlay

**KPI**：用户 ≤ 3s 看到首字符，≤ 10s 完成 patch  
**风险**：streaming 中间 HTML 格式不完整；overlay 用 `innerHTML` 渲染并做容错处理

---

### Phase 3：annotate 客户端 overlay

**文件**：`mcp/server.cjs`（新增路由）

```
GET  /annotations?anchor_id=X  → 返回该 anchor 的所有注解
POST /annotations               → {anchor_id, text, ts} → 写入 logs/workspace/annotations.json
```

**文件**：`bridge/webview/anchor-client.js`

1. 拦截 `annotate` op：**不发送到 LLM**，直接 POST `/annotations`
2. `_mountAnnotations(anchorId)`：查询 `/annotations?anchor_id=X`，在目标元素下方插入 `<div class="anc-annotation-pill">` 节点
3. `anchor_patch` 广播后，对每个被 patch 的 `anchor_id` 重新调用 `_mountAnnotations()`

**注解数据格式**：
```json
{"id": "ann_xxx", "anchor_id": "market.card.yyy", "text": "注解内容", "ts": "ISO8601"}
```
`anchor_id` 存储完整 anchor path（如 `market.card.xxx`），不存 DOM 选择器。

**KPI**：annotate 注解可创建、可查看、patch 后不丢失  
**风险**：`anc-annotation-pill` CSS 未在 `styles.css` 中实现，需同步添加样式定义

---

### Phase 4：inbox 列表实时刷新 + 消息详情

**文件**：`bridge/webview/anchor-client.js`

1. 约 830 行 `case 'inbox_updated':` 追加：
   ```js
   if (window.InboxPanel) InboxPanel._fetchItems();
   ```
2. inbox item 点击事件：在 `#inbox-list` 内 inline 展开详情区域（显示 payload 全文 + 时间戳 + source），提供"跳转域名页"按钮

**KPI**：新消息到达时列表秒刷新；用户可在 inbox 面板内读到消息全文

---

## 实施顺序与优先级

| 优先级 | Phase | 复杂度 | 独立性 |
|--------|-------|--------|--------|
| P0 | Phase 1：inproc-agent 集成 | 中 | 独立 |
| P1 | Phase 4：inbox 修复 | 低 | 独立 |
| P2 | Phase 3：annotate overlay | 中 | 独立 |
| P3 | Phase 2：streaming | 高 | 依赖 Phase 1 |

Phase 1 和 Phase 4 可并行实施。Phase 2 必须在 Phase 1 之后。

---

## 未纳入本方案的范围

- CSS/视觉层任何修改（约束 C1）
- inbox 连接器数据质量问题（另行处理）
- annotate 的 AI 辅助改写模式（留待后续需求）
