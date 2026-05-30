# Loom/Anchor 实时性与功能完整性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 anchor op 冷启动延迟，修复全 HTML 生成问题，实现 annotate overlay 和 inbox 实时刷新。

**Architecture:** 将 `mcp/inproc-agent.cjs`（已有，直接调 Anthropic SDK）集成到 `server.cjs` 替代 `spawnCCProcessor`；annotate op 在客户端拦截写入独立存储；inbox WS handler 补全刷新调用。

**Tech Stack:** Node.js (server.cjs), Vanilla JS (anchor-client.js), `@anthropic-ai/sdk` (bridge/node_modules), Express routes

---

## File Map

| File | 改动 |
|------|------|
| `mcp/server.cjs` | 新增 inproc-agent 初始化 + toolRegistry；修改 `notifyPendingChanged()`；新增 `/annotations` CRUD 路由 |
| `bridge/webview/anchor-client.js` | inbox_updated handler 补全；inbox 详情展开；`_doDispatch` 拦截 annotate；新增 `_handleAnnotateOp` + `_mountAnnotations`；`applyPatches` 后重挂注解 |

---

## Task 1: inproc-agent 集成到 server.cjs

**Files:**
- Modify: `mcp/server.cjs:52` (requires 区域)
- Modify: `mcp/server.cjs:1714-1720` (`notifyPendingChanged`)

- [ ] **Step 1: 在 server.cjs 顶部 require 区域（line 52 之后）插入 SDK 路径常量和 inprocAgent 变量**

在 `const inbox = require('./inbox.cjs');`（line 52）之后，插入：

```js
const ANTHROPIC_SDK_PATH = path.join(BRIDGE_NM, '..', 'node_modules', '@anthropic-ai', 'sdk');
let inprocAgent = null;
```

- [ ] **Step 2: 在 `notifyPendingChanged` 函数之前（line ~1710）插入 `initInprocAgent()` 函数**

在 `function clearPendingFallback()` 之后、`function notifyPendingChanged()` 之前，插入：

```js
function initInprocAgent() {
  if (inprocAgent) return inprocAgent;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return null;
  let Anthropic;
  try {
    const sdk = require(ANTHROPIC_SDK_PATH);
    Anthropic = sdk.default || sdk;
  } catch (e) {
    log('[inproc] SDK load failed: ' + e.message);
    return null;
  }
  const inprocMod = require('./inproc-agent.cjs');
  const model = process.env.ANCHOR_INPROC_MODEL || 'claude-haiku-4-5-20251001';
  const toolRegistry = {
    anchor_get_pending_op: async (input, ctx) => {
      if (ctx.opConsumed) return JSON.stringify({ pending: false });
      ctx.opConsumed = true;
      const op = ctx.opPayload;
      const subtree = op?.render_state?.relevant_subtree || null;
      const opKind = op?.intent?.op || '';
      const needsFull = ['restructure', 'branch', 'expand'].includes(opKind) || !subtree;
      return JSON.stringify({
        pending: true, op,
        relevant_subtree: subtree || undefined,
        current_html: needsFull ? currentHtml : undefined,
      });
    },
    anchor_get_html: async () => currentHtml,
    anchor_emit_event: async (input, ctx) => {
      const { type, payload } = input;
      broadcastAgentEvent({ type, target_anchor: ctx.target, ...(payload || {}) });
      if (type === 'complete') ctx.completed = true;
      return 'ok';
    },
    anchor_patch: async (input, ctx) => {
      const { patches } = input;
      if (!Array.isArray(patches) || patches.length === 0) return 'no patches';
      broadcastPatches(patches);
      ctx.completed = true;
      return 'patched ' + patches.length + ' node(s)';
    },
  };
  try {
    inprocAgent = inprocMod.create({
      Anthropic, apiKey, model, toolRegistry,
      log: (msg) => log('[inproc] ' + msg),
      autoExecLog: (evt) => addSpawnEvent({
        status: evt.event === 'inproc_complete' ? 'done' : 'start',
        msg: `inproc op=${evt.opKind||''} target=${evt.target||''}`,
      }),
      concurrency: parseInt(process.env.ANCHOR_INPROC_CONCURRENCY || '3'),
    });
    log('[inproc] agent initialized model=' + model);
    return inprocAgent;
  } catch (e) {
    log('[inproc] init failed: ' + e.message);
    return null;
  }
}
```

