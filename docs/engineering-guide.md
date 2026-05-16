# Anchor → Agentic Media · 工程实施详尽指南

> 配套文档：`C:\Users\qi\.claude\plans\agent-hook-agent-context-memory-skills-enchanted-twilight.md`（设计文档）
> 本文档：**逐 Phase、逐子任务**的实施手册，包含输入/输出契约、函数签名、伪代码骨架、测试用例、常见坑。

---

## 通用约定

- 现有代码基线：`D:\ai-native chrome`
- 单一 server 入口：`mcp/server.cjs`
- Webview 文件：`bridge/webview/{index.html, anchor-client.js, styles.css}`
- 所有路径以仓库根为基准
- 新代码继续遵守"零运行时依赖、vanilla JS、复用 frost/jelly 设计 token"
- 命名约定：
  - server 端函数：`camelCase`，文件用 `.cjs`
  - 客户端模块：大写命名空间对象（如 `Anchor`、`ContextPanel`、`SelectionToolbar`、`TimelinePanel`）
  - CSS class 前缀：`anc-`
  - 事件 type：`snake_case` 字符串（`agent_event`、`context_changed`、`html`、`op`、`ack`、`error`）

---

# Phase 0 · 基础整理 + 浏览器自启动

**预估**：半天
**前置**：无
**完成判据**：单一 server 文件；Claude Code 启动后浏览器自动打开 localhost:3000；`ANCHOR_NO_AUTO_BROWSER=1` 可禁用

## 0.1 server 收敛：保留 `mcp/server.cjs`，移除 `bridge/server.js`

### 输入
- 现状：`.claude/mcp.json` 指向 `bridge/server.js`，但 `mcp/server.cjs` 才是 CLAUDE.md 中的主路径
- 两个 server 能力差异（已比对）：
  - `mcp/server.cjs` 已有 MCP JSON-RPC + `/html` POST + WS
  - `bridge/server.js` 多了 `/op` POST + `logOp()` 写入 `logs/ops.jsonl`

### 实施步骤
1. **修改 `.claude/mcp.json`**：把 `args` 改为 `["mcp/server.cjs"]`
2. **把 `logOp` 能力迁移到 `mcp/server.cjs`**：
   - 在 WS 收到 `op` 消息时调用 `logOp(op)`
   - `logOp` 实现：追加一行 JSON 到 `logs/ops.jsonl`，含 `timestamp / html_snapshot / op`
   - 注意：这是为了向旧消费者保持兼容；Phase 5 之后此函数被 `recordEvent` 取代但保留
3. **加 `/op` HTTP POST 路由**（兼容性 fallback）：与 WS `op` 同路径处理
4. **删除 `bridge/server.js`**（或重命名为 `bridge/server.js.deprecated`）
5. **冒烟**：Claude Code 重启 → MCP 起来 → `anchor_render` 推送 → webview 显示

### 关键代码骨架（伪代码，server 端）
```js
// mcp/server.cjs 新增
const OPS_LOG = path.join(ROOT, 'logs', 'ops.jsonl');
const LOGS_DIR = path.dirname(OPS_LOG);
if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });

function logOp(op) {
  const line = JSON.stringify({
    timestamp: new Date().toISOString(),
    html_snapshot: currentHtml,
    op
  }) + '\n';
  fs.appendFile(OPS_LOG, line, () => {});  // 非阻塞
}

// WS 消息处理
ws.on('message', (data) => {
  const msg = JSON.parse(data.toString());
  if (msg.type === 'op') {
    pendingOp = msg.op;
    fs.writeFileSync(PENDING_PROMPT, formatOpAsPrompt(msg.op), 'utf8');
    logOp(msg.op);                              // ← 新增
    notifyPendingChanged();
    ws.send(JSON.stringify({ type: 'ack', message: 'Op received' }));
  }
});

// HTTP /op 路由（fallback）
app.post('/op', (req, res) => {
  const op = req.body;
  if (!op || !op.op) return res.status(400).json({ error: 'invalid op' });
  pendingOp = op;
  fs.writeFileSync(PENDING_PROMPT, formatOpAsPrompt(op), 'utf8');
  logOp(op);
  notifyPendingChanged();
  res.json({ ok: true });
});
```

## 0.2 浏览器自启动

### 输入
- server 监听 `localhost:3000` 成功
- 环境变量 `ANCHOR_NO_AUTO_BROWSER` 未设置（或不为 `1`）
- 5 秒内 `webviewClients.size === 0`

### 实施步骤
1. **平台命令路由表**
   - `win32` → `start "" "http://localhost:3000"`（注意 `start` 第一个引号参数是窗口标题）
   - `darwin` → `open http://localhost:3000`
   - 其它 → `xdg-open http://localhost:3000`
2. **在 `httpServer.listen` 回调中注册延迟自启**
3. **延迟 800ms 启动**（给 WS server 完全就绪一点缓冲）
4. **再检查一次 `webviewClients.size`**：若已有 client（用户手动开过）则跳过
5. **`exec` 失败只 log 警告**

### 关键代码骨架
```js
// mcp/server.cjs 末尾、httpServer.listen 内
const { exec } = require('child_process');

function maybeAutoOpenBrowser() {
  if (process.env.ANCHOR_NO_AUTO_BROWSER === '1') {
    log('auto-browser disabled by env var');
    return;
  }
  setTimeout(() => {
    if (webviewClients.size > 0) {
      log('webview already connected, skipping auto-open');
      return;
    }
    const url = `http://localhost:${PORT}`;
    let cmd;
    if (process.platform === 'win32')      cmd = `start "" "${url}"`;
    else if (process.platform === 'darwin') cmd = `open "${url}"`;
    else                                    cmd = `xdg-open "${url}"`;
    exec(cmd, (err) => {
      if (err) log(`auto-open browser failed: ${err.message}`);
      else     log(`opened ${url}`);
    });
  }, 800);
}

httpServer.listen(PORT, () => {
  log(`Webview at http://localhost:${PORT}`);
  maybeAutoOpenBrowser();
});
```

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T0.1 | 重启 Claude Code，未打开浏览器 | 0.8 秒后浏览器自动弹出 localhost:3000 |
| T0.2 | 手动先开浏览器，再重启 | 不重复弹 tab（5 秒窗口检测） |
| T0.3 | 设 `ANCHOR_NO_AUTO_BROWSER=1` 重启 | 不弹浏览器 |
| T0.4 | 在无 GUI 环境（关闭 X server）启动 | log 警告但 server 仍可用 |
| T0.5 | `anchor_render(html)` 调用 | 浏览器中内容立即更新，无需 F5 |

### 常见坑
- **Windows `start` 命令参数**：第一个引号参数是窗口标题，不能省略空字符串
- **WSL 环境**：`process.platform === 'linux'` 但实际是 Windows，`xdg-open` 不存在；MVP 期不特殊处理，依赖 `ANCHOR_NO_AUTO_BROWSER`
- **多次 `httpServer.listen`**：确认只调用一次；MCP server 与 listen 是同一进程

---

# Phase 1 · 上下文配置面板（L2）

**预估**：2-3 天
**前置**：Phase 0 完成
**完成判据**：4 组下拉可用、选择持久化、`pending.md` 含 `context_bundle` 段

## 1.1 后端 manifest 端点（半天）

### 输入
- 用户 home：`C:\Users\qi\.claude\`
- 项目 `.claude/`：`D:\ai-native chrome\.claude\`

### 输出
`GET /context-manifest` → JSON，结构见设计文档 §4.2

### 实施步骤

1. **新增 `/context-manifest` HTTP 路由**（带 5 秒缓存）
2. **`loadMemoryManifest()`**：
   - 扫描 `C:\Users\qi\.claude\memory\*.md`
   - 排除 `MEMORY.md`（索引文件本身）
   - 每个文件读前 2KB 提取 YAML frontmatter
   - 返回 `{id, name, description, type, source_path, size_bytes}` 列表
3. **`loadSkillsManifest()`**：
   - 扫描 `C:\Users\qi\.claude\skills\*\SKILL.md` 和 `D:\ai-native chrome\.claude\skills\*\SKILL.md`
   - 解析 frontmatter
   - 返回 `{id, name, description, source: 'user'|'project'|'plugin', source_path}`
4. **`loadSubagentsManifest()`**：
   - MVP 期硬编码内置 5 个（`Explore`、`general-purpose`、`Plan`、`claude-code-guide`、`statusline-setup`）
   - 扫描 `D:\ai-native chrome\.claude\agents\*.md` 加用户自定义
5. **`loadResourcesManifest()`**：
   - 内置 2 个 MCP resource (`anchor://current-html`, `anchor://pending-op`)
   - 加 `prompts/pinned-resources.json`（不存在则返回空数组）

