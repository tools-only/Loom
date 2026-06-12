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
import html
import json
import time
import urllib.parse
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

# Register brain-inline adapter (default executor for Brain-generated runtime
# hands). Uses the brain's own Anthropic client and model; the per-call
# system_prompt comes from Brain's AtomicTask spec via the envelope.
from loom_core.agent_adapters.providers.sdk_legacy import create_brain_inline_provider

_brain_client, _brain_model = get_client_for_brain()
_brain_inline_prov = create_brain_inline_provider(
    client=_brain_client,
    model=_brain_model,
)
_adapter_registry.upsert(_brain_inline_prov["instance"])

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
from brain_harness.goal_context import GoalContextStore
from brain_harness.flywheel import FlywheelRecord, FlywheelWriter
from loom_core.agents.core_agent import LoomCoreAgent
from brain_portfolio import PortfolioDataHub

_brain_harness = BrainHarness(_ROOT)
# _brain_client / _brain_model were initialized above for brain-inline adapter
_brain_resolver = WorkflowResolver(_ROOT, REGISTRY, _brain_client, _brain_model)
_brain_distiller = ResourceDistiller(_ROOT, _brain_client, _brain_model)
_intent_stream = IntentStream(_ROOT / "brain" / "context" / "intent-stream.jsonl")
_intent_processor = IntentProcessor(_ROOT, _brain_client, _brain_model)
_intent_wiki = IntentWiki(_ROOT)
_brain_harness.intent_wiki = _intent_wiki
_brain_harness._intent_stream = _intent_stream  # inject stream into harness prompt layer

_goal_store = GoalContextStore(_ROOT)
_flywheel = FlywheelWriter(_ROOT)
_portfolio_hub = PortfolioDataHub(_ROOT)


def _with_brain_portfolio_context(hand_id: str, context: dict) -> dict:
    """Attach Brain-owned, redacted portfolio context for portfolio-capable hands.

    Capability-based check: a hand receives portfolio context when its
    ``agentic_hand_spec`` declares ``portfolio`` in ``capabilities`` (or sets
    ``needs_portfolio: true``). The literal ``hand_id == "position"`` fallback
    is kept for backward compatibility during the runtime-hand transition.
    """
    spec = (context or {}).get("agentic_hand_spec", {}) or {}
    needs_portfolio = (
        "portfolio" in (spec.get("capabilities") or [])
        or bool(spec.get("needs_portfolio"))
        or hand_id == "position"  # backward compat during transition
    )
    if not needs_portfolio:
        return context
    payload = _portfolio_hub.build_hand_payload()
    if not payload.get("portfolio_summary", {}).get("position_count"):
        return context
    next_context = dict(context or {})
    next_context["portfolio_data"] = payload
    next_context["position_data"] = json.dumps(payload, ensure_ascii=False)
    next_context["data_policy"] = {
        "owner": "brain",
        "hand_visibility": "redacted_summary_only",
        "raw_user_data": "not_shared",
        "credentials": "not_shared",
    }
    tags = list(next_context.get("tags", []) or [])
    if "portfolio" not in tags:
        tags.append("portfolio")
    next_context["tags"] = tags
    return next_context