- [ ] **Step 3: 修改 `notifyPendingChanged()` 函数（line 1714-1720），当 inproc 可用时路由到 inproc 而非 spawn**

将：
```js
function notifyPendingChanged() {
  // When ops are buffered and no idle processor is available, spawn a new CC processor.
  const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;
  if (pendingOps.length > 0 && idleCount === 0) {
    setTimeout(spawnCCProcessor, 150);
  }
}
```

改为：
```js
function notifyPendingChanged() {
  if (pendingOps.length === 0) return;
  const idleCount = Array.from(processorPool.values()).filter(e => e.ws && e.ws.readyState === 1).length;
  if (idleCount > 0) return;
  const agent = initInprocAgent();
  if (agent) {
    while (pendingOps.length > 0) agent.enqueue(pendingOps.shift());
  } else {
    setTimeout(spawnCCProcessor, 150);
  }
}
```

- [ ] **Step 4: 手动验证**

重启 Anchor service (`scripts\start-anchor.bat`)，在浏览器打开 http://localhost:3000，点击一个 anchor block 的 refine handle，在 server stderr 中应看到：
```
[inproc] agent initialized model=claude-haiku-4-5-20251001
[inproc] in-process agent: start opId=iop_... op=refine target=...
```
且 patch 在约 5s 内到达（而非之前的 15s+）。

若看到 `[inproc] SDK load failed` 或无 `[inproc]` 日志，说明 `ANTHROPIC_API_KEY` 未设置，系统会 fallback 到 spawnCCProcessor（正常）。

- [ ] **Step 5: Commit**

```bash
git add mcp/server.cjs
git commit -m "feat(server): integrate inproc-agent to eliminate claude -p cold-start latency"
```

---

## Task 2: inbox 实时刷新 + 消息详情

**Files:**
- Modify: `bridge/webview/anchor-client.js:830-832` (inbox_updated handler)
- Modify: `bridge/webview/anchor-client.js:3455-3465` (item click handler)

- [ ] **Step 1: 修复 inbox_updated handler（line 830-832）**

将：
```js
      case 'inbox_updated':
        if (window.InboxPanel) InboxPanel.applyServerCounts(msg.counts);
        break;
```

改为：
```js
      case 'inbox_updated':
        if (window.InboxPanel) {
          InboxPanel.applyServerCounts(msg.counts);
          InboxPanel._fetchItems();
        }
        break;
```

- [ ] **Step 2: 修改 inbox item 点击处理器（line 3455-3465），增加 inline 详情展开**

将：
```js
    // item click → mark read + open domain
    this._list.addEventListener('click', (e) => {
      const item = e.target.closest('.inbox-item');
      if (!item) return;
      const id = item.dataset.id;
      const domain = item.dataset.domain;
      fetch('/inbox/' + id + '/read', { method: 'POST' }).catch(() => {});
      const found = this._items.find(it => it.id === id);
      if (found) { found.read = true; this._renderList(); }
      if (domain) _openDomain(domain);
    });
```

改为：
```js
    // item click → mark read + toggle inline detail
    this._list.addEventListener('click', (e) => {
      if (e.target.closest('.inbox-item-detail')) return; // clicks inside detail don't re-toggle
      const item = e.target.closest('.inbox-item');
      if (!item) return;
      const id = item.dataset.id;
      const domain = item.dataset.domain;
      const wasExpanded = item.classList.contains('inbox-item--expanded');
      fetch('/inbox/' + id + '/read', { method: 'POST' }).catch(() => {});
      const found = this._items.find(it => it.id === id);
      if (found) { found.read = true; }
      this._renderList();
      if (!wasExpanded) {
        const freshItem = this._list.querySelector('[data-id="' + CSS.escape(id) + '"]');
        if (freshItem && found) {
          freshItem.classList.add('inbox-item--expanded');
          const detail = document.createElement('div');
          detail.className = 'inbox-item-detail';
          const ts = found.timestamp ? new Date(found.timestamp).toLocaleString('zh-CN') : '';
          const payloadStr = found.payload ? JSON.stringify(found.payload, null, 2) : '(no payload)';
          detail.innerHTML =
            `<div class="inbox-detail-meta">${_escHtml(found.source || '')} · ${_escHtml(ts)}</div>` +
            `<pre class="inbox-detail-payload">${_escHtml(payloadStr)}</pre>` +
            (domain ? `<button class="btn btn--sm btn--ghost inbox-detail-nav" data-domain="${_escHtml(domain)}">查看详情页 →</button>` : '');
          detail.querySelector('.inbox-detail-nav')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            _openDomain(domain);
          });
          freshItem.appendChild(detail);
        }
      }
    });
```

