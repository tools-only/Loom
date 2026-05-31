"""Loom Brain — FastAPI service on port 3001.

Routes:
  POST /run   { hand_id, task, context, runtime? }  →  { ok, hand_id, artifact }
  GET  /health                                       →  { ok, service, hands }
  GET  /resources/:id                                →  raw connector data (no policy)
  GET  /feedback                                     →  raw feedback events
  POST /feedback                                     →  append feedback event
  GET  /hand/:id/config                              →  hand config
  PUT  /hand/:id/config                              →  write hand config
"""
from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel

from hand_registry import REGISTRY
from provider_client import read_config, write_config
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

app = FastAPI(title="Loom Brain", version="0.2.0")

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


def _build_hand_system_prompt(hand_id: str, description: str) -> str:
    info = REGISTRY.get(hand_id, {})
    label = info.get("label", hand_id)
    domain = info.get("description", "")
    user_note = f"\n\n## 用户说明\n{description.strip()}" if description.strip() else ""
    return (
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


# Restore mounts on startup
_load_mounts()


class RunRequest(BaseModel):
    hand_id: str
    task: str
    context: dict = {}
    runtime: str = ""


class TimingRequest(BaseModel):
    timing: dict


@app.post("/timing/stages")
def timing_stages(body: TimingRequest):
    result = compute_stages(body.timing)
    return {"ok": True, **result}


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
        envelope = {
            "task": req.task,
            "context": req.context,
            "hand_id": req.hand_id,
            "hand_dir": hand_dir,
            "wiki_dir": wiki_dir,
            "resource_api": "http://127.0.0.1:3001/resources",
            "feedback_log": str(_ROOT / "logs" / "feedback.jsonl"),
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
async def put_config(request: Request):
    try:
        cfg = await request.json()
        write_config(cfg)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