async def _brain_hand_runner(hand_id: str, task: str, ctx: dict) -> dict:
    """Run a single hand for Brain's /analyze — reuses sdk path.

    Routing precedence:
      1. ``hand_id in REGISTRY`` → existing SDK / mounted-adapter path
      2. ``hand_id in _mounted`` → existing mounted-adapter path
      3. Otherwise (Brain-generated runtime hand) → route to ``brain-inline``
         adapter using the spec's ``system_prompt`` (synthesized from the
         declared dimension when absent).
    """
    ctx = _with_brain_portfolio_context(hand_id, ctx)

    # Runtime-generated hand: not registered statically and not mounted.
    if hand_id not in REGISTRY and hand_id not in _mounted:
        spec = (ctx or {}).get("agentic_hand_spec", {}) or {}
        system_prompt = spec.get("system_prompt", "") or ""
        if not system_prompt:
            dimension = spec.get("dimension", "general") or "general"
            system_prompt = (
                f"You are a Brain-generated analysis agent for dimension: {dimension}. "
                "Produce a run.artifact JSON with narrative and metadata."
            )
        adapter = _adapter_registry.find_by_id("brain-inline")
        if adapter is None:
            raise RuntimeError("brain-inline adapter not registered")
        envelope = {
            "task": task,
            "context": ctx,
            "hand_id": hand_id,
            "system_prompt": system_prompt,
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


def _confidence_delta(goal) -> float:
    h = goal.synthesis_history
    if len(h) < 2:
        return 0.0
    return h[-1].confidence - h[-2].confidence


def _build_state_engine(goal, fw_record, synthesis, intent_activation, reward_report) -> dict:
    """Assemble Brain state engine dict from goal/flywheel/intent/reward."""
    stance_history = [
        {"stance": s.stance, "confidence": s.confidence, "ts": s.ts}
        for s in goal.synthesis_history
    ]
    latest_reversal = ""
    if goal.synthesis_history:
        latest_reversal = goal.synthesis_history[-1].reversal_condition or ""

    active_nodes = []
    if intent_activation is not None:
        active_nodes = intent_activation.active_intents or []

    latest_score = None
    if reward_report is not None:
        latest_score = reward_report.overall_reward

    return {
        "goal": {
            "goal_id": goal.goal_id,
            "title": goal.title,
            "goal_type": goal.goal_type,
            "status": goal.status,
            "stance_history": stance_history,
            "latest_reversal": latest_reversal,
            "episode_count": len(goal.episode_ids),
        },
        "flywheel": {
            "episode_id": fw_record.episode_id,
            "domain": fw_record.domain,
        },
        "intent_focus": {
            "active_nodes": active_nodes,
        },
        "reward": {
            "latest_score": latest_score,
        },
        "targeted_abstract": {
            "regime_relevance": synthesis.get("regime_relevance", ""),
            "watch_conditions": synthesis.get("watch_conditions", []),
            "priority_signal": synthesis.get("priority_signal", ""),
        },
    }


def _render_state_engine(state_engine: dict) -> str:
    """Render Brain State Engine as Anchor section card."""
    g = state_engine.get("goal", {})
    fw = state_engine.get("flywheel", {})
    intent_focus = state_engine.get("intent_focus", {})
    reward = state_engine.get("reward", {})
    targeted = state_engine.get("targeted_abstract", {})

    title = html.escape(g.get("title", ""))
    domain = html.escape(fw.get("domain", "?"))
    episode_id = html.escape(fw.get("episode_id", ""))
    status = g.get("status", "open")
    status_class = {"open": "anc-pill--active", "investigating": "anc-pill--review",
                    "concluded": "anc-pill--done"}.get(status, "anc-pill--gen")

    stance_history = g.get("stance_history", [])
    history_parts = []
    for s in stance_history[-5:]:
        sv = s.get("stance", "?")
        conf = int(s.get("confidence", 0) * 100)
        sc = {"buy": "anc-pill--active", "hold": "anc-pill--review",
              "reduce": "anc-pill--warn"}.get(sv, "anc-pill--edit")
        history_parts.append(f'<span class="anc-pill {sc}" style="font-size:10px">'
                              f'{html.escape(sv)} {conf}%</span>')
    history_html = ('<div class="anc-pill-row">' + "".join(history_parts) + '</div>'
                    if history_parts else "")

    latest_reversal = html.escape(g.get("latest_reversal", ""))
    reversal_html = (f'<blockquote style="font-size:12px">{latest_reversal}</blockquote>'
                     if latest_reversal else "")

    priority_signal = html.escape(targeted.get("priority_signal", ""))
    priority_html = (
        f'<div class="insight-box" style="border-left:3px solid var(--accent-iris)">'
        f'<strong>优先信号：</strong> {priority_signal}</div>'
    ) if priority_signal else ""

    watch = targeted.get("watch_conditions", [])
    watch_html = ""
    if watch:
        items = "".join(f"<li>{html.escape(str(w))}</li>" for w in watch)
        watch_html = f"<ul>{items}</ul>"

    regime = html.escape(targeted.get("regime_relevance", ""))
    regime_html = f'<p style="font-size:12px;color:var(--ink-muted)">{regime}</p>' if regime else ""

    active_nodes = intent_focus.get("active_nodes", [])
    intents_html = ""
    if active_nodes:
        items = "".join(
            f'<li>{html.escape(str(n.get("label", n.get("intent_id", "?"))))}</li>'
            for n in active_nodes[:5]
        )
        intents_html = f"<ul>{items}</ul>"

    latest_score = reward.get("latest_score")
    reward_html = ""
    if latest_score is not None:
        pct = int(latest_score * 100)
        reward_html = (
            f'<div class="anc-eval-block"><div class="anc-eval-label">Reward</div>'
            f'<div class="confidence-bar"><div class="confidence-fill" style="width:{pct}%">'
            f'</div></div> {pct}%</div>'
        )

    episode_count = g.get("episode_count", 0)

    return (
        f'<section class="anc-section anc-section--gc brain-state-engine" '
        f'data-anc="brain-state-engine" data-handles="refine" data-has-detail="true">'
        f'<div class="anc-pill-row">'
        f'<span class="anc-pill anc-pill--gen">状态推理</span>'
        f'<span class="anc-pill {status_class}">{html.escape(status)}</span>'
        f'</div>'
        f'<h2>{title}</h2>'
        f'{priority_html}'
        f'{regime_html}'
        f'<h4>观察变量</h4>{watch_html}'
        f'<h4>立场历史</h4>{history_html}'
        f'{"<h4>反转条件</h4>" + reversal_html if latest_reversal else ""}'
        f'<p style="font-size:11px;color:var(--ink-muted)">'
        f'Domain: {domain} — Episode #{episode_count} [{episode_id}]</p>'
        f'<aside class="anc-detail" hidden>'
        f'<section class="anc-detail-section" data-detail-section="intent-focus" '
        f'data-detail-label="Intent Focus"><h3>Intent Focus</h3>{intents_html}</section>'
        f'<section class="anc-detail-section" data-detail-section="reward" '
        f'data-detail-label="Reward"><h3>Reward</h3>{reward_html}</section>'
        f'</aside>'
        f'</section>'
    )


def _render_raw_sources(artifact: dict) -> str:
    """Render raw_sources as a raw detail section. Returns '' when empty."""
    sources = artifact.get("raw_sources") or []
    if not sources:
        return ""
    parts = []
    for s in sources:
        rid = html.escape(str(s.get("resource_id", "")))
        ts = html.escape(str(s.get("fetched_at", "")))
        ct = html.escape(str(s.get("content_type", "")))
        summary = html.escape(str(s.get("summary", "")))
        url = s.get("url", "")
        query = s.get("query", "")
        url_html = ""
        if url:
            url_str = html.escape(str(url))
            url_html = f'<br><a href="{url_str}" target="_blank" rel="noopener" style="font-size:11px;color:var(--accent-iris)">🔗 {url_str}</a>'
        if query:
            query_str = html.escape(str(query))
            url_html += f'<br><span style="font-size:11px;color:var(--ink-muted)">搜索词: {query_str}</span>'
        parts.append(
            f'<div class="anc-source-row" data-layer-type="raw_source">'
            f'<strong>{rid}</strong>'
            f'<span style="font-size:11px;color:var(--ink-muted)"> [{ct}] {ts}</span>'
            f'{url_html}'
            f'<p style="margin:2px 0 0">{summary}</p>'
            f'</div>'
        )
    return (
        f'<section class="anc-detail-section" data-detail-section="raw-sources" '
        f'data-detail-label="Raw Sources" data-layer-type="raw_source">'
        f'<h3>Raw Sources</h3>{"".join(parts)}'
        f'</section>'
    )


def _render_raw_items(artifact: dict) -> str:
    """Render raw_items as a raw detail section. Returns '' when empty."""
    items = artifact.get("raw_items") or []
    if not items:
        return ""
    parts = []
    for item in items:
        item_type = item.get("item_type", "")
        tier = html.escape(str(item.get("tier", "")))
        relevance = html.escape(str(item.get("relevance", "")))
        if item_type == "news":
            title_text = html.escape(str(item.get("title", "")))
            source = html.escape(str(item.get("source", "")))
            pub = html.escape(str(item.get("published_at", "")))
            summary = html.escape(str(item.get("summary", "")))
            item_url = item.get("url", "")
            title_html = (
                f'<a href="{html.escape(item_url)}" target="_blank" rel="noopener">{title_text}</a>'
                if item_url else f'<strong>{title_text}</strong>'
            )
            parts.append(
                f'<div class="anc-raw-item" data-layer-type="raw_item" data-item-type="news">'
                f'{title_html}'
                f'<span class="anc-pill anc-pill--review" style="font-size:10px">Tier {tier}</span>'
                f'<span style="font-size:11px;color:var(--ink-muted)"> {source} · {pub}</span>'
                f'<p style="margin:2px 0 0">{summary}</p>'
                f'<p style="font-size:11px;color:var(--accent-iris)">{relevance}</p>'
                f'</div>'
            )
        elif item_type == "data_point":
            label = html.escape(str(item.get("label", "")))
            value = html.escape(str(item.get("value", "")))
            source = html.escape(str(item.get("source", "")))
            freshness = html.escape(str(item.get("freshness", "")))
            parts.append(
                f'<div class="anc-raw-item" data-layer-type="raw_item" data-item-type="data_point">'
                f'<strong>{label}</strong>: <code>{value}</code>'
                f'<span class="anc-pill anc-pill--gen" style="font-size:10px">Tier {tier}</span>'
                f'<span style="font-size:11px;color:var(--ink-muted)"> {source} · {freshness}</span>'
                f'<p style="font-size:11px;color:var(--accent-iris)">{relevance}</p>'
                f'</div>'
            )
        else:
            text = html.escape(str(item.get("title", item.get("label", ""))))
            item_url = item.get("url", "")
            item_summary = html.escape(str(item.get("summary", item.get("text", ""))))
            title_html = (
                f'<a href="{html.escape(item_url)}" target="_blank" rel="noopener">{text}</a>'
                if item_url else f'<span>{text}</span>'
            )
            parts.append(
                f'<div class="anc-raw-item" data-layer-type="raw_item">'
                f'{title_html}'
                f'<span class="anc-pill anc-pill--review" style="font-size:10px">Tier {tier}</span>'
                f'{("<p style=\"margin:2px 0 0;font-size:12px\">" + item_summary + "</p>") if item_summary else ""}'
                f'<p style="font-size:11px;color:var(--accent-iris)">{relevance}</p>'
                f'</div>'
            )
    return (
        f'<section class="anc-detail-section" data-detail-section="raw-items" '
        f'data-detail-label="Raw Items" data-layer-type="raw_item">'
        f'<h3>Raw Items</h3>{"".join(parts)}'
        f'</section>'
    )


def _render_brain_synthesis(
    synthesis: dict, workflow: dict, cold_start: bool,
    episode_id: str = "", goal_id: str = "",
) -> str:
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

    ep_attrs = ""
    if episode_id:
        ep_attrs += f' data-episode-id="{episode_id}"'
    if goal_id:
        ep_attrs += f' data-goal-id="{goal_id}"'
    reversal_detail_html = (
        '<div class="anc-eval-block"><div class="anc-eval-label">Reversal condition</div>'
        + reversal + '</div>'
    ) if reversal else ''

    return (
        f'<section class="anc-section anc-section--gc anc-section--aurora brain-synthesis" '
        f'data-anc="brain-synthesis" data-handles="refine,expand" data-has-detail="true"{ep_attrs}>'
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
        f'<aside class="anc-detail" hidden>'
        f'<section class="anc-detail-section anc-detail-section--brain-eval" data-detail-section="brain-eval" data-detail-label="Brain Eval">'
        f'<h3>Brain Eval</h3>'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Confidence</div>{confidence_pct}%</div>'
        f'<div class="anc-eval-block"><div class="anc-eval-label">Stance</div>{stance}</div>'
        f'{reversal_detail_html}'
        f'</section>'
        f'<section class="anc-detail-section anc-detail-section--content" data-detail-section="reasoning" data-detail-label="Reasoning">'
        f'<h3>Reasoning</h3>{drivers_html}{refs_html}'
        f'</section>'
        f'</aside>'
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


class PortfolioSourceRequest(BaseModel):
    id: str = ""
    type: str = "local_file"
    name: str = ""
    api_token: str = ""
    oauth_token: str = ""
    access_token: str = ""
    document_id: str = ""
    sheet_name: str = ""
    database_id: str = ""
    page_id: str = ""
    sync_mode: str = "manual"
    file_name: str = ""
    mime_type: str = ""
    label: str = ""


class PortfolioImportTextRequest(BaseModel):
    text: str
    source_id: str = "manual"


class PortfolioImportFileRequest(BaseModel):
    file_name: str
    mime_type: str = ""
    content_base64: str
    source_id: str = "local-upload"


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


@app.get("/portfolio/sources")
async def portfolio_sources():
    return {"ok": True, "sources": _portfolio_hub.list_sources()}


@app.post("/portfolio/sources")
async def portfolio_source_upsert(req: PortfolioSourceRequest):
    source = _portfolio_hub.upsert_source(req.model_dump())
    return {"ok": True, "source": source, "sources": _portfolio_hub.list_sources()}


@app.get("/portfolio/snapshot")
async def portfolio_snapshot():
    return {"ok": True, "snapshot": _portfolio_hub.get_snapshot()}


@app.post("/portfolio/import-text")
async def portfolio_import_text(req: PortfolioImportTextRequest):
    snapshot = _portfolio_hub.import_position_text(req.text, source_id=req.source_id)
    return {"ok": True, "snapshot": snapshot, "hand_payload": _portfolio_hub.build_hand_payload()}


@app.post("/portfolio/import-file")
async def portfolio_import_file(req: PortfolioImportFileRequest):
    snapshot = _portfolio_hub.import_file(req.model_dump())
    return {"ok": True, "snapshot": snapshot, "hand_payload": _portfolio_hub.build_hand_payload()}


@app.get("/portfolio/hand-payload")
async def portfolio_hand_payload():
    return {"ok": True, "payload": _portfolio_hub.build_hand_payload()}


# ── OAuth 2.0 ─────────────────────────────────────────────────────────────────

_OAUTH_CLIENTS_PATH = _ROOT / "brain" / "oauth_clients.json"


def _load_oauth_clients() -> dict:
    try:
        return json.loads(_OAUTH_CLIENTS_PATH.read_text())
    except Exception:
        return {}


def _save_oauth_clients(data: dict) -> None:
    _OAUTH_CLIENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OAUTH_CLIENTS_PATH.write_text(json.dumps(data, indent=2))


def _oauth_done_page(provider: str, source_id: str, ok: bool, error: str = "") -> str:
    safe_prov = html.escape(provider.title())
    msg_js = json.dumps({"ok": ok, "source_id": source_id, "provider": provider})
    if ok:
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>授权完成</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:320px}}
.icon{{font-size:48px;margin-bottom:16px}}h2{{margin:0 0 8px;color:#1a1a2e}}p{{color:#666;font-size:14px}}</style>
</head><body><div class="card"><div class="icon">✅</div><h2>授权成功</h2>
<p>已连接到 {safe_prov}，此窗口将自动关闭。</p></div>
<script>if(window.opener){{window.opener.postMessage({msg_js},'*')}}setTimeout(()=>window.close(),1500)</script>
</body></html>"""
    safe_err = html.escape(error)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>授权失败</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:320px}}
.icon{{font-size:48px;margin-bottom:16px}}h2{{margin:0 0 8px;color:#1a1a2e}}p{{color:#e53e3e;font-size:14px}}
button{{margin-top:16px;padding:8px 20px;border-radius:8px;border:1px solid #ddd;cursor:pointer}}</style>
</head><body><div class="card"><div class="icon">❌</div><h2>授权失败</h2>
<p>{safe_err}</p><button onclick="window.close()">关闭</button></div>
</body></html>"""


class OAuthClientRequest(BaseModel):
    provider: str
    client_id: str
    client_secret: str


@app.get("/oauth/clients")
async def oauth_clients_get():
    data = _load_oauth_clients()
    return {"ok": True, "clients": {p: {"configured": bool(cfg.get("client_id"))} for p, cfg in data.items()}}


@app.post("/oauth/clients")
async def oauth_clients_post(req: OAuthClientRequest):
    data = _load_oauth_clients()
    data[req.provider] = {"client_id": req.client_id, "client_secret": req.client_secret}
    _save_oauth_clients(data)
    return {"ok": True}


@app.get("/oauth/google/start")
async def oauth_google_start(source_id: str = ""):
    from fastapi.responses import RedirectResponse
    cfg = _load_oauth_clients().get("google", {})
    if not cfg.get("client_id"):
        return {"ok": False, "error": "Google OAuth not configured — POST /oauth/clients first"}
    qs = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": "http://localhost:3002/oauth/google/callback",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/spreadsheets.readonly https://www.googleapis.com/auth/drive.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": source_id,
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/auth?{qs}")


@app.get("/oauth/google/callback")
async def oauth_google_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import HTMLResponse
    if error or not code:
        return HTMLResponse(_oauth_done_page("google", state, ok=False, error=error or "authorization denied"))
    cfg = _load_oauth_clients().get("google", {})
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient() as client:
            r = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": "http://localhost:3002/oauth/google/callback",
                "grant_type": "authorization_code",
            })
        token = r.json()
    except Exception as exc:
        return HTMLResponse(_oauth_done_page("google", state, ok=False, error=str(exc)))
    if "access_token" not in token:
        return HTMLResponse(_oauth_done_page("google", state, ok=False, error=token.get("error_description", token.get("error", "token exchange failed"))))
    _portfolio_hub.upsert_source({
        "id": state, "type": "google_docs", "name": state,
        "access_token": token.get("access_token", ""),
        "oauth_token": token.get("refresh_token", ""),
    })
    return HTMLResponse(_oauth_done_page("google", state, ok=True))


