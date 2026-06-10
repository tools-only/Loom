# Loom 信息数据架构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Loom card 增加 L0/L1/L2 三层信息架构，让用户可以看到 hand 抓取的原始素材（L0）、hand 归纳（L1）、Brain 状态推理（L2），并通过密度 level 系统自由切换信息密度。

**Architecture:** Artifact schema 升级为 `layers[]` 结构（同时保留 `sections[]` 兼容旧渲染路径），hand 执行层捕获 `raw_sources[]`，LLM 自报 `raw_items[]`，Brain 合成后生成独立 State Engine 卡，overlay 新增密度控制栏。

**Tech Stack:** Python / FastAPI（`loom/`），vanilla JS（`bridge/webview/`），现有 Bloom Design System CSS（无新依赖）

---

## File Map

| 文件 | 变更 |
|------|------|
| `loom/hands/base.py` | `_normalize_artifact()` shim；output contract；`run()` raw_sources 捕获；density 校验 |
| `loom/brain_harness/base.py` | Brain output contract 追加 3 字段 |
| `loom/brain.py` | `_build_state_engine()`；`_render_state_engine()`；`_render_raw_sources()`；`_render_raw_items()`；`_render_artifact()` 插入 L0；`/analyze` patch state-engine |
| `bridge/webview/loom-detail-overlay.js` | `_renderDensityBar()`；`_filterSectionsByDensity()`；`open()` 调用 |
| `loom/panel.html` | 预置 `brain-state-engine` anchor |
| `tests/test_hand_artifact_density.py` | 追加 raw_items + layers shim 测试 |
| `tests/test_loom_info_arch.py` | 新文件：state engine + raw rendering 测试 |

---

## Task 1: Artifact Schema Shim

**Files:**
- Modify: `loom/hands/base.py`
- Test: `tests/test_hand_artifact_density.py`

- [ ] **Step 1: 写失败测试 — layers↔sections 双向转换**

在 `tests/test_hand_artifact_density.py` 末尾追加：

```python
def test_normalize_populates_layers_from_sections(self):
    """Artifact with only sections[] gets layers[] populated by shim."""
    art = {
        "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
        "narrative": "test",
        "sections": [
            {"id": "summary", "title": "Summary", "summary": "s", "bullets": ["a"]},
            {"id": "analysis", "title": "Analysis", "summary": "a", "bullets": ["b"]},
        ],
        "evidence": [],
    }
    result = BaseHand._normalize_artifact(art)
    self.assertIn("layers", result)
    self.assertEqual(len(result["layers"]), 2)
    self.assertEqual(result["layers"][0]["layer_type"], "summary")
    self.assertEqual(result["layers"][1]["layer_type"], "analysis")

def test_normalize_populates_sections_from_layers(self):
    """Artifact with only layers[] gets sections[] populated by shim."""
    art = {
        "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
        "narrative": "test",
        "layers": [
            {"layer_id": "summary", "layer_type": "summary", "title": "Summary", "summary": "s", "items": [{"claim": "c"}]},
            {"layer_id": "gaps", "layer_type": "gaps", "title": "Gaps", "summary": "g", "items": [{"claim": "gap1"}]},
        ],
    }
    result = BaseHand._normalize_artifact(art)
    self.assertIn("sections", result)
    self.assertEqual(len(result["sections"]), 2)
    self.assertEqual(result["sections"][0]["id"], "summary")

def test_normalize_populates_evidence_from_evidence_layer(self):
    """evidence layer_type items are promoted to top-level evidence[]."""
    art = {
        "metadata": {"confidence": 0.8, "key_claims": [], "gaps": [], "source_notes": []},
        "narrative": "test",
        "layers": [
            {
                "layer_id": "evidence",
                "layer_type": "evidence",
                "title": "Evidence",
                "summary": "",
                "items": [
                    {"claim": "c1", "support": "s1", "source": "FRED", "source_tier": "A", "freshness": "today"}
                ],
            }
        ],
    }
    result = BaseHand._normalize_artifact(art)
    self.assertEqual(len(result.get("evidence", [])), 1)
    self.assertEqual(result["evidence"][0]["claim"], "c1")

def test_normalize_adds_raw_defaults(self):
    """_normalize_artifact adds empty raw_sources/raw_items when absent."""
    art = {
        "metadata": {"confidence": 0.5, "key_claims": [], "gaps": [], "source_notes": []},
        "narrative": "test",
        "sections": [],
        "evidence": [],
    }
    result = BaseHand._normalize_artifact(art)
    self.assertIn("raw_sources", result)
    self.assertIn("raw_items", result)
    self.assertEqual(result["raw_sources"], [])
    self.assertEqual(result["raw_items"], [])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v -k "normalize"
```

期望：4 tests FAIL — `_normalize_artifact` 还没有 shim 逻辑。

- [ ] **Step 3: 实现 shim**

在 `loom/hands/base.py` 的 `_normalize_artifact()` 方法（当前约 line 373）里，在现有 `key_claims` 和 `source_notes` normalize 逻辑**之后**追加：

```python
        # ── layers ↔ sections backward-compat shim ────────────────────────
        has_layers = isinstance(data.get("layers"), list) and bool(data.get("layers"))
        has_sections = isinstance(data.get("sections"), list) and bool(data.get("sections"))

        _LAYER_TYPE_MAP = {
            "summary": "summary", "evidence": "evidence",
            "analysis": "analysis", "gaps": "gaps",
        }

        if has_layers and not has_sections:
            # layers → sections (for old render path)
            sections: list[dict] = []
            evidence_from_layers: list[dict] = []
            for layer in data["layers"]:
                if not isinstance(layer, dict):
                    continue
                lt = layer.get("layer_type", "summary")
                if lt == "evidence":
                    evidence_from_layers.extend(layer.get("items") or [])
                else:
                    sections.append({
                        "id": layer.get("layer_id") or lt,
                        "title": layer.get("title") or lt,
                        "summary": layer.get("summary") or "",
                        "bullets": [
                            {"claim": item} if isinstance(item, str) else item
                            for item in (layer.get("items") or [])
                        ],
                    })
            data["sections"] = sections
            if evidence_from_layers and not data.get("evidence"):
                data["evidence"] = evidence_from_layers

        elif has_sections and not has_layers:
            # sections → layers (for new density render path)
            layers: list[dict] = []
            for sec in data.get("sections") or []:
                if not isinstance(sec, dict):
                    continue
                sid = sec.get("id") or ""
                lt = _LAYER_TYPE_MAP.get(sid, "summary")
                layers.append({
                    "layer_id": sid or lt,
                    "layer_type": lt,
                    "title": sec.get("title") or sid,
                    "summary": sec.get("summary") or "",
                    "items": [
                        {"claim": b} if isinstance(b, str) else b
                        for b in (sec.get("bullets") or [])
                    ],
                })
            data["layers"] = layers

        # ── raw defaults ──────────────────────────────────────────────────
        data.setdefault("raw_sources", [])
        data.setdefault("raw_items", [])

        return data
```

