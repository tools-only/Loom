# Loom 端到端测试手册

**测试方式：纯 UI 操作 — 浏览器点击，无需终端命令**
**测试入口：http://localhost:3000/loom**

---

## 前置条件

1. Anchor Server 必须运行（日常已在后台运行）
   - 验证：浏览器打开 http://localhost:3000 可以看到 Anchor 主界面
2. Python 3.11+ 已安装（仅 Phase 1 后需要）
3. Anthropic API Key 已配置为环境变量 `ANTHROPIC_API_KEY`（仅 Phase 1 后需要）

---

## Phase 0 — 服务端接口验证（无需 Python Brain）

**目标**：确认 server.cjs 的三个新接口正常工作。

### 测试 0-A：Loom 控制面板加载

1. 浏览器打开 `http://localhost:3000/loom`
2. ✅ **预期**：看到"Loom 控制面板"页面，左侧侧边栏有 4 个 Hand 按钮
3. ✅ **预期**：状态栏显示"Anchor Server 运行中"（绿点）
4. ✅ **预期**：状态栏显示"Loom Brain 未运行"（红点）— 正常，Brain 尚未启动

---

### 测试 0-B：Connector 数据接口

1. 点击面板底部的 **"FRED 数据"** 快捷链接（或直接打开 `http://localhost:3000/data/fred`）
2. ✅ **预期**：返回 JSON，格式：`{ "ok": true, "connector_id": "fred", "count": N, "items": [...] }`
   - 若 count=0：正常（connector 尚未推送任何数据到 inbox）
   - 若 count>0：有数据，验证 items 中的 `source` 字段 = "fred"

3. 同样测试 Fear & Greed：点击 **"F&G 数据"** 链接（`/data/fear-greed`）
4. ✅ **预期**：返回相同格式的 JSON

---

### 测试 0-C：Thesis Store 接口

1. 浏览器打开 `http://localhost:3000/loom/thesis/NVDA`
2. ✅ **预期**：返回 `{ "ok": true, "thesis": null }`（thesis store 尚为空）

---

### 测试 0-D：Brain 未运行时的错误处理

1. 在 Loom 控制面板，点击任意 Hand 按钮（例如"📊 市场研判"）
2. ✅ **预期**：显示错误卡片"Loom Brain 未运行"，并提示启动命令
3. ✅ **预期**：错误信息准确，不显示空白页或系统崩溃

---

## Phase 1 — 三个分析型 Hand（需要 Python Brain）

**前置步骤**：

在系统终端执行一次：
```
cd D:\ai-native chrome\loom
pip install -r requirements.txt
python main.py
```

等待看到 `Uvicorn running on http://127.0.0.1:3001` 后开始测试。

> 注：此步骤只需执行一次。后续所有测试均在浏览器完成。

---

### 测试 1-A：Brain 健康检查

1. 浏览器打开 Loom 控制面板 `http://localhost:3000/loom`
2. ✅ **预期**：状态栏"Loom Brain"变为绿点，显示"运行中 (4 hands)"

---

### 测试 1-B：市场研判

1. 在 Loom 控制面板，**任务描述留空**
2. 点击 **"📊 市场研判"** 按钮
3. ✅ **预期**：按钮变为"⏳"加载状态，主区域显示"正在分析…"
4. 等待（约 15-30 秒，取决于网络和 API 响应）
5. ✅ **预期**：结果卡片出现，包含：
   - 置信度百分比
   - 分析叙述（中文，2-4段）
   - 关键判断列表
   - 数据缺口列表
   - 资源使用详情（哪些资源被展示、哪些被用、哪些被忽略）
   - "已 patch 到主 webview"确认提示

6. 在另一个浏览器标签打开 `http://localhost:3000`
7. ✅ **预期**：主 webview 中出现"市场研判"分析区块（带 AI 生成标签）

**资源使用验证**：
- 检查"资源使用详情"：若 FRED/MarketWatch connector 有数据，这些资源应显示"✓ 已使用"
- 若 connector 无数据（API key 未配置），数据缺口列表会注明

---

### 测试 1-C：情绪追踪

1. 在 Loom 控制面板，**任务描述留空**
2. 点击 **"🌡️ 情绪追踪"** 按钮
3. ✅ **预期**：分析完成后，叙述内容聚焦于情绪指标（fear/greed、AAII、NAAIM），而非市场 regime
4. ✅ **预期**：关键判断中包含具体读数（若有数据）或明确的数据缺口说明

