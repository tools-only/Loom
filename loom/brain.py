"""Loom Brain — FastAPI service on port 3002.

Routes:
  POST /analyze { question, context?, domain_hint?, hands? }
                → { ok, synthesis, hand_artifacts, workflow_decision, cold_start }
  POST /run   { hand_id, task, context, runtime? }  →  { ok, hand_id, artifact }
  GET  /health                                       →  { ok, service, hands }
  GET  /resources/:id                                →  raw connector data (no policy)
  GET  /intent-stream                                →  intent stream UI page
  GET  /intent-stream/data                           →  intent events + derived context (JSON)
  GET  /feedback                                     →  raw feedback events
  POST /feedback                                     →  append feedback event
  GET  /hand/:id/config                              →  hand config
  PUT  /hand/:id/config                              →  write hand config
"""
from __future__ import annotations

import asyncio
import datetime
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel

from hand_registry import REGISTRY
from provider_client import read_config, write_config, get_client_for_brain
from bridge import patch_webview, get_connector_data
from timing_stats import compute_stages
from harness.eval_log import append_signal
from hands.market import MarketHand
from hands.sentiment import SentimentHand
from hands.target import TargetHand
from hands.position import PositionHand

# --- Loom Core in-process runtime ---
import sys
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loom_core.runtime.app import LoomCoreRuntime
from loom_core.agent_adapters.registry import create_adapter_registry
from loom_core.agent_adapters.providers import create_providers

_core = LoomCoreRuntime(root_dir=_ROOT)
_core.bootstrap()
_adapter_registry = create_adapter_registry()

# Register process-based providers (cc, codex, openclaw, herms, opencode)
for _pid, _info in create_providers().items():
    try:
        _adapter_registry.register(_info["instance"])
    except ValueError:
        pass

# Register SDK legacy adapters for each hand
from loom_core.agent_adapters.providers.sdk_legacy import create_provider as _sdk_create

HANDS = {
    "market":    MarketHand(),
    "sentiment": SentimentHand(),
    "target":    TargetHand(),
    "position":  PositionHand(),
}

from resource_disclosure import get_menu_for_hand


def _make_sdk_invoke(hand, hid: str):
    async def _invoke(task: dict) -> dict:
        task_str = task.get("task", "")
        ctx = task.get("context", {})
        menu = get_menu_for_hand(hid, ctx.get("tags", []))
        return await hand.run(task_str, ctx, menu)
    return _invoke


for _hid, _hand in HANDS.items():
    _prov = _sdk_create(
        adapter_id=f"sdk-{_hid}",
        invoke_fn=_make_sdk_invoke(_hand, _hid),
        capabilities=[f"{_hid}.analysis"],
        label=f"SDK Legacy — {_hid}",
    )
    try:
        _adapter_registry.register(_prov["instance"])
    except ValueError:
        pass

from loom_core.agent_adapters.cloud_bootstrap import register_cloud_adapters
register_cloud_adapters(_adapter_registry, _core, _ROOT)

# ── Brain agent wiring ────────────────────────────────────────────────────────
import sys as _sys
_loom_dir = Path(__file__).resolve().parent
if str(_loom_dir) not in _sys.path:
    _sys.path.insert(0, str(_loom_dir))

from brain_harness.base import BrainHarness
from brain_harness.dispatcher import WorkflowResolver
from brain_harness.distiller import ResourceDistiller
from brain_harness.intent_processor import IntentProcessor, IntentStream
from brain_harness.intent_wiki import IntentWiki
from loom_core.agents.core_agent import LoomCoreAgent

_brain_harness = BrainHarness(_ROOT)
_brain_client, _brain_model = get_client_for_brain()
_brain_resolver = WorkflowResolver(_ROOT, REGISTRY, _brain_client, _brain_model)
_brain_distiller = ResourceDistiller(_ROOT, _brain_client, _brain_model)
_intent_stream = IntentStream(_ROOT / "brain" / "context" / "intent-stream.jsonl")
_intent_processor = IntentProcessor(_ROOT, _brain_client, _brain_model)
_intent_wiki = IntentWiki(_ROOT)
_brain_harness.intent_wiki = _intent_wiki
_brain_harness._intent_stream = _intent_stream  # inject stream into harness prompt layer


async def _brain_hand_runner(hand_id: str, task: str, ctx: dict) -> dict:
    """Run a single hand for Brain's /analyze — reuses sdk path."""
    info = REGISTRY.get(hand_id, {})
    runtime = _mounted.get(hand_id) or info.get("runtime", "sdk")
    if runtime == "sdk":
        hand = HANDS.get(hand_id)
        if not hand:
            raise ValueError(f"unknown hand: {hand_id}")
        resource_menu = get_menu_for_hand(hand_id, ctx.get("tags", []))
        return await hand.run(task, ctx, resource_menu)
    adapter = _adapter_registry.find_by_id(runtime)
    if adapter is None:
        raise ValueError(f"unknown runtime adapter: {runtime}")
    envelope = {
        "task": task, "context": ctx, "hand_id": hand_id,
        "resource_api": "http://127.0.0.1:3001/resources",
    }
    artifact = None
    async for event in adapter.invoke(envelope):
        if event.get("type") == "run.artifact":
            artifact = event.get("artifact")
        elif event.get("type") == "run.error":
            raise RuntimeError(event.get("message", "adapter error"))
    if artifact is None:
        raise RuntimeError(f"hand {hand_id} returned no artifact")
    return artifact


_core_agent = LoomCoreAgent(
    _brain_harness, _brain_resolver, _brain_hand_runner, _brain_client, _brain_model
)

app = FastAPI(title="Loom Brain", version="0.3.0")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Tracks currently mounted external agents per hand: {hand_id: adapter_id}
_mounted: dict[str, str] = {}
_MOUNT_PATH = _ROOT / "loom" / "mounts.json"