### 关键函数签名
```js
// mcp/server.cjs

const MANIFEST_CACHE_MS = 5000;
let _manifestCache = null;
let _manifestCacheTime = 0;

function getContextManifest() {
  const now = Date.now();
  if (_manifestCache && now - _manifestCacheTime < MANIFEST_CACHE_MS) {
    return _manifestCache;
  }
  _manifestCache = {
    memory:    loadMemoryManifest(),
    skills:    loadSkillsManifest(),
    subagents: loadSubagentsManifest(),
    resources: loadResourcesManifest()
  };
  _manifestCacheTime = now;
  return _manifestCache;
}

function loadMemoryManifest()    { /* scan C:/Users/qi/.claude/memory */ }
function loadSkillsManifest()    { /* scan user + project skills */ }
function loadSubagentsManifest() { /* hardcoded + scan .claude/agents */ }
function loadResourcesManifest() { /* MCP resources + pinned */ }

function parseFrontmatter(filePath) {
  const head = fs.readFileSync(filePath, 'utf8').slice(0, 2048);
  const m = head.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return null;
  const fm = {};
  for (const line of m[1].split('\n')) {
    const kv = line.match(/^(\w+):\s*(.*)$/);
    if (kv) fm[kv[1]] = kv[2].trim();
  }
  return fm;
}

app.get('/context-manifest', (req, res) => {
  res.json(getContextManifest());
});
```

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T1.1.1 | `curl localhost:3000/context-manifest` | 返回 4 个非空数组 |
| T1.1.2 | 增加一个 `~/.claude/memory/foo.md` | 5 秒后 manifest 包含 `foo` |
| T1.1.3 | memory 文件无 frontmatter | 跳过，不报错 |
| T1.1.4 | 文件无读权限 | 跳过，server 不 crash |

### 常见坑
- **frontmatter 解析**：不要引入 yaml 包；手写按 `key: value` 行解析够用，不支持嵌套
- **路径含空格**：项目根 `D:\ai-native chrome` 路径含空格，所有 `path.join` 必须用，不用字符串拼接
- **大文件**：只读前 2KB，避免误读巨型文件
- **缓存失效时机**：5 秒太短可能反复扫盘；太长用户加文件看不到。MVP 用 5 秒

## 1.2 侧栏 UI 骨架（半天）

### 输入
- `bridge/webview/index.html`（当前结构：header + main）

### 输出
- 左侧 320px 折叠面板，4 组 `<details>`，每组含搜索框 + 占位列表

### 实施步骤

1. **修改 `index.html`**：
   - 把 `<main id="anchor-stage">` 改为 flex 容器
   - 在内部加 `<aside id="anchor-context-panel">`（左）+ `<div id="anchor-content">`（中）
2. **写 4 个 `<details>`**：memory / skills / subagents / resources
3. **每个 `<details>`** 内含：搜索 input + 列表容器（空）
4. **样式**：复用 `--glass`、`--brand`、`--shadow-md`、`--r-md`

### HTML 骨架
```html
<main id="anchor-stage">
  <aside id="anchor-context-panel" class="anc-context-panel">
    <header class="ctx-header">
      <span>Context</span>
      <button class="ctx-collapse">‹</button>
    </header>
    <details open data-group="memory">
      <summary>Memory <span class="ctx-count">0</span></summary>
      <input class="ctx-search" placeholder="search memory...">
      <ul class="ctx-list"></ul>
    </details>
    <details data-group="skills">...</details>
    <details data-group="subagents">...</details>
    <details data-group="resources">...</details>
  </aside>
  <div id="anchor-content"></div>
</main>
```

### CSS（新增到 `styles.css`）
```css
#anchor-stage { display: flex; min-height: calc(100vh - 56px); }
.anc-context-panel {
  width: 320px; flex-shrink: 0;
  background: var(--glass); backdrop-filter: blur(20px);
  border-right: 1px solid var(--glass-border);
  padding: 16px; overflow-y: auto;
  transition: width 0.3s var(--ease-smooth);
}
.anc-context-panel.collapsed { width: 48px; padding: 16px 8px; }
.anc-context-panel.collapsed details, .anc-context-panel.collapsed .ctx-header span { display: none; }
.ctx-header { display: flex; justify-content: space-between; margin-bottom: 12px; font-weight: 650; }
.ctx-list { list-style: none; padding: 0; margin: 8px 0; max-height: 240px; overflow-y: auto; }
.ctx-list li { padding: 6px 8px; display: flex; gap: 8px; cursor: pointer; border-radius: var(--r-sm); }
.ctx-list li:hover { background: var(--glass-strong); }
.ctx-list li input[type=checkbox] { flex-shrink: 0; }
.ctx-search {
  width: 100%; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: var(--r-sm); background: var(--glass-strong); font-size: 0.85rem;
}
.ctx-count { font-size: 0.8rem; color: var(--text-soft); margin-left: 8px; }
.ctx-count.has-selection { color: var(--brand); font-weight: 700; }
```

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T1.2.1 | 打开页面 | 左侧出现 4 个折叠组 |
| T1.2.2 | 点 `‹` 按钮 | 面板收缩到 48px，组隐藏 |
| T1.2.3 | 再点 `›`（实现切换） | 展开 |
| T1.2.4 | 主内容区不再撑满 | 主内容宽度减去 320 |

## 1.3 数据加载与渲染（半天）

### 输入
- 1.1 已经能返回 manifest
- 1.2 已经渲染骨架

### 输出
- `ContextPanel` 模块加载数据、渲染列表、处理选择、持久化

### 实施步骤

1. **新建 `ContextPanel` 模块**（在 `anchor-client.js` 内，与 `Anchor` 同级）
2. **`init()` 时 fetch manifest，渲染**
3. **每条 item**：`<li>` 含 `<input type="checkbox">` + `<span class="ctx-name">` + `<span class="ctx-meta">`
4. **搜索过滤**：oninput debounce 100ms，按 name + description 模糊匹配
5. **选择状态**：`bundle = {memory_ids, skill_ids, subagent_ids, resource_ids, scope_hint: "standard"}`
6. **持久化**：`localStorage.setItem("anchor.contextBundle", JSON.stringify(bundle))`
7. **通知 server**（仅用于日志）：WS `{type: "context_changed", bundle}`