- [ ] **Step 3: 在 styles.css 中为 inbox 详情添加最小样式（不改变已有视觉）**

在 `styles.css` 末尾追加（不修改任何现有规则）：

```css
/* ── Inbox item detail expansion ── */
.inbox-item--expanded { background: var(--paper-2, #f8f8f8); }
.inbox-item-detail { padding: 8px 12px; border-top: 1px solid var(--border, #e0e0e0); }
.inbox-detail-meta { font-size: 11px; color: var(--fg-3, #888); margin-bottom: 6px; }
.inbox-detail-payload { font-size: 11px; font-family: var(--ff-mono, monospace); white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto; margin: 0 0 8px; }
```

- [ ] **Step 4: 手动验证**

重载页面，触发一条新消息（用 `curl -X POST http://localhost:3000/push/manual -H "Content-Type: application/json" -d '{"domain":"market","title":"测试消息","summary":"这是一条测试"}'`），检查：
1. inbox 角标立即更新
2. 打开 inbox 面板，列表中出现新消息（无需关闭再打开）
3. 点击消息条目，展开详情（payload JSON + 时间戳 + 跳转按钮）
4. 再次点击同一条目，详情收起

- [ ] **Step 5: Commit**

```bash
git add bridge/webview/anchor-client.js bridge/webview/styles.css
git commit -m "feat(inbox): real-time list refresh on inbox_updated + inline detail expansion"
```

---

## Task 3: annotate 客户端 overlay

**Files:**
- Modify: `mcp/server.cjs:540` (annotations 路由)
- Modify: `bridge/webview/anchor-client.js:1707` (新增 _handleAnnotateOp + _mountAnnotations)
- Modify: `bridge/webview/anchor-client.js:3111` (_doDispatch 拦截)
- Modify: `bridge/webview/anchor-client.js:950` (applyPatches 后重挂)

- [ ] **Step 1: 在 server.cjs 的 inbox 路由之后（line 540 之后）添加 annotations 路由**

在 `app.post('/inbox/:id/read', ...)` 路由结束后（`});` 的下一行），插入：

```js
// ── Annotations store ─────────────────────────────────────────────
const ANNOTATIONS_FILE = path.join(WORKSPACE_DIR, 'annotations.json');

function _loadAnnotations() {
  try { return JSON.parse(fs.readFileSync(ANNOTATIONS_FILE, 'utf8')); } catch { return []; }
}
function _saveAnnotations(items) {
  try { fs.writeFileSync(ANNOTATIONS_FILE, JSON.stringify(items, null, 2), 'utf8'); } catch {}
}

app.get('/annotations', (req, res) => {
  const { anchor_id } = req.query;
  let items = _loadAnnotations();
  if (anchor_id) items = items.filter(a => a.anchor_id === anchor_id);
  res.json({ items });
});

app.post('/annotations', (req, res) => {
  const { anchor_id, text } = req.body || {};
  if (!anchor_id || !text) return res.status(400).json({ error: 'anchor_id and text required' });
  const items = _loadAnnotations();
  const ann = {
    id: 'ann_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6),
    anchor_id, text,
    ts: new Date().toISOString(),
  };
  items.push(ann);
  _saveAnnotations(items);
  res.json(ann);
});

app.delete('/annotations/:id', (req, res) => {
  let items = _loadAnnotations();
  items = items.filter(a => a.id !== req.params.id);
  _saveAnnotations(items);
  res.json({ ok: true });
});
```

- [ ] **Step 2: 在 anchor-client.js 的 `sendEnvelope` 方法之后（line 1707）插入 `_handleAnnotateOp` 和 `_mountAnnotations`**

在 `sendEnvelope` 的 `},`（line 1707）之后，插入：