def _load_mounts() -> None:
    """Restore mounts from disk so they survive Brain restarts."""
    if not _MOUNT_PATH.exists():
        print(f"[brain] mounts.json not found at {_MOUNT_PATH}", flush=True)
        return
    import json
    try:
        data = json.loads(_MOUNT_PATH.read_text(encoding="utf-8"))
        print(f"[brain] restoring {len(data)} mount(s) from {_MOUNT_PATH}", flush=True)
    except Exception:
        return
    for hand_id, entry in data.items():
        endpoint = entry.get("endpoint", "")
        desc = entry.get("description", "")
        timeout_s = entry.get("timeout_s", 90.0)
        auth_token = entry.get("auth_token", "") or None
        try:
            adapter_id = f"{hand_id}-mounted"
            system_prompt = _build_hand_system_prompt(hand_id, desc)
            from loom_core.agent_adapters.adapter import AgentAdapter
            adapter = AgentAdapter(
                adapter_id=adapter_id,
                transport="http",
                protocol="openai",
                endpoint=endpoint,
                auth_token=auth_token,
                timeout_s=timeout_s,
                system_prompt=system_prompt,
                capabilities=[f"{hand_id}.analysis"],
            )
            _adapter_registry.upsert(adapter)
            _mounted[hand_id] = adapter_id
        except Exception as e:
            print(f"[brain] failed to restore mount for {hand_id}: {e}", flush=True)


def _save_mounts() -> None:
    """Persist current mounts to disk."""
    import json
    data: dict = {}
    for hand_id, adapter_id in _mounted.items():
        adapter = _adapter_registry.find_by_id(adapter_id)
        if adapter:
            data[hand_id] = {
                "endpoint": adapter._endpoint,
                "description": "",
                "timeout_s": 90.0,
                "auth_token": adapter._auth_token or "",
            }
    try:
        _MOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MOUNT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[brain] failed to save mounts: {e}", flush=True)


def _register_mount_adapter(hand_id: str, endpoint: str, description: str,
                            timeout_s: float = 90.0, auth_token: str | None = None) -> str:
    """Create and register an AgentAdapter for a mounted hand. Returns adapter_id."""
    adapter_id = f"{hand_id}-mounted"
    system_prompt = _build_hand_system_prompt(hand_id, description)
    from loom_core.agent_adapters.adapter import AgentAdapter
    adapter = AgentAdapter(
        adapter_id=adapter_id,
        transport="http",
        protocol="openai",
        endpoint=endpoint,
        auth_token=auth_token,
        timeout_s=timeout_s,
        system_prompt=system_prompt,
        capabilities=[f"{hand_id}.analysis"],
    )
    _adapter_registry.upsert(adapter)
    return adapter_id


def _read_personal_context(hand_id: str) -> dict[str, str]:
    """Return {label: content} for SKILL.md + personal/ + fresh context/."""
    out: dict[str, str] = {}
    skill_md = _ROOT / "skills" / "investment-research-framework" / "SKILL.md"
    if skill_md.exists():
        out["skill_index"] = skill_md.read_text("utf-8")
    personal_dir = _ROOT / "hands" / hand_id / "personal"
    for fname in ["profile.md", "themes.md", "watchlist.md", "sources.md"]:
        p = personal_dir / fname
        if p.exists() and p.stat().st_size > 0:
            out[f"personal/{fname}"] = p.read_text("utf-8")
    notes = personal_dir / "learned-notes.md"
    if notes.exists() and notes.stat().st_size > 0:
        txt = notes.read_text("utf-8")
        out["personal/learned-notes.md"] = txt[-4000:]
    snap = _ROOT / "hands" / hand_id / "context" / "regime-snapshot.md"
    if snap.exists() and (time.time() - snap.stat().st_mtime) < 86400:
        out["context/regime-snapshot.md"] = snap.read_text("utf-8")
    return out


def _format_personal_block(personal: dict[str, str]) -> str:
    """Format personal context dict as markdown sections for prompt injection."""
    if not personal:
        return ""
    parts = ["\n\n---\n\n# Research Framework & User Context\n"]
    if "skill_index" in personal:
        parts.append(f"\n## Skill Index\n\n{personal['skill_index']}")
    for k, v in personal.items():
        if k != "skill_index":
            parts.append(f"\n\n## ({k})\n\n{v}")
    return "".join(parts)


def _build_hand_system_prompt(hand_id: str, description: str) -> str:
    info = REGISTRY.get(hand_id, {})
    label = info.get("label", hand_id)
    domain = info.get("description", "")
    user_note = f"\n\n## 用户说明\n{description.strip()}" if description.strip() else ""
    base = (
        f"你是 Loom Fin 的【{label}】hand agent。{user_note}\n\n"
        f"## 分析职责\n{domain}\n\n"
        "## 输出协议（严格遵守）\n"
        "分析完成后，输出 EXACTLY 一行 JSON：\n"
        '{"type":"run.artifact","artifact":{"metadata":{"resources_used":[...],"key_claims":[...],"gaps":[...]},"narrative":"..."}}\n\n'
        "- resources_used: 你访问的所有数据源名称\n"
        "- key_claims: 2-5 条有数据支撑的核心判断\n"
        "- gaps: 你需要但无法获取的数据\n"
        "- narrative: 2-4 段中文分析\n\n"
        "不要输出其他任何内容。"
    )
    return base + _format_personal_block(_read_personal_context(hand_id))


# Restore mounts on startup
_load_mounts()