### 模块骨架
```js
const ContextPanel = {
  panel: null,
  manifest: null,
  bundle: { memory_ids: [], skill_ids: [], subagent_ids: [], resource_ids: [], scope_hint: 'standard' },

  init() {
    this.panel = document.getElementById('anchor-context-panel');
    this.loadBundle();              // 从 localStorage 读
    this.fetchManifest()
      .then(() => this.render())
      .catch(err => console.error('[context] manifest load failed:', err));
    this.bindCollapse();
  },

  loadBundle() {
    try {
      const raw = localStorage.getItem('anchor.contextBundle');
      if (raw) this.bundle = JSON.parse(raw);
    } catch {}
  },

  saveBundle() {
    localStorage.setItem('anchor.contextBundle', JSON.stringify(this.bundle));
    if (Anchor.ws?.readyState === WebSocket.OPEN) {
      Anchor.ws.send(JSON.stringify({ type: 'context_changed', bundle: this.bundle }));
    }
  },

  async fetchManifest() {
    const r = await fetch('/context-manifest');
    this.manifest = await r.json();
  },

  render() {
    for (const group of ['memory', 'skills', 'subagents', 'resources']) {
      this.renderGroup(group);
    }
  },

  renderGroup(group) {
    const det = this.panel.querySelector(`details[data-group="${group}"]`);
    const list = det.querySelector('.ctx-list');
    const search = det.querySelector('.ctx-search');
    const items = this.manifest[group];
    const bundleKey = this.bundleKeyFor(group);   // memory → memory_ids

    const renderList = (filter = '') => {
      list.innerHTML = '';
      const q = filter.toLowerCase();
      for (const item of items) {
        if (q && !`${item.name} ${item.description||''}`.toLowerCase().includes(q)) continue;
        const li = document.createElement('li');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = this.bundle[bundleKey].includes(item.id);
        cb.addEventListener('change', () => this.toggle(bundleKey, item.id, cb.checked));
        const name = document.createElement('span');
        name.className = 'ctx-name';
        name.textContent = item.name;
        name.title = item.description || '';
        li.appendChild(cb); li.appendChild(name);
        list.appendChild(li);
      }
      this.updateCount(det, group);
    };
    search.addEventListener('input', debounce(() => renderList(search.value), 100));
    renderList();
  },

  bundleKeyFor(group) {
    return { memory:'memory_ids', skills:'skill_ids', subagents:'subagent_ids', resources:'resource_ids' }[group];
  },

  toggle(key, id, on) {
    const arr = this.bundle[key];
    const i = arr.indexOf(id);
    if (on && i < 0) arr.push(id);
    if (!on && i >= 0) arr.splice(i, 1);
    this.saveBundle();
  },

  updateCount(det, group) {
    const cnt = this.bundle[this.bundleKeyFor(group)].length;
    const span = det.querySelector('.ctx-count');
    span.textContent = cnt;
    span.classList.toggle('has-selection', cnt > 0);
  },

  getBundle() { return JSON.parse(JSON.stringify(this.bundle)); },

  bindCollapse() {
    this.panel.querySelector('.ctx-collapse').addEventListener('click', () => {
      this.panel.classList.toggle('collapsed');
    });
  }
};

function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

document.addEventListener('DOMContentLoaded', () => { Anchor.init(); ContextPanel.init(); });
```

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T1.3.1 | 加载页面 | 4 组列表显示来自 manifest 的数据 |
| T1.3.2 | 勾选 1 个 memory | 计数 +1，localStorage 已写入 |
| T1.3.3 | 刷新页面 | 之前的选择被恢复 |
| T1.3.4 | 搜索 "user" | 列表过滤为匹配项 |
| T1.3.5 | server 端 log | 收到 `context_changed` 消息 |

### 常见坑
- **fetch CORS**：同域 `localhost:3000`，无 CORS 问题
- **特殊字符**：name 可能含 HTML 特殊字符，必须用 `textContent` 而非 `innerHTML`
- **首次加载**：`renderGroup` 必须在 manifest fetch 完成之后

## 1.4 Per-op 临时覆盖（半天）

### 输入
- `Anchor.togglePopup` 现有逻辑（`anchor-client.js:142`）

### 输出
- 弹窗顶部多一个 Context 芯片，可临时覆盖 default bundle

### 实施步骤
1. **修改 `togglePopup`**：在 `header` 之后、handles 按钮之前插入 Context 行
2. **Context 行结构**：`<div class="op-ctx-row">Context: <button class="op-ctx-chip">default ▾</button></div>`
3. **点击芯片**：在 popup 内展开 4 组迷你选择器（复用 `ContextPanel.renderGroup` 逻辑，作用于临时 bundle）
4. **`sendOp` 修改**：检测 popup 上有临时 bundle 时优先使用

### 关键变更
```js
// Anchor.togglePopup 增加
let overrideBundle = null;  // 临时 bundle，null 表示用 default

const ctxRow = document.createElement('div');
ctxRow.className = 'op-ctx-row';
const chip = document.createElement('button');
chip.className = 'op-ctx-chip';
chip.textContent = 'Context: default ▾';
chip.addEventListener('click', (e) => {
  e.stopPropagation();
  if (!overrideBundle) overrideBundle = ContextPanel.getBundle();
  // 展开 mini-context 选择器（与 ContextPanel 类似但简化版）
  this.showCtxOverride(popup, overrideBundle, () => {
    chip.textContent = `Context: custom (${countSelections(overrideBundle)} items) ▾`;
  });
});
ctxRow.appendChild(chip);
popup.appendChild(ctxRow);

// sendOp 修改：替换 ContextPanel.getBundle() 为 (overrideBundle || ContextPanel.getBundle())
```

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T1.4.1 | 点 + handle，看到 popup 顶部有 Context 芯片 | 显示 "default" |
| T1.4.2 | 点芯片，展开 mini-context，勾选额外 skill | 芯片显示 "custom (N)" |
| T1.4.3 | 提交 op | `pending.md` 中 context_bundle 反映 override |
| T1.4.4 | 关闭 popup 再开一个新的 | 新 popup 又是 default（override 是一次性的） |

## 1.5 联调（半天）

整合 1.1-1.4，跑端到端：
1. 启动服务 → 浏览器自启 → ContextPanel 加载 4 组
2. 勾选 2 memory + 1 skill
3. 渲染一个 Anchor 页面 → 点 + → context 显示 default → 提交 refine
4. 检查 `prompts/pending.md`：含 `Context Bundle` 段，列出选中的 memory/skill ID 和 source_path

---

# Phase 2 · Agent Interface 类型化（L3）

**预估**：1-2 天
**前置**：Phase 1 完成
**完成判据**：所有 op 走 IntentEnvelope；invalid envelope 被拒；`pending.md` 升级

## 2.1 Schema 文件（半天）

### 实施步骤
1. **创建 `mcp/schemas/intent-envelope.json`**：完整 JSON Schema（设计文档 §4.3 已给出草案）
2. **server 启动时一次性加载**：`const ENVELOPE_SCHEMA = JSON.parse(fs.readFileSync(...))`

### 测试用例
| # | 操作 | 期望 |
|---|---|---|
| T2.1.1 | server 启动 | log "schema loaded" |
| T2.1.2 | schema 文件错误（手动破坏） | server 启动失败，明确错误 |

## 2.2 Server 端校验器（半天）

### 输入
- WS 收到 `{type:"op", envelope}` 消息

### 输出
- 通过 → 继续处理；不通过 → 回 `{type:"error", code, message, details}`