@app.get("/oauth/notion/start")
async def oauth_notion_start(source_id: str = ""):
    from fastapi.responses import RedirectResponse
    cfg = _load_oauth_clients().get("notion", {})
    if not cfg.get("client_id"):
        return {"ok": False, "error": "Notion OAuth not configured — POST /oauth/clients first"}
    qs = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": "http://localhost:3002/oauth/notion/callback",
        "response_type": "code",
        "owner": "user",
        "state": source_id,
    })
    return RedirectResponse(f"https://api.notion.com/v1/oauth/authorize?{qs}")


@app.get("/oauth/notion/callback")
async def oauth_notion_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import HTMLResponse
    if error or not code:
        return HTMLResponse(_oauth_done_page("notion", state, ok=False, error=error or "authorization denied"))
    cfg = _load_oauth_clients().get("notion", {})
    try:
        import httpx as _httpx
        import base64 as _b64
        creds = _b64.b64encode(f'{cfg["client_id"]}:{cfg["client_secret"]}'.encode()).decode()
        async with _httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.notion.com/v1/oauth/token",
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
                json={"grant_type": "authorization_code", "code": code,
                      "redirect_uri": "http://localhost:3002/oauth/notion/callback"},
            )
        token = r.json()
    except Exception as exc:
        return HTMLResponse(_oauth_done_page("notion", state, ok=False, error=str(exc)))
    if "access_token" not in token:
        return HTMLResponse(_oauth_done_page("notion", state, ok=False, error=token.get("message", "token exchange failed")))
    _portfolio_hub.upsert_source({
        "id": state, "type": "notion", "name": state,
        "access_token": token.get("access_token", ""),
    })
    return HTMLResponse(_oauth_done_page("notion", state, ok=True))


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Brain B-business: workflow resolve → parallel hands → synthesis → render."""
    ctx = dict(req.context)
    if req.domain_hint:
        ctx["domain_hint"] = req.domain_hint
    if req.hands:
        ctx["hands"] = req.hands

    # Resolve or create a GoalContext for this request
    goal_id = ctx.get("goal_id", "")
    goal = None
    if goal_id:
        goal = _goal_store.load(goal_id)
    if goal is None:
        goal = _goal_store.create(
            goal_type=ctx.get("goal_type", "ad_hoc"),
            title=req.question[:80],
        )
        goal_id = goal.goal_id
    ctx["goal_id"] = goal_id

    print(f"[brain] /analyze question={req.question[:60]!r} goal={goal_id}", flush=True)

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
    presentation = result.get("presentation") or {}

    # Write flywheel record and link episode to goal
    try:
        fw_record = FlywheelRecord.new(
            goal_id=goal_id,
            question=req.question,
            domain=wf.get("domain", "") if wf else "",
            synthesis=synthesis,
            hand_artifacts=result.get("hand_artifacts", {}),
            cold_start=cold,
        )
        _flywheel.append_record(fw_record)
        goal.record_episode(fw_record.episode_id)
        if synthesis:
            from brain_harness.goal_context import SynthesisSnapshot
            goal.append_synthesis(SynthesisSnapshot(
                episode_id=fw_record.episode_id,
                ts=fw_record.ts,
                stance=synthesis.get("stance", "n/a"),
                confidence=synthesis.get("confidence", 0.0),
                key_drivers=[d.get("claim", "") for d in synthesis.get("key_drivers", [])],
                reversal_condition=synthesis.get("reversal_condition", ""),
            ))
        _goal_store.save(goal)
        episode_id = fw_record.episode_id
    except Exception as exc:
        print(f"[brain] flywheel write error: {exc}", flush=True)
        episode_id = ""

    brain_html = _render_brain_synthesis(synthesis, wf, cold, episode_id=episode_id, goal_id=goal_id)
    await patch_webview("brain-synthesis", brain_html)

    try:
        se_data = _build_state_engine(
            goal, fw_record, synthesis,
            _brain_harness._last_intent_activation,
            _brain_harness._last_reward_report,
        )
        await patch_webview("brain-state-engine", _render_state_engine(se_data))
    except Exception as _se_exc:
        print(f"[brain] state-engine render error: {_se_exc}", flush=True)

    for hand_id, art in result["hand_artifacts"].items():
        info = REGISTRY.get(hand_id, {})
        anchor_id = info.get("anchor_id", hand_id)
        # Error cards skip the Brain presentation layer — the enrichment function
        # produces the full card structure (error/impact/recovery sections) directly.
        # This ensures every card, even from a failed/unconfigured hand, follows
        # the same 5-dimensional framework as a successful hand card.
        if art.get("metadata", {}).get("error"):
            art = _enrich_error_artifact(art, hand_id)
            hand_html = _render_artifact(art, hand_id)
        else:
            hand_html = _render_artifact(
                _presentation_artifact_for_hand(presentation, hand_id, art),
                hand_id,
            )
        await patch_webview(anchor_id, hand_html)

    return {"ok": True, "episode_id": episode_id, "goal_id": goal_id, **result}


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
    context = _with_brain_portfolio_context(req.hand_id, req.context)
    # Mounted external agent takes priority over registry default
    runtime = req.runtime or _mounted.get(req.hand_id) or info.get("runtime", "sdk")
    print(f"[brain] /run hand={req.hand_id} runtime={runtime} task={req.task[:60]!r}", flush=True)

    if runtime == "sdk":
        # Legacy in-process SDK path
        hand = HANDS.get(req.hand_id)
        if not hand:
            return {"ok": False, "error": f"unknown hand: {req.hand_id}"}
        resource_menu = get_menu_for_hand(req.hand_id, context.get("tags", []))
        try:
            artifact = await hand.run(req.task, context, resource_menu)
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
        context_with_personal = {**context}
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
        context.get("tags", []),
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


# Connector ID → tier mapping (for backward compat when no per-claim tier available)
_TIER_A = {"fred", "sec-edgar"}
_TIER_B = {"finnhub", "yahoo-finance", "cftc-cot", "investing-calendar", "config.json"}
_TIER_C = {"reuters-rss", "marketwatch-rss", "cnbc-rss"}
_TIER_D = set()  # industry sources (eia, sema, sia, gartner, etc.)
_TIER_E = set()  # handled alongside F below for historical compat
_TIER_F = {"fear-greed", "aaii", "naaim", "stocktwits", "reddit", "kol-rss"}
_TIER_G = set()  # secondary commentary (newsletters, KOL blogs, podcasts)
_TIER_A_B = _TIER_A | _TIER_B
_TIER_E_F = _TIER_F  # no longer merged with E; E is company filings


def _source_authority(sources: list) -> tuple[str, str]:
    """Return (label, pill_class) based on highest-tier source present.
    Falls back to connector IDs when per-claim tier data is unavailable.
    """
    s = set(sources)
    has_a = bool(s & _TIER_A)
    has_b = bool(s & _TIER_B)
    has_c = bool(s & _TIER_C)
    has_d = bool(s & _TIER_D)
    has_e = bool(s & _TIER_E)
    has_f = bool(s & _TIER_F)
    has_g = bool(s & _TIER_G)
    if has_a or has_b:
        return "权威数据", "anc-pill--done"
    if has_c or has_d:
        return "新闻来源", "anc-pill--warn"
    if has_e:
        return "公司来源", "anc-pill--review"
    if has_f:
        return "情绪参考", "anc-pill--edit"
    if has_g:
        return "二手参考", "anc-pill--edit"
    return "来源未知", "anc-pill--edit"


def _compute_source_distribution(artifact: dict) -> dict:
    """Scan key_claims and evidence for per-item source/tier data.

    Returns {"best_tier": "A"|...|"unknown", "worst_tier": ..., "mixed": bool, "tiers": {...}}.
    """
    tiers_seen: dict[str, int] = {}
    meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
    evidence = artifact.get("evidence", []) if isinstance(artifact, dict) else []

    for claim in (meta.get("key_claims", []) or []):
        if isinstance(claim, dict):
            t = (claim.get("tier") or claim.get("source_tier") or "").strip().upper()
            if t:
                tiers_seen[t] = tiers_seen.get(t, 0) + 1

    for row in (evidence or []):
        if isinstance(row, dict):
            t = (row.get("source_tier") or "").strip().upper()
            if t:
                tiers_seen[t] = tiers_seen.get(t, 0) + 1

    if not tiers_seen:
        return {"best_tier": "unknown", "worst_tier": "unknown", "mixed": False, "tiers": {}}

    tier_order = ["A", "B", "C", "D", "E", "F", "G"]
    seen_ranks = [tier_order.index(t) for t in tiers_seen if t in tier_order]
    if not seen_ranks:
        return {"best_tier": "unknown", "worst_tier": "unknown", "mixed": False, "tiers": tiers_seen}
    best = tier_order[min(seen_ranks)]
    worst = tier_order[max(seen_ranks)]
    return {
        "best_tier": best,
        "worst_tier": worst,
        "mixed": best != worst,
        "tiers": tiers_seen,
    }


def _html_text(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _list_html(items: list) -> str:
    rendered = []
    for item in items or []:
        if isinstance(item, dict):
            primary = item.get("claim") or item.get("source") or item.get("note") or item.get("title") or ""
            support = item.get("support") or item.get("freshness") or ""
            tier = _claim_source_tag(item)
            text = " | ".join(str(part) for part in (primary, support) if part)
            rendered.append(f"<li>{tier}{_html_text(text or str(item))}</li>")
        else:
            rendered.append(f"<li>{_html_text(item)}</li>")
    return "".join(rendered)


def _provenance_html(items: list) -> str:
    if not isinstance(items, list) or not items:
        return ""
    rows = []
    for item in items[:8]:
        if not isinstance(item, dict):
            rows.append(f"<li>{_html_text(item)}</li>")
            continue
        source = item.get("source", "unknown")
        tier = item.get("source_tier", item.get("tier", "unknown"))
        tier_tag = ""
        if str(tier).upper() in {"A","B","C","D","E","F","G"}:
            css = {"A":"anc-tier-pill--a","B":"anc-tier-pill--b","C":"anc-tier-pill--c",
                   "D":"anc-tier-pill--c","E":"anc-tier-pill--b","F":"anc-tier-pill--e",
                   "G":"anc-tier-pill--e"}.get(tier.upper(), "anc-tier-pill--e")
            tier_tag = f'<span class="anc-tier-pill {css}">{tier.upper()}</span> '
        freshness = item.get("freshness", "")
        note = item.get("note", "")
        rows.append(
            f"<li>{tier_tag}<strong>{_html_text(source)}</strong>"
            f'{(" · " + _html_text(freshness)) if freshness else ""}'
            f'{("<br>" + _html_text(note)) if note else ""}</li>'
        )
    return '<h4>Provenance</h4><ul class="anc-source-list">' + "".join(rows) + "</ul>"


def _render_artifact_sections(artifact: dict, fallback_narrative: str, fallback_claims_html: str) -> str:
    layers = artifact.get("layers") or []
    if isinstance(layers, list) and layers:
        rendered_layers = []
        for idx, layer in enumerate(layers[:8]):
            if not isinstance(layer, dict):
                continue
            lid = _html_text(layer.get("id") or f"layer-{idx + 1}")
            title = _html_text(layer.get("title") or layer.get("id") or f"Layer {idx + 1}")
            summary = _html_text(layer.get("summary") or "")
            items = layer.get("items") if isinstance(layer.get("items"), list) else []
            provenance = layer.get("provenance") if isinstance(layer.get("provenance"), list) else []
            lt = _html_text(layer.get("layer_type", "analysis"))
            rendered_layers.append(
                f'<section class="anc-detail-section anc-detail-section--content" '
                f'data-detail-section="{lid}" data-detail-label="{title}" data-layer-type="{lt}">'
                f'<h3>{title}</h3>'
                f'{("<p>" + summary + "</p>") if summary else ""}'
                f'{("<ul>" + _list_html(items) + "</ul>") if items else ""}'
                f'{_provenance_html(provenance)}'
                '</section>'
            )
        if rendered_layers:
            return "".join(rendered_layers)

    sections = artifact.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return (
            '<section class="anc-detail-section anc-detail-section--content" '
            'data-detail-section="content" data-detail-label="Full Detail" data-layer-type="analysis">'
            '<h3>Full Detail</h3>'
            f'<p>{_html_text(fallback_narrative)}</p>'
            f'{("<h4>Key Claims</h4><ul>" + fallback_claims_html + "</ul>") if fallback_claims_html else ""}'
            '</section>'
        )

    _SID_TO_LT = {"summary": "summary", "evidence": "evidence", "analysis": "analysis", "gaps": "gaps"}
    rendered = []
    for idx, sec in enumerate(sections[:8]):
        if not isinstance(sec, dict):
            continue
        sid = _html_text(sec.get("id") or f"section-{idx + 1}")
        title = _html_text(sec.get("title") or sec.get("id") or f"Section {idx + 1}")
        summary = _html_text(sec.get("summary") or "")
        bullets = sec.get("bullets") if isinstance(sec.get("bullets"), list) else []
        lt = _SID_TO_LT.get(str(sec.get("id", "")).lower(), "analysis")
        rendered.append(
            f'<section class="anc-detail-section anc-detail-section--content" '
            f'data-detail-section="{sid}" data-detail-label="{title}" data-layer-type="{lt}">'
            f'<h3>{title}</h3>'
            f'{("<p>" + summary + "</p>") if summary else ""}'
            f'{("<ul>" + _list_html(bullets) + "</ul>") if bullets else ""}'
            '</section>'
        )
    return "".join(rendered) or _render_artifact_sections({}, fallback_narrative, fallback_claims_html)


def _presentation_artifact_for_hand(presentation: dict, hand_id: str, fallback: dict) -> dict:
    """Use Brain-composed presentation layers as the UI artifact when available."""
    if not isinstance(presentation, dict):
        return fallback
    panels = presentation.get("detail_panels", {})
    panel = panels.get(hand_id, {}) if isinstance(panels, dict) else {}
    cards = presentation.get("cards", [])
    card = next(
        (item for item in cards if isinstance(item, dict) and item.get("hand_id") == hand_id),
        {},
    )
    if not panel and not card:
        return fallback

    fallback_meta = fallback.get("metadata", {}) if isinstance(fallback, dict) else {}
    error = fallback_meta.get("error")
    return {
        "metadata": {
            "confidence": card.get("confidence", fallback_meta.get("confidence", 0.0)),
            "key_claims": panel.get("key_claims", fallback_meta.get("key_claims", [])),
            "source_notes": panel.get("source_notes", fallback_meta.get("source_notes", [])),
            "gaps": panel.get("gaps", fallback_meta.get("gaps", [])),
            "resources_used": panel.get("resources_used", fallback_meta.get("resources_used", [])),
            "brain_requirements": panel.get("brain_requirements", {}),
            "overview_only": True,
            **({"error": error} if error else {}),
        },
        "narrative": card.get("visible_summary", fallback.get("narrative", "") if isinstance(fallback, dict) else ""),
        "sections": panel.get("sections", fallback.get("sections", []) if isinstance(fallback, dict) else []),
        "layers": panel.get("layers", []),
        "evidence": panel.get("evidence", fallback.get("evidence", []) if isinstance(fallback, dict) else []),
        "raw_sources": fallback.get("raw_sources", []) if isinstance(fallback, dict) else [],
        "raw_items": fallback.get("raw_items", []) if isinstance(fallback, dict) else [],
    }


def _render_evidence_section(artifact: dict) -> str:
    evidence = artifact.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        return ""
    rows = []
    for ev in evidence[:12]:
        if not isinstance(ev, dict):
            continue
        tier = ev.get("source_tier", "").strip().upper()
        tier_css = {"A":"anc-tier-pill--a","B":"anc-tier-pill--b","C":"anc-tier-pill--c",
                    "D":"anc-tier-pill--c","E":"anc-tier-pill--b","F":"anc-tier-pill--e",
                    "G":"anc-tier-pill--e"}.get(tier, "")
        tier_html = (
            f'<span class="anc-tier-pill {tier_css}">{_html_text(tier)}</span>'
            if tier and tier_css else _html_text(tier)
        )
        rows.append(
            "<tr>"
            f"<td>{_html_text(ev.get('claim', ''))}</td>"
            f"<td>{_html_text(ev.get('support', ''))}</td>"
            f"<td>{_html_text(ev.get('source', ''))}</td>"
            f"<td>{tier_html}</td>"
            f"<td>{_html_text(ev.get('freshness', ''))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        '<section class="anc-detail-section anc-detail-section--sources" '
        'data-detail-section="evidence" data-detail-label="Evidence" data-layer-type="evidence">'
        '<h3>Evidence</h3>'
        '<table class="anc-detail-kv"><thead><tr>'
        '<th>Claim</th><th>Support</th><th>Source</th><th>Tier</th><th>Freshness</th>'
        '</tr></thead><tbody>'
        + "".join(rows) +
        '</tbody></table></section>'
    )


def _render_source_notes(meta: dict, sources_html: str) -> str:
    notes = meta.get("source_notes") or []
    if isinstance(notes, list) and notes:
        items = []
        for note in notes[:10]:
            if isinstance(note, dict):
                source = _html_text(note.get("source", "Unknown"))
                tier = note.get("tier", note.get("source_tier", "unknown"))
                freshness = _html_text(note.get("freshness", ""))
                body = _html_text(note.get("note", ""))
                tier_upper = str(tier).strip().upper()
                css = {"A":"anc-tier-pill--a","B":"anc-tier-pill--b","C":"anc-tier-pill--c",
                       "D":"anc-tier-pill--c","E":"anc-tier-pill--b","F":"anc-tier-pill--e",
                       "G":"anc-tier-pill--e"}.get(tier_upper, "anc-tier-pill--e")
                items.append(
                    f'<li><span class="anc-tier-pill {css}">{_html_text(tier_upper)}</span>'
                    f'<div><strong>{source}</strong>{(" · " + freshness) if freshness else ""}'
                    f'{("<br>" + body) if body else ""}</div></li>'
                )
            else:
                items.append(f'<li><span class="anc-tier-pill anc-tier-pill--c">Source</span><div>{_html_text(note)}</div></li>')
        return '<ul class="anc-source-list">' + "".join(items) + '</ul>'
    return f"<p>{sources_html}</p>"


def _claim_text(item) -> str:
    """Extract display text from a key_claims item (string or dict)."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("claim", item.get("text", str(item)))
    return str(item)