def _render_brain_synthesis(synthesis: dict, workflow: dict, cold_start: bool) -> str:
    """Render Brain synthesis as an Anchor section card above hand cards."""
    stance = synthesis.get("stance", "n/a")
    confidence = synthesis.get("confidence", 0.0)
    key_drivers = synthesis.get("key_drivers", [])
    reversal = synthesis.get("reversal_condition", "")
    clarify = synthesis.get("clarifying_question")
    strategy_refs = synthesis.get("strategy_refs", [])
    domain = workflow.get("domain", "?")
    mode = workflow.get("mode", "?")
    rationale = workflow.get("rationale", "")

    stance_class = {"buy": "anc-pill--active", "hold": "anc-pill--review",
                    "reduce": "anc-pill--warn", "n/a": "anc-pill--edit"}.get(stance, "anc-pill--edit")
    stance_label = {"buy": "建议买入", "hold": "建议持有", "reduce": "建议减持", "n/a": "无明确立场"}.get(stance, stance)
    confidence_pct = int(confidence * 100)

    cold_html = ""
    if cold_start:
        cold_html = (
            '<div class="anc-pill-row">'
            '<span class="anc-pill anc-pill--warn">⚠ 使用系统默认策略</span></div>'
            '<p style="font-size:12px;color:var(--ink-muted)">补充 '
            '<code>brain/personal/strategy.md</code> 以个性化整合结论。</p>'
        )

    clarify_html = ""
    if clarify:
        clarify_html = (
            f'<div class="insight-box" style="border-left:3px solid var(--accent-amber)">'
            f'<strong>需要澄清：</strong> {clarify}</div>'
        )

    drivers_html = ""
    if key_drivers:
        items_parts = []
        for d in key_drivers:
            rule = d.get("rule", "")
            hand = d.get("hand", "?")
            claim = d.get("claim", "")
            items_parts.append(
                f'<li><code class="strategy-ref" title="strategy ref: {rule}">'
                f'[{hand}]</code> {claim}'
                f'<span class="strategy-tag">{rule}</span></li>'
            )
        items = "".join(items_parts)
        drivers_html = f'<h4>驱动因素</h4><ul class="risk-list">{items}</ul>'

    refs_html = ""
    if strategy_refs:
        tags = " ".join(f'<code>{r}</code>' for r in strategy_refs)
        refs_html = f'<p style="font-size:12px;color:var(--ink-muted)">策略引用：{tags}</p>'

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    return (
        f'<section class="anc-section anc-section--gc anc-section--aurora brain-synthesis" '
        f'data-anc="brain-synthesis" data-handles="refine,expand">'
        f'{cold_html}'
        f'<div class="anc-pill-row">'
        f'<span class="anc-pill anc-pill--gen">Brain 整合</span>'
        f'<span class="anc-pill {stance_class}">{stance_label}</span>'
        f'</div>'
        f'<h2>整合结论</h2>'
        f'<div class="brain-confidence">'
        f'<span>置信度 {confidence_pct}%</span>'
        f'<div class="confidence-bar"><div class="confidence-fill" style="width:{confidence_pct}%"></div></div>'
        f'</div>'
        f'{clarify_html}'
        f'{drivers_html}'
        f'{"<h4>反转条件</h4><blockquote>" + reversal + "</blockquote>" if reversal else ""}'
        f'{refs_html}'
        f'<p style="font-size:11px;color:var(--ink-muted)">'
        f'Domain: {domain} ({mode}) — {rationale} ｜ {ts}</p>'
        f'</section>'
    )


class AnalyzeRequest(BaseModel):
    question: str
    context: dict = {}
    domain_hint: str = ""
    hands: list[str] = []


class RunRequest(BaseModel):
    hand_id: str
    task: str
    context: dict = {}
    runtime: str = ""


class TimingRequest(BaseModel):
    timing: dict


class IntentCaptureRequest(BaseModel):
    input_type: str = "query"
    raw_input: str
    extra_context: str = ""
    session_id: str = ""
    anchor_op: str = ""
    anchor_id: str = ""
    anchor_kind: str = ""
    anchor_content: str = ""


@app.post("/timing/stages")
def timing_stages(body: TimingRequest):
    result = compute_stages(body.timing)
    return {"ok": True, **result}


async def _async_capture_intent(
    input_type: str,
    raw_input: str,
    extra_context: str = "",
    session_id: str = "",
    anchor_context: dict | None = None,
) -> None:
    try:
        event = await _intent_processor.parse(
            input_type, raw_input, extra_context, session_id, anchor_context
        )
        _intent_stream.append(event)
        _intent_wiki.ingest_event(event)
    except Exception:
        pass