注意：在现有 `return data` 之前插入，删除原有的 `return data`。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v -k "normalize"
```

期望：4 tests PASS。

- [ ] **Step 5: 运行全套测试确认无回归**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v
```

期望：全部 PASS（包含原有 3 个测试）。

- [ ] **Step 6: Commit**

```bash
cd "D:/ai-native chrome" && git add loom/hands/base.py tests/test_hand_artifact_density.py
git commit -m "feat(artifact): layers↔sections shim + raw_sources/raw_items defaults"
```

---

## Task 2: raw_items Density Validation + Output Contract + raw_sources Capture

**Files:**
- Modify: `loom/hands/base.py`
- Test: `tests/test_hand_artifact_density.py`

- [ ] **Step 1: 写失败测试 — raw_items density gap**

在 `tests/test_hand_artifact_density.py` 末尾追加：

```python
def test_density_gap_caught_for_missing_raw_items(self):
    """Artifact with used resources but < 5 raw_items triggers density gap."""
    art = {
        "metadata": {
            "confidence": 0.8,
            "key_claims": ["c1", "c2", "c3"],
            "source_notes": [
                {"source": "fred", "tier": "A", "freshness": "today", "note": ""},
                {"source": "finnhub", "tier": "B", "freshness": "today", "note": ""},
                {"source": "reuters-rss", "tier": "C", "freshness": "today", "note": ""},
            ],
            "gaps": [],
        },
        "narrative": "test",
        "sections": [
            {"id": "summary", "title": "S", "summary": "s", "bullets": ["a", "b", "c"]},
            {"id": "evidence", "title": "E", "summary": "e", "bullets": ["a", "b", "c"]},
            {"id": "analysis", "title": "A", "summary": "a", "bullets": ["a", "b", "c"]},
            {"id": "gaps", "title": "G", "summary": "g", "bullets": ["a", "b", "c"]},
        ],
        "evidence": [
            {"claim": f"c{i}", "support": "s", "source": "fred",
             "source_tier": "A", "freshness": "today", "confidence": 0.8}
            for i in range(5)
        ],
        "raw_items": [],  # empty — should trigger gap
    }
    gaps = BaseHand._artifact_density_gaps(
        art,
        used_resources=["fred", "finnhub"],
        shown_resources=["fred", "finnhub"],
    )
    self.assertTrue(any("raw_items" in g for g in gaps))

def test_density_no_gap_with_sufficient_raw_items(self):
    """Artifact with >= 5 raw_items does not trigger raw_items density gap."""
    art = {
        "metadata": {
            "confidence": 0.8,
            "key_claims": ["c1", "c2", "c3"],
            "source_notes": [
                {"source": "fred", "tier": "A", "freshness": "today", "note": ""},
                {"source": "finnhub", "tier": "B", "freshness": "today", "note": ""},
                {"source": "reuters-rss", "tier": "C", "freshness": "today", "note": ""},
            ],
            "gaps": [],
        },
        "narrative": "test",
        "sections": [
            {"id": "summary", "title": "S", "summary": "s", "bullets": ["a", "b", "c"]},
            {"id": "evidence", "title": "E", "summary": "e", "bullets": ["a", "b", "c"]},
            {"id": "analysis", "title": "A", "summary": "a", "bullets": ["a", "b", "c"]},
            {"id": "gaps", "title": "G", "summary": "g", "bullets": ["a", "b", "c"]},
        ],
        "evidence": [
            {"claim": f"c{i}", "support": "s", "source": "fred",
             "source_tier": "A", "freshness": "today", "confidence": 0.8}
            for i in range(5)
        ],
        "raw_items": [
            {"item_type": "news", "title": f"News {i}", "source": "reuters-rss",
             "tier": "C", "published_at": "2026-06-11", "summary": "s", "relevance": "r"}
            for i in range(5)
        ],
    }
    gaps = BaseHand._artifact_density_gaps(
        art,
        used_resources=["fred", "finnhub"],
        shown_resources=["fred", "finnhub"],
    )
    self.assertFalse(any("raw_items" in g for g in gaps))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v -k "raw_items"
```

期望：2 tests FAIL。

- [ ] **Step 3: 在 `_artifact_density_gaps()` 追加 raw_items 校验**

在 `loom/hands/base.py` 的 `_artifact_density_gaps()` 方法末尾，在 `return gaps` 之前追加：

```python
        if used_resources and len(artifact.get("raw_items", []) or []) < 5:
            gaps.append("raw_items density low: fewer than 5 annotated raw items despite resource usage")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v -k "raw_items"
```

期望：2 tests PASS。

- [ ] **Step 5: 扩展 output contract — 加入 raw_items + layers**

在 `loom/hands/base.py` 的 `run()` 方法里，找到 `user_parts.append(` 开头的 output contract 字符串（约 line 158）。

将其中 `"sections"` 部分替换为 `"layers"` + 新增 `"raw_items"`：

把：
```python
            '  "sections": [\n'
            '    {"id":"summary", "title":"High-level judgment", "summary":"...", "bullets":["string bullet", {"claim":"sourced bullet","source":"FRED","tier":"A"}]},\n'
            '    {"id":"evidence", "title":"Evidence and data support", "summary":"...", "bullets":[...]},\n'
            '    {"id":"analysis", "title":"Detailed analysis", "summary":"...", "bullets":[...]},\n'
            '    {"id":"gaps", "title":"Coverage gaps", "summary":"...", "bullets":[...]}\n'
            "  ],\n"
            '  "evidence": [{"claim":"...", "support":"...", "source":"...", "source_tier":"A|B|C|D|E|F|G|unknown", "freshness":"...", "confidence":0.0}]\n'
```