def _claim_source_tag(item) -> str:
    """Return HTML source tier tag for a claim item, or empty string."""
    if not isinstance(item, dict):
        return ""
    tier = (item.get("tier") or item.get("source_tier") or "").strip().upper()
    if not tier:
        return ""
    css = {
        "A": "anc-tier-pill--a", "B": "anc-tier-pill--b",
        "C": "anc-tier-pill--c", "D": "anc-tier-pill--c",
        "E": "anc-tier-pill--b", "F": "anc-tier-pill--e",
        "G": "anc-tier-pill--e",
    }.get(tier, "anc-tier-pill--e")
    return f'<span class="anc-tier-pill {css}">{tier}</span> '


def _enrich_error_artifact(artifact: dict, hand_id: str) -> dict:
    """Enrich an error artifact with proper card structure so it follows the same
    dimensional framework as a successful hand card.

    All hand agents — configured or not — produce cards measured by the same 5
    dimensions. A connection-refused error is just (L0 provenance, L4 gap transparency,
    L2 structure, etc.) rather than an empty card.
    """
    meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
    if not meta.get("error"):
        return artifact
    info = REGISTRY.get(hand_id, {})
    label = info.get("label", hand_id)
    description = info.get("description", f"{hand_id} analysis")
    err = str(meta["error"])
    # Only enrich once — subsequent calls see a non-error artifact
    if meta.get("_enriched"):
        return artifact
    artifact.setdefault("sections", [])
    artifact.setdefault("evidence", [])
    meta.setdefault("gaps", [])
    meta.setdefault("source_notes", [])
    meta.setdefault("resources_used", [])
    meta.setdefault("key_claims", [])
    meta["_enriched"] = True
    meta["confidence"] = max(meta.get("confidence", 0.0), 0.0)
    # narrative
    if not artifact.get("narrative"):
        artifact["narrative"] = f"{label} hand unavailable — {err}. This card normally contains {description}."
    # gaps
    if not meta["gaps"]:
        meta["gaps"].append(f"Hand {hand_id} failed with: {err}. All data that would normally be provided by this hand is unavailable.")
    # key_claims
    if not meta["key_claims"]:
        meta["key_claims"].append({"claim": f"{label} hand did not respond", "source": "system", "tier": "G"})
    # source_notes
    if not meta["source_notes"]:
        meta["source_notes"].append({"source": "system", "tier": "G", "freshness": "now", "note": f"Hand agent error: {err}"})
    # sections
    sections = artifact.setdefault("sections", [])
    if not sections:
        sections.append({
            "id": "error",
            "title": "Error Detail",
            "summary": "The hand agent process could not be reached or returned no data.",
            "bullets": [{"claim": err, "source": "system", "tier": "G"}],
        })
        sections.append({
            "id": "impact",
            "title": "Missing Analysis",
            "summary": f"Normally covers: {description}.",
            "bullets": [
                {"claim": "All connector data for this hand is unavailable", "source": "system", "tier": "G"},
                {"claim": "No key claims, evidence rows, or structured sections were produced", "source": "system", "tier": "G"},
                {"claim": "Confidence is 0 — no data was received", "source": "system", "tier": "G"},
            ],
        })
        sections.append({
            "id": "recovery",
            "title": "Recovery",
            "summary": "Actions to restore this hand.",
            "bullets": [
                {"claim": f"Start the {hand_id} hand service (port 3002 if using Brain)", "source": "system", "tier": "G"},
                {"claim": "Restart the analysis after the service is running", "source": "system", "tier": "G"},
            ],
        })
    # evidence is intentionally left empty — no data was received
    meta.setdefault("evidence", [])
    return artifact


