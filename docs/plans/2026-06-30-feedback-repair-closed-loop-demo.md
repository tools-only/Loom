# Feedback → Intent → Repair 闭环 — 用户真机测试

## 前备

```bat
scripts\start-anchor.bat    # 1 号窗口：Anchor webview (port 3000)
cd loom && D:\conda\python.exe -m uvicorn brain:app --host 127.0.0.1 --port 3002   # 2 号窗口：Brain (port 3002)
```

浏览器打开 http://localhost:3000

---

## Step 1 — 提问，触发完整 Episode

### 方式 A：页面 Prompt Bar（推荐）

在浏览器 http://localhost:3000 底部 prompt 输入框中，使用 `/brain` 斜杠命令：

```
/brain Analyze NVIDIA investment value across macro, fundamentals, and sentiment
```

按 Enter。页面显示 "Brain thinking..."，Brain 开始工作。完成后，webview 自动渲染：
- **brain-synthesis** 卡片（stance/confidence/key_drivers）
- 各 **hand card**（market / sentiment / target / position）
- **orchestration DAG**（嵌入在 synthesis 卡片底部）
- **brain-state-engine**（state reasoning 视图）

### 方式 B：API 直接调用

```bash
curl -s -X POST http://127.0.0.1:3002/analyze \
  -H "Content-Type: application/json" \
  -d '{"question":"Analyze NVIDIA investment value — macro, fundamentals, sentiment","domain_hint":"trading"}'
```

**Harness 内部发生了什么**（用户不可见，但这是理解后续交互的关键）：

```
/analyze
  → core_agent.analyze()
    → workflow decision（Brain 决定 split 成几个 hand、各自什么任务）
    → parallel hand dispatch（每个 hand agent 独立执行）
    → review（Brain 审查各 hand 产出，检查 rubric coverage）
    → synthesis（合并所有 hand 产出为最终结论）
  → build_minimal_orchestration_snapshot()  ← orchestration.py:8
  → FlywheelRecord 持久化
  → HTML 渲染 → patch_webview("brain-synthesis", html)
  → 逐个 hand card → patch_webview(anchor_id, hand_html)
```

**返回值**：
```json
{
  "ok": true,
  "episode_id": "xxx-xxx-xxx",
  "goal_id": "...",
  "workflow_decision": {"domain":"trading","hands":["market","sentiment","..."]},
  "synthesis": {"stance":"...","confidence":0.8,...},
  "hand_artifacts": {"market":{...},"sentiment":{...}}
}
```

**用户看到**：浏览器里 Anchor 页面出现 Brain synthesis 卡片 + 各 hand card（market / sentiment / target 等）。

---

## Step 2 — 用户对 Agent 中间产出提交 Scoped Feedback

这是**用户与 harness 的核心交互点**。

### 用户在页面上做什么

每个 hand card 底部自动挂载了 `hand-feedback-widget`：
- **thumbs-up** / **thumbs-down** 按钮
- 文本输入框（可选注释）
- Submit 按钮

用户操作：点击某个 hand card（比如 market）的 **thumbs-down**，输入框填写：
> "WACC assumption too old, use Q1 2026 data"

点 **Submit**。

### 数据怎么流入 Harness

```
前端 hand-feedback-widget.js:62-88
  → POST /feedback
    body: {
      episode_id, hand_id,
      object_ref: "claim:valuation_wacc",    ← 用户反馈锚定到哪个对象
      object_type: "claim",                  ← 对象类型（claim/source/hand/artifact/episode）
      raw_signal: "thumbs_down",
      comment: "WACC assumption too old..."
    }
```

### Harness 如何处理

```
brain.py:3805  → /feedback 端点
  → ScopedFeedback.from_event(body)             ← contextual_intent.py:27
  → flywheel.load_detail(episode_id)            ← 捞出该 episode 的完整上下文
  → ContextualIntentCompiler.compile(feedback, episode=detail)  ← contextual_intent.py:85
    → 根据 object_type 路由到不同策略：
        claim    → target="claim_revision"     ← :170
        source   → target="source_preference"  ← :183
        hand/artifact/task → target="task_repair" ← :195
        其他     → target="episode_diagnosis"   ← :207（需先定位）
    → 产出 IntentDelta(target, instruction, affected_objects, required_constraints)
  → flywheel.append_feedback_event()            ← 持久化
  → flywheel.append_intent_analysis()           ← 持久化
  → 返回 intent_lens 给前端:
    {
      summary: "Feedback is interpreted as a scoped claim correction. Scope: claim.",
      affected_objects: ["claim:valuation_wacc", "task:t1", "hand:market"],
      intent_delta: {
        target: "claim_revision",
        instruction: "Re-check the scoped claim using the user's feedback: ...",
        required_constraints: ["verify_supporting_evidence", "preserve_feedback_provenance"]
      },
      confidence: "medium"
    }
```

**用户看到**：widget 显示 "Recorded" 2 秒后消失。intent_lens.summary 写入 widget 的 `data-intent-lens` 属性（hand-feedback-widget.js:90）。

### 验证

```bash
# 替换 EPISODE_ID
curl -s http://127.0.0.1:3002/flywheel?limit=5 | python -m json.tool
# 应看到 feedback_event + intent_analysis 记录
```