改为：
```python
            '  "layers": [\n'
            '    {"layer_id":"summary",  "layer_type":"summary",  "title":"High-level judgment",    "summary":"...", "items":[{"claim":"sourced bullet","source":"FRED","tier":"A"}]},\n'
            '    {"layer_id":"evidence", "layer_type":"evidence", "title":"Evidence and data",       "summary":"...", "items":[{"claim":"...","support":"...","source":"...","source_tier":"A","freshness":"..."}]},\n'
            '    {"layer_id":"analysis", "layer_type":"analysis", "title":"Detailed analysis",       "summary":"...", "items":[{"claim":"...","source":"...","tier":"B"}]},\n'
            '    {"layer_id":"gaps",     "layer_type":"gaps",     "title":"Coverage gaps",           "summary":"...", "items":[{"claim":"gap description"}]}\n'
            "  ],\n"
            '  "raw_items": [\n'
            '    {"item_type":"data_point","label":"10Y Treasury","value":"4.52%","source":"FRED","tier":"A","freshness":"2026-06-10","relevance":"rate regime anchor"},\n'
            '    {"item_type":"news","title":"Fed holds rates","source":"Reuters","tier":"C","published_at":"2026-06-10","summary":"首句摘要","relevance":"supports regime assessment","url":""},\n'
            '    {"item_type":"tweet","author":"@handle","text":"原文","source":"web_search","tier":"E","published_at":"","relevance":"sentiment signal"},\n'
            '    {"item_type":"search_snippet","title":"标题","summary":"snippet","source":"web_search","tier":"C","published_at":"","relevance":"context"}\n'
            "  ],\n"
```

并在 minimum density 说明里追加：
```python
            "- raw_items: at least 5 entries covering sources used; data_point must have value field; all entries must have relevance.\n"
```

- [ ] **Step 6: 实现 raw_sources 捕获**

在 `loom/hands/base.py` 的 `run()` 方法里：

在 `used: list[str] = []` 行**之后**追加：
```python
        raw_sources: list[dict] = []
```

在 `fetch_resource` 分支（约 `rid = block.input.get("resource_id", "")` 之后，`data = await get_connector_data(...)` 之后）追加：
```python
                        raw_sources.append({
                            "resource_id": rid,
                            "fetched_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                            "content_type": "json",
                            "summary": BaseHand._summarize_raw(data),
                            "raw": data,
                        })
```

在 `fetch_url` 分支（`content = await _fetch_url(url)` 之后）追加：
```python
                        raw_sources.append({
                            "resource_id": "fetch_url",
                            "url": url,
                            "fetched_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                            "content_type": "html",
                            "raw": content,
                        })
```

在 `artifact = self._parse_artifact(final_text)` 行**之后**追加：
```python
        artifact["raw_sources"] = raw_sources
```

在 `BaseHand` 类里（`_density_score` 之后）追加静态方法：
```python
    @staticmethod
    def _summarize_raw(data) -> str:
        text = (
            __import__("json").dumps(data, ensure_ascii=False)
            if not isinstance(data, str)
            else data
        )
        return text[:200].rstrip() + ("…" if len(text) > 200 else "")
```

- [ ] **Step 7: 运行完整测试**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_hand_artifact_density.py -v
```

期望：全部 PASS。

- [ ] **Step 8: Commit**

```bash
cd "D:/ai-native chrome" && git add loom/hands/base.py tests/test_hand_artifact_density.py
git commit -m "feat(hand): raw_sources execution capture + raw_items output contract + density validation"
```

---

## Task 3: Brain Output Contract 扩展

**Files:**
- Modify: `loom/brain_harness/base.py`
- Test: 手动验证（Brain output contract 是 prompt string，无纯 Python 单元测试入口）

- [ ] **Step 1: 定位 output contract**

在 `loom/brain_harness/base.py` 的 `_assemble_prompt()` 方法里找到 Brain output contract 字符串（搜索 `"stance"`，约在 `brain.md` 加载之后的某个 `parts.append` 里，或在继承方法里）。

实际上 Brain 的 output contract 在 `loom_core/agents/core_agent.py`。先读：

```bash
cd "D:/ai-native chrome" && grep -n "stance\|reversal_condition\|key_drivers\|output contract\|Return.*JSON" loom_core/agents/core_agent.py | head -30
```

- [ ] **Step 2: 在 core_agent.py 里找到 synthesis prompt 并追加三字段**

读取 `loom_core/agents/core_agent.py` 找到 synthesis output contract（含 `stance`, `confidence`, `key_drivers`, `reversal_condition` 的那段字符串）。

在 `reversal_condition` 字段定义之后追加：

```
"regime_relevance": "当前 regime 为何使本次问题权重异常（≤80字符，无 regime 信号时填空字符串）",
"watch_conditions": ["需要持续监控的变量或事件，2-3条，无则空数组"],
"priority_signal": "本次分析的最高优先级信号，一句话（无明确信号时填空字符串）"
```

- [ ] **Step 3: Commit**

```bash
cd "D:/ai-native chrome" && git add loom_core/agents/core_agent.py
git commit -m "feat(brain): add regime_relevance/watch_conditions/priority_signal to synthesis contract"
```

---

## Task 4: Brain State Engine 数据构建 + 渲染

**Files:**
- Create: `tests/test_loom_info_arch.py`
- Modify: `loom/brain.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_loom_info_arch.py`：

```python
import unittest
from unittest.mock import MagicMock