```js
  _handleAnnotateOp(anchorId, text) {
    fetch('/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchor_id: anchorId, text }),
    })
    .then(r => r.json())
    .then(() => this._mountAnnotations(anchorId))
    .catch(() => {});
  },

  _mountAnnotations(anchorId) {
    fetch('/annotations?anchor_id=' + encodeURIComponent(anchorId))
      .then(r => r.json())
      .then(data => {
        const sel = '[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]';
        const el = this.container.querySelector(sel);
        if (!el) return;
        const existing = el.querySelector('.anc-annotations');
        if (existing) existing.remove();
        const annotations = data.items || [];
        if (annotations.length === 0) return;
        const wrap = document.createElement('div');
        wrap.className = 'anc-annotations';
        annotations.forEach(ann => {
          const pill = document.createElement('span');
          pill.className = 'anc-annotation-pill';
          pill.innerHTML = _escHtml(ann.text) +
            '<span class="remove-anno" data-ann-id="' + _escHtml(ann.id) + '" title="删除注解">×</span>';
          pill.querySelector('.remove-anno').addEventListener('click', (e) => {
            e.stopPropagation();
            fetch('/annotations/' + ann.id, { method: 'DELETE' })
              .then(() => this._mountAnnotations(anchorId));
          });
          wrap.appendChild(pill);
        });
        el.appendChild(wrap);
      })
      .catch(() => {});
  },
```

- [ ] **Step 3: 在 `_doDispatch`（line 3111）中拦截 annotate op**

将：
```js
  _doDispatch(op, targetKind, targetRef, instruction, meta) {
    const envelope = this.anchor.buildEnvelope({
      op, target_kind: targetKind, target_ref: targetRef, instruction, selection: meta
    });
    this.anchor.sendEnvelope(envelope);
    this.hide();
  },
```

改为：
```js
  _doDispatch(op, targetKind, targetRef, instruction, meta) {
    if (op === 'annotate') {
      this.anchor._handleAnnotateOp(targetRef, instruction);
      this.hide();
      return;
    }
    const envelope = this.anchor.buildEnvelope({
      op, target_kind: targetKind, target_ref: targetRef, instruction, selection: meta
    });
    this.anchor.sendEnvelope(envelope);
    this.hide();
  },
```

- [ ] **Step 4: 在 `applyPatches` 中重挂注解（line 950-956 之后）**

在 `applyPatches` 方法中，找到：
```js
    patches.forEach(p => {
      const newEl = this.container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (newEl) {
        this.injectHandlesIn(newEl);
        this.injectCollapseIn(newEl);
      }
    });
```

改为：
```js
    patches.forEach(p => {
      const newEl = this.container.querySelector('[data-anc="' + p.anchor_id.replace(/"/g, '\\"') + '"]');
      if (newEl) {
        this.injectHandlesIn(newEl);
        this.injectCollapseIn(newEl);
        this._mountAnnotations(p.anchor_id);
      }
    });
```

- [ ] **Step 5: 手动验证**

重载页面，在任意 anchor block 上点击 Annotate 按钮，输入文字后提交：
1. 注解 pill 出现在元素底部
2. 点 `×` 删除注解，pill 消失
3. 对同一 block 做 refine/expand，patch 回来后注解 pill 自动重新出现

- [ ] **Step 6: Commit**

```bash
git add mcp/server.cjs bridge/webview/anchor-client.js
git commit -m "feat(annotate): client-side overlay — no LLM, POST to /annotations, remount after patch"
```

---

## Task 4: streaming partial render（依赖 Task 1 完成）

**Files:**
- Modify: `mcp/inproc-agent.cjs:144-178` (messages.create → stream)
- Modify: `bridge/webview/anchor-client.js` (partial_render handler)

> **注意**：streaming 仅对 inproc 路径有效（Task 1 必须先完成）。若 inproc 未启用，此 task 无效。

- [ ] **Step 1: 修改 inproc-agent.cjs 中的 LLM 调用为 streaming**

在 `inproc-agent.cjs` 中找到 `while (turn < MAX_TURNS)` 循环内的 `client.messages.create(...)` 调用（line ~147），替换整个 while 循环体：