@app.post("/intent/capture")
async def intent_capture(req: IntentCaptureRequest):
    """Fire-and-forget: queues async intent parse + stream append. Returns immediately."""
    anchor_context = None
    if req.anchor_op or req.anchor_id or req.anchor_content:
        anchor_context = {
            "anchor_op": req.anchor_op,
            "anchor_id": req.anchor_id,
            "anchor_kind": req.anchor_kind,
            "anchor_content": req.anchor_content[:2000],
        }
    asyncio.create_task(_async_capture_intent(
        req.input_type, req.raw_input, req.extra_context, req.session_id, anchor_context
    ))
    return {"ok": True}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Brain B-business: workflow resolve → parallel hands → synthesis → render."""
    ctx = dict(req.context)
    if req.domain_hint:
        ctx["domain_hint"] = req.domain_hint
    if req.hands:
        ctx["hands"] = req.hands
    print(f"[brain] /analyze question={req.question[:60]!r}", flush=True)

    # Parse intent concurrently with synthesis; stream uses PREVIOUS events for context
    intent_task = asyncio.create_task(
        _intent_processor.parse("query", req.question)
    )

    try:
        result = await _core_agent.analyze(req.question, ctx)
    except Exception as exc:
        intent_task.cancel()
        return {"ok": False, "error": str(exc)}

    # Store intent event after synthesis (available for next call)
    try:
        intent_event = await intent_task
        _intent_stream.append(intent_event)
        _intent_wiki.ingest_event(intent_event)
    except Exception:
        pass

    synthesis = result["synthesis"]
    wf = result["workflow_decision"]
    cold = result["cold_start"]

    brain_html = _render_brain_synthesis(synthesis, wf, cold)
    await patch_webview("brain-synthesis", brain_html)

    for hand_id, art in result["hand_artifacts"].items():
        info = REGISTRY.get(hand_id, {})
        anchor_id = info.get("anchor_id", hand_id)
        hand_html = _render_artifact(art, hand_id)
        await patch_webview(anchor_id, hand_html)

    return {"ok": True, **result}


class DistillRequest(BaseModel):
    text: str = ""
    url: str = ""
    source_author: str = ""
    source_date: str = ""


class FrameworkAcceptRequest(BaseModel):
    framework: dict


@app.post("/distill")
async def distill(req: DistillRequest):
    """Distill a resource (text or URL) into AnalyticalFramework candidates.

    Returns a list of framework candidates for user review (accept/edit/reject).
    Does NOT persist automatically — call /frameworks/accept to store.
    """
    import httpx as _httpx

    text = req.text.strip()
    if not text and req.url:
        try:
            async with _httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
                r = await c.get(req.url, headers={"User-Agent": "Mozilla/5.0 (compatible; LoomBrain/1.0)"})
            import re as _re
            raw = r.text
            raw = _re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=_re.DOTALL)
            raw = _re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=_re.DOTALL)
            raw = _re.sub(r"<[^>]+>", " ", raw)
            text = _re.sub(r"\s+", " ", raw).strip()[:12000]
        except Exception as e:
            return {"ok": False, "error": f"URL fetch failed: {e}", "candidates": []}

    if not text:
        return {"ok": False, "error": "provide text or url", "candidates": []}

    # Run framework distillation + intent parsing concurrently
    raw_label = req.url or req.source_author or text[:80]
    distill_task = asyncio.create_task(
        _brain_distiller.distill(
            text,
            source_url=req.url or None,
            source_author=req.source_author or None,
            source_date=req.source_date or None,
        )
    )
    intent_task = asyncio.create_task(
        _intent_processor.parse("resource_share", raw_label,
                                extra_context=f"author={req.source_author}")
    )

    candidates = await distill_task
    try:
        intent_event = await intent_task
        _intent_stream.append(intent_event)
        _intent_wiki.ingest_event(intent_event)
    except Exception:
        pass

    print(f"[brain] /distill → {len(candidates)} framework candidate(s)", flush=True)
    return {"ok": True, "candidates": candidates}


@app.post("/frameworks/accept")
async def frameworks_accept(req: FrameworkAcceptRequest):
    """Accept a distilled framework and persist it to brain/personal/frameworks.json."""
    fw = req.framework
    if not fw.get("framework_id") or not fw.get("name"):
        return {"ok": False, "error": "framework_id and name are required"}
    _brain_harness.state.append_framework(fw)
    total = len(_brain_harness.state._frameworks)
    print(f"[brain] /frameworks/accept id={fw['framework_id']!r} total={total}", flush=True)
    return {"ok": True, "framework_id": fw["framework_id"], "total_frameworks": total}


@app.get("/frameworks")
async def frameworks_list():
    """List all persisted analytical frameworks."""
    _brain_harness.state._reload()
    fws = _brain_harness.state._frameworks
    return {
        "ok": True,
        "count": len(fws),
        "frameworks": [
            {
                "framework_id": f.framework_id,
                "name": f.name,
                "confidence": f.confidence,
                "tags": f.tags,
                "key_variables": f.key_variables,
                "source_author": f.source_author,
                "distilled_at": f.distilled_at[:10],
            }
            for f in fws
        ],
    }


@app.get("/intent-stream/data")
async def intent_stream_data():
    """JSON API — full event log + derived context."""
    events = _intent_stream.all()
    derived = _intent_stream.derive_context()
    graph = _intent_wiki.graph()
    harness = _brain_harness.rewarded_intent_harness.snapshot()
    return {
        "ok": True,
        "total": len(events),
        "events": [
            {
                "ts": e.ts,
                "input_type": e.input_type,
                "raw_input": e.raw_input,
                "intent": e.intent,
                "anchor_context": e.anchor_context,
                "resource_intent": e.resource_intent,
                "session_id": e.session_id,
            }
            for e in reversed(events)  # newest first for UI
        ],
        "derived": derived,
        "intent_graph": graph,
        "intent_harness": harness,
    }


@app.get("/intent-graph/data")
async def intent_graph_data():
    """JSON API for the long-lived user intent graph."""
    return {"ok": True, **_intent_wiki.graph()}


@app.get("/intent-harness/data")
async def intent_harness_data():
    """JSON API for rewarded intent policies and latest reward signals."""
    return {"ok": True, **_brain_harness.rewarded_intent_harness.snapshot()}


@app.get("/intent-stream")
async def intent_stream_page():
    from fastapi.responses import HTMLResponse
    html = _INTENT_STREAM_PAGE
    return HTMLResponse(html)


_INTENT_STREAM_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intent Stream — Loom Brain</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600&family=Bricolage+Grotesque:wght@600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://unpkg.com/@phosphor-icons/web@2.1.1/src/index.js" crossorigin></script>
<style>
  :root {
    --ink: #1a1a2e;
    --ink-secondary: #4a4a6a;
    --ink-muted: #8a8aaa;
    --paper: #f8f7ff;
    --surface: #ffffff;
    --border: #e8e6f0;
    --radius-md: 12px;
    --radius-sm: 8px;
    --shadow-sm: 0 1px 4px rgba(80,60,160,.07);
    --shadow-md: 0 4px 16px rgba(80,60,160,.10);
    --font-display: 'Bricolage Grotesque', sans-serif;
    --font-body: 'Plus Jakarta Sans', sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
    --col-query: #4f8ef7;
    --col-resource: #2ecc8e;
    --col-strategy: #f59e0b;
    --col-feedback: #a855f7;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--font-body);
    background: var(--paper);
    color: var(--ink);
    min-height: 100vh;
    display: grid;
    grid-template-rows: 56px 1fr;
    grid-template-columns: 1fr 320px;
    grid-template-areas: "header header" "timeline sidebar";
  }

  /* ── Header ── */
  header {
    grid-area: header;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 24px;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: var(--shadow-sm);
  }
  header h1 {
    font-family: var(--font-display);
    font-size: 17px;
    font-weight: 700;
    letter-spacing: -.3px;
  }
  header .back-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 500;
    color: var(--ink-secondary);
    text-decoration: none;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid var(--border);
    cursor: pointer;
    background: none;
    transition: background .15s, color .15s;
  }
  header .back-btn:hover { background: var(--paper); color: var(--ink); }
  .filter-chips {
    display: flex;
    gap: 6px;
    margin-left: auto;
    align-items: center;
  }
  .chip {
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1.5px solid transparent;
    transition: all .15s;
    background: var(--paper);
    color: var(--ink-secondary);
    border-color: var(--border);
  }
  .chip.active-query  { background: #eff6ff; color: var(--col-query);    border-color: var(--col-query); }
  .chip.active-resource { background: #ecfdf5; color: var(--col-resource); border-color: var(--col-resource); }
  .chip.active-strategy { background: #fffbeb; color: var(--col-strategy); border-color: var(--col-strategy); }
  .chip.active-feedback { background: #faf5ff; color: var(--col-feedback); border-color: var(--col-feedback); }
  .chip.active-all { background: var(--ink); color: #fff; border-color: var(--ink); }
  .refresh-btn {
    margin-left: 8px;
    padding: 6px 14px;
    border-radius: 999px;
    border: 1.5px solid var(--border);
    background: none;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    color: var(--ink-secondary);
    display: flex;
    align-items: center;
    gap: 5px;
    transition: all .15s;
  }
  .refresh-btn:hover { background: var(--ink); color: #fff; border-color: var(--ink); }

  /* ── Timeline ── */
  #timeline {
    grid-area: timeline;
    padding: 24px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .event-card {
    background: var(--surface);
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
    padding: 16px 18px;
    box-shadow: var(--shadow-sm);
    border-left: 4px solid var(--border);
    transition: transform .1s, box-shadow .1s;
  }
  .event-card:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
  .event-card[data-type="query"]          { border-left-color: var(--col-query); }
  .event-card[data-type="resource_share"] { border-left-color: var(--col-resource); }
  .event-card[data-type="strategy_edit"]  { border-left-color: var(--col-strategy); }
  .event-card[data-type="feedback"]       { border-left-color: var(--col-feedback); }
  .event-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .type-badge {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 999px;
    letter-spacing: .3px;
    text-transform: uppercase;
  }
  [data-type="query"]          .type-badge { background: #eff6ff; color: var(--col-query); }
  [data-type="resource_share"] .type-badge { background: #ecfdf5; color: var(--col-resource); }
  [data-type="strategy_edit"]  .type-badge { background: #fffbeb; color: var(--col-strategy); }
  [data-type="feedback"]       .type-badge { background: #faf5ff; color: var(--col-feedback); }
  .event-ts {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--ink-muted);
    margin-left: auto;
  }
  .raw-input {
    font-size: 13px;
    font-weight: 500;
    color: var(--ink);
    margin-bottom: 10px;
    line-height: 1.5;
  }
  .anchor-context {
    margin-bottom: 10px;
    padding: 8px 10px;
    background: #f4f7fb;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }
  .anchor-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--ink-secondary);
    margin-bottom: 5px;
  }
  .anchor-preview {
    font-size: 12px;
    color: var(--ink-muted);
    line-height: 1.45;
    max-height: 3.1em;
    overflow: hidden;
  }
  .intent-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .intent-item {
    background: var(--paper);
    border-radius: var(--radius-sm);
    padding: 8px 10px;
  }
  .intent-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .5px;
    color: var(--ink-muted);
    margin-bottom: 3px;
  }
  .intent-value {
    font-size: 12px;
    color: var(--ink-secondary);
    line-height: 1.4;
  }
  .resource-intent {
    margin-top: 8px;
    padding: 8px 10px;
    background: #ecfdf580;
    border-radius: var(--radius-sm);
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  .resource-intent .ri-item {
    font-size: 11px;
  }
  .resource-intent .ri-label {
    font-weight: 700;
    color: var(--col-resource);
    margin-right: 4px;
  }
  .graph-zone {
    margin-bottom: 14px;
  }
  .graph-zone-title {
    font-size: 11px;
    font-weight: 700;
    color: var(--ink-secondary);
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: .5px;
  }
  .talent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 8px;
  }
  .talent-node {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: #f5f4fb;
    padding: 9px 10px;
    opacity: .58;
  }
  .talent-node.is-active {
    opacity: 1;
    background: #eff6ff;
    border-color: var(--col-query);
    box-shadow: 0 0 0 2px rgba(79,142,247,.12);
  }
  .talent-label {
    font-size: 12px;
    font-weight: 700;
    color: var(--ink);
    line-height: 1.35;
  }
  .talent-meta {
    margin-top: 5px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--ink-muted);
  }
  .reward-box {
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: #fbfcfe;
    padding: 10px;
    font-size: 12px;
    color: var(--ink-secondary);
  }
  .reward-score {
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 800;
    color: var(--ink);
    margin-bottom: 4px;
  }
  .policy-row {
    border-top: 1px solid var(--border);
    padding: 8px 0;
    font-size: 12px;
  }
  .policy-row:first-child { border-top: none; }
  .policy-weight {
    float: right;
    font-family: var(--font-mono);
    color: var(--ink-muted);
  }
  .empty-state {
    text-align: center;
    padding: 80px 24px;
    color: var(--ink-muted);
  }
  .empty-state i { font-size: 48px; margin-bottom: 12px; display: block; }
  .empty-state p { font-size: 14px; }

  /* ── Sidebar ── */
  #sidebar {
    grid-area: sidebar;
    background: var(--surface);
    border-left: 1px solid var(--border);
    padding: 20px;
    overflow-y: auto;
  }
  .sidebar-section { margin-bottom: 24px; }
  .sidebar-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .6px;
    color: var(--ink-muted);
    margin-bottom: 12px;
  }
  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .stat-row:last-child { border-bottom: none; }
  .stat-label { color: var(--ink-secondary); }
  .stat-value { font-weight: 700; font-family: var(--font-mono); font-size: 14px; }
  .decision-context {
    background: var(--paper);
    border-radius: var(--radius-sm);
    padding: 12px;
    font-size: 12px;
    color: var(--ink-secondary);
    line-height: 1.6;
    font-style: italic;
    border-left: 3px solid var(--col-query);
  }
  .pref-bar-row { margin-bottom: 10px; }
  .pref-bar-label {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    margin-bottom: 4px;
    color: var(--ink-secondary);
  }
  .pref-bar-track {
    height: 6px;
    background: var(--border);
    border-radius: 999px;
    overflow: hidden;
  }
  .pref-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #4f8ef7, #a855f7);
    border-radius: 999px;
    transition: width .4s;
  }
  .auto-badge {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 999px;
    background: #eff6ff;
    color: var(--col-query);
    margin-left: auto;
  }
</style>
</head>
<body>
<header>
  <button class="back-btn" onclick="window.open('http://localhost:3000','_self')">
    <i class="ph-bold ph-arrow-left"></i> Loom
  </button>
  <h1><i class="ph-bold ph-brain" style="margin-right:6px"></i>Intent Stream</h1>
  <div class="filter-chips">
    <button class="chip active-all" data-filter="all" onclick="setFilter('all',this)">All</button>
    <button class="chip" data-filter="query" onclick="setFilter('query',this)">Query</button>
    <button class="chip" data-filter="resource_share" onclick="setFilter('resource_share',this)">Resource</button>
    <button class="chip" data-filter="strategy_edit" onclick="setFilter('strategy_edit',this)">Strategy</button>
    <button class="chip" data-filter="feedback" onclick="setFilter('feedback',this)">Feedback</button>
    <button class="refresh-btn" onclick="loadData()"><i class="ph-bold ph-arrows-clockwise"></i> Refresh</button>
  </div>
</header>

<main id="timeline"><div class="empty-state"><i class="ph-bold ph-ghost"></i><p>No intent events yet. Run a query to see the stream.</p></div></main>

<aside id="sidebar">
  <div class="sidebar-section">
    <div class="sidebar-title">Intent Graph</div>
    <div id="intent-graph"></div>
  </div>
  <div class="sidebar-section">
    <div class="sidebar-title">Rewarded Harness</div>
    <div id="rewarded-harness"></div>
  </div>
  <div class="sidebar-section">
    <div class="sidebar-title">Overview</div>
    <div id="stats-rows"></div>
  </div>
  <div class="sidebar-section">
    <div class="sidebar-title">Active Decision Context</div>
    <div id="decision-context" class="decision-context" style="color:var(--ink-muted);font-style:normal">—</div>
  </div>
  <div class="sidebar-section">
    <div class="sidebar-title">Analytical Focus (resource shares)</div>
    <div id="pref-bars"></div>
  </div>
</aside>

<script>
  let _filter = 'all';
  let _data = null;

  async function loadData() {
    try {
      const r = await fetch('/intent-stream/data');
      _data = await r.json();
      render(_data);
    } catch(e) {
      console.error(e);
    }
  }

  function setFilter(f, el) {
    _filter = f;
    document.querySelectorAll('.chip').forEach(c => {
      c.className = 'chip';
      if (c.dataset.filter === f) c.classList.add('active-' + (f === 'all' ? 'all' : f.replace('_share','').replace('_edit','')));
    });
    if (_data) render(_data);
  }

  function fmtType(t) {
    return {query:'Query',resource_share:'Resource',strategy_edit:'Strategy Edit',feedback:'Feedback'}[t] || t;
  }

  function render(data) {
    // Timeline
    const tl = document.getElementById('timeline');
    const events = data.events.filter(e => _filter === 'all' || e.input_type === _filter);
    if (!events.length) {
      tl.innerHTML = '<div class="empty-state"><i class="ph-bold ph-ghost"></i><p>No events match this filter.</p></div>';
    } else {
      tl.innerHTML = events.map(e => {
        const ts = e.ts.slice(0,16).replace('T',' ');
        const intentItems = Object.entries(e.intent || {})
          .filter(([k,v]) => v)
          .map(([k,v]) => `<div class="intent-item"><div class="intent-label">${k.replace(/_/g,' ')}</div><div class="intent-value">${esc(v)}</div></div>`)
          .join('');
        const ri = e.resource_intent;
        const riBlock = ri ? `<div class="resource-intent">
          ${ri.engagement_type ? `<span class="ri-item"><span class="ri-label">engagement</span>${esc(ri.engagement_type)}</span>` : ''}
          ${ri.what_user_values ? `<span class="ri-item"><span class="ri-label">values</span>${esc(ri.what_user_values)}</span>` : ''}
          ${ri.author_signal ? `<span class="ri-item"><span class="ri-label">author</span>${esc(ri.author_signal)}</span>` : ''}
        </div>` : '';
        const ac = e.anchor_context || null;
        const acBlock = ac ? `<div class="anchor-context">
          <div class="anchor-meta">
            ${ac.anchor_id ? `<span>anchor:${esc(ac.anchor_id)}</span>` : ''}
            ${ac.anchor_op ? `<span>op:${esc(ac.anchor_op)}</span>` : ''}
            ${ac.anchor_kind ? `<span>kind:${esc(ac.anchor_kind)}</span>` : ''}
          </div>
          ${ac.anchor_content ? `<div class="anchor-preview">${esc(ac.anchor_content)}</div>` : ''}
        </div>` : '';
        return `<div class="event-card" data-type="${esc(e.input_type)}">
          <div class="event-header">
            <span class="type-badge">${fmtType(e.input_type)}</span>
            <span class="event-ts">${ts}</span>
          </div>
          <div class="raw-input">${esc(e.raw_input)}</div>
          ${acBlock}
          <div class="intent-grid">${intentItems}</div>
          ${riBlock}
        </div>`;
      }).join('');
    }

    renderIntentGraph(data.intent_graph || {});
    renderRewardedHarness(data.intent_harness || {});

    // Sidebar stats
    const counts = data.derived.counts || {};
    const total = data.derived.total || 0;
    const statsEl = document.getElementById('stats-rows');
    const rows = [['Total events', total], ...Object.entries(counts).map(([k,v])=>[fmtType(k), v])];
    statsEl.innerHTML = rows.map(([l,v]) => `<div class="stat-row"><span class="stat-label">${l}</span><span class="stat-value">${v}</span></div>`).join('');

    // Decision context
    const dc = document.getElementById('decision-context');
    if (data.derived.decision_context) {
      dc.style.cssText = '';
      dc.textContent = data.derived.decision_context;
    } else {
      dc.style.color = 'var(--ink-muted)';
      dc.style.fontStyle = 'normal';
      dc.textContent = 'No decision context captured yet.';
    }

    // Preference bars
    const prefs = data.derived.preferences || [];
    const pbEl = document.getElementById('pref-bars');
    if (!prefs.length) {
      pbEl.innerHTML = '<p style="font-size:12px;color:var(--ink-muted)">Share resources to build this profile.</p>';
    } else {
      pbEl.innerHTML = prefs.map(p => `<div class="pref-bar-row">
        <div class="pref-bar-label"><span>${esc(p.value)}</span><span>${p.count}x (${Math.round(p.strength*100)}%)</span></div>
        <div class="pref-bar-track"><div class="pref-bar-fill" style="width:${p.strength*100}%"></div></div>
      </div>`).join('');
    }
  }

  function renderIntentGraph(graph) {
    const el = document.getElementById('intent-graph');
    const zones = graph.zones || [];
    const nodes = graph.nodes || [];
    if (!nodes.length) {
      el.innerHTML = '<p style="font-size:12px;color:var(--ink-muted)">No long-lived intents yet. Interact with anchors, resources, or canvas prompts to grow the graph.</p>';
      return;
    }
    el.innerHTML = zones.map(z => {
      const zoneNodes = nodes.filter(n => n.zone === z.id);
      if (!zoneNodes.length) return '';
      return `<div class="graph-zone">
        <div class="graph-zone-title">${esc(z.label)}</div>
        <div class="talent-grid">
          ${zoneNodes.map(n => `<div class="talent-node ${n.is_active ? 'is-active' : ''}" title="${esc(n.principle)}">
            <div class="talent-label">${esc(n.label)}</div>
            <div class="talent-meta">${n.is_active ? 'active' : 'inactive'} · conf ${Math.round((n.confidence || 0)*100)}% · ev ${n.evidence_count || 0}</div>
          </div>`).join('')}
        </div>
      </div>`;
    }).join('');
  }

  function renderRewardedHarness(harness) {
    const el = document.getElementById('rewarded-harness');
    const reward = harness.latest_reward || null;
    const policies = harness.policies || [];
    const rewardHtml = reward ? `<div class="reward-box">
      <div class="reward-score">${Math.round((reward.overall_reward || 0) * 100)}%</div>
      <div>${esc(reward.diagnosis || '')}</div>
    </div>` : '<p style="font-size:12px;color:var(--ink-muted)">No reward episode yet. Run Brain analysis to populate policy rewards.</p>';
    const policyHtml = policies.slice(0, 5).map(p => `<div class="policy-row">
      <span>${esc(p.label)}</span>
      <span class="policy-weight">${Math.round((p.weight || 0) * 100)}%</span>
    </div>`).join('');
    el.innerHTML = rewardHtml + (policyHtml ? `<div style="margin-top:10px">${policyHtml}</div>` : '');
  }

  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  loadData();
  setInterval(loadData, 30000);
</script>
</body>
</html>"""