### 实施步骤
1. **手写最小校验器** `validateEnvelope(env, schema)`：
   - 必含字段（schema.required）
   - 字段类型（string / integer / object / array）
   - 枚举值（schema.properties.X.enum）
   - 嵌套 object 递归验证
2. **错误结构**：`{path: "intent.op", error: "not in enum", expected: [...]}`
3. **WS handler 集成**：先 validate，失败立即回 error 并 `recordEvent("system.error", ...)`（Phase 5 接入）

### 校验器签名
```js
function validateEnvelope(envelope, schema = ENVELOPE_SCHEMA) {
  const errors = [];
  validateNode(envelope, schema, '', errors);
  return { valid: errors.length === 0, errors };
}

function validateNode(value, schema, path, errors) {
  if (schema.type) {
    const t = Array.isArray(schema.type) ? schema.type : [schema.type];
    const actualType = value === null ? 'null' :
                       Array.isArray(value) ? 'array' :
                       typeof value === 'number' && Number.isInteger(value) ? 'integer' :
                       typeof value;
    if (!t.includes(actualType) && !(t.includes('integer') && actualType === 'number'))
      errors.push({ path, error: `expected ${t.join('|')}, got ${actualType}` });
  }
  if (schema.enum && !schema.enum.includes(value))
    errors.push({ path, error: `expected one of ${JSON.stringify(schema.enum)}, got ${value}` });
  if (schema.const !== undefined && value !== schema.const)
    errors.push({ path, error: `expected const ${schema.const}, got ${value}` });
  if (schema.required) {
    for (const k of schema.required) {
      if (!(k in (value || {}))) errors.push({ path: `${path}.${k}`, error: 'required' });
    }
  }
  if (schema.properties && typeof value === 'object' && value !== null) {
    for (const [k, sub] of Object.entries(schema.properties)) {
      if (k in value) validateNode(value[k], sub, `${path}.${k}`, errors);
    }
  }
  if (schema.items && Array.isArray(value)) {
    value.forEach((v, i) => validateNode(v, schema.items, `${path}[${i}]`, errors));
  }
}
```

### 测试（建议写一个 `mcp/test-envelope.cjs`）
```js
// 测试用例数据
const cases = [
  { name: 'happy',           env: validEnvelope(),                                expectValid: true },
  { name: 'missing intent',  env: { provenance: {...}, schema_version: '1.0' },  expectValid: false },
  { name: 'wrong op enum',   env: { ...validEnvelope(), intent: { ...validEnvelope().intent, op: 'BOGUS' } }, expectValid: false },
  { name: 'wrong type',      env: { ...validEnvelope(), provenance: 'string' },  expectValid: false },
];
// 跑：node mcp/test-envelope.cjs
```

### 常见坑
- **`typeof null === 'object'`**：必须先判 `null`
- **`Array.isArray` 优先**：array 也是 object
- **integer vs number**：JS 没有 integer 类型，需要 `Number.isInteger` 检查

## 2.3 `pending.md` 模板升级（半天）

### 输入
- 通过校验的 envelope
- 当前 `currentHtml`
- `ContextManifest`（用于解析 ID → 路径）

### 输出
- 写到 `prompts/pending.md` 的格式化文本

### 模板结构
```markdown
# Anchor Intent

## Intent
- **Op**: `refine`
- **Target Kind**: `selection`
- **Target Ref**: `selection:analysis.overview:abc123`
- **Instruction**: 让说明更突出 AI 战略

## Selection
- **Text**: "Apple 是全球市值最高的消费电子公司..."
- **Ancestor Anchor**: `analysis.overview`
- **DOM Path**: `[data-anc="analysis.overview"] > p`

## Context Bundle
> 处理这个 op 时，请优先利用以下用户指定的资源。

### Memory (2)
- `user_role` — User Role · [`C:\Users\qi\.claude\memory\user_role.md`]
- `feedback_terse` — Terse Responses · [`C:\Users\qi\.claude\memory\feedback_terse.md`]

### Skills (1)
- `/debug` — help user debug a current session issue

### Subagents (1)
- `Explore` — fast codebase exploration agent

### External Resources (0)
(none)

## Render State
- **Anchor tree** (top 20):
  - `analysis`
  - `analysis.overview`
  - `analysis.revenue` (5 children)
  - ...
- **DOM signature**: `sha1:abc123...`

## Current HTML
\`\`\`html
<截断到 15000 字符>
\`\`\`

## Instruction to Claude
1. 处理仅限于 target 范围 (`selection` → 仅修改选中文本对应区域)
2. 保留所有 `data-anc`/`data-handles`/`data-deps`
3. 处理期间用 `anchor_emit_event` 上报 thinking/tool_call/decision
4. 完成后调用 `anchor_render` 推送完整 HTML
```

### 实施步骤
1. **替换 `formatOpAsPrompt(op)`** → `formatEnvelopeAsPrompt(envelope)`
2. **`expandBundleIds(bundle)`**：根据 ID 从 manifest 取 name/description/source_path
3. **保留 `formatOpAsPrompt` 兼容**（内部转 envelope）

## 2.4 客户端 envelope 构造（半天）

### 输入
- 现有 `Anchor.sendOp(opName, anchorId, args)`
- `ContextPanel.getBundle()` 已就绪

### 输出
- `buildEnvelope({...})` 返回符合 schema 的 envelope
- `sendEnvelope(env)` 走 WS 发送

### 函数骨架
```js
buildEnvelope({ op, target_kind, target_ref, instruction, selection, overrideBundle }) {
  const sessionId = sessionStorage.getItem('anchor.sessionId') || this.genSessionId();
  sessionStorage.setItem('anchor.sessionId', sessionId);
  return {
    schema_version: '1.0',
    intent: { op, target_kind, target_ref, instruction },
    selection: selection || null,
    context_bundle: {
      ...(overrideBundle || ContextPanel.getBundle()),
      transient_override: !!overrideBundle
    },
    render_state: {
      anchor_tree: Array.from(this.container.querySelectorAll('[data-anc]')).map(e => e.getAttribute('data-anc')).slice(0, 100),
      dom_signature: this.hashHTML(this.currentHtml),
      viewport: { scroll_top: window.scrollY, visible_anchors: this.getVisibleAnchors() }
    },
    provenance: {
      session_id: sessionId,
      event_id: this.genEventId(),
      parent_event_id: null,
      timestamp: new Date().toISOString(),
      client_version: '1.0'
    }
  };
},

genEventId() { return 'evt_' + Date.now().toString(36) + Math.random().toString(36).slice(2,8); },
genSessionId() { return 'sess_' + Date.now().toString(36) + Math.random().toString(36).slice(2,8); },
hashHTML(s) { let h=0; for (let i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h|=0;} return 'h_'+Math.abs(h).toString(36); },
```

### `sendOp` 重构
```js
sendOp(opName, anchorId, args) {
  const el = this.container.querySelector(`[data-anc="${anchorId}"]`);
  const sel = window.getSelection();
  let selection = null;
  if (sel && sel.toString().trim() && el && el.contains(sel.anchorNode)) {
    selection = {
      text: sel.toString(),
      start_offset: Math.min(sel.anchorOffset, sel.focusOffset),
      end_offset: Math.max(sel.anchorOffset, sel.focusOffset),
      ancestor_anchor: anchorId,
      dom_path: ''
    };
  }
  const env = this.buildEnvelope({
    op: opName,
    target_kind: 'anchor',
    target_ref: anchorId,
    instruction: args?.instruction || '',
    selection
  });
  this.sendEnvelope(env);
},

sendEnvelope(env) {
  if (this.ws?.readyState !== WebSocket.OPEN) {
    this.toast('Connection lost — reconnecting...');
    return;
  }
  this.ws.send(JSON.stringify({ type: 'op', envelope: env }));
  this.toast(`Sent: ${env.intent.op} → ${env.intent.target_ref}`);
}
```