def _render_artifact(artifact: dict, hand_id: str) -> str:
    artifact = _enrich_error_artifact(artifact, hand_id)
    meta = artifact.get("metadata", {})
    narrative = artifact.get("narrative", "")
    gaps = meta.get("gaps", [])
    key_claims = meta.get("key_claims", [])
    sources_used = meta.get("resources_used", [])
    overview_only = bool(meta.get("overview_only"))

    # Per-claim source distribution (overrides connector-only label when data exists)
    dist = _compute_source_distribution(artifact)
    if dist["best_tier"] != "unknown":
        best_label, best_class = {
            "A": ("权威数据", "anc-pill--done"), "B": ("市场数据", "anc-pill--done"),
            "C": ("新闻来源", "anc-pill--warn"), "D": ("行业数据", "anc-pill--warn"),
            "E": ("公司来源", "anc-pill--review"), "F": ("情绪参考", "anc-pill--edit"),
            "G": ("二手参考", "anc-pill--edit"),
        }.get(dist["best_tier"], ("来源未知", "anc-pill--edit"))
        authority_label, auth_class = best_label, best_class
        if dist["mixed"]:
            authority_label += " · 多级混用"
            auth_class = "anc-pill--warn"
    else:
        authority_label, auth_class = _source_authority(sources_used)

    gaps_html = "".join(f"<li>{_html_text(g)}</li>" for g in gaps) or "<li>无明显数据缺口</li>"
    claims_html = "".join(
        f"<li>{_claim_source_tag(c)}{_html_text(_claim_text(c))}</li>"
        for c in (key_claims or [])
    )
    sources_html = ", ".join(f"<code>{_html_text(s)}</code>" for s in sources_used) or "无"

    info = REGISTRY.get(hand_id, {})
    anchor_id = info.get("anchor_id", hand_id)
    label = info.get("label", hand_id)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    detail_sections_html = _render_artifact_sections(artifact, narrative, claims_html)
    evidence_html = _render_evidence_section(artifact)
    source_notes_html = _render_source_notes(meta, sources_html)
    raw_sources_html = _render_raw_sources(artifact)
    raw_items_html = _render_raw_items(artifact)

    if overview_only:
        # True summary: pill + title + narrative only visible; detail in aside
        return f"""<section class="anc-section anc-section--gc" data-anc="{anchor_id}" data-handles="refine,expand" data-has-detail="true">
  <div class="anc-pill-row">
    <span class="anc-pill anc-pill--gen">AI 生成</span>
    <span class="anc-pill {auth_class}">{authority_label}</span>
  </div>
  <h2>{label}</h2>
  <div class="insight-box"><p>{_html_text(narrative)}</p></div>
  <aside class="anc-detail" hidden>
    {raw_sources_html}
    {raw_items_html}
    {detail_sections_html}
    {evidence_html}
    <section class="anc-detail-section anc-detail-section--sources" data-detail-section="sources" data-detail-label="Sources" data-layer-type="analysis">
      <h3>Sources</h3>
      {source_notes_html}
    </section>
    <section class="anc-detail-section anc-detail-section--hand-eval" data-detail-section="hand-eval" data-detail-label="Hand Eval" data-layer-type="analysis">
      <h3>Hand Eval</h3>
      <div class="anc-eval-block"><div class="anc-eval-label">Authority</div>{authority_label}</div>
      <div class="anc-eval-block"><div class="anc-eval-label">Coverage gaps</div><ul>{gaps_html}</ul></div>
    </section>
  </aside>
</section>"""

    return f"""<section class="anc-section anc-section--gc" data-anc="{anchor_id}" data-handles="refine,expand" data-has-detail="true">
  <div class="anc-pill-row">
    <span class="anc-pill anc-pill--gen">AI 生成</span>
    <span class="anc-pill {auth_class}">{authority_label}</span>
  </div>
  <h2>{label}</h2>
  <div class="insight-box"><p>{_html_text(narrative)}</p></div>
  {('<h4>关键判断</h4><ul>' + claims_html + '</ul>') if claims_html else ''}
  <h4>数据缺口</h4>
  <ul class="risk-list">{gaps_html}</ul>
  <p>数据来源：{sources_html} ｜ {ts}</p>
  <aside class="anc-detail" hidden>
    {raw_sources_html}
    {raw_items_html}
    {detail_sections_html}
    {evidence_html}
    <section class="anc-detail-section anc-detail-section--sources" data-detail-section="sources" data-detail-label="Sources" data-layer-type="analysis">
      <h3>Sources</h3>
      {source_notes_html}
    </section>
    <section class="anc-detail-section anc-detail-section--hand-eval" data-detail-section="hand-eval" data-detail-label="Hand Eval" data-layer-type="analysis">
      <h3>Hand Eval</h3>
      <div class="anc-eval-block"><div class="anc-eval-label">Authority</div>{authority_label}</div>
      <div class="anc-eval-block"><div class="anc-eval-label">Coverage gaps</div><ul>{gaps_html}</ul></div>
    </section>
  </aside>
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
    adapters_info = [
        {
            "id": a.id,
            "hw_capabilities": getattr(a, "hw_capabilities", {}),
        }
        for a in _adapter_registry.list()
    ]
    return {
        "ok": True,
        "service": "loom-brain",
        "hands": list(HANDS.keys()),
        "adapters": adapters_info,
        "mounted": dict(_mounted),
    }


@app.get("/goals")
async def list_goals(status: str = "open"):
    if status == "all":
        goals = _goal_store.list_all()
    else:
        goals = _goal_store.list_open()
    return {
        "ok": True,
        "count": len(goals),
        "goals": [
            {
                "goal_id": g.goal_id,
                "goal_type": g.goal_type,
                "title": g.title,
                "status": g.status,
                "updated_at": g.updated_at,
                "episode_count": len(g.episode_ids),
                "latest_stance": g.latest_stance(),
            }
            for g in goals
        ],
    }


@app.get("/goals/{goal_id}")
async def get_goal(goal_id: str):
    goal = _goal_store.load(goal_id)
    if not goal:
        return {"ok": False, "error": "goal not found"}
    return {"ok": True, "goal": goal.to_dict()}


@app.get("/flywheel")
async def flywheel_log(limit: int = 50):
    records = _flywheel.read_summary_log(limit=limit)
    return {"ok": True, "count": len(records), "records": records}


class FeedbackRequest(BaseModel):
    episode_id: str
    signal: str = "thumbs_up"
    comment: str = ""
    corrected_stance: str = ""


@app.post("/flywheel/feedback")
async def flywheel_feedback(req: FeedbackRequest):
    from brain_harness.flywheel import HumanFeedback
    import datetime
    fb = HumanFeedback(
        episode_id=req.episode_id,
        ts=datetime.datetime.utcnow().isoformat() + "Z",
        signal=req.signal,
        comment=req.comment,
        corrected_stance=req.corrected_stance,
    )
    ok = _flywheel.append_human_feedback(req.episode_id, fb)
    return {"ok": ok}


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