```js
    try {
      while (turn < MAX_TURNS) {
        turn++;

        // Accumulate text delta for partial_render during first turn
        let streamedText = '';
        let isFirstTurn = turn === 1;

        const stream = client.messages.stream({
          model,
          max_tokens: MAX_TOKENS,
          system: SYSTEM_PROMPT,
          tools: TOOL_DEFS,
          messages,
        });

        // Emit partial_render deltas so the browser shows a streaming overlay
        if (isFirstTurn) {
          stream.on('text', (delta) => {
            streamedText += delta;
            if (streamedText.trimStart().startsWith('<')) {
              const handler = toolRegistry.anchor_emit_event;
              if (handler) {
                handler({ type: 'partial_render', payload: {
                  target_anchor: ctx.target,
                  html_fragment: streamedText,
                }}, ctx).catch(() => {});
              }
            }
          });
        }

        const resp = await stream.finalMessage();
        stopReason = resp.stop_reason;

        const toolUses = (resp.content || []).filter(b => b.type === 'tool_use');
        if (toolUses.length === 0) break;

        const toolResults = [];
        for (const tu of toolUses) {
          const handler = toolRegistry[tu.name];
          if (!handler) {
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Unknown tool: ' + tu.name, is_error: true });
            continue;
          }
          try {
            const out = await handler(tu.input || {}, ctx);
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: String(out == null ? '' : out) });
          } catch (e) {
            toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Tool error: ' + (e && e.message || e), is_error: true });
          }
        }

        messages.push({ role: 'assistant', content: resp.content });
        messages.push({ role: 'user', content: toolResults });

        if (resp.stop_reason !== 'tool_use') break;
        if (ctx.completed) break;
      }
    }
```

- [ ] **Step 2: 在 anchor-client.js 中添加 `partial_render` WS handler**

在 `handleMessage(msg)` 的 `switch (msg.type)` 中，在 `case 'patch':` 之前插入：

```js
      case 'agent_event': {
        const evt = msg.event;
        if (evt && evt.payload && evt.payload.type === 'partial_render') {
          const { target_anchor, html_fragment } = evt.payload;
          if (target_anchor && html_fragment) {
            this._showStreamingOverlay(target_anchor, html_fragment);
          }
        }
        this._handleAgentEvent(evt);
        break;
      }
```

> 注意：检查是否已有 `case 'agent_event':` 处理器。若已有，将 partial_render 检测加到其中，不要重复 case。

在 anchor 对象中（紧接 `_mountAnnotations` 之后）插入：

```js
  _showStreamingOverlay(anchorId, html) {
    const sel = '[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]';
    const el = this.container.querySelector(sel);
    if (!el) return;
    let overlay = el._streamOverlay;
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'anc-stream-overlay';
      overlay.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(255,255,255,0.85);z-index:10;pointer-events:none;overflow:hidden;border-radius:inherit;padding:inherit;';
      el.style.position = 'relative';
      el.appendChild(overlay);
      el._streamOverlay = overlay;
    }
    overlay.innerHTML = html;
  },

  _clearStreamingOverlay(anchorId) {
    const sel = '[data-anc="' + anchorId.replace(/"/g, '\\"') + '"]';
    const el = this.container.querySelector(sel);
    if (el && el._streamOverlay) {
      el._streamOverlay.remove();
      el._streamOverlay = null;
    }
  },
```

- [ ] **Step 3: 在 `applyPatches` 结束时清除 streaming overlay**

在 Task 3 Step 4 修改的 `patches.forEach` 循环中，在 `_mountAnnotations` 之后加：

```js
        this._clearStreamingOverlay(p.anchor_id);
```

- [ ] **Step 4: 手动验证**

触发一个 refine op，在 LLM 生成过程中，被修改的 anchor block 上应看到半透明白色 overlay 显示正在生成的 HTML 片段（逐字出现）；生成完成后 overlay 消失，正式内容替换。

- [ ] **Step 5: Commit**

```bash
git add mcp/inproc-agent.cjs bridge/webview/anchor-client.js
git commit -m "feat(streaming): partial_render overlay during LLM generation in inproc path"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: G1(inproc)→Task1, G4(inbox)→Task2, G3(annotate)→Task3, G2(streaming)→Task4
- [x] **Placeholder scan**: 所有步骤含完整代码，无 TBD
- [x] **Type consistency**: `_mountAnnotations(anchorId)` 在 Task3/Step2 定义，Task3/Step4 和 Task4/Step3 调用，名称一致；`_showStreamingOverlay` / `_clearStreamingOverlay` Task4 定义并使用
- [x] **Task 4 dependency**: 明确标注依赖 Task 1
- [x] **Constraint C1**: 未修改现有颜色/主题变量，仅追加新 CSS 规则和内联样式
- [x] **ANNOTATIONS_FILE**: 使用已有 `WORKSPACE_DIR` 常量，路径格式与 inbox.json 一致