### Server WS 改造
```js
if (msg.type === 'op') {
  const envelope = msg.envelope || msg.op;       // 兼容旧字段
  if (!envelope) { ws.send(JSON.stringify({ type:'error', code:'EMPTY' })); return; }
  // 兼容：如果是旧 op 结构，包装成 envelope
  const env = isEnvelope(envelope) ? envelope : wrapLegacyOp(envelope);
  const { valid, errors } = validateEnvelope(env);
  if (!valid) {
    ws.send(JSON.stringify({ type:'error', code:'INVALID_ENVELOPE', errors }));
    recordEvent('system.error', { code:'INVALID_ENVELOPE', errors });  // Phase 5
    return;
  }
  pendingOp = env;
  fs.writeFileSync(PENDING_PROMPT, formatEnvelopeAsPrompt(env), 'utf8');
  logOp(env);
  recordEvent('user.intent', { envelope: env });  // Phase 5
  notifyPendingChanged();
  ws.send(JSON.stringify({ type:'ack' }));
}
```

### 测试
| # | 操作 | 期望 |
|---|---|---|
| T2.4.1 | 点 + 触发 refine | server 收到带 envelope 的消息，validate 通过 |
| T2.4.2 | devtools 注入恶意消息 `{type:'op', envelope:{}}` | server 回 INVALID_ENVELOPE，不写 pending |
| T2.4.3 | 老式 `{type:'op', op:{...}}` 消息 | server 兼容包装为 envelope 并处理 |

---

# Phase 3 · 自由选择 + 浮动工具栏（L1）

**预估**：2 天
**前置**：Phase 2 完成（envelope 已支持 `target_kind:"selection"`）

## 3.1 选区监听（半天）

### 实施步骤
1. **新增 `SelectionToolbar` 模块**
2. **监听 `document.selectionchange`**（debounce 100ms，避免高频触发）
3. **过滤条件**：
   - 选区非空（`range.toString().trim()`）
   - 选区在 `#anchor-content` 内（`#anchor-content.contains(range.commonAncestorContainer)`）
4. **不满足条件 → 隐藏工具栏**

### 模块骨架
```js
const SelectionToolbar = {
  el: null,
  currentRange: null,

  init() {
    this.el = this.createToolbar();
    document.body.appendChild(this.el);
    document.addEventListener('selectionchange', debounce(() => this.onSelectionChange(), 100));
    document.addEventListener('mousedown', (e) => {
      if (this.el && !this.el.contains(e.target)) this.hide();
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
  },

  onSelectionChange() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return this.hide();
    const text = sel.toString().trim();
    if (!text) return this.hide();
    const range = sel.getRangeAt(0);
    const content = document.getElementById('anchor-content');
    if (!content.contains(range.commonAncestorContainer)) return this.hide();
    this.currentRange = range.cloneRange();
    this.show(range);
  },

  show(range) {
    const rect = range.getBoundingClientRect();
    this.el.style.left = `${Math.min(rect.right + 8, window.innerWidth - 200)}px`;
    this.el.style.top = `${rect.top + window.scrollY - 8}px`;
    this.el.classList.add('visible');
  },

  hide() {
    this.el.classList.remove('visible');
    this.currentRange = null;
  },

  createToolbar() {
    const div = document.createElement('div');
    div.className = 'anc-floating-toolbar';
    for (const op of ['refine', 'annotate', 'branch', 'ask']) {
      const btn = document.createElement('button');
      btn.className = 'btn btn--sm';
      btn.textContent = Anchor.opDefs[op]?.label || op;
      btn.addEventListener('click', (e) => { e.stopPropagation(); this.triggerOp(op); });
      div.appendChild(btn);
    }
    return div;
  },

  triggerOp(op) {
    if (!this.currentRange) return;
    const instruction = prompt(`${op}: 输入指令`);    // MVP 用 prompt，后续可改 inline input
    if (!instruction) return;
    const meta = this.extractMetadata(this.currentRange);
    const env = Anchor.buildEnvelope({
      op,
      target_kind: 'selection',
      target_ref: `selection:${meta.ancestor_anchor || 'global'}:${this.shortHash(meta.text)}`,
      instruction,
      selection: meta
    });
    Anchor.sendEnvelope(env);
    this.hide();
    window.getSelection().removeAllRanges();
  },

  extractMetadata(range) { /* 见 3.3 */ },
  shortHash(s) { /* 简单 6 字符 hash */ }
};
```

## 3.2 浮动工具栏 UI（半天）

### CSS
```css
.anc-floating-toolbar {
  position: absolute;
  display: none;
  background: var(--glass-strong);
  backdrop-filter: blur(20px);
  border: 1px solid var(--glass-border-strong);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
  padding: 6px;
  z-index: 1000;
  gap: 4px;
  transform: translateY(-100%) translateY(-8px);
  animation: jellyIn 0.2s var(--ease-jelly);
}
.anc-floating-toolbar.visible { display: flex; }
.anc-floating-toolbar .btn { padding: 4px 10px; font-size: 0.85rem; }
@keyframes jellyIn { from { opacity: 0; transform: scale(0.9) translateY(-100%) translateY(-4px); } to { opacity: 1; } }
```

### 屏幕边缘自适应
- 计算 `rect.right + toolbarWidth > window.innerWidth` 时，靠左对齐：`left = rect.left`
- 计算 `rect.top - toolbarHeight < 0` 时，下方显示：`top = rect.bottom + 8`

## 3.3 选区元数据提取（半天）

### `extractMetadata(range)` 实现
```js
extractMetadata(range) {
  const text = range.toString();
  // 找最近 [data-anc] 祖先
  let node = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer.parentElement : range.startContainer;
  let ancestor = null;
  while (node && node.id !== 'anchor-content') {
    if (node.hasAttribute && node.hasAttribute('data-anc')) { ancestor = node; break; }
    node = node.parentElement;
  }
  // 在 ancestor 内计算字符偏移
  let startOffset = 0, endOffset = 0;
  if (ancestor) {
    const fullText = ancestor.textContent;
    startOffset = fullText.indexOf(text);
    endOffset = startOffset + text.length;
  }
  // DOM path：简化版（仅 tag + nth-of-type）
  const path = this.buildDomPath(range.startContainer, ancestor);
  return {
    text,
    start_offset: Math.max(0, startOffset),
    end_offset: Math.max(0, endOffset),
    ancestor_anchor: ancestor ? ancestor.getAttribute('data-anc') : null,
    dom_path: path
  };
},

buildDomPath(node, stopAt) {
  const parts = [];
  let n = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  while (n && n !== stopAt && n !== document.body) {
    const tag = n.tagName.toLowerCase();
    const idx = Array.from(n.parentElement?.children || []).indexOf(n) + 1;
    parts.unshift(`${tag}:nth-child(${idx})`);
    n = n.parentElement;
  }
  return parts.join(' > ');
}
```

### 测试
| # | 操作 | 期望 |
|---|---|---|
| T3.3.1 | 选中段落中 5 个字 | 工具栏出现，`ancestor_anchor` 正确 |
| T3.3.2 | 选中跨段落文本 | `ancestor_anchor` 是最近公共祖先 |
| T3.3.3 | 选中 `#anchor-content` 外文本（如 toolbar） | 工具栏不出现 |
| T3.3.4 | 触发 refine | envelope 含 selection 字段，server 端 prompt 输出 ancestor outerHTML |
| T3.3.5 | offset 计算 | text 可在 ancestor 的 textContent 中找到 |