class StateEngineTests(unittest.TestCase):

    def _make_goal(self, stances=None):
        from loom.brain_harness.goal_context import GoalContext, SynthesisSnapshot
        goal = GoalContext.new(goal_type="ad_hoc", title="Test Goal")
        for s in (stances or []):
            snap = SynthesisSnapshot(
                episode_id="ep-1",
                ts="2026-06-11T10:00:00Z",
                stance=s["stance"],
                confidence=s["confidence"],
                reversal_condition=s.get("reversal_condition", ""),
            )
            goal.append_synthesis(snap)
        return goal

    def test_build_state_engine_shape(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _build_state_engine

        goal = self._make_goal([
            {"stance": "hold", "confidence": 0.6},
            {"stance": "buy", "confidence": 0.75, "reversal_condition": "CPI > 4%"},
        ])

        fw_record = MagicMock()
        fw_record.episode_id = "ep-test"
        fw_record.domain = "equities"

        synthesis = {
            "stance": "buy",
            "confidence": 0.75,
            "key_drivers": [{"hand": "market", "claim": "rates falling", "rule": "rule-1"}],
            "regime_relevance": "pivot regime",
            "watch_conditions": ["CPI", "NFP"],
            "priority_signal": "Watch CPI next print",
        }

        result = _build_state_engine(goal, fw_record, synthesis, None, None)

        self.assertIn("goal", result)
        self.assertIn("flywheel", result)
        self.assertIn("intent_focus", result)
        self.assertIn("reward", result)
        self.assertIn("targeted_abstract", result)

        self.assertEqual(result["goal"]["title"], "Test Goal")
        self.assertEqual(len(result["goal"]["stance_history"]), 2)
        self.assertEqual(result["goal"]["stance_history"][-1]["stance"], "buy")
        self.assertEqual(result["goal"]["latest_reversal"], "CPI > 4%")
        self.assertEqual(result["flywheel"]["domain"], "equities")
        self.assertEqual(result["targeted_abstract"]["priority_signal"], "Watch CPI next print")
        self.assertEqual(result["targeted_abstract"]["watch_conditions"], ["CPI", "NFP"])

    def test_build_state_engine_handles_none_activation_and_reward(self):
        """_build_state_engine does not crash when activation/reward are None."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _build_state_engine

        goal = self._make_goal()
        fw_record = MagicMock()
        fw_record.episode_id = "ep-2"
        fw_record.domain = "macro"

        synthesis = {"stance": "n/a", "confidence": 0.0, "key_drivers": []}

        result = _build_state_engine(goal, fw_record, synthesis, None, None)
        self.assertEqual(result["intent_focus"]["active_nodes"], [])
        self.assertIsNone(result["reward"]["latest_score"])

    def test_render_state_engine_returns_html_with_key_elements(self):
        """_render_state_engine produces HTML with expected structure."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _build_state_engine, _render_state_engine
        from loom.brain_harness.goal_context import GoalContext

        goal = self._make_goal([{"stance": "buy", "confidence": 0.8, "reversal_condition": "CPI > 4%"}])
        fw_record = MagicMock()
        fw_record.episode_id = "ep-3"
        fw_record.domain = "equities"

        synthesis = {
            "stance": "buy",
            "confidence": 0.8,
            "key_drivers": [],
            "regime_relevance": "rate cut cycle",
            "watch_conditions": ["CPI", "PCE"],
            "priority_signal": "Monitor rate trajectory",
        }

        se = _build_state_engine(goal, fw_record, synthesis, None, None)
        html = _render_state_engine(se)

        self.assertIn('data-anc="brain-state-engine"', html)
        self.assertIn("状态推理", html)
        self.assertIn("Monitor rate trajectory", html)
        self.assertIn("anc-detail", html)


class RawRenderingTests(unittest.TestCase):

    def test_render_raw_sources_empty(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _render_raw_sources
        html = _render_raw_sources({"raw_sources": []})
        self.assertEqual(html, "")

    def test_render_raw_sources_with_json_entry(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _render_raw_sources
        art = {
            "raw_sources": [
                {
                    "resource_id": "fred",
                    "fetched_at": "2026-06-11T10:00:00Z",
                    "content_type": "json",
                    "summary": "10Y Treasury 4.52%",
                    "raw": {"rate": 4.52},
                }
            ]
        }
        html = _render_raw_sources(art)
        self.assertIn("fred", html)
        self.assertIn("10Y Treasury 4.52%", html)
        self.assertIn('data-layer-type="raw_source"', html)

    def test_render_raw_items_empty(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _render_raw_items
        html = _render_raw_items({"raw_items": []})
        self.assertEqual(html, "")

    def test_render_raw_items_news_and_data_point(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from loom.brain import _render_raw_items
        art = {
            "raw_items": [
                {
                    "item_type": "news",
                    "title": "Fed holds rates",
                    "source": "Reuters",
                    "tier": "C",
                    "published_at": "2026-06-10",
                    "summary": "Fed kept rates unchanged.",
                    "relevance": "regime signal",
                },
                {
                    "item_type": "data_point",
                    "label": "10Y Treasury",
                    "value": "4.52%",
                    "source": "FRED",
                    "tier": "A",
                    "freshness": "2026-06-10",
                    "relevance": "rate anchor",
                },
            ]
        }
        html = _render_raw_items(art)
        self.assertIn("Fed holds rates", html)
        self.assertIn("4.52%", html)
        self.assertIn('data-layer-type="raw_item"', html)
        self.assertIn("regime signal", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_loom_info_arch.py -v
```

期望：全部 FAIL — `_build_state_engine`, `_render_state_engine`, `_render_raw_sources`, `_render_raw_items` 还不存在。

- [ ] **Step 3: 实现 `_build_state_engine()` 和 `_confidence_delta()`**

在 `loom/brain.py` 的 `_render_brain_synthesis()` 函数**之前**（约 line 306）插入：

```python
def _confidence_delta(goal) -> float:
    """Return confidence change from second-to-last to last synthesis snapshot."""
    history = goal.synthesis_history if hasattr(goal, "synthesis_history") else []
    if len(history) < 2:
        return 0.0
    return round(history[-1].confidence - history[-2].confidence, 3)


def _build_state_engine(goal, fw_record, synthesis, intent_activation, reward_report) -> dict:
    history = goal.synthesis_history if hasattr(goal, "synthesis_history") else []
    latest_reversal = history[-1].reversal_condition if history else ""

    active_nodes = []
    decision_context = ""
    if intent_activation is not None:
        for item in (intent_activation.active_intents or [])[:4]:
            if isinstance(item, dict):
                active_nodes.append({
                    "label": item.get("label", ""),
                    "zone": item.get("zone", ""),
                    "confidence": item.get("confidence", 0.0),
                })
        decision_context = getattr(intent_activation, "decision_context", "") or ""

    reward_score = None
    reward_diagnosis = ""
    top_policies: list[dict] = []
    if reward_report is not None:
        reward_score = getattr(reward_report, "overall_reward", None)
        reward_diagnosis = getattr(reward_report, "diagnosis", "")
        pr = getattr(reward_report, "policy_rewards", {}) or {}
        top_policies = [
            {"label": k, "weight": v}
            for k, v in sorted(pr.items(), key=lambda x: x[1], reverse=True)[:3]
        ]

    return {
        "goal": {
            "goal_id": goal.goal_id,
            "title": goal.title,
            "episode_count": len(goal.episode_ids),
            "stance_history": [
                {"ts": s.ts[:10], "stance": s.stance, "confidence": s.confidence}
                for s in history[-5:]
            ],
            "latest_reversal": latest_reversal,
            "confidence_delta": _confidence_delta(goal),
        },
        "flywheel": {
            "episode_id": fw_record.episode_id,
            "domain": fw_record.domain,
        },
        "intent_focus": {
            "active_nodes": active_nodes,
            "decision_context": decision_context,
        },
        "reward": {
            "latest_score": reward_score,
            "diagnosis": reward_diagnosis,
            "top_policies": top_policies,
        },
        "targeted_abstract": {
            "focus_variables": synthesis.get("key_drivers", [])[:3],
            "regime_relevance": synthesis.get("regime_relevance", ""),
            "watch_conditions": synthesis.get("watch_conditions", []),
            "priority_signal": synthesis.get("priority_signal", ""),
        },
    }
```

- [ ] **Step 4: 实现 `_render_state_engine()`**

在 `_build_state_engine()` 函数之後插入：

```python
def _render_state_engine(state_engine: dict) -> str:
    ta = state_engine.get("targeted_abstract", {})
    goal = state_engine.get("goal", {})
    flywheel = state_engine.get("flywheel", {})
    intent = state_engine.get("intent_focus", {})
    reward = state_engine.get("reward", {})

    priority = _html_text(ta.get("priority_signal", ""))
    regime = _html_text(ta.get("regime_relevance", ""))
    watch = ta.get("watch_conditions", [])
    watch_html = "".join(f"<li>{_html_text(w)}</li>" for w in watch) if watch else ""

    title_short = _html_text((goal.get("title") or "Goal")[:40])
    delta = goal.get("confidence_delta", 0.0)
    delta_html = (
        f'<span style="color:var(--accent-green)">↑{abs(delta):.0%}</span>'
        if delta > 0 else
        f'<span style="color:var(--accent-rose)">↓{abs(delta):.0%}</span>'
        if delta < 0 else
        '<span style="color:var(--ink-muted)">→</span>'
    )

    # Stance history timeline
    history = goal.get("stance_history", [])
    history_html = "".join(
        f'<li><code>{_html_text(s["ts"])}</code> '
        f'{_html_text(s["stance"])} '
        f'<span style="color:var(--ink-muted)">{int(s["confidence"] * 100)}%</span></li>'
        for s in history
    )
    reversal_html = (
        f'<div class="anc-eval-block"><div class="anc-eval-label">Reversal condition</div>'
        f'{_html_text(goal.get("latest_reversal",""))}</div>'
        if goal.get("latest_reversal") else ""
    )

    # Intent focus
    nodes = intent.get("active_nodes", [])
    nodes_html = "".join(
        f'<div style="font-size:12px;padding:6px 8px;background:var(--paper);'
        f'border-radius:8px;border:1px solid var(--border)">'
        f'<strong>{_html_text(n["label"])}</strong>'
        f'<span style="float:right;font-size:11px;color:var(--ink-muted)">'
        f'{_html_text(n["zone"])}</span></div>'
        for n in nodes
    ) if nodes else "<p style='font-size:12px;color:var(--ink-muted)'>No active intent nodes.</p>"
    dc_html = (
        f'<p style="font-size:12px;color:var(--ink-secondary);margin-top:8px;'
        f'font-style:italic">{_html_text(intent.get("decision_context",""))}</p>'
        if intent.get("decision_context") else ""
    )

    # Reward & policy
    score = reward.get("latest_score")
    score_html = (
        f'<div style="font-family:var(--font-display);font-size:32px;font-weight:800">'
        f'{int(score * 100)}%</div>'
        if score is not None else
        '<p style="font-size:12px;color:var(--ink-muted)">No reward episode yet.</p>'
    )
    diagnosis_html = (
        f'<p style="font-size:12px;color:var(--ink-secondary);margin-top:6px">'
        f'{_html_text(reward.get("diagnosis",""))}</p>'
        if reward.get("diagnosis") else ""
    )
    policies_html = "".join(
        f'<div style="display:flex;justify-content:space-between;font-size:12px;'
        f'padding:6px 0;border-top:1px solid var(--border)">'
        f'<span>{_html_text(p["label"])}</span>'
        f'<span style="font-family:var(--font-mono);color:var(--ink-muted)">'
        f'{int(p["weight"] * 100)}%</span></div>'
        for p in reward.get("top_policies", [])
    )

    focus_vars = ta.get("focus_variables", [])
    fv_html = ""
    if focus_vars:
        items = []
        for d in focus_vars:
            if isinstance(d, dict):
                hand = _html_text(d.get("hand", ""))
                claim = _html_text(d.get("claim", ""))
                items.append(f"<li><code>[{hand}]</code> {claim}</li>")
        if items:
            fv_html = f'<h4>关键驱动因子</h4><ul class="risk-list">{"".join(items)}</ul>'

    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    return (
        f'<section class="anc-section anc-section--gc anc-section--aurora" '
        f'data-anc="brain-state-engine" data-handles="refine,expand" data-has-detail="true">'
        f'<div class="anc-pill-row">'
        f'<span class="anc-pill anc-pill--gen">Brain 状态</span>'
        f'<span class="anc-pill anc-pill--review">{title_short}</span>'
        f'{delta_html}'
        f'</div>'
        f'<h2>状态推理</h2>'
        f'{("<div class=\"insight-box\"><p>" + priority + "</p></div>") if priority else ""}'
        f'{("<p style=\"font-size:13px;color:var(--ink-secondary)\">" + regime + "</p>") if regime else ""}'
        f'{("<h4>持续监控</h4><ul>" + watch_html + "</ul>") if watch_html else ""}'
        f'{fv_html}'
        f'<p style="font-size:11px;color:var(--ink-muted)">'
        f'domain: {_html_text(flywheel.get("domain","?"))} ｜ {ts}</p>'
        f'<aside class="anc-detail" hidden>'
        f'<section class="anc-detail-section anc-detail-section--content" '
        f'data-detail-section="goal-track" data-detail-label="Goal Track">'
        f'<h3>Goal Track</h3>'
        f'{("<ul>" + history_html + "</ul>") if history_html else "<p style=\"font-size:12px;color:var(--ink-muted)\">No history yet.</p>"}'
        f'{reversal_html}'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Confidence Δ</div>{delta_html}</div>'
        f'</section>'
        f'<section class="anc-detail-section anc-detail-section--content" '
        f'data-detail-section="intent-focus" data-detail-label="Intent Focus">'
        f'<h3>Intent Focus</h3>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">{nodes_html}</div>'
        f'{dc_html}'
        f'</section>'
        f'<section class="anc-detail-section anc-detail-section--content" '
        f'data-detail-section="reward-policy" data-detail-label="Reward & Policy">'
        f'<h3>Reward & Policy</h3>'
        f'{score_html}{diagnosis_html}'
        f'<div style="margin-top:10px">{policies_html}</div>'
        f'</section>'
        f'<section class="anc-detail-section anc-detail-section--content" '
        f'data-detail-section="flywheel" data-detail-label="Flywheel">'
        f'<h3>Flywheel</h3>'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Episode</div>'
        f'{_html_text(flywheel.get("episode_id",""))}</div>'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Domain</div>'
        f'{_html_text(flywheel.get("domain",""))}</div>'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Episodes total</div>'
        f'{goal.get("episode_count", 0)}</div>'
        f'</section>'
        f'</aside>'
        f'</section>'
    )
```

- [ ] **Step 5: 运行测试**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_loom_info_arch.py -v -k "StateEngine"
```

期望：3 StateEngine tests PASS。

- [ ] **Step 6: 实现 `_render_raw_sources()` 和 `_render_raw_items()`**

在 `loom/brain.py` 的 `_render_artifact()` 函数**之前**插入：

```python
def _render_raw_sources(artifact: dict) -> str:
    sources = artifact.get("raw_sources") or []
    if not sources:
        return ""
    rows = []
    for src in sources[:20]:
        if not isinstance(src, dict):
            continue
        rid = _html_text(src.get("resource_id", "unknown"))
        ct = _html_text(src.get("content_type", ""))
        ts = _html_text((src.get("fetched_at") or "")[:19].replace("T", " "))
        summary = _html_text(src.get("summary", ""))
        raw_text = src.get("raw", "")
        if isinstance(raw_text, dict):
            raw_text = __import__("json").dumps(raw_text, ensure_ascii=False, indent=2)
        raw_escaped = _html_text(str(raw_text)[:2000])
        rows.append(
            f'<div style="margin-bottom:12px;padding:10px 12px;background:var(--paper);'
            f'border-radius:8px;border:1px solid var(--border)">'
            f'<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">'
            f'<code style="font-size:11px;background:#e8e6f0;padding:2px 7px;border-radius:4px">{rid}</code>'
            f'<span style="font-size:11px;color:var(--ink-muted)">{ct}</span>'
            f'<span style="font-size:11px;color:var(--ink-muted);margin-left:auto">{ts}</span>'
            f'</div>'
            f'<p style="font-size:12px;color:var(--ink-secondary);margin-bottom:6px">{summary}</p>'
            f'<details style="font-size:11px">'
            f'<summary style="cursor:pointer;color:var(--ink-muted)">展开原始内容</summary>'
            f'<pre style="overflow:auto;max-height:200px;font-size:10px;'
            f'background:#f8f7ff;padding:8px;border-radius:6px;margin-top:6px">{raw_escaped}</pre>'
            f'</details>'
            f'</div>'
        )
    return (
        '<section class="anc-detail-section anc-detail-section--raw" '
        'data-detail-section="raw-sources" data-detail-label="原始数据" '
        'data-layer-type="raw_source">'
        '<h3>原始数据</h3>'
        + "".join(rows) +
        '</section>'
    )


def _render_raw_items(artifact: dict) -> str:
    items = artifact.get("raw_items") or []
    if not items:
        return ""

    _TIER_CSS = {
        "A": "anc-tier-pill--a", "B": "anc-tier-pill--b",
        "C": "anc-tier-pill--c", "D": "anc-tier-pill--c",
        "E": "anc-tier-pill--e", "F": "anc-tier-pill--e",
        "G": "anc-tier-pill--e",
    }

    def _tier_pill(tier: str) -> str:
        t = str(tier).strip().upper()
        css = _TIER_CSS.get(t, "anc-tier-pill--e")
        return f'<span class="anc-tier-pill {css}">{_html_text(t)}</span> ' if t else ""

    rows = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        it = item.get("item_type", "news")
        tier_html = _tier_pill(item.get("tier", ""))
        relevance = _html_text(item.get("relevance", ""))
        rel_html = (
            f'<p style="font-size:11px;color:var(--ink-muted);font-style:italic;margin-top:4px">'
            f'{relevance}</p>'
            if relevance else ""
        )

        if it == "data_point":
            label = _html_text(item.get("label") or item.get("title") or "")
            value = _html_text(item.get("value") or "")
            freshness = _html_text(item.get("freshness") or "")
            rows.append(
                f'<div style="display:inline-flex;flex-direction:column;'
                f'background:var(--paper);border:1px solid var(--border);'
                f'border-radius:8px;padding:8px 12px;margin:4px">'
                f'{tier_html}'
                f'<span style="font-size:11px;color:var(--ink-secondary)">{label}</span>'
                f'<span style="font-family:var(--font-display);font-size:20px;font-weight:700">'
                f'{value}</span>'
                f'<span style="font-size:10px;color:var(--ink-muted)">{freshness}</span>'
                f'{rel_html}'
                f'</div>'
            )
        elif it == "tweet":
            author = _html_text(item.get("author") or "")
            text = _html_text(item.get("text") or "")
            pub = _html_text((item.get("published_at") or "")[:10])
            rows.append(
                f'<div style="padding:10px 12px;background:var(--paper);border-radius:8px;'
                f'border:1px solid var(--border);margin-bottom:8px">'
                f'<div style="display:flex;gap:8px;margin-bottom:4px">'
                f'{tier_html}<strong style="font-size:12px">{author}</strong>'
                f'<span style="font-size:11px;color:var(--ink-muted);margin-left:auto">{pub}</span>'
                f'</div>'
                f'<p style="font-size:12px;color:var(--ink-secondary)">{text}</p>'
                f'{rel_html}'
                f'</div>'
            )
        else:
            # news, blog, search_snippet, filing, custom
            title = _html_text(item.get("title") or item.get("label") or "")
            summary = _html_text(item.get("summary") or "")
            source = _html_text(item.get("source") or "")
            pub = _html_text((item.get("published_at") or "")[:10])
            url = item.get("url") or ""
            url_html = (
                f'<a href="{_html_text(url)}" style="font-size:11px;color:var(--ink-muted)" '
                f'target="_blank">↗</a>'
                if url else ""
            )
            rows.append(
                f'<div style="padding:10px 12px;background:var(--paper);border-radius:8px;'
                f'border:1px solid var(--border);margin-bottom:8px">'
                f'<div style="display:flex;gap:8px;align-items:center;margin-bottom:4px">'
                f'{tier_html}'
                f'<strong style="font-size:12px">{title}</strong>'
                f'{url_html}'
                f'</div>'
                f'<div style="font-size:11px;color:var(--ink-muted);margin-bottom:4px">'
                f'{source}{(" · " + pub) if pub else ""}'
                f'</div>'
                f'<p style="font-size:12px;color:var(--ink-secondary)">{summary}</p>'
                f'{rel_html}'
                f'</div>'
            )

    return (
        '<section class="anc-detail-section anc-detail-section--raw" '
        'data-detail-section="raw-items" data-detail-label="素材" '
        'data-layer-type="raw_item">'
        '<h3>素材</h3>'
        + "".join(rows) +
        '</section>'
    )
```

- [ ] **Step 7: 运行全部 RawRendering 测试**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/test_loom_info_arch.py -v
```

期望：全部 PASS。

- [ ] **Step 8: 在 `/analyze` 末尾追加 State Engine patch**

在 `loom/brain.py` 的 `/analyze` 函数里，找到：
```python
    brain_html = _render_brain_synthesis(synthesis, wf, cold, episode_id=episode_id, goal_id=goal_id)
    await patch_webview("brain-synthesis", brain_html)
```

在其后追加：
```python
    try:
        state_engine_data = _build_state_engine(
            goal, fw_record, synthesis,
            _brain_harness._last_intent_activation,
            _brain_harness._last_reward_report,
        )
        state_engine_html = _render_state_engine(state_engine_data)
        await patch_webview("brain-state-engine", state_engine_html)
    except Exception as exc:
        print(f"[brain] state-engine render error: {exc}", flush=True)
```

- [ ] **Step 9: Commit**

```bash
cd "D:/ai-native chrome" && git add loom/brain.py tests/test_loom_info_arch.py
git commit -m "feat(brain): State Engine card + raw_sources/raw_items rendering"
```

---

## Task 5: L0 插入 Hand Card + panel.html anchor

**Files:**
- Modify: `loom/brain.py`
- Modify: `loom/panel.html`

- [ ] **Step 1: 在 `_render_artifact()` 里插入 L0 区块**

在 `loom/brain.py` 的 `_render_artifact()` 函数里，找到：
```python
    detail_sections_html = _render_artifact_sections(artifact, narrative, claims_html)
    evidence_html = _render_evidence_section(artifact)
    source_notes_html = _render_source_notes(meta, sources_html)
```

在其后追加：
```python
    raw_sources_html = _render_raw_sources(artifact)
    raw_items_html = _render_raw_items(artifact)
```

然后在 `overview_only` 分支的 aside 内容里，`{detail_sections_html}` 之前插入：
```python
f'    {raw_sources_html}\n'
f'    {raw_items_html}\n'
```

同样在非 `overview_only` 分支的 aside 里，`{detail_sections_html}` 之前插入：
```python
f'    {raw_sources_html}\n'
f'    {raw_items_html}\n'
```

- [ ] **Step 2: 在 panel.html 追加 brain-state-engine anchor**

在 `loom/panel.html` 里，找到现有的 brain-synthesis anchor（搜索 `brain-synthesis`）。如不存在，找到 hand cards 区域末尾。追加：

```html
<section class="anc-section anc-section--gc" 
         data-anc="brain-state-engine" 
         data-handles="refine,expand"
         style="min-height:48px">
  <!-- Brain 分析完成后由 State Engine 填充 -->
</section>
```

- [ ] **Step 3: 运行完整测试套件**

```bash
cd "D:/ai-native chrome" && python -m pytest tests/ -v --tb=short
```

期望：全部 PASS，无新失败。

- [ ] **Step 4: Commit**

```bash
cd "D:/ai-native chrome" && git add loom/brain.py loom/panel.html
git commit -m "feat(render): insert L0 raw blocks into hand card aside + panel anchor"
```

---

## Task 6: Density Level 系统（loom-detail-overlay.js）

**Files:**
- Modify: `bridge/webview/loom-detail-overlay.js`

- [ ] **Step 1: 在文件顶部（`'use strict';` 之后）插入密度系统常量和 API**

在 `var overlay = null;` 之前插入：

```javascript
  // ── Density level system ──────────────────────────────────────────────
  var DENSITY_LEVELS = {
    L0: ['raw_source', 'raw_item'],
    L1: ['summary', 'evidence', 'analysis', 'gaps'],
    L2: ['state_engine'],
  };

  var _density = {
    level: localStorage.getItem('loom.density.level') || 'L1',
    overrides: JSON.parse(localStorage.getItem('loom.density.overrides') || '{}'),
    customLayers: JSON.parse(localStorage.getItem('loom.density.custom_layers') || '[]'),
  };

  var LoomDensity = {
    registerLayer: function(cfg) {
      var existing = _density.customLayers.find(function(l) { return l.layer_type === cfg.layer_type; });
      if (!existing) {
        _density.customLayers.push(cfg);
        localStorage.setItem('loom.density.custom_layers', JSON.stringify(_density.customLayers));
      }
    },
    setLevel: function(level) {
      _density.level = level;
      localStorage.setItem('loom.density.level', level);
    },
    toggle: function(layer_type, visible) {
      _density.overrides[layer_type] = visible;
      localStorage.setItem('loom.density.overrides', JSON.stringify(_density.overrides));
    },
    isVisible: function(layer_type) {
      if (layer_type in _density.overrides) return _density.overrides[layer_type];
      var preset = DENSITY_LEVELS[_density.level] || DENSITY_LEVELS['L1'];
      // custom layers: check default_level
      var custom = _density.customLayers.find(function(l) { return l.layer_type === layer_type; });
      if (custom) {
        var customPreset = DENSITY_LEVELS[custom.default_level] || [];
        return customPreset.indexOf(layer_type) !== -1;
      }
      return preset.indexOf(layer_type) !== -1;
    },
  };
  window.LoomDensity = LoomDensity;
```

- [ ] **Step 2: 实现 `_renderDensityBar()`**

在 `function init(config)` 之前插入：

```javascript
  function _renderDensityBar(overlayEl) {
    var existing = overlayEl.querySelector('.loom-density-bar');
    if (existing) existing.remove();

    var bar = document.createElement('div');
    bar.className = 'loom-density-bar';
    bar.style.cssText = (
      'display:flex;align-items:center;gap:6px;padding:8px 16px;' +
      'border-bottom:1px solid var(--border,#e8e6f0);flex-wrap:wrap'
    );

    // Level buttons
    ['L0', 'L1', 'L2'].forEach(function(lvl) {
      var btn = document.createElement('button');
      btn.textContent = lvl;
      btn.dataset.level = lvl;
      btn.style.cssText = (
        'padding:3px 10px;border-radius:999px;border:1.5px solid #e8e6f0;' +
        'font-size:11px;font-weight:700;cursor:pointer;background:' +
        (_density.level === lvl ? '#7A5AF8' : 'transparent') + ';' +
        'color:' + (_density.level === lvl ? '#fff' : '#6b7280')
      );
      btn.addEventListener('click', function() {
        LoomDensity.setLevel(lvl);
        _renderDensityBar(overlayEl);
        _filterSectionsByDensity(overlayEl);
      });
      bar.appendChild(btn);
    });

    // Custom toggle
    var sep = document.createElement('span');
    sep.style.cssText = 'width:1px;height:16px;background:#e8e6f0;margin:0 4px';
    bar.appendChild(sep);

    var customBtn = document.createElement('button');
    customBtn.textContent = '自定义 ▾';
    customBtn.style.cssText = (
      'padding:3px 10px;border-radius:999px;border:1.5px solid #e8e6f0;' +
      'font-size:11px;font-weight:600;cursor:pointer;background:transparent;color:#6b7280'
    );
    var customPanel = document.createElement('div');
    customPanel.style.cssText = (
      'display:none;position:absolute;background:#fff;border:1px solid #e8e6f0;' +
      'border-radius:10px;padding:12px;box-shadow:0 4px 16px rgba(80,60,160,.10);' +
      'z-index:100;min-width:200px;margin-top:4px;flex-direction:column;gap:8px'
    );

    var allTypes = Object.values(DENSITY_LEVELS).reduce(function(a, b) { return a.concat(b); }, []);
    _density.customLayers.forEach(function(cl) {
      if (allTypes.indexOf(cl.layer_type) === -1) allTypes.push(cl.layer_type);
    });
    var LABELS = {
      raw_source: '原始数据', raw_item: '媒体/推文',
      summary: 'Hand 归纳', evidence: '证据行',
      analysis: '深度分析', gaps: '数据缺口',
      state_engine: 'Brain 分析',
    };

    allTypes.forEach(function(lt) {
      var row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = LoomDensity.isVisible(lt);
      cb.addEventListener('change', function() {
        LoomDensity.toggle(lt, cb.checked);
        _filterSectionsByDensity(overlayEl);
      });
      row.appendChild(cb);
      row.appendChild(document.createTextNode(LABELS[lt] || lt));
      customPanel.appendChild(row);
    });

    customBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      customPanel.style.display = customPanel.style.display === 'none' ? 'flex' : 'none';
    });
    document.addEventListener('click', function() { customPanel.style.display = 'none'; }, { once: true });

    var wrap = document.createElement('div');
    wrap.style.position = 'relative';
    wrap.appendChild(customBtn);
    wrap.appendChild(customPanel);
    bar.appendChild(wrap);

    // Insert after overlay header (first child)
    var header = overlayEl.querySelector('.loom-detail-header, [class*="header"]');
    if (header && header.nextSibling) {
      overlayEl.insertBefore(bar, header.nextSibling);
    } else {
      overlayEl.insertBefore(bar, overlayEl.firstChild);
    }
  }

  function _filterSectionsByDensity(overlayEl) {
    var sections = overlayEl.querySelectorAll('[data-layer-type]');
    sections.forEach(function(sec) {
      var lt = sec.getAttribute('data-layer-type');
      sec.style.display = LoomDensity.isVisible(lt) ? '' : 'none';
    });
  }
```

- [ ] **Step 3: 在 `open()` 函数末尾调用密度系统**

在 `loom-detail-overlay.js` 的 `open()` 函数里，找到最后一个 `return;` 或函数末尾，追加：

```javascript
    _renderDensityBar(overlay);
    _filterSectionsByDensity(overlay);
```

- [ ] **Step 4: 手动验证**

启动 Anchor service，运行一次 Brain analyze，打开任意 hand card overlay：

1. 检查 overlay header 下方出现 `[L0] [L1] [L2] [自定义▾]` 控制栏
2. L1（默认）时：看到 Detail/Sources/Hand Eval，看不到原始数据/素材
3. 切换到 L0：看到原始数据和素材 section，不看到 summary/analysis
4. 自定义▾展开：每个 layer_type 有对应 checkbox
5. 选择持久化：刷新页面后 level 保持

- [ ] **Step 5: Commit**

```bash
cd "D:/ai-native chrome" && git add bridge/webview/loom-detail-overlay.js
git commit -m "feat(overlay): L0/L1/L2 density level bar + custom layer toggles"
```

---

## 自检结果

**Spec coverage:**
- [x] L0 raw_sources execution capture → Task 2
- [x] L0 raw_items LLM output → Task 2 (output contract)
- [x] layers↔sections shim → Task 1
- [x] raw_items density validation → Task 2
- [x] Brain output contract 3 new fields → Task 3
- [x] `_build_state_engine()` → Task 4
- [x] `_render_state_engine()` → Task 4
- [x] L0 in hand card aside → Task 5
- [x] brain-state-engine anchor in panel.html → Task 5
- [x] density bar + filter → Task 6
- [x] localStorage persistence → Task 6
- [x] `LoomDensity.registerLayer()` extension API → Task 6

**Type consistency:**
- `_build_state_engine` 签名与 `/analyze` 调用一致
- `_render_raw_sources` / `_render_raw_items` 接受 `artifact: dict`，与 `_render_artifact()` 内调用一致
- `synthesis_history` 属性名来自 `GoalContext` dataclass（已确认）
- `intent_activation.active_intents` 来自 `IntentActivation` dataclass（已确认）