@app.post("/run")
async def run(req: RunRequest):
    info = REGISTRY.get(req.hand_id, {})
    # Mounted external agent takes priority over registry default
    runtime = req.runtime or _mounted.get(req.hand_id) or info.get("runtime", "sdk")
    print(f"[brain] /run hand={req.hand_id} runtime={runtime} task={req.task[:60]!r}", flush=True)

    if runtime == "sdk":
        # Legacy in-process SDK path
        hand = HANDS.get(req.hand_id)
        if not hand:
            return {"ok": False, "error": f"unknown hand: {req.hand_id}"}
        resource_menu = get_menu_for_hand(req.hand_id, req.context.get("tags", []))
        try:
            artifact = await hand.run(req.task, req.context, resource_menu)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        # Adapter-based path (cc, codex, sdk-<id>, etc.)
        adapter = _adapter_registry.find_by_id(runtime)
        if adapter is None:
            return {"ok": False, "error": f"unknown runtime adapter: {runtime}"}
        wiki_dir = info.get("wiki_dir", "")
        hand_dir = str(Path(wiki_dir).parent) if wiki_dir else ""
        personal = _read_personal_context(req.hand_id)
        # Inject into context so http×loom _build_snapshot forwards it to cloud agents.
        context_with_personal = {**req.context}
        if personal:
            context_with_personal["__personal__"] = personal
        envelope = {
            "task": req.task,
            "context": context_with_personal,
            "hand_id": req.hand_id,
            "hand_dir": hand_dir,
            "wiki_dir": wiki_dir,
            "resource_api": "http://127.0.0.1:3001/resources",
            "feedback_log": str(_ROOT / "logs" / "feedback.jsonl"),
            "personal": personal,  # top-level for process×loom agents (stdin JSON)
        }
        artifact = None
        try:
            async for event in adapter.invoke(envelope):
                if event.get("type") == "run.artifact":
                    artifact = event.get("artifact")
                elif event.get("type") == "run.error":
                    return {"ok": False, "error": event.get("message", "unknown error")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if artifact is None:
            return {"ok": False, "error": "adapter returned no artifact"}

    # Patch webview
    anchor_id = info.get("anchor_id", req.hand_id)
    html = _render_artifact(artifact, req.hand_id)
    await patch_webview(anchor_id, html)

    # Record eval signal (legacy harness)
    meta = artifact.get("metadata", {})
    append_signal(
        req.hand_id,
        req.task,
        req.context.get("tags", []),
        meta.get("resources_shown", []),
        meta.get("resources_used", []),
    )

    return {"ok": True, "hand_id": req.hand_id, "artifact": artifact}


@app.get("/resources/{resource_id:path}")
async def get_resource(resource_id: str, request: Request):
    params = dict(request.query_params)
    try:
        data = await get_connector_data(resource_id, params)
        return {"ok": True, "resource_id": resource_id, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/feedback")
async def get_feedback(hand_id: str = "", since: float = 0.0):
    events = _core.feedback_store.read(
        hand_id=hand_id or None,
        since=since or None,
    )
    return {"ok": True, "events": events}


@app.post("/feedback")
async def post_feedback(request: Request):
    body = await request.json()
    if not body:
        return {"ok": False, "error": "event body required"}
    _core.feedback_store.append(body)
    return {"ok": True}


@app.get("/hand/{hand_id}/config")
async def get_hand_config(hand_id: str):
    config = _core.hand_config_store.read(hand_id)
    return {"ok": True, "hand_id": hand_id, "config": config}


@app.put("/hand/{hand_id}/config")
async def put_hand_config(hand_id: str, request: Request):
    config = await request.json()
    _core.hand_config_store.write(hand_id, config)
    return {"ok": True, "hand_id": hand_id}


_TIER_A_B = {"fred", "sec-edgar", "finnhub", "yahoo-finance", "cftc-cot", "investing-calendar", "config.json"}
_TIER_C = {"reuters-rss", "marketwatch-rss", "cnbc-rss"}
_TIER_E_F = {"fear-greed", "aaii", "naaim", "stocktwits", "reddit", "kol-rss"}


def _source_authority(sources: list) -> tuple[str, str]:
    """Return (label, pill_class) based on highest-tier source present."""
    s = set(sources)
    if s & _TIER_A_B:
        return "权威数据", "anc-pill--done"
    if s & _TIER_C:
        return "新闻来源", "anc-pill--warn"
    if s & _TIER_E_F:
        return "情绪参考", "anc-pill--edit"
    return "来源未知", "anc-pill--edit"


def _render_artifact(artifact: dict, hand_id: str) -> str:
    meta = artifact.get("metadata", {})
    narrative = artifact.get("narrative", "")
    gaps = meta.get("gaps", [])
    key_claims = meta.get("key_claims", [])
    sources_used = meta.get("resources_used", [])

    authority_label, auth_class = _source_authority(sources_used)
    gaps_html = "".join(f"<li>{g}</li>" for g in gaps) or "<li>无明显数据缺口</li>"
    claims_html = "".join(f"<li>{c}</li>" for c in key_claims)
    sources_html = ", ".join(f"<code>{s}</code>" for s in sources_used) or "无"

    info = REGISTRY.get(hand_id, {})
    anchor_id = info.get("anchor_id", hand_id)
    label = info.get("label", hand_id)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<section class="anc-section anc-section--gc" data-anc="{anchor_id}" data-handles="refine,expand">
  <div class="anc-pill-row">
    <span class="anc-pill anc-pill--gen">AI 生成</span>
    <span class="anc-pill {auth_class}">{authority_label}</span>
  </div>
  <h2>{label}</h2>
  <div class="insight-box"><p>{narrative}</p></div>
  {('<h4>关键判断</h4><ul>' + claims_html + '</ul>') if claims_html else ''}
  <h4>数据缺口</h4>
  <ul class="risk-list">{gaps_html}</ul>
  <p>数据来源：{sources_html} ｜ {ts}</p>
</section>"""


class MountRequest(BaseModel):
    endpoint: str
    description: str = ""
    timeout_s: float = 90.0
    auth_token: str = ""


@app.post("/hand/{hand_id}/mount")
async def mount_agent(hand_id: str, req: MountRequest):
    if hand_id not in REGISTRY:
        return {"ok": False, "error": f"unknown hand: {hand_id}"}
    adapter_id = _register_mount_adapter(hand_id, req.endpoint, req.description,
                                          req.timeout_s, req.auth_token or None)
    _mounted[hand_id] = adapter_id
    _save_mounts()
    return {"ok": True, "hand_id": hand_id, "adapter_id": adapter_id}


@app.delete("/hand/{hand_id}/mount")
async def unmount_agent(hand_id: str):
    adapter_id = _mounted.pop(hand_id, None)
    if adapter_id:
        _adapter_registry.unregister(adapter_id)
    _save_mounts()
    return {"ok": True, "hand_id": hand_id, "unmounted": adapter_id}


@app.get("/hand/{hand_id}/mount")
async def get_mount(hand_id: str):
    adapter_id = _mounted.get(hand_id)
    if not adapter_id:
        return {"ok": True, "mounted": False}
    adapter = _adapter_registry.find_by_id(adapter_id)
    return {
        "ok": True,
        "mounted": True,
        "adapter_id": adapter_id,
        "endpoint": adapter._endpoint if adapter else None,
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "loom-brain",
        "hands": list(HANDS.keys()),
        "adapters": [a.id for a in _adapter_registry.list()],
        "mounted": dict(_mounted),
    }


@app.get("/review")
async def review():
    from harness.review import compute_review, run_daily_review
    data = compute_review(days=7)
    await run_daily_review()
    return {"ok": True, "review": data}


@app.get("/config")
def get_config():
    return read_config()


@app.put("/config")
@app.post("/config")
async def put_config(request: Request):
    try:
        cfg = await request.json()
        write_config(cfg)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