### 常见坑
- **`Range.commonAncestorContainer`** 是 text node 时 `.contains()` 不工作 → 取 `parentElement`
- **`getBoundingClientRect`** 在选区为 0 width 时为空 → 选区折叠时不显示
- **`window.getSelection().removeAllRanges()`** 在触发 op 后调用，否则 selectionchange 立即重触

## 3.4 `pending.md` 选区分支

### `formatEnvelopeAsPrompt` 中处理
当 `intent.target_kind === 'selection'`：
- 在 "Selection" 段提供 `text` 和 `dom_path`
- 在 "Current HTML" 之前额外提供 `<ancestor outerHTML>`（如果有 ancestor）
- 在 instruction-to-Claude 段强调："仅修改选中文本对应的位置，其它保留"

---

# Phase 4 · 实时中间过程渲染（L4）

**预估**：2-3 天
**前置**：Phase 2 完成（schema 已建立）

## 4.1 新增 MCP tool `anchor_emit_event`（半天）

### MCP 注册
在 `tools/list` 响应中追加：
```json
{
  "name": "anchor_emit_event",
  "description": "Emit a process event during op handling. Shown in the webview timeline panel. Use to surface thinking, tool calls, decisions, partial renders, completion, errors.",
  "inputSchema": {
    "type": "object",
    "required": ["type", "payload"],
    "properties": {
      "type":    { "enum": ["thinking", "tool_call", "partial_render", "decision", "complete", "error"] },
      "payload": { "type": "object" }
    }
  }
}
```

### `tools/call` 分支
```js
if (name === 'anchor_emit_event') {
  const { type, payload } = args || {};
  if (!type || !payload) { /* error */ }
  const event = {
    event_id: genEventId(),
    session_id: currentSessionId,
    parent_event_id: pendingOp?.provenance?.event_id || null,
    timestamp: new Date().toISOString(),
    kind: `agent.${type}`,
    payload
  };
  recordEvent(event.kind, payload, { event_id: event.event_id, parent_event_id: event.parent_event_id });
  broadcast(JSON.stringify({ type: 'agent_event', event }));
  sendMCP({ jsonrpc:'2.0', id, result: { content: [{ type:'text', text: 'emitted' }] }});
  return;
}
```

## 4.2 Timeline panel UI（1 天）

### HTML
```html
<aside id="anchor-timeline-panel" class="anc-timeline-panel">
  <header class="tl-header">
    <span>Timeline</span>
    <button class="tl-clear">Clear</button>
  </header>
  <div class="tl-body"><!-- groups injected here --></div>
</aside>
```

### CSS
```css
.anc-timeline-panel {
  width: 320px; flex-shrink: 0;
  background: var(--glass); backdrop-filter: blur(20px);
  border-left: 1px solid var(--glass-border);
  padding: 16px; overflow-y: auto;
}
.tl-group { margin-bottom: 16px; padding: 8px; background: var(--glass-strong); border-radius: var(--r-md); }
.tl-group .tl-group-head { font-size: 0.85rem; color: var(--text-soft); margin-bottom: 6px; }
.tl-event { padding: 6px 8px; margin: 4px 0; border-radius: var(--r-sm); display: flex; gap: 8px; align-items: start; }
.tl-event--thinking      { background: rgba(99,102,241,0.08);  border-left: 3px solid var(--brand); }
.tl-event--tool_call     { background: rgba(6,182,212,0.08);   border-left: 3px solid var(--cyan); }
.tl-event--decision      { background: rgba(245,158,11,0.08);  border-left: 3px solid var(--amber); }
.tl-event--partial_render { background: rgba(100,116,139,0.08); border-left: 3px solid var(--slate); }
.tl-event--complete      { background: rgba(16,185,129,0.08);  border-left: 3px solid var(--green); }
.tl-event--error         { background: rgba(244,63,94,0.08);   border-left: 3px solid var(--pink); }
.tl-event-icon { flex-shrink: 0; font-size: 1.1rem; }
.tl-event-body { flex: 1; }
.tl-event-summary { font-size: 0.88rem; }
.tl-event-time { font-size: 0.7rem; color: var(--text-mute); }
```

### JS 模块
```js
const TimelinePanel = {
  body: null,
  currentGroup: null,
  iconMap: {
    thinking: '✦',
    tool_call: '⚙',
    decision: '◆',
    partial_render: '↻',
    complete: '✓',
    error: '✕'
  },

  init() {
    this.body = document.querySelector('.tl-body');
    document.querySelector('.tl-clear').addEventListener('click', () => this.clear());
  },

  onUserIntent(envelope) {
    this.currentGroup = this.makeGroup(`${envelope.intent.op} → ${envelope.intent.target_ref}`);
    this.body.prepend(this.currentGroup);
  },

  onAgentEvent(event) {
    if (!this.currentGroup) this.onUserIntent({ intent: { op: 'unknown', target_ref: '?' } });
    const type = event.kind.replace('agent.', '');
    const card = document.createElement('div');
    card.className = `tl-event tl-event--${type}`;
    card.innerHTML = `
      <span class="tl-event-icon">${this.iconMap[type] || '·'}</span>
      <div class="tl-event-body">
        <div class="tl-event-summary"></div>
        <div class="tl-event-time">${this.relTime(event.timestamp)}</div>
      </div>
    `;
    card.querySelector('.tl-event-summary').textContent = this.summarize(event);
    card.addEventListener('click', () => this.expand(card, event));
    this.currentGroup.querySelector('.tl-group-body').appendChild(card);
  },

  summarize(event) {
    const p = event.payload || {};
    if (event.kind === 'agent.thinking')        return p.summary || '(no summary)';
    if (event.kind === 'agent.tool_call')       return `${p.tool}: ${p.input_summary || ''} [${p.status}]`;
    if (event.kind === 'agent.decision')        return `${p.choice}`;
    if (event.kind === 'agent.partial_render')  return `partial render → ${p.target_anchor || 'root'}`;
    if (event.kind === 'agent.complete')        return p.summary || 'done';
    if (event.kind === 'agent.error')           return p.message || 'error';
    return event.kind;
  },

  expand(card, event) {
    let pre = card.querySelector('pre');
    if (pre) { pre.remove(); return; }
    pre = document.createElement('pre');
    pre.style.cssText = 'font-size:0.7rem;max-height:200px;overflow:auto;margin-top:6px;';
    pre.textContent = JSON.stringify(event.payload, null, 2);
    card.querySelector('.tl-event-body').appendChild(pre);
  },

  makeGroup(title) {
    const g = document.createElement('div');
    g.className = 'tl-group';
    g.innerHTML = `<div class="tl-group-head">${title}</div><div class="tl-group-body"></div>`;
    return g;
  },

  clear() { this.body.innerHTML = ''; this.currentGroup = null; },

  relTime(iso) {
    const dt = (Date.now() - new Date(iso).getTime()) / 1000;
    if (dt < 60) return `${Math.round(dt)}s`;
    if (dt < 3600) return `${Math.round(dt/60)}m`;
    return `${Math.round(dt/3600)}h`;
  }
};

// 接入 Anchor.handleMessage
Anchor.handleMessage_orig = Anchor.handleMessage;
Anchor.handleMessage = function(msg) {
  if (msg.type === 'agent_event') return TimelinePanel.onAgentEvent(msg.event);
  return this.handleMessage_orig(msg);
};
// 在 sendEnvelope 后调用：
TimelinePanel.onUserIntent(envelope);
```