---

### 测试 1-D：标的 Thesis（首次）

1. 在股票代码输入框输入 **`NVDA`**
2. 点击 **"🎯 标的 Thesis"** 按钮
3. ✅ **预期**：叙述内容关于 NVDA，包含核心假设、催化剂、失效条件
4. ✅ **预期**：第一次运行时，关键判断中无"上次分析"等字样（无历史 thesis）

**验证 Thesis 持久化**：

5. 分析完成后，打开 `http://localhost:3000/loom/thesis/NVDA`
6. ✅ **预期**：返回 JSON，包含刚才分析的 thesis 数据（ticker="NVDA"，narrative 不为空）

---

### 测试 1-E：标的 Thesis（增量更新）

1. 确保已完成测试 1-D（NVDA 有历史 thesis）
2. 在任务描述填写：**"今天有什么新消息影响 NVDA thesis？"**
3. 股票代码保持 **`NVDA`**
4. 点击 **"🎯 标的 Thesis"** 按钮
5. ✅ **预期**：叙述内容包含"与上次分析的变化"或对先前判断的更新引用
6. ✅ **预期**：关键判断中包含"先前假设 X 有所变化/维持"之类的增量表述

---

## Phase 2 — 持仓管理 Hand（session-driven）

### 测试 2-A：持仓报告（简单）

1. 在 Loom 控制面板，**持仓数据**输入框填写：
   ```
   NVDA 100股 成本$450
   AAPL 50股 成本$180
   现金 $30,000
   ```
2. 点击 **"💼 持仓更新"** 按钮
3. ✅ **预期**：报告包含总市值估算、主要持仓摘要
4. ✅ **预期**：资源使用详情显示"0/0 个资源"（Position Hand 不使用外部数据）

---

### 测试 2-B：集中度风险检测

1. 在持仓数据填写一个高度集中的组合：
   ```
   NVDA 500股 成本$450
   现金 $5,000
   ```
2. 点击 **"💼 持仓更新"**
3. ✅ **预期**：报告的关键判断或叙述中提及集中度风险（NVDA 超过 20% 警戒线）

---

## Phase 3 — 渐进披露优化验证

**目标**：验证多次调用后，资源排序是否根据实际使用情况调整。

### 测试 3-A：资源使用率积累

1. 连续进行 3 次市场研判分析（Phase 1-B），每次稍微修改任务描述
2. 每次查看"资源使用详情"，记录哪些资源被实际使用

### 测试 3-B：观察资源排序变化

1. 再次点击"📊 市场研判"
2. 在浏览器开发者工具 Network 面板查看 `/loom/run` 的请求响应
3. 观察 `artifact.metadata.resources_shown` 列表的顺序
4. ✅ **预期**：频繁被使用的资源排在前面（高使用率资源优先披露）

---

## Phase 3-日报 — Harness 日报（手动触发测试）

Harness 日报正常在每个交易日 07:00 ET 自动触发。以下是手动验证方法：

### 测试 4-A：手动触发日报（需要临时修改）

在主 webview `http://localhost:3000` 中，打开浏览器控制台（F12），执行：
```javascript
fetch('/loom/run', {
  method: 'POST',
  headers: {'Content-Type':'application/json'},
  body: JSON.stringify({ hand_id: '__review__', task: 'trigger_review', context: {} })
})
```

> 注：此命令调用 Brain 的 review 端点（需要先在 brain.py 添加该路由，或直接访问 http://localhost:3001/review）

**更简单的方式**：浏览器打开 `http://localhost:3001/review`

✅ **预期**：返回 JSON，包含各 Hand 的调用统计和资源使用率

---

## 常见问题排查

| 症状 | 原因 | 解决 |
|------|------|------|
| "Loom Brain 未运行" 红点 | Python Brain 未启动 | 执行 `cd loom && python main.py` |
| 分析叙述为空或结构混乱 | ANTHROPIC_API_KEY 未设置 | 设置环境变量后重启 Brain |
| 资源全显示"未使用" | Connector inbox 为空 | 等待 connector 推送数据，或手动测试时正常 |
| 主 webview 无更新 | 主 webview 未打开或无对应 anchor_id | 确认 http://localhost:3000 已打开 |
| 置信度固定 50% | LLM 未返回结构化 JSON | 查看 Brain 终端日志，通常是提示词需要调整 |

---

*Testing manual for Loom Harness v0.1 — Phase 0-3 coverage*