---

## Step 3 — 用户触发 Repair（反馈驱动修复）

### API 方式

```bash
curl -s -X POST http://127.0.0.1:3002/feedback/repair \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id":"<EPISODE_ID>",
    "hand_id":"market",
    "signal":"thumbs_down",
    "comment":"WACC too old, use Q1 2026 data",
    "object_ref":"claim:valuation_wacc",
    "object_type":"claim",
    "target_hands":["market"],
    "context":{"source":"manual_test"}
  }'
```

### Harness 内部链路

```
brain.py:3833 → _run_episode_repair()
  → ScopedFeedback 构造                               ← :3861
  → ContextualIntentCompiler.compile() → IntentDelta   ← :3872
  → build_repair_plan(episode, comment, hand_id, target_hands)
      → choose_repair_hands()                          ← episode_repair.py:19
        → 按 explicit → mentioned → lowest-confidence 优先级选 hand
  → build_repair_task(episode, hand_id, comment, intent_delta)
      → 生成 agent 可读的 repair instruction            ← episode_repair.py:84
      → 内容包含：original question, previous stance/confidence,
         user correction, intent_delta(target/instruction/constraints)
  → adapter.invoke(envelope)  →  hand agent 重新执行修复任务
  → flywheel.append_repair_result()                    ← 持久化
  → patch_webview() → 前端更新修复后的 hand card
```

**返回值**：
```json
{
  "ok": true,
  "repair_plan": {"target_hands":["market"],"reason":"explicit feedback target"},
  "artifacts": {"market": {"metadata":{"confidence":0.9,...},"narrative":"...",...}},
  "intent_analysis": {...},
  "intent_delta": {"target":"claim_revision",...}
}
```

---

## Step 4 — 查看 Orchestration Snapshot

```bash
curl -s http://127.0.0.1:3002/orchestration/<EPISODE_ID> | python -m json.tool
```

返回 episode 的结构化调度视图（orchestration.py:8 构建）：

```json
{
  "nodes": [
    {"id":"brain","type":"brain"},
    {"id":"task:t1","type":"task","task":"Analyze macro regime..."},
    {"id":"hand:market","type":"hand","executor_id":"codex"},
    {"id":"artifact:t1","type":"artifact","confidence":0.85,"claim_count":3},
    {"id":"review","type":"review"}
  ],
  "edges": [
    {"from":"brain","to":"task:t1","reason":"task decomposition"},
    {"from":"task:t1","to":"hand:market","reason":"hand routing"},
    {"from":"hand:market","to":"artifact:t1","reason":"returned artifact"},
    {"from":"brain","to":"review","reason":"quality review"}
  ],
  "profiles": {"market":{"agent_id":"market","capabilities":["market.analysis"],"status":"selected"}},
  "diagnostics": [{"type":"artifact_gap","object_ref":"artifact:t1","message":"missing liquidity analysis"}]
}
```

**用途**：用户可以看到 Brain 如何拆解任务、分配给哪些 hand、每个 hand 产出物的置信度和 gap 数。

---

## Step 5 — 确认修复有效（Confirmed Correction）

```bash
curl -s -X POST http://127.0.0.1:3002/corrections/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id":"<EPISODE_ID>",
    "analysis_id":"<INTENT_ANALYSIS_ID>",
    "comment":"Confirmed: WACC updated to Q1 2026. This repair is correct.",
    "reuse_scope":"task_pattern",
    "enabled":true
  }'
```

**Harness 内部**：
```
brain.py:4896 → /corrections/confirm
  → flywheel.append_confirmed_correction(episode_id, correction)
    → 写入 flywheel detail 的 confirmed_corrections 列表
    → reuse_scope="task_pattern" 表示此修复模式可在后续 episode 复用
```

查看所有已确认修正：
```bash
curl -s http://127.0.0.1:3002/corrections?limit=10 | python -m json.tool
```

---

## 用户交互总结

| 步骤 | 用户动作 | 交互点 | 流入 Harness | Harness 输出 |
|------|---------|--------|-------------|-------------|
| 1 | 提问 | CLI / API `/analyze` | Brain workflow | synthesis HTML → webview |
| 2 | 对 hand card 评分+写注释 | **thumbs-down + note + Submit** | `/feedback` → `ScopedFeedback` → `ContextualIntentCompiler` | `intent_lens` → widget 显示 summary |
| 3 | 触发修复 | API `/feedback/repair` | `_run_episode_repair` → `build_repair_plan` → `build_repair_task` → adapter invoke | 修复后的 artifact → webview 更新 |
| 4 | 查看调度 | 浏览器 URL `/orchestration/{id}` | `build_minimal_orchestration_snapshot` | nodes + edges + diagnostics |
| 5 | 确认修正 | API `/corrections/confirm` | `flywheel.append_confirmed_correction` | 持久化，reuse_scope 标记 |

**核心闭环**：用户反馈不是一次性信号——它被 `ContextualIntentCompiler` 编译为结构化的 `IntentDelta`（含 target、instruction、constraints），repair 路径直接消费这个 delta 来生成 agent 能理解的修复指令，确认后的修正可跨 episode 复用。