### 测试
| # | 操作 | 期望 |
|---|---|---|
| T4.2.1 | server log 一个事件，broadcast | 浏览器 timeline 出现一个卡片 |
| T4.2.2 | 触发 op → Claude 调 3 次 emit_event | timeline 同组内 3 张卡片按序 |
| T4.2.3 | 点击卡片 | 展开 payload JSON |
| T4.2.4 | 点 Clear | timeline 清空 |

## 4.3 CLAUDE.md 引导（半天）

### 在 CLAUDE.md 末尾追加段落

```markdown
## 处理 IntentEnvelope 时的事件上报最佳实践

当 Claude 调用 `anchor_get_pending_op` 后，应当在处理 envelope 期间通过 `anchor_emit_event(type, payload)` 上报关键事件，让用户在 webview 的 timeline 中看到推理过程。

### 推荐时机

| 时刻 | 调用 |
|---|---|
| 开始处理 | `anchor_emit_event("thinking", {summary: "..."})` 说明计划 |
| 调用工具前 | `anchor_emit_event("tool_call", {tool, input_summary, status: "start"})` |
| 调用工具后 | `anchor_emit_event("tool_call", {tool, result_summary, status: "end"})` |
| 关键分支决策 | `anchor_emit_event("decision", {choice, alternatives, reason})` |
| 中间产出 | `anchor_emit_event("partial_render", {html_fragment, target_anchor})` |
| 完成 | `anchor_emit_event("complete", {success: true, summary})` |
| 失败 | `anchor_emit_event("error", {message, retriable})` |

事件是建议而非强制；timeline 越完整，loop 的复盘价值越高。
```

## 4.4 端到端联调（半天）

跑一个完整 op，目视确认：
1. 用户触发 refine
2. Timeline 出现新组（标题：refine → ...）
3. Claude 调 thinking → tool_call (start) → tool_call (end) → decision → complete
4. 每个事件在 timeline 出现，颜色和图标正确
5. 点击事件展开看到 payload
6. Anchor 内容更新

---

# Phase 5 · 过程事件记录器（L5）

**预估**：1-2 天
**前置**：Phase 4 完成

## 5.1 Session 目录管理（半天）

### 启动逻辑
```js
// mcp/server.cjs
const SESSIONS_DIR = path.join(LOGS_DIR, 'sessions');
let currentSessionId = null;
let currentSessionDir = null;
let sessionEventCount = 0;

function startSession() {
  if (!fs.existsSync(SESSIONS_DIR)) fs.mkdirSync(SESSIONS_DIR, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  currentSessionId = 'sess_' + Date.now().toString(36) + Math.random().toString(36).slice(2,6);
  currentSessionDir = path.join(SESSIONS_DIR, `${ts}_${currentSessionId}`);
  fs.mkdirSync(currentSessionDir);
  fs.mkdirSync(path.join(currentSessionDir, 'envelopes'));
  fs.mkdirSync(path.join(currentSessionDir, 'renders'));
  fs.mkdirSync(path.join(currentSessionDir, 'context_snapshots'));
  const manifest = {
    session_id: currentSessionId,
    start_time: new Date().toISOString(),
    anchor_version: '1.0',
    client_info: process.versions,
    event_count: 0
  };
  fs.writeFileSync(path.join(currentSessionDir, 'manifest.json'), JSON.stringify(manifest, null, 2));
  recordEvent('system.session_start', { manifest });
  log(`session started: ${currentSessionId}`);
}

process.on('SIGINT',  endSession); process.on('SIGTERM', endSession); process.on('exit', endSession);
function endSession() {
  if (!currentSessionId) return;
  try { recordEvent('system.session_end', { event_count: sessionEventCount }); }
  catch {}
}

// listen 回调中
startSession();
```

## 5.2 `recordEvent` 实现（半天）

```js
function recordEvent(kind, payload, opts = {}) {
  if (!currentSessionDir) return;            // 未启动会话期间不记录
  const eventId = opts.event_id || genEventId();
  const event = {
    event_id: eventId,
    session_id: currentSessionId,
    timestamp: new Date().toISOString(),
    kind,
    parent_event_id: opts.parent_event_id || null,
    payload
  };
  // 1. 附属文件
  if (kind === 'user.intent' && payload.envelope) {
    const f = path.join(currentSessionDir, 'envelopes', `${eventId}.json`);
    fs.writeFileSync(f, JSON.stringify(payload.envelope, null, 2));
    event.envelope_ref = `envelopes/${eventId}.json`;
  }
  if (kind === 'agent.render' && payload.html) {
    const f = path.join(currentSessionDir, 'renders', `${eventId}.html`);
    fs.writeFileSync(f, payload.html);
    event.render_ref = `renders/${eventId}.html`;
    // 去掉 html 字段（已在 file 中），避免重复
    delete event.payload.html;
  }
  // 2. 追加 events.jsonl
  fs.appendFileSync(
    path.join(currentSessionDir, 'events.jsonl'),
    JSON.stringify(event) + '\n'
  );
  sessionEventCount++;
  // 3. 更新 manifest 的 event_count（每 10 条 flush 一次，减少 IO）
  if (sessionEventCount % 10 === 0) updateManifest({ event_count: sessionEventCount });
}

function updateManifest(patch) {
  const f = path.join(currentSessionDir, 'manifest.json');
  const m = JSON.parse(fs.readFileSync(f, 'utf8'));
  Object.assign(m, patch);
  fs.writeFileSync(f, JSON.stringify(m, null, 2));
}
```

### 触发点接入
- `anchor_render(html)` → `recordEvent('agent.render', { html, length: html.length })`
- WS `op` 收到（envelope validated） → `recordEvent('user.intent', { envelope })`
- WS `context_changed` → `recordEvent('user.context_changed', { bundle })`
- `anchor_emit_event` 内部已经调
- 校验失败 → `recordEvent('system.error', { code, errors })`

## 5.3 HTTP API（半天）

```js
app.get('/sessions', (req, res) => {
  const items = fs.readdirSync(SESSIONS_DIR)
    .filter(d => d.startsWith('20'))
    .map(d => {
      const mfp = path.join(SESSIONS_DIR, d, 'manifest.json');
      if (!fs.existsSync(mfp)) return null;
      const m = JSON.parse(fs.readFileSync(mfp, 'utf8'));
      return { dir: d, ...m };
    })
    .filter(Boolean)
    .sort((a, b) => b.start_time.localeCompare(a.start_time));
  res.json(items);
});

app.get('/session/:dir', (req, res) => {
  const d = path.join(SESSIONS_DIR, req.params.dir);
  if (!fs.existsSync(d)) return res.status(404).json({ error: 'not found' });
  const manifest = JSON.parse(fs.readFileSync(path.join(d, 'manifest.json'), 'utf8'));
  const events = fs.existsSync(path.join(d, 'events.jsonl'))
    ? fs.readFileSync(path.join(d, 'events.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
    : [];
  res.json({ manifest, events });
});

app.get('/session/:dir/render/:eid', (req, res) => {
  const f = path.join(SESSIONS_DIR, req.params.dir, 'renders', `${req.params.eid}.html`);
  if (!fs.existsSync(f)) return res.status(404).send('not found');
  res.set('Content-Type', 'text/html; charset=utf-8').send(fs.readFileSync(f, 'utf8'));
});

app.get('/session/:dir/envelope/:eid', (req, res) => {
  const f = path.join(SESSIONS_DIR, req.params.dir, 'envelopes', `${req.params.eid}.json`);
  if (!fs.existsSync(f)) return res.status(404).json({ error: 'not found' });
  res.set('Content-Type', 'application/json').send(fs.readFileSync(f, 'utf8'));
});
```

## 5.4 MCP `anchor_replay_session` tool（半天）

### 注册
```json
{
  "name": "anchor_replay_session",
  "description": "Read a recorded session's event stream. Read-only. Returns up to 1000 events. Use for replay analysis or evaluation.",
  "inputSchema": {
    "type": "object",
    "required": ["session_id"],
    "properties": {
      "session_id":       { "type": "string" },
      "up_to_event_id":   { "type": "string" },
      "include_envelopes": { "type": "boolean", "default": false }
    }
  }
}
```

### 实现
```js
if (name === 'anchor_replay_session') {
  const sid = args.session_id;
  const dir = fs.readdirSync(SESSIONS_DIR).find(d => d.includes(sid));
  if (!dir) { /* error */ return; }
  const events = fs.readFileSync(path.join(SESSIONS_DIR, dir, 'events.jsonl'), 'utf8')
    .trim().split('\n').map(JSON.parse);
  let cutoff = events.length;
  if (args.up_to_event_id) {
    const idx = events.findIndex(e => e.event_id === args.up_to_event_id);
    if (idx >= 0) cutoff = idx + 1;
  }
  const result = events.slice(0, Math.min(cutoff, 1000));
  sendMCP({ jsonrpc:'2.0', id, result: { content:[{ type:'text', text: JSON.stringify(result) }] }});
  return;
}
```

### 测试
| # | 操作 | 期望 |
|---|---|---|
| T5.1 | 跑一次 op 后看 `logs/sessions/<id>/events.jsonl` | 含 session_start → user.intent → agent.* → agent.render → agent.complete |
| T5.2 | `curl localhost:3000/sessions` | 返回会话列表 |
| T5.3 | `curl localhost:3000/session/<dir>` | 返回 manifest + events |
| T5.4 | `anchor_replay_session(session_id)` from Claude | 返回事件流 |
| T5.5 | 多次 server 重启 | 每次新建独立 session 目录 |
| T5.6 | crash 后下次启动 | 旧 session 目录保留，新 session 正常开始 |

### 常见坑
- **`fs.appendFileSync` 在高频写时阻塞** → MVP 可接受；后续可改异步队列
- **`events.jsonl` 解析时空行** → split 后 filter
- **`process.on('exit')` 无法做异步** → 用 SIGINT/SIGTERM 提前关闭

---

# Phase 6 · 代码报告 Demo（跨域验证）

**预估**：1 天

## 6.1 模板 HTML

`examples/code-review-demo/sample.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>PR Review</title></head><body>

<section data-anc="review" data-handles="refine,expand,branch" class="anc-section anc-section--brand">
  <div class="anc-pill-row">
    <span class="anc-pill anc-pill--gen">AI Generated</span>
    <span class="anc-pill anc-pill--review">Reviewing</span>
  </div>
  <h1>PR #1234 — Refactor auth middleware</h1>

  <div class="anc-kpi-grid">
    <div class="anc-kpi anc-kpi--brand"><div class="kpi-value">8</div><div class="kpi-label">Files changed</div></div>
    <div class="anc-kpi anc-kpi--green"><div class="kpi-value">+412</div><div class="kpi-label">Lines added</div></div>
    <div class="anc-kpi anc-kpi--pink"><div class="kpi-value">-187</div><div class="kpi-label">Lines removed</div></div>
    <div class="anc-kpi anc-kpi--amber"><div class="kpi-value">Medium</div><div class="kpi-label">Risk</div></div>
  </div>

  <hr class="anc-divider">

  <div data-anc="review.summary" data-handles="refine,expand,lock" class="anc-section">
    <h2>概览</h2>
    <p>这次 PR 把 session token 存储从 cookie 换成 server-side session map，主要为了符合最新合规要求...</p>
  </div>

  <div data-anc="review.file.auth-middleware" data-handles="refine,expand,branch,restructure" class="anc-section anc-section--cyan">
    <h2>src/auth/middleware.ts</h2>
    <p data-anc="review.suggestion.s1" data-handles="refine,annotate,branch,lock">
      <strong>建议</strong>：第 42 行的 session map 应当使用 LRU cache 替代 Map，否则在长时间运行后会内存泄漏。
    </p>
    <p data-anc="review.suggestion.s2" data-handles="refine,annotate,branch">
      <strong>建议</strong>：第 78 行的同步 token 解析在高并发下会阻塞 event loop，建议改为 async。
    </p>
  </div>

  <div data-anc="review.file.session-store" data-handles="refine,expand,branch" class="anc-section anc-section--green">
    <h2>src/auth/session-store.ts</h2>
    <p data-anc="review.suggestion.s3" data-handles="refine,annotate,branch">
      <strong>建议</strong>：缺少 graceful shutdown 时的 session flush，重启后所有用户会被强制登出。
    </p>
  </div>

  <div data-anc="review.risks" data-handles="refine,expand,annotate,lock" class="anc-section anc-section--amber">
    <h2>风险评估</h2>
    <ul>
      <li data-anc="review.risks.compat" data-handles="refine,expand">向后兼容：旧 cookie 用户首次访问会被强制重登</li>
      <li data-anc="review.risks.perf"   data-handles="refine,expand">性能：session map 在 10k+ 用户时未做基准测试</li>
    </ul>
  </div>
</section>

</body></html>
```

## 6.2 端到端验证流程

1. `anchor_render(sampleHtml)` 推送
2. ContextPanel 中勾选 `code-reviewer` subagent（假设已在 `.claude/agents/` 中存在）+ 任意相关 memory
3. 选中 `review.suggestion.s1` 中的"LRU cache"四个字
4. 浮动工具栏 → `Branch`，instruction："考虑用 WeakMap 是否可行"
5. 期望：
   - Timeline 出现 thinking → tool_call → decision → render → complete
   - 新渲染中 s1 段落多了备选方案，其它锚点完全不变
   - `logs/sessions/<id>/events.jsonl` 完整

---

# 跨 Phase 的工程实践

## 调试技巧

- **server 日志**：`process.stderr.write` 输出到 Claude Code 的 MCP server 日志；用 `log()` 前缀 `[anchor-mcp]` 便于过滤
- **client 调试**：浏览器 devtools console 查看 `Anchor.ws.readyState`、`ContextPanel.bundle`、`Anchor.currentHtml.length`
- **手动注入测试消息**：devtools console 执行 `Anchor.ws.send(JSON.stringify({type:'op', envelope: {...}}))`

## Git 提交建议

每个 Phase 完成后提交一次：
- `Phase 0: consolidate server + auto-open browser`
- `Phase 1: context configuration panel (memory/skills/subagents/resources)`
- `Phase 2: typed IntentEnvelope + schema validation`
- `Phase 3: free-form selection + floating op toolbar`
- `Phase 4: anchor_emit_event + timeline panel`
- `Phase 5: structured session recorder`
- `Phase 6: code-review demo (cross-domain validation)`

## 可选清理（不阻断 MVP）

- 移除 `hooks/anchor-hook.cjs`（如果 MCP-only 已充分验证）
- 移除 `bridge/server.js`（Phase 0 完成后）
- `logs/ops.jsonl` 改为只在 Phase 0 兼容期保留，Phase 5 后可移除

---

**文档版本**：v1.0 · 2026-05-14
**作者**：实施工程师参考
