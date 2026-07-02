"""Loom Brain 鈥?FastAPI service on port 3002.

Routes:
  POST /analyze { question, context?, domain_hint?, hands? }
                鈫?{ ok, synthesis, hand_artifacts, workflow_decision, cold_start }
  POST /run   { hand_id, task, context, runtime? }  鈫? { ok, hand_id, artifact }
  GET  /health                                       鈫? { ok, service, hands }
  GET  /resources/:id                                鈫? raw connector data (no policy)
  GET  /intent-stream                                鈫? intent stream UI page
  GET  /intent-stream/data                           鈫? intent events + derived context (JSON)
  GET  /feedback                                     鈫? raw feedback events
  POST /feedback                                     鈫? append feedback event
  GET  /hand/:id/config                              鈫? hand config
  PUT  /hand/:id/config                              鈫? write hand config
"""
from __future__ import annotations

import asyncio
import datetime
import html
import json
import os
import sys
import time
import urllib.parse
import uuid
from dataclasses import asdict
from pathlib import Path

_LOOM_DIR = Path(__file__).resolve().parent
if str(_LOOM_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOM_DIR))
_bridge_module = sys.modules.get("bridge")
if _bridge_module is not None and not hasattr(_bridge_module, "patch_webview"):
    del sys.modules["bridge"]

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from hand_registry import REGISTRY
from provider_client import (
    read_config,
    write_config,
    get_client_for_brain,
)
from domains import DomainRegistry
from domains.finance import LoomFinanceAdapter
from domains.general import LoomGeneralAdapter
from bridge import patch_webview, get_connector_data
from timing_stats import compute_stages
from harness.eval_log import append_signal
from hands.market import MarketHand
from hands.sentiment import SentimentHand
from hands.target import TargetHand
from hands.position import PositionHand

# --- Loom Core in-process runtime ---
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loom_core.runtime.app import LoomCoreRuntime
from loom_core.agent_adapters.registry import create_adapter_registry
from loom_core.agent_adapters.providers import create_providers
from loom_core.agent_adapters.runtime_bindings import (
    HandRuntimeBindingStore,
    hand_runtime_config_path,
    resolve_hand_runtime,
)
from loom_core.codex_hand_channel import CodexHandChannel, HandRequest
from loom_core.agent_service import AgentSessionService

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
        label=f"SDK Legacy 鈥?{_hid}",
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

# Register runtime-hand adapter (default executor for Brain-generated hands).
# Falls back to brain-inline if claude is not in PATH.
import shutil as _shutil
from loom_core.agent_adapters.providers.runtime_hand import create_runtime_hand_provider as _rh_create

_rh_cmd = os.environ.get("LOOM_RUNTIME_HAND_COMMAND", "claude -p").split()
_use_runtime_hand = _shutil.which(_rh_cmd[0]) is not None
if _use_runtime_hand:
    _rh_prov = _rh_create(base_command=_rh_cmd)
    _adapter_registry.upsert(_rh_prov["instance"])
    _adapter_registry.set_default_runtime_adapter("runtime-hand")
# else: default stays "brain-inline" (set in AgentAdapterRegistry.__init__)

from loom_core.agent_adapters.cloud_bootstrap import register_cloud_adapters
from loom_core.agent_adapters.factory import (
    adapter_from_config,
    adapter_public_info,
    normalize_adapter_config,
    persistable_adapter_config,
)
register_cloud_adapters(_adapter_registry, _core, _ROOT)

_DYNAMIC_ADAPTER_PATH = _ROOT / "loom" / "agent-adapters.json"
_DYNAMIC_ADAPTER_CONFIGS: dict[str, dict] = {}


def _register_dynamic_adapter_config(config: dict, *, persist: bool = True) -> dict:
    """Register a process/http adapter from runtime config."""
    normalized = normalize_adapter_config(config)
    adapter = adapter_from_config(
        normalized,
        runtime=_core,
        hands_root=_ROOT / "hands",
    )
    _adapter_registry.upsert(adapter)
    _DYNAMIC_ADAPTER_CONFIGS[adapter.id] = {
        **persistable_adapter_config(config),
        "set_default_runtime": bool(config.get("set_default_runtime", False)),
    }
    if config.get("set_default_runtime"):
        _adapter_registry.set_default_runtime_adapter(adapter.id)
    if persist:
        _save_dynamic_adapters()
    return adapter_public_info(adapter)


def _load_dynamic_adapters() -> None:
    if not _DYNAMIC_ADAPTER_PATH.exists():
        return
    try:
        data = json.loads(_DYNAMIC_ADAPTER_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[brain] failed to load dynamic adapters: {exc}", flush=True)
        return
    entries = data.get("adapters", data if isinstance(data, dict) else {})
    if not isinstance(entries, dict):
        return
    for adapter_id, config in entries.items():
        if not isinstance(config, dict):
            continue
        try:
            _register_dynamic_adapter_config(
                {"adapter_id": adapter_id, **config},
                persist=False,
            )
        except Exception as exc:
            print(f"[brain] dynamic adapter {adapter_id} skipped: {exc}", flush=True)


def _save_dynamic_adapters() -> None:
    try:
        _DYNAMIC_ADAPTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DYNAMIC_ADAPTER_PATH.write_text(
            json.dumps(
                {"version": 1, "adapters": _DYNAMIC_ADAPTER_CONFIGS},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[brain] failed to save dynamic adapters: {exc}", flush=True)


def _ensure_runtime_adapter(adapter_id: str):
    """Find an adapter, lazily loading CLI-written dynamic config if needed."""
    adapter = _adapter_registry.find_by_id(adapter_id)
    if adapter is not None or not _DYNAMIC_ADAPTER_PATH.exists():
        return adapter
    try:
        data = json.loads(_DYNAMIC_ADAPTER_PATH.read_text("utf-8"))
        entries = data.get("adapters", {}) if isinstance(data, dict) else {}
        config = entries.get(adapter_id) if isinstance(entries, dict) else None
        if isinstance(config, dict):
            _register_dynamic_adapter_config(
                {"adapter_id": adapter_id, **config},
                persist=False,
            )
    except Exception as exc:
        print(f"[brain] failed to lazy-load adapter {adapter_id}: {exc}", flush=True)
    return _adapter_registry.find_by_id(adapter_id)


_load_dynamic_adapters()

_DIRECT_CODEX_RUNTIME_ID = "codex-app-server"


def _create_direct_codex_channel() -> CodexHandChannel:
    """Build the direct channel from the active Codex runtime configuration."""
    config = _DYNAMIC_ADAPTER_CONFIGS.get(_DIRECT_CODEX_RUNTIME_ID, {})
    codex_home = os.environ.get("LOOM_CODEX_HOME") or config.get("codex_home") or None
    raw_timeout = os.environ.get("LOOM_CODEX_HAND_TIMEOUT_S") or config.get("timeout_s", 120.0)
    try:
        timeout_s = float(raw_timeout)
    except (TypeError, ValueError):
        timeout_s = 120.0
    return CodexHandChannel(codex_home=codex_home, timeout_s=timeout_s)


async def _run_direct_codex_hand(hand_id: str, task: str, context: dict) -> dict:
    """Invoke a Brain Hand through the SDK/app-server channel."""
    spec = (context or {}).get("agentic_hand_spec", {}) or {}
    system_prompt = str(spec.get("system_prompt") or "") if isinstance(spec, dict) else ""
    started = time.monotonic()
    print(f"[brain] codex-hand start hand={hand_id}", flush=True)
    artifact = await _create_direct_codex_channel().run(
        HandRequest(
            task=task,
            hand_id=hand_id,
            cwd=str(_ROOT),
            system_prompt=system_prompt,
            context=dict(context or {}),
        )
    )
    elapsed = time.monotonic() - started
    print(f"[brain] codex-hand completed hand={hand_id} elapsed={elapsed:.1f}s", flush=True)
    return artifact

# 鈹€鈹€ Brain agent wiring 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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
from brain_harness.contextual_intent import ContextualIntentCompiler, ScopedFeedback
from brain_harness.orchestration import build_minimal_orchestration_snapshot
from loom_core.interaction_protocol.social import (
    _is_loom_command_token,
    build_analyze_request_from_social,
    is_explicit_loom_command,
    normalize_social_payload,
    parse_agent_command,
    resolve_social_agent_request,
)
from loom_core.interaction_protocol.social_channel import (
    SocialChannelAdapter,
    available_social_channel_types,
    social_channel_from_config,
)
from loom_core.interaction_protocol.social_channel_config import (
    create_social_channel_registry_from_document,
    load_social_channel_document,
    registry_to_document,
    save_social_channel_document,
    social_channel_config_path,
)
from loom_core.interaction_protocol.social_reply import (
    render_analysis_reply,
    send_social_reply,
)
from loom_core.interaction_protocol.social_progress import DiscordProgress, DiscordProgressReporter
from loom_core.interaction_protocol.social_verify import verify_social_request
from loom_core.repair.episode_repair import (
    build_repair_plan,
    build_repair_task,
    summarize_repair_for_reply,
)
from loom_core.agents.core_agent import LoomCoreAgent
from brain_portfolio import PortfolioDataHub

# 鈹€鈹€ Domain adapter layer 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
_domain_registry = DomainRegistry(default_domain="general")
_domain_registry.register(LoomFinanceAdapter())
_domain_registry.register(LoomGeneralAdapter())

# Merge default hands from domain adapters into REGISTRY
for adapter in (_domain_registry.get("finance"), _domain_registry.get("general")):
    for hand_id, cfg in (adapter.default_hands or {}).items():
        if hand_id not in REGISTRY:
            REGISTRY[hand_id] = cfg

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
_contextual_intent_compiler = ContextualIntentCompiler()
_portfolio_hub = PortfolioDataHub(_ROOT)
_SOCIAL_CHANNEL_CONFIG_PATH = social_channel_config_path(_ROOT)
_social_channel_registry = create_social_channel_registry_from_document(
    load_social_channel_document(_SOCIAL_CHANNEL_CONFIG_PATH)
)
_agent_session_service = AgentSessionService(_adapter_registry)
from loom_core.agent_session_registry import AgentSessionRegistry
from loom_core.interaction_protocol.social import SessionCommand, parse_session_command
_session_registry = AgentSessionRegistry()


def _save_social_channels() -> None:
    doc = registry_to_document(_social_channel_registry)
    save_social_channel_document(
        _SOCIAL_CHANNEL_CONFIG_PATH,
        default_channel=doc["default_channel"],
        channels=doc["channels"],
    )


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


def _ensure_web_search_capability(hand_id: str, ctx: dict) -> tuple:
    """Ensure every hand has web_search capability by default.

    When tools config is empty or missing web_search, inject it.
    Reuses Codex/Claude Code native web search. Returns (ctx, injected).
    """
    spec = (ctx or {}).get("agentic_hand_spec", {}) or {}
    capabilities = list(spec.get("capabilities", []) or [])
    tools = list(spec.get("tools", []) or [])

    info = REGISTRY.get(hand_id, {})
    registry_tools = info.get("tools", []) or []
    registry_capabilities = info.get("capabilities", []) or []

    has_web = (
        "web_search" in capabilities
        or "web_search" in tools
        or "web_search" in registry_tools
        or "web_search" in registry_capabilities
    )

    if has_web:
        return ctx, False

    if "web_search" not in capabilities:
        capabilities.append("web_search")
        spec["capabilities"] = capabilities
        ctx = dict(ctx or {})
        ctx["agentic_hand_spec"] = spec

    ctx["_web_search"] = {
        "injected": True,
        "source": "codex_default",
        "note": "web_search injected as default; configure tools in registry to override",
    }
    print(f"[brain] web_search injected as default for hand={hand_id}", flush=True)
    return ctx, True



async def _brain_hand_runner(hand_id: str, task: str, ctx: dict) -> dict:
    """Run a single hand for Brain's /analyze 鈥?reuses sdk path.

    Routing precedence:
      1. ``hand_id in REGISTRY`` 鈫?existing SDK / mounted-adapter path
      2. ``hand_id in _mounted`` 鈫?existing mounted-adapter path
      3. Otherwise (Brain-generated runtime hand) 鈫?route to ``brain-inline``
         adapter using the spec's ``system_prompt`` (synthesized from the
         declared dimension when absent).
    """
    ctx = _with_brain_portfolio_context(hand_id, ctx)

    # Inject domain adapter config so hands can use domain-specific skill/personal paths
    info = REGISTRY.get(hand_id, {})
    hand_domains = info.get("domains", ["general"])
    if _domain_registry:
        adapter = _domain_registry.get(hand_domains[0])
        ctx["_domain_adapter_config"] = {
            "skill_path": adapter.skill_path,
            "personal_file_names": adapter.personal_file_names,
            "context_snapshot_name": adapter.context_snapshot_name,
            "assistant_branding": adapter.assistant_branding,
        }

    # Runtime-generated hand: not registered statically and not mounted.
    # Ensure every hand has web_search capability by default (reuses Codex/Claude Code native search)
    ctx, _web_injected = _ensure_web_search_capability(hand_id, ctx)

    if hand_id not in REGISTRY and hand_id not in _mounted:
        spec = (ctx or {}).get("agentic_hand_spec", {}) or {}
        system_prompt = spec.get("system_prompt", "") or ""
        if not system_prompt:
            dimension = spec.get("dimension", "general") or "general"
            system_prompt = (
                f"You are a Brain-generated analysis agent for dimension: {dimension}. "
                "Produce a run.artifact JSON with narrative and metadata."
            )
        _executor_id = spec.get("executor_id") or "brain-inline"
        _resolved_id = _adapter_registry.resolve_runtime_adapter(_executor_id)
        if _resolved_id == _DIRECT_CODEX_RUNTIME_ID:
            try:
                artifact = await _run_direct_codex_hand(hand_id, task, ctx)
                if artifact and isinstance(artifact, dict):
                    artifact.setdefault("_degradation", {})
                    artifact["_degradation"]["web_search"] = {
                        "source": "codex_default",
                        "note": "web_search provided by Codex/Claude Code native search",
                    }
                return artifact
            except Exception as _codex_err:
                print(f"[brain] codex-hand failed for hand={hand_id}, falling back to brain-inline: {_codex_err}", flush=True)
                fallback_adapter = _adapter_registry.find_by_id("brain-inline")
                if fallback_adapter is None:
                    raise RuntimeError(f"codex-hand failed and brain-inline not available: {_codex_err}")
                envelope = {
                    "task": task,
                    "context": ctx,
                    "hand_id": hand_id,
                    "system_prompt": system_prompt,
                    "resource_api": "http://127.0.0.1:3001/resources",
                }
                artifact = None
                async for event in fallback_adapter.invoke(envelope):
                    if event.get("type") == "run.artifact":
                        artifact = event.get("artifact")
                    elif event.get("type") == "run.error":
                        raise RuntimeError(event.get("message", "brain-inline adapter error"))
                if artifact is None:
                    raise RuntimeError(f"hand {hand_id} returned no artifact from fallback")
                if isinstance(artifact, dict):
                    artifact.setdefault("_degradation", {})
                    artifact["_degradation"]["runtime"] = {
                        "requested": "codex-app-server",
                        "actual": "brain-inline",
                        "reason": str(_codex_err)[:200],
                    }
                    artifact["_degradation"]["web_search"] = {
                        "source": "codex_default",
                        "note": "codex-hand failed; web_search downgraded to brain-inline with codex native search",
                    }
                return artifact
        adapter = _adapter_registry.find_by_id(_resolved_id)
        if adapter is None:
            adapter = _adapter_registry.find_by_id("brain-inline")  # fallback
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
    runtime = _runtime_for_hand(hand_id)
    if runtime == "sdk":
        hand = HANDS.get(hand_id)
        if not hand:
            raise ValueError(f"unknown hand: {hand_id}")
        resource_menu = get_menu_for_hand(hand_id, ctx.get("tags", []))
        return await hand.run(task, ctx, resource_menu)
    adapter = _ensure_runtime_adapter(runtime)
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
_core_agent._domain_registry = _domain_registry

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
_HAND_RUNTIME_BINDINGS = HandRuntimeBindingStore(hand_runtime_config_path(_ROOT))


def _runtime_for_hand(hand_id: str, explicit: str = "") -> str:
    info = REGISTRY.get(hand_id, {})
    return resolve_hand_runtime(
        explicit=explicit,
        bound=_HAND_RUNTIME_BINDINGS.get(hand_id),
        mounted=_mounted.get(hand_id, ""),
        declared=str(info.get("runtime", "sdk")),
    )


def _hand_runtime_state(hand_id: str) -> dict:
    info = REGISTRY.get(hand_id, {})
    configured = _HAND_RUNTIME_BINDINGS.get(hand_id)
    return {
        "hand_id": hand_id,
        "label": info.get("label", hand_id),
        "configured_runtime": configured,
        "effective_runtime": _runtime_for_hand(hand_id),
        "declared_runtime": info.get("runtime", "sdk"),
        "mounted_runtime": _mounted.get(hand_id, ""),
    }


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
    # Look up domain adapter config from the hand's REGISTRY entry
    info = REGISTRY.get(hand_id, {})
    hand_domains = info.get("domains", ["general"])
    adapter = _domain_registry.get(hand_domains[0]) if _domain_registry else None
    skill_path = adapter.skill_path if adapter else "skills/investment-research-framework"
    fnames = adapter.personal_file_names if adapter else ["profile.md", "themes.md", "watchlist.md", "sources.md"]
    snap_name = adapter.context_snapshot_name if adapter else "regime-snapshot.md"

    if skill_path:
        skill_md = _ROOT / skill_path / "SKILL.md"
        if skill_md.exists():
            out["skill_index"] = skill_md.read_text("utf-8")
    personal_dir = _ROOT / "hands" / hand_id / "personal"
    for fname in fnames:
        p = personal_dir / fname
        if p.exists() and p.stat().st_size > 0:
            out[f"personal/{fname}"] = p.read_text("utf-8")
    notes = personal_dir / "learned-notes.md"
    if notes.exists() and notes.stat().st_size > 0:
        txt = notes.read_text("utf-8")
        out["personal/learned-notes.md"] = txt[-4000:]
    snap = _ROOT / "hands" / hand_id / "context" / snap_name
    if snap.exists() and (time.time() - snap.stat().st_mtime) < 86400:
        out[f"context/{snap_name}"] = snap.read_text("utf-8")
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
    hand_domains = info.get("domains", ["general"])
    adapter = _domain_registry.get(hand_domains[0]) if _domain_registry else None
    branding = adapter.assistant_branding if adapter else "Loom"
    domain_desc = info.get("description", "")
    user_note = f"\n\n## 鐢ㄦ埛璇存槑\n{description.strip()}" if description.strip() else ""
    base = (
        f"You are {branding}'s [{label}] hand agent. {user_note}\n\n"
        f"## Analysis responsibility\n{domain}\n\n"
        "## Output protocol (strict)\n"
        "After analysis, output exactly one JSON line:\n"
        '{"type":"run.artifact","artifact":{"metadata":{"resources_used":[...],"key_claims":[...],"gaps":[...]},"narrative":"..."}}\n\n'
        "- resources_used: every data source you accessed\n"
        "- key_claims: 2-5 core claims supported by evidence\n"
        "- gaps: data you needed but could not obtain\n"
        "- narrative: 2-4 concise analysis paragraphs\n\n"
        "Do not output any other content."
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
        f'<strong>Priority signal:</strong> {priority_signal}</div>'
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
        f'<span class="anc-pill anc-pill--gen">State reasoning</span>'
        f'<span class="anc-pill {status_class}">{html.escape(status)}</span>'
        f'</div>'
        f'<h2>{title}</h2>'
        f'{priority_html}'
        f'{regime_html}'
        f'<h4>Observation Variables</h4>{watch_html}'
        f'<h4>Stance History</h4>{history_html}'
        f'{"<h4>Reversal Condition</h4>" + reversal_html if latest_reversal else ""}'
        f'<p style="font-size:11px;color:var(--ink-muted)">'
        f'Domain: {domain} - Episode #{episode_count} [{episode_id}]</p>'
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
            url_html = f'<br><a href="{url_str}" target="_blank" rel="noopener" style="font-size:11px;color:var(--accent-iris)">馃敆 {url_str}</a>'
        if query:
            query_str = html.escape(str(query))
            url_html += f'<br><span style="font-size:11px;color:var(--ink-muted)">鎼滅储璇? {query_str}</span>'
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
                f'<span style="font-size:11px;color:var(--ink-muted)"> {source} 路 {pub}</span>'
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
                f'<span style="font-size:11px;color:var(--ink-muted)"> {source} 路 {freshness}</span>'
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


# 鈹€鈹€ Hand color assignment for participant indicators 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
_HAND_COLORS: dict[str, str] = {
    "market": "#7A5AF8",
    "sentiment": "#F59E0B",
    "target": "#10B981",
    "position": "#EF4444",
}
_RUNTIME_HAND_PALETTE = ["#06B6D4", "#EC4899", "#8B5CF6", "#14B8A6", "#F97316", "#6366F1"]


def _hand_color(hand_id: str) -> str:
    """Deterministic color for any hand_id 鈥?known hands get stable colors,
    runtime-generated hands are assigned from a rotation palette."""
    if hand_id in _HAND_COLORS:
        return _HAND_COLORS[hand_id]
    return _RUNTIME_HAND_PALETTE[hash(hand_id) % len(_RUNTIME_HAND_PALETTE)]


def _hand_label(hand_id: str) -> str:
    """Human-readable short label for a hand."""
    info = REGISTRY.get(hand_id, {})
    return info.get("label", info.get("name", hand_id))


def _render_hand_participants(hand_artifacts: dict) -> str:
    """Render a compact participants bar showing which hands contributed."""
    if not hand_artifacts:
        return ""
    dots = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:12px">'
        f'<span style="width:8px;height:8px;border-radius:50%;background:{_hand_color(hid)};'
        f'display:inline-block;flex-shrink:0"></span>'
        f'{html.escape(_hand_label(hid))}'
        f'</span>'
        for hid in sorted(hand_artifacts.keys())
    )
    return (
        f'<div class="hand-participants" style="display:flex;gap:8px;align-items:center;'
        f'flex-wrap:wrap;margin-bottom:12px;padding-bottom:10px;'
        f'border-bottom:1px solid rgba(255,255,255,0.15)">'
        f'<span style="font-size:11px;font-weight:600;opacity:0.7;white-space:nowrap">Participants</span>'
        f'{dots}</div>'
    )


def _render_brain_synthesis(
    synthesis: dict, workflow: dict, cold_start: bool,
    episode_id: str = "", goal_id: str = "",
    hand_artifacts: dict | None = None,
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

    adapter = _domain_registry.get(domain) if _domain_registry else None
    stance_class = (adapter.stance_css_classes or {}).get(
        stance, adapter.default_stance_css_class if adapter else "anc-pill--edit"
    )
    stance_label = (adapter.stance_labels or {}).get(stance, stance)
    confidence_pct = int(confidence * 100)

    cold_html = ""
    if cold_start:
        cold_html = (
            '<div class="anc-pill-row">'
            '<span class="anc-pill anc-pill--warn">WARNING Using default strategy</span></div>'
            '<p style="font-size:12px;color:var(--ink-muted)">Add <code>brain/personal/strategy.md</code> to personalize synthesis.</p>'
            ''
        )

    clarify_html = ""
    if clarify:
        clarify_html = (
            f'<div class="insight-box" style="border-left:3px solid var(--accent-amber)">'
            f'<strong>闇€瑕佹緞娓咃細</strong> {clarify}</div>'
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
        drivers_html = f'<h4>椹卞姩鍥犵礌</h4><ul class="risk-list">{items}</ul>'

    refs_html = ""
    if strategy_refs:
        tags = " ".join(f'<code>{r}</code>' for r in strategy_refs)
        refs_html = f'<p style="font-size:12px;color:var(--ink-muted)">Strategy refs: {tags}</p>'

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
        f'{_render_hand_participants(hand_artifacts) if hand_artifacts else ""}'
        f'<div class="anc-pill-row">'
        f'<span class="anc-pill anc-pill--gen">Brain synthesis</span>'
        f'<span class="anc-pill {stance_class}">{stance_label}</span>'
        f'</div>'
        f'<h2>Synthesis</h2>'
        f'<div class="brain-confidence">'
        f'<span>Confidence: {confidence_pct}%</span>'
        f'<div class="confidence-bar"><div class="confidence-fill" style="width:{confidence_pct}%"></div></div>'
        f'</div>'
        f'{clarify_html}'
        f'{drivers_html}'
        f'{"<h4>Reversal Condition</h4><blockquote>" + reversal + "</blockquote>" if reversal else ""}'
        f'{refs_html}'
        f'<p style="font-size:11px;color:var(--ink-muted)">'
        f'Domain: {domain} ({mode}) - {rationale} -> {ts}</p>'
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


class SocialIngressRequest(BaseModel):
    platform: str = "generic"
    channel_adapter_id: str = ""
    payload: dict = Field(default_factory=dict)
    text: str = ""
    user_id: str = ""
    channel_id: str = ""
    message_id: str = ""
    thread_id: str = ""
    event_id: str = ""
    timestamp: str = ""
    domain_hint: str = ""
    context: dict = Field(default_factory=dict)
    send_reply: bool = False
    reply_webhook_url: str = ""
    reply_token: str = ""


class SocialChannelRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    channel_id: str
    platform: str = "generic"
    label: str = ""
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)
    default_context: dict = Field(default_factory=dict)
    response_mode: str = ""
    reply_webhook_url: str = Field(default="", alias="replyWebhookUrl")
    reply_webhook_env: str = Field(default="", alias="replyWebhookEnv")
    reply_token: str = Field(default="", alias="replyToken")
    reply_token_env: str = Field(default="", alias="replyTokenEnv")
    receive_id_type: str = Field(default="", alias="receiveIdType")
    require_verification: bool | None = Field(default=None, alias="requireVerification")
    allow_from: list[str] = Field(default_factory=list, alias="allowFrom")
    mode: str = ""
    status: str = ""
    settings: dict = Field(default_factory=dict)
    set_default: bool = False


class DefaultSocialChannelRequest(BaseModel):
    channel_id: str


class SocialChannelsConfigRequest(BaseModel):
    default_channel: str = "generic"
    channels: list[dict] = Field(default_factory=list)


class RunRequest(BaseModel):
    hand_id: str
    task: str
    context: dict = {}
    runtime: str = ""


class AgentSessionRequest(BaseModel):
    adapter_id: str = ""
    task: str
    cwd: str = ""
    context: dict = Field(default_factory=dict)
    dangerous: bool = False
    session_key: str = ""


class AgentSessionStartRequest(BaseModel):
    adapter_id: str = "runtime-hand"
    platform: str = "discord"
    channel_id: str = ""
    user_id: str = ""
    label: str = ""


class AgentSessionSelectRequest(BaseModel):
    platform: str = "discord"
    channel_id: str = ""
    user_id: str = ""
    session_id: str


class AgentSessionListQuery(BaseModel):
    platform: str = ""
    channel_id: str = ""
    user_id: str = ""


class AgentAdapterRegisterRequest(BaseModel):
    adapter_id: str
    transport: str = "process"
    protocol: str = "loom"
    command: list[str] | str = Field(default_factory=list)
    task_as_arg: bool = False
    endpoint: str = ""
    auth_token: str = ""
    auth_token_env: str = ""
    timeout_s: float = 120.0
    capabilities: list[str] = Field(default_factory=list)
    system_prompt: str = ""
    codex_backend: str = "sdk"
    hw_capabilities: dict = Field(default_factory=dict)
    set_default_runtime: bool = False
    persist: bool = True


class DefaultRuntimeAdapterRequest(BaseModel):
    adapter_id: str


class HandRuntimeRequest(BaseModel):
    adapter_id: str = ""


class RepairFeedbackRequest(BaseModel):
    episode_id: str
    signal: str = "correction"
    comment: str = ""
    corrected_stance: str = ""
    hand_id: str = ""
    target_hands: list[str] = Field(default_factory=list)
    object_ref: str = ""
    object_type: str = ""
    ui_selection: str = ""
    anchor_id: str = ""
    intent_delta: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    social: dict = Field(default_factory=dict)
    send_reply: bool = False
    reply_webhook_url: str = ""
    reply_token: str = ""
    resynthesize: bool = True


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


def _social_payload(req: SocialIngressRequest, platform: str | None = None) -> dict:
    payload = dict(req.payload or {})
    payload.setdefault("platform", platform or req.platform or "generic")
    for key in (
        "text",
        "user_id",
        "channel_id",
        "message_id",
        "thread_id",
        "event_id",
        "timestamp",
    ):
        value = getattr(req, key, "")
        if value:
            payload[key] = value
    return payload


def _decode_raw_json(raw_body: bytes) -> dict:
    if not raw_body:
        return {}
    try:
        data = json.loads(raw_body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _verification_payload(req: SocialIngressRequest, raw_payload: dict) -> dict:
    if raw_payload:
        return raw_payload
    return _social_payload(req)


def _select_social_channel(
    req: SocialIngressRequest,
    platform: str | None = None,
) -> SocialChannelAdapter:
    context = req.context or {}
    channel_id = (
        req.channel_adapter_id
        or str(context.get("channel_adapter_id") or context.get("social_channel_id") or "")
    )
    return _social_channel_registry.resolve(
        channel_id=channel_id,
        platform=platform or req.platform or "generic",
    )


def _verify_social_or_response(
    *,
    channel: SocialChannelAdapter,
    headers,
    raw_body: bytes,
    payload: dict,
):
    verification = channel.verify(
        headers=headers,
        body=raw_body,
        payload=payload,
    )
    if verification.challenge:
        return verification, {"challenge": verification.challenge}
    if not verification.ok:
        return verification, JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": verification.error or "social webhook verification failed",
                "verification_method": verification.method,
            },
        )
    return verification, None


def _social_bridge_managed_reply(channel_context: dict) -> bool:
    return bool(
        channel_context.get("bridgeManagedReply")
        or channel_context.get("bridge_managed_reply")
    )


def _social_should_send_reply(req: SocialIngressRequest, channel_context: dict) -> bool:
    return bool(
        not _social_bridge_managed_reply(channel_context)
        and (
            req.send_reply
            or req.reply_webhook_url
            or str(channel_context.get("responseMode", "")).lower() in {"reply", "auto_reply"}
            or str(channel_context.get("response_mode", "")).lower() in {"reply", "auto_reply"}
        )
    )


def _is_loom_visual_command(text: str) -> bool:
    """True when the message explicitly requests visual output."""
    clean = str(text or "").strip().lower()
    return bool(clean) and clean.split()[0] == "/loom-visual"


def _save_visual_html(episode_id: str) -> str:
    """Save the current interactive Loom anchor HTML to disk. Returns file path."""
    if not episode_id:
        return ""
    html = _build_standalone_anchor_html()
    if not html:
        return ""
    out_dir = _ROOT / "output" / "visual"
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"{episode_id}.html"
    filepath.write_text(html, encoding="utf-8")
    return str(filepath)


_STANDALONE_CSS_CACHE: str | None = None
_STANDALONE_HTML_TEMPLATE: str | None = None


def _build_standalone_anchor_html() -> str:
    """Build a self-contained interactive Loom HTML page."""
    import re
    global _STANDALONE_HTML_TEMPLATE
    current_html_path = _ROOT / "output" / "current.html"
    if not current_html_path.exists():
        return ""

    body_content = current_html_path.read_text(encoding="utf-8")
    # Extract just the body inner content (skip doctype/head/body tags)
    body_match = re.search(r"<body>\s*(.+?)\s*</body>", body_content, re.DOTALL)
    if body_match:
        body_content = body_match.group(1)
    else:
        # Fallback: use everything inside body
        idx1 = body_content.find("<body")
        idx1 = body_content.find(">", idx1) + 1 if idx1 >= 0 else 0
        idx2 = body_content.rfind("</body>")
        if idx2 > idx1:
            body_content = body_content[idx1:idx2]

    css = _load_standalone_css()
    js = _STANDALONE_ANCHOR_JS

    title_match = re.search(r"<title>(.+?)</title>", current_html_path.read_text(encoding="utf-8"))
    title = title_match.group(1) if title_match else "Loom Analysis"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css">
<style>
{css}
</style>
</head>
<body data-loom-entry="fin" data-standalone="true">

<header id="anchor-toolbar" style="margin-bottom:28px">
  <span style="font-family:'Bricolage Grotesque',sans-serif;font-weight:700;font-size:18px">
    馃К Loom
  </span>
  <div style="font-size:12px;color:var(--ink-muted,#8888aa);margin-top:2px">
    Standalone interactive page &middot; Ctrl+Click to expand blocks
  </div>
</header>

{body_content}

<script>
{js}
</script>
</body>
</html>"""


def _load_standalone_css() -> str:
    """Load and cache the Bloom + base CSS for standalone pages."""
    import re
    global _STANDALONE_CSS_CACHE
    if _STANDALONE_CSS_CACHE is not None:
        return _STANDALONE_CSS_CACHE

    parts: list[str] = []

    # 1. Bloom design tokens
    bloom_path = _ROOT / "bridge" / "webview" / "resource" / "colors_and_type.css"
    if bloom_path.exists():
        tokens = bloom_path.read_text(encoding="utf-8")
        # Keep only :root block and body fonts 鈥?skip the @import (we use <link>)
        tokens = re.sub(r'@import[^;]+;', '', tokens)
        parts.append(tokens)
        parts.append("\n")

    # 2. Core component styles 鈥?extracted from styles.css
    styles_path = _ROOT / "bridge" / "webview" / "styles.css"
    if styles_path.exists():
        core = styles_path.read_text(encoding="utf-8")
        # Remove imports and font-face blocks
        core = re.sub(r'@import[^;]+;', '', core)
        core = re.sub(r'@font-face\s*\{[^}]*\}', '', core)
        parts.append(core)
        parts.append("\n")

    # 3. Detail overlay CSS
    overlay_path = _ROOT / "bridge" / "webview" / "loom-detail-overlay.css"
    if overlay_path.exists():
        parts.append(overlay_path.read_text(encoding="utf-8"))

    _STANDALONE_CSS_CACHE = "".join(parts)
    return _STANDALONE_CSS_CACHE


# Minimal anchor protocol client for standalone HTML files.
# Handles: Ctrl+click to expand detail sections, status pill rendering.
_STANDALONE_ANCHOR_JS = r"""
(function () {
  "use strict";

  const detailOverlay = createDetailOverlay();
  document.body.appendChild(detailOverlay);

  // 鈹€鈹€ Ctrl key detection 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  let ctrlDown = false;
  document.addEventListener("keydown", function (e) {
    if (e.key === "Control") {
      ctrlDown = true;
      document.body.classList.add("anc-ctrl-active");
    }
  });
  document.addEventListener("keyup", function (e) {
    if (e.key === "Control") {
      ctrlDown = false;
      document.body.classList.remove("anc-ctrl-active");
    }
  });

  // 鈹€鈹€ Click handler 鈥?Ctrl+click expands detail 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  document.addEventListener("click", function (e) {
    if (!ctrlDown) return;

    const el = e.target.closest("[data-anc]");
    if (!el) return;

    // KPI cards with hidden details
    const detail = el.querySelector(".anc-detail[hidden]");
    if (detail) {
      detail.removeAttribute("hidden");
      return;
    }

    // Elements with explicit detail flag
    if (el.dataset.hasDetail === "true") {
      const detail = el.querySelector(".anc-detail");
      if (detail) {
        detail.hidden = !detail.hidden;
        return;
      }
    }

    // Open full detail overlay for the anchor
    const anchorId = el.dataset.anc;
    if (anchorId) {
      showDetailOverlay(anchorId, el);
    }
  });

  // 鈹€鈹€ Detail overlay 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  function createDetailOverlay() {
    const ov = document.createElement("div");
    ov.id = "anc-detail-overlay";
    ov.className = "anc-detail-overlay";
    ov.setAttribute("aria-hidden", "true");
    ov.innerHTML = (
      '<div class="anc-detail-overlay__backdrop"></div>' +
      '<div class="anc-detail-overlay__panel">' +
        '<button class="anc-detail-overlay__close" aria-label="Close">&times;</button>' +
        '<div class="anc-detail-overlay__body"></div>' +
      '</div>'
    );
    ov.querySelector(".anc-detail-overlay__backdrop").addEventListener("click", hideOverlay);
    ov.querySelector(".anc-detail-overlay__close").addEventListener("click", hideOverlay);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") hideOverlay();
    });
    return ov;
  }

  function showDetailOverlay(anchorId, sourceEl) {
    const body = detailOverlay.querySelector(".anc-detail-overlay__body");
    // Collect all detail sections from the source element
    const detailSections = sourceEl.querySelectorAll(".anc-detail-section");
    let html = '<h2 style="margin:0 0 16px;font-family:var(--font-display)">' + escapeHtml(sourceEl.innerText.substring(0, 80) || anchorId) + '</h2>';

    if (detailSections.length) {
      detailSections.forEach(function (sec) {
        html += '<div style="margin-bottom:20px">' + sec.outerHTML + '</div>';
      });
    } else {
      // Show all text content from the element
      html += '<div style="white-space:pre-wrap;line-height:1.7">' + escapeHtml(sourceEl.innerText) + '</div>';
    }

    body.innerHTML = html;
    detailOverlay.setAttribute("aria-hidden", "false");
    detailOverlay.style.display = "flex";
  }

  function hideOverlay() {
    detailOverlay.setAttribute("aria-hidden", "true");
    detailOverlay.style.display = "none";
  }

  function escapeHtml(text) {
    var d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
  }

  // 鈹€鈹€ Style: Ctrl indicator 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  var style = document.createElement("style");
  style.textContent = (
    ".anc-ctrl-active [data-anc] { cursor: pointer; }" +
    ".anc-ctrl-active [data-anc]:hover { outline: 2px dashed var(--accent,#7A5AF8); outline-offset: 2px; border-radius: var(--radius-sm,8px); }" +
    ".anc-ctrl-active [data-anc][data-has-detail]:hover, " +
    ".anc-ctrl-active .anc-kpi:hover { outline: 2px dashed var(--accent,#7A5AF8); outline-offset: 4px; border-radius: var(--radius-md,14px); }" +
    "/* overlay styles */" +
    ".anc-detail-overlay { display:none; position:fixed; inset:0; z-index:9999; align-items:center; justify-content:center; }" +
    ".anc-detail-overlay[aria-hidden=false] { display:flex; }" +
    ".anc-detail-overlay__backdrop { position:absolute; inset:0; background:rgba(0,0,0,.35); backdrop-filter:blur(4px); }" +
    ".anc-detail-overlay__panel { position:relative; background:var(--paper,#fafafc); border-radius:var(--radius-md,14px); max-width:720px; width:90vw; max-height:80vh; overflow-y:auto; padding:32px; box-shadow:0 20px 60px rgba(0,0,0,.15); }" +
    ".anc-detail-overlay__close { position:absolute; top:12px; right:16px; background:none; border:none; font-size:24px; cursor:pointer; color:var(--ink-muted,#8888aa); }" +
    ".anc-detail-overlay__close:hover { color:var(--ink,#1a1a2e); }" +
    "/* standalone toolbar badge */" +
    "#anchor-toolbar { display:flex; justify-content:space-between; align-items:flex-start; padding-bottom:12px; border-bottom:1px solid var(--pastel-lavender,#d4c5f9); }"
  );
  document.head.appendChild(style);
})();
"""


def _public_webview_url(episode_id: str = "") -> str:
    """Build a public URL pointing to the analysis result visual page."""
    public = os.environ.get("LOOM_PUBLIC_URL", "").strip()
    if public:
        base = public.rstrip("/")
    else:
        base = _detect_base_url()
    if episode_id:
        return f"{base}/visual/{episode_id}"
    return base


def _detect_base_url() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    port = os.environ.get("LOOM_BRAIN_PORT", "3002")
    return f"http://{ip}:{port}"


_HTML_OUTPUT_KEYWORDS = [
    r"html\s*鏂囦欢", r"灏?*(?:缁撴灉|鍒嗘瀽|鎶ュ憡).*(?:鍙戦€亅缁欐垜|瀵煎嚭|杈撳嚭)",
    r"(?:鍙戦€亅缁欐垜|瀵煎嚭|杈撳嚭).*(?:html|鏂囦欢|缁撴灉|鎶ュ憡)",
    r"鐢熸垚.*(?:html|椤甸潰|鏂囦欢)", r"瀵煎嚭.*(?:html|鏂囦欢)",
    r"鍙?*(?:html|鏂囦欢|缁撴灉)", r"瑕?*(?:html|鏂囦欢)",
]


def _wants_html_output(text: str) -> bool:
    """True when the user asks for HTML/file output 鈥?route to full agent session."""
    import re as _re
    clean = str(text or "").strip().lower()
    if not clean:
        return False
    return any(_re.search(p, clean) for p in _HTML_OUTPUT_KEYWORDS)


def _find_agent_html(workspace: str) -> str:
    """Return the most recent .html file in <workspace>/output/, or ''."""
    import time as _time
    out_dir = Path(workspace) / "output"
    if not out_dir.is_dir():
        return ""
    best = ""
    best_mtime = 0.0
    cutoff = _time.time() - 300  # last 5 minutes
    try:
        for entry in out_dir.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".html":
                continue
            mtime = entry.stat().st_mtime
            if mtime < cutoff:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best = str(entry)
    except OSError:
        pass
    return best


async def _classify_complexity(question: str) -> str:
    """Classify user message complexity: 'simple' or 'complex'.

    Short-circuits very short / trivial messages; uses one LLM call for the rest.
    Falls back to 'simple' on error for graceful degradation.
    """
    clean = str(question or "").strip()
    # Very short messages are always simple 鈥?but check _wants_html_output first
    # (that bypass is handled in _route_social_message before this is called)
    if len(clean) <= 3:
        return "simple"
    try:
        resp = await _brain_client.messages.create(
            model=_brain_model,
            max_tokens=8,
            system=(
                "Classify the user message as 'simple' or 'complex'.\n"
                "simple = greeting, small talk, simple factual question, quick help, "
                "single-step request that needs no research or multi-step analysis.\n"
                "complex = multi-domain analysis, market research, file creation, "
                "coding, multi-step workflow, or anything requiring decomposition into subtasks.\n"
                "Reply ONLY 'simple' or 'complex'."
            ),
            messages=[{"role": "user", "content": clean}],
        )
        text = "".join(
            b.text for b in resp.content if hasattr(b, "text")
        ).strip().lower()
        return "simple" if "simple" in text else "complex"
    except Exception:
        return "simple"  # graceful degradation: quick reply beats silence


async def _simple_brain_reply(question: str, channel_context: dict) -> str:
    """Single-turn LLM reply for simple questions 鈥?no hand dispatch."""
    try:
        resp = await _brain_client.messages.create(
            model=_brain_model,
            max_tokens=2048,
            system=(
                "You are Loom Brain, an AI assistant. "
                "Give a concise, helpful reply in the same language as the user. "
                "Keep responses focused and brief unless the user asks for detail."
            ),
            messages=[{"role": "user", "content": question}],
        )
        return "".join(
            b.text for b in resp.content if hasattr(b, "text")
        ).strip()
    except Exception:
        return "Loom Brain is temporarily unavailable. Please try again."


async def _handle_session_command(
    sc: SessionCommand,
    message,
    channel_context: dict,
) -> tuple[str, dict]:
    """Execute /agent session management commands."""
    platform = str(getattr(message, "platform", "") or channel_context.get("platform", "discord"))
    channel_id = str(getattr(message, "channel_id", "") or channel_context.get("channel_id", ""))
    user_id = str(getattr(message, "user_id", "") or "")

    def _session_list_text(sessions) -> str:
        if not sessions:
            return "No active agent sessions."
        lines = [f"**Active Sessions** ({len(sessions)}):"]
        for s in sessions:
            fg = _session_registry.get_foreground(platform, channel_id, user_id)
            marker = "鈻?" if (fg and fg.session_id == s.session_id) else "  "
            lines.append(
                f"{marker}`{s.session_id[:8]}` {s.adapter_id} "
                f"[{s.status}] _{s.label}_ ({s.message_count} msgs)"
            )
        return "\n".join(lines)

    if sc.action == "start":
        # Friendly name mapping
        _friendly = {"codex": "codex-app-server", "claude": "runtime-hand", "cc": "runtime-hand"}
        adapter = _friendly.get(sc.adapter_id, sc.adapter_id) or "runtime-hand"
        label = sc.label or sc.adapter_id or adapter
        record = _session_registry.start(adapter, platform, channel_id, user_id, label)
        _session_registry.set_foreground(platform, channel_id, user_id, record.session_id)
        return (
            f"[session] **Session Mode** - `{label}`\n"
            f"ID: `{record.session_id[:8]}` | Adapter: {adapter}\n\n"
            f"All messages now route directly to this session (Brain bypassed).\n"
            f"Switch back: `/brain` | End session: `/agent close` | Loom analysis: `/loom <task>`",
            {"ok": True, "session_id": record.session_id},
        )

    if sc.action == "list":
        sessions = _session_registry.list_sessions(platform, channel_id, user_id)
        return _session_list_text(sessions), {"ok": True, "sessions": [s.to_dict() for s in sessions]}

    if sc.action == "status":
        fg = _session_registry.get_foreground(platform, channel_id, user_id)
        if fg is None:
            sessions = _session_registry.list_sessions(platform, channel_id, user_id)
            return (
                "No foreground session set.\n\n" + _session_list_text(sessions),
                {"ok": True, "foreground": None, "sessions": [s.to_dict() for s in sessions]},
            )
        return (
            f"**Foreground Session**\n"
            f"ID: `{fg.session_id[:8]}`\n"
            f"Adapter: {fg.adapter_id}\n"
            f"Label: {fg.label}\n"
            f"Status: {fg.status}\n"
            f"Messages: {fg.message_count}\n\n"
            f"Send any message to route to this session. "
            f"Use `/agent close {fg.session_id[:8]}` to end.",
            {"ok": True, "foreground": fg.to_dict()},
        )

    if sc.action == "select":
        sid = sc.session_id
        sessions = _session_registry.list_sessions(platform, channel_id, user_id)
        matched = [s for s in sessions if s.session_id.startswith(sid)] if sid else []
        if not matched:
            return f"Session `{sid or '?'}` not found.", {"ok": False}
        record = matched[0]
        _session_registry.set_foreground(platform, channel_id, user_id, record.session_id)
        return (
            f"**Switched to session** `{record.session_id[:8]}` ({record.adapter_id}, {record.label})",
            {"ok": True, "session_id": record.session_id},
        )

    if sc.action == "close":
        sid = sc.session_id
        sessions = _session_registry.list_sessions(platform, channel_id, user_id)
        matched = [s for s in sessions if s.session_id.startswith(sid)] if sid else []
        if not matched:
            fg = _session_registry.get_foreground(platform, channel_id, user_id)
            if fg:
                matched = [fg]
        if not matched:
            return "No session to close.", {"ok": False}
        record = matched[0]
        _session_registry.close(record.session_id)
        return (
            f"**Session closed** `{record.session_id[:8]}` ({record.label})",
            {"ok": True, "session_id": record.session_id},
        )

    if sc.action == "brain":
        _session_registry.clear_foreground(platform, channel_id, user_id)
        return (
            "[brain] **Switched to Brain mode.** Messages will be routed to Loom Brain for analysis.\n\n"
            "Use `/agent start` to switch back to agent session mode.",
            {"ok": True},
        )

    # help
    return (
        "**Loom Channel - Two Modes**\n\n"
        "[brain] **Brain Mode** (default) - Loom Brain analyzes with multi-hand pipeline:\n"
        "`/loom <task>` - Full analysis with hand agents\n"
        "`/brain` - Switch to Brain mode\n\n"
        "[session] **Session Mode** - Direct agent, Brain bypassed:\n"
        "`/agent start [codex|claude] [label]` - Start persistent session\n"
        "`/agent list` - List your sessions\n"
        "`/agent select <id>` - Switch foreground session\n"
        "`/agent status` - Show current session\n"
        "`/agent close [id]` - Close session\n\n"
        "`/codex <task>` - One-shot Codex (no session)\n"
        "`/claude <task>` - One-shot Claude Code (no session)",
        {"ok": True},
    )


async def _run_session_relay(
    session_route: dict,
    message,
    channel_context: dict,
    progress_reporter=None,
) -> dict | None:
    """Relay a channel message to the foreground agent session."""
    adapter_id = session_route.get("adapter_id", "runtime-hand")
    task = session_route.get("task", "")
    session_id = session_route.get("session_id", "")

    _session_registry.set_status(session_id, "running")

    if progress_reporter is not None:
        # Mark progress as session mode so embed shows "Session Mode" vs "Brain"
        progress_reporter._progress.session_mode = True
        progress_reporter.notify({
            "type": "dispatch.sent",
            "hand_id": adapter_id,
            "task_id": session_id,
            "dimension": "session relay",
        })

    try:
        result = await _agent_session_service.run(
            adapter_id=adapter_id,
            task=task,
            cwd=str(_ROOT),
            context={
                "source": "session_relay",
                "session_id": session_id,
                "social": asdict(message),
                "agent_session": True,
            },
            dangerous=True,
            session_key=session_id,
        )
    except Exception as exc:
        _session_registry.set_status(session_id, "idle")
        if progress_reporter is not None:
            progress_reporter.notify({
                "type": "dispatch.error",
                "hand_id": adapter_id,
                "task_id": session_id,
                "message": str(exc),
            })
        raise

    _session_registry.touch(session_id)
    _session_registry.set_status(session_id, "idle")

    if progress_reporter is not None:
        progress_reporter.notify({
            "type": "dispatch.artifact",
            "hand_id": adapter_id,
            "task_id": session_id,
        })

    return result


async def _route_social_message(
    message,
    channel_context: dict,
) -> dict:
    """Route messages: /agent commands 鈫?foreground session 鈫?Brain pipeline."""
    # 鈹€鈹€ Layer 0: /agent session management commands 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    session_cmd = parse_session_command(message.text)
    if session_cmd is not None:
        return {
            "route": "session_command",
            "reply_text": "",
            "reason": f"session command: {session_cmd.action}",
            "confidence": 1.0,
            "router": "session",
            "session_command": session_cmd,
        }

    settings = channel_context.get("channel_settings")
    if not isinstance(settings, dict):
        settings = {}

    # 鈹€鈹€ Layer 1: foreground session bypasses Brain 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    platform = str(
        channel_context.get("platform")
        or settings.get("platform")
        or getattr(message, "platform", "")
        or "discord"
    )
    channel_id = str(
        channel_context.get("channel_id")
        or getattr(message, "channel_id", "")
        or ""
    )
    user_id = str(getattr(message, "user_id", "") or "")
    if platform and channel_id and user_id:
        session_route = _session_registry.resolve_route(
            platform, channel_id, user_id, message.text
        )
        if session_route["route"] == "session":
            if not is_explicit_loom_command(message.text) and parse_agent_command(message.text) is None:
                return {
                    "route": "route_to_session",
                    "reply_text": "",
                    "reason": "foreground session active",
                    "confidence": 1.0,
                    "router": "session",
                    "session_route": session_route,
                }

    direct_command = parse_agent_command(message.text)
    direct_default = (
        str(settings.get("executionMode") or settings.get("execution_mode") or "brain").lower()
        == "agent"
        and not is_explicit_loom_command(message.text)
    )
    if direct_command is not None or direct_default:
        return {
            "route": "direct_agent",
            "reply_text": "",
            "reason": "explicit agent command" if direct_command is not None else "channel direct-agent mode",
            "confidence": 1.0,
            "router": "direct",
        }
    # Explicit Loom commands always go through the full Brain pipeline
    # so the UI rendering (visual page, webview patches) fires correctly.
    if is_explicit_loom_command(message.text):
        return {
            "route": "complex_task",
            "reply_text": "",
            "reason": "explicit Loom command 鈥?full Brain pipeline for UI rendering",
            "confidence": 1.0,
            "router": "direct",
        }
    # HTML/file output requests: route to full agent session (Codex/CC).
    # The Brain pipeline's structured JSON artifact contract is too rigid
    # for deep analysis 鈥?a free-form agent produces much richer output.
    if _wants_html_output(message.text):
        # Route to the best available agent adapter for deep analysis.
        # Falls back gracefully in _run_social_agent if none is registered.
        return {
            "route": "direct_agent",
            "reply_text": "",
            "reason": "HTML/file output requested 鈥?full agent session",
            "confidence": 1.0,
            "router": "direct",
        }
    # Complexity classification: simple 鈫?direct reply; complex 鈫?full Brain pipeline
    try:
        complexity = await _classify_complexity(message.text)
    except Exception:
        complexity = "simple"
    if complexity == "simple":
        return {
            "route": "simple",
            "reply_text": "",
            "reason": "simple question 鈥?Brain direct reply",
            "confidence": 1.0,
            "router": "classifier",
        }
    return {
        "route": "complex_task",
        "reply_text": "",
        "reason": "complex task 鈥?full Brain hand pipeline",
        "confidence": 1.0,
        "router": "classifier",
    }


def _best_agent_adapter() -> str:
    """Return the best available full agent adapter id, or empty string."""
    for aid in ("runtime-hand", "codex-app-server"):
        if _adapter_registry.find_by_id(aid):
            return aid
    for a in _adapter_registry.list():
        if "runtime.hand" in a.capabilities:
            return a.id
    return ""


async def _run_social_agent(message, channel_context: dict, progress_reporter=None) -> dict | None:
    """Run a channel message directly on a configured full agent runtime.

    Falls back to the best available agent adapter when no explicit command
    or agent-mode channel configuration is present (e.g. HTML output requests).
    """
    request = resolve_social_agent_request(
        text=message.text,
        user_id=message.user_id,
        context=channel_context,
        default_adapter_id=_adapter_registry.get_default_runtime_adapter(),
    )
    if request is None:
        # Fallback for routes that want direct_agent but user didn't type
        # /codex or /claude 鈥?pick best available adapter.
        adapter_id = _best_agent_adapter()
        if not adapter_id:
            return None
        from loom_core.interaction_protocol.social import SocialAgentCommand
        request = SocialAgentCommand(adapter_id=adapter_id, task=message.text, dangerous=True)
    settings = channel_context.get("channel_settings")
    if not isinstance(settings, dict):
        settings = {}
    workspace = str(
        settings.get("agentWorkspace")
        or settings.get("agent_workspace")
        or _ROOT
    )
    adapter_id = request.adapter_id

    if progress_reporter is not None:
        progress_reporter.notify({
            "type": "dispatch.sent",
            "hand_id": adapter_id,
            "task_id": "direct-agent",
            "dimension": "full agent session",
        })

    async def _agent_event(event: dict) -> None:
        if progress_reporter is None:
            return
        if event.get("type") == "run.started":
            progress_reporter.notify({
                "type": "episode.start",
                "episode_id": str(event.get("run_id") or ""),
            })
            progress_reporter.notify({
                "type": "state.transition",
                "to": "Dispatching",
                "episode_id": str(event.get("run_id") or ""),
            })

    try:
        session_key = str(channel_context.get("session_id") or "")
        result = await _agent_session_service.run(
            adapter_id=adapter_id,
            task=request.task,
            cwd=workspace,
            context={
                "source": "social",
                "session_id": session_key,
                "social": asdict(message),
                "agent_session": True,
            },
            event_sink=_agent_event,
            dangerous=request.dangerous,
            session_key=session_key,
        )
    except Exception as exc:
        if progress_reporter is not None:
            progress_reporter.notify({
                "type": "dispatch.error",
                "hand_id": adapter_id,
                "task_id": "direct-agent",
                "message": str(exc),
            })
            progress_reporter.notify({"type": "episode.error", "message": str(exc)})
            progress_reporter.notify({"type": "state.transition", "from": "Dispatching", "to": "Failed"})
        raise

    if progress_reporter is not None:
        progress_reporter.notify({
            "type": "dispatch.artifact",
            "hand_id": adapter_id,
            "task_id": "direct-agent",
        })
        progress_reporter.notify({
            "type": "state.transition",
            "to": "Persisted",
            "episode_id": result.get("run_id", ""),
        })
    return result


async def _handle_social_ingress(
    req: SocialIngressRequest,
    *,
    channel: SocialChannelAdapter,
    platform: str | None = None,
) -> dict:
    message = channel.normalize_payload(_social_payload(req, platform=platform or channel.platform))
    if not channel.is_allowed(message.user_id):
        return {
            "ok": False,
            "error": "sender is not allowed for this social channel",
            "social": asdict(message),
            "social_channel": channel.public_info(),
        }
    channel_context = channel.context(req.context)
    social_route = await _route_social_message(message, channel_context)
    channel_context["social_route"] = social_route
    progress_reporter = None
    status_message_id = str(channel_context.get("statusMessageId") or "")
    if channel.platform == "discord" and status_message_id:
        async def _publish_progress(embed: dict) -> None:
            await channel.edit_progress(
                message=message,
                status_message_id=status_message_id,
                embed=embed,
                context=channel_context,
            )

        progress_reporter = DiscordProgressReporter(_publish_progress)
        channel_context["_episode_event_sink"] = progress_reporter.notify
    analyze_payload = build_analyze_request_from_social(
        message,
        extra_context=channel_context,
        domain_hint=req.domain_hint,
        domain_registry=_domain_registry,
    )
    if not analyze_payload["question"]:
        return {"ok": False, "error": "social message text is required", "reply_text": ""}
    route = social_route.get("route", "complex_task")
    agent_session = None
    try:
        # 鈹€鈹€ Session command route 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        if route == "session_command":
            sc = social_route.get("session_command")
            reply_text, result = await _handle_session_command(
                sc, message, channel_context
            )
            visual_html_file = ""
            if progress_reporter is not None:
                progress_reporter._progress.direct_reply = True
        # 鈹€鈹€ Route to foreground session 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        elif route == "route_to_session":
            sr = social_route.get("session_route", {})
            agent_session = await _run_session_relay(
                sr, message, channel_context, progress_reporter
            )
            if agent_session is not None:
                result = {"episode_id": agent_session.get("run_id", "")}
                reply_text = str(agent_session.get("text") or "")
                visual_html_file = ""
            else:
                reply_text = "Agent session returned no output."
                result = {"episode_id": ""}
                visual_html_file = ""
        elif route == "direct_agent":
            agent_session = await _run_social_agent(message, channel_context, progress_reporter)
            if agent_session is not None:
                result = {"episode_id": agent_session.get("run_id", "")}
                reply_text = str(agent_session.get("text") or "")
                # Find HTML files the agent created in workspace
                settings = channel_context.get("channel_settings")
                ws = str(
                    (settings.get("agentWorkspace") or settings.get("agent_workspace") or _ROOT)
                    if isinstance(settings, dict) else _ROOT
                )
                visual_html_file = _find_agent_html(ws)
                if visual_html_file:
                    reply_text += "\n\nHTML analysis page attached."
                else:
                    visual_html_file = ""
            else:
                # Agent session not available 鈥?fall through to simple reply
                reply_text = await _simple_brain_reply(message.text, channel_context)
                result = {"episode_id": ""}
                visual_html_file = ""
                if progress_reporter is not None:
                    progress_reporter._progress.direct_reply = True
        elif route == "simple":
            reply_text = await _simple_brain_reply(message.text, channel_context)
            result = {"episode_id": ""}
            visual_html_file = ""
            if progress_reporter is not None:
                progress_reporter._progress.direct_reply = True
        else:  # complex_task
            result = await analyze(AnalyzeRequest(**analyze_payload))
            visual_html_file = ""
            if _is_loom_visual_command(message.text):
                ep_id = result.get("episode_id", "")
                visual_html_file = _save_visual_html(ep_id)
            reply_text = render_analysis_reply(result, visual_html_file=visual_html_file)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        reply_text = f"Loom Brain error: {exc}"
        result = {"episode_id": ""}
        visual_html_file = ""
    finally:
        if progress_reporter is not None:
            await progress_reporter.flush()
    reply_result = None
    if _social_should_send_reply(req, channel_context):
        reply_result = await channel.send_reply(
            text=reply_text,
            message=message,
            webhook_url=req.reply_webhook_url or str(channel_context.get("reply_webhook_url", "")),
            token=req.reply_token or str(channel_context.get("reply_token", "")),
            context=channel_context,
            file_path=visual_html_file,
        )
    return {
        "ok": True,
        "social": asdict(message),
        "social_channel": channel.public_info(),
        "social_route": social_route,
        "episode_id": result.get("episode_id", ""),
        "reply_text": reply_text,
        "visual_html_file": visual_html_file,
        "agent_session": agent_session,
        "reply": asdict(reply_result) if reply_result else {"skipped": True},
    }


@app.get("/social/channels")
async def list_social_channels():
    return {
        "ok": True,
        "default_channel": _social_channel_registry.get_default(),
        "config_path": str(_SOCIAL_CHANNEL_CONFIG_PATH),
        "available_channel_types": available_social_channel_types(),
        "channels": [channel.public_info() for channel in _social_channel_registry.list()],
    }


@app.get("/social/channels/config")
async def get_social_channels_config():
    return {
        "ok": True,
        "config_path": str(_SOCIAL_CHANNEL_CONFIG_PATH),
        **registry_to_document(_social_channel_registry),
    }


@app.put("/social/channels/config")
async def replace_social_channels_config(req: SocialChannelsConfigRequest):
    global _social_channel_registry
    document = {
        "version": 1,
        "default_channel": req.default_channel,
        "channels": req.channels,
    }
    try:
        registry = create_social_channel_registry_from_document(document)
        _social_channel_registry = registry
        _save_social_channels()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "default_channel": _social_channel_registry.get_default(),
        "channels": [channel.public_info() for channel in _social_channel_registry.list()],
    }


@app.post("/social/channels/register")
async def register_social_channel(req: SocialChannelRegisterRequest):
    config = req.model_dump(by_alias=True) if hasattr(req, "model_dump") else req.dict(by_alias=True)
    try:
        channel = social_channel_from_config(config)
        _social_channel_registry.upsert(channel)
        if req.set_default:
            _social_channel_registry.set_default(channel.id)
        _save_social_channels()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "channel": channel.public_info(),
        "default_channel": _social_channel_registry.get_default(),
    }


@app.post("/social/channels/default")
async def set_default_social_channel(req: DefaultSocialChannelRequest):
    try:
        _social_channel_registry.set_default(req.channel_id)
        _save_social_channels()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "default_channel": _social_channel_registry.get_default()}


@app.delete("/social/channels/{channel_id}")
async def delete_social_channel(channel_id: str):
    if channel_id == "generic":
        return {"ok": False, "error": "generic channel cannot be deleted"}
    removed = _social_channel_registry.unregister(channel_id)
    if not removed:
        return {"ok": False, "error": f"unknown social channel: {channel_id}"}
    if _social_channel_registry.get_default() == channel_id:
        _social_channel_registry.set_default("generic")
    _save_social_channels()
    return {"ok": True, "channel_id": channel_id}


@app.post("/social/ingress")
async def social_ingress(req: SocialIngressRequest, request: Request):
    raw_body = await request.body()
    raw_payload = _decode_raw_json(raw_body)
    try:
        channel = _select_social_channel(req)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    verification, early_response = _verify_social_or_response(
        channel=channel,
        headers=request.headers,
        raw_body=raw_body,
        payload=_verification_payload(req, raw_payload),
    )
    if early_response is not None:
        return early_response
    req.context.setdefault("verification", {
        "method": verification.method,
        "skipped": verification.skipped,
    })
    return await _handle_social_ingress(req, channel=channel)


@app.post("/social/{platform}/ingress")
async def social_platform_ingress(platform: str, req: SocialIngressRequest, request: Request):
    raw_body = await request.body()
    raw_payload = _decode_raw_json(raw_body)
    try:
        channel = _select_social_channel(req, platform=platform)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    verification, early_response = _verify_social_or_response(
        channel=channel,
        headers=request.headers,
        raw_body=raw_body,
        payload=_verification_payload(req, raw_payload),
    )
    if early_response is not None:
        return early_response
    req.context.setdefault("verification", {
        "method": verification.method,
        "skipped": verification.skipped,
    })
    return await _handle_social_ingress(req, channel=channel, platform=platform)


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


# 鈹€鈹€ OAuth 2.0 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

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
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Authorization Complete</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:320px}}
.icon{{font-size:48px;margin-bottom:16px}}h2{{margin:0 0 8px;color:#1a1a2e}}p{{color:#666;font-size:14px}}</style>
</head><body><div class="card"><div class="icon">OK</div><h2>Authorization successful</h2>
<p>Connected to {safe_prov}. This window will close automatically.</p></div>
<script>if(window.opener){{window.opener.postMessage({msg_js},'*')}}setTimeout(()=>window.close(),1500)</script>
</body></html>"""
    safe_err = html.escape(error)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Authorization Failed</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f8fafc}}
.card{{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:320px}}
.icon{{font-size:48px;margin-bottom:16px}}h2{{margin:0 0 8px;color:#1a1a2e}}p{{color:#e53e3e;font-size:14px}}
button{{margin-top:16px;padding:8px 20px;border-radius:8px;border:1px solid #ddd;cursor:pointer}}</style>
</head><body><div class="card"><div class="icon">ERROR</div><h2>Authorization failed</h2>
<p>{safe_err}</p><button onclick="window.close()">Close</button></div>
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
        return {"ok": False, "error": "Google OAuth not configured 鈥?POST /oauth/clients first"}
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
        return {"ok": False, "error": "Notion OAuth not configured 鈥?POST /oauth/clients first"}
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
    """Brain B-business: workflow resolve 鈫?parallel hands 鈫?synthesis 鈫?render."""
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
    intent_extra_context = json.dumps(
        {
            "source": ctx.get("source", "api"),
            "entrypoint": ctx.get("entrypoint", ""),
            "goal_id": goal_id,
            "social": ctx.get("social", {}),
        },
        ensure_ascii=False,
    )
    intent_task = asyncio.create_task(
        _intent_processor.parse(
            "query",
            req.question,
            extra_context=intent_extra_context,
            session_id=str(ctx.get("session_id", "")),
        )
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
            intent_activation=result.get("intent_activation"),
            intent_rubric=result.get("intent_rubric"),
            intent_reward_report=result.get("intent_reward_report"),
        )
        fw_record.orchestration_snapshot = build_minimal_orchestration_snapshot(
            episode_id=fw_record.episode_id,
            goal=req.question,
            domain=wf.get("domain", "general") if isinstance(wf, dict) else "general",
            workflow=wf if isinstance(wf, dict) else {},
            hand_plan=result.get("hand_plan") or {},
            hand_artifacts=result.get("hand_artifacts", {}),
            review_result=result.get("review_result") or {},
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

    brain_html = _render_brain_synthesis(synthesis, wf, cold, episode_id=episode_id, goal_id=goal_id,
                                         hand_artifacts=result.get("hand_artifacts", {}))
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
        # Error cards skip the Brain presentation layer 鈥?the enrichment function
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
    source_platform: str = ""
    resource_kind: str = ""
    trust_tier: str = ""
    intent_hint: str = ""
    tags: list[str] = Field(default_factory=list)
    domain: str = "general"


class FrameworkAcceptRequest(BaseModel):
    framework: dict


class ResourceCaptureRequest(BaseModel):
    title: str = ""
    url: str = ""
    text: str = ""
    note: str = ""
    source: str = ""
    source_author: str = ""
    source_platform: str = ""
    source_date: str = ""
    resource_kind: str = ""
    trust_tier: str = ""
    intent_hint: str = ""
    value_signal: str = ""
    tags: list[str] = Field(default_factory=list)
    domain: str = "general"
    market_scope: dict = Field(default_factory=dict)
    user_signal: dict = Field(default_factory=dict)


@app.post("/resources/capture")
async def resources_capture(req: ResourceCaptureRequest):
    """Capture resource metadata for evaluator-side wiki/rubric use."""
    resource = _brain_harness.resource_registry.capture(req.model_dump())
    return {
        "ok": True,
        "resource": asdict(resource),
        "paths": {
            "resource_wiki": "brain/resource_wiki/resources.json",
        },
    }


@app.get("/resources/wiki")
async def resources_wiki():
    """List captured resource wiki entries and distilled strategy primitives."""
    return {
        "ok": True,
        "resources": _brain_harness.resource_registry.list_resources(include_channel=True),
        "strategy_primitives": _brain_harness.resource_registry.list_strategy_primitives(),
    }


@app.get("/resources/rubric-context")
async def resources_rubric_context(domain: str = "general", question: str = "", limit: int = 5):
    """Preview the compact resource sidecar context used by rubric compilation."""
    return {
        "ok": True,
        "context": _brain_harness.resource_registry.query_rubric_context(
            domain=domain,
            question=question,
            limit=limit,
        ),
    }


@app.post("/distill")
async def distill(req: DistillRequest):
    """Distill a resource (text or URL) into AnalyticalFramework candidates.

    Returns a list of framework candidates for user review (accept/edit/reject).
    Does NOT persist automatically 鈥?call /frameworks/accept to store.
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

    captured_resource = _brain_harness.resource_registry.capture({
        "title": req.url or req.source_author or text[:80],
        "url": req.url,
        "text": text,
        "source_author": req.source_author,
        "source_date": req.source_date,
        "source_platform": req.source_platform,
        "resource_kind": req.resource_kind or ("link" if req.url else "excerpt"),
        "trust_tier": req.trust_tier,
        "intent_hint": req.intent_hint,
        "tags": req.tags,
        "domain": req.domain,
    })

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
    strategy_primitives = _brain_harness.resource_registry.add_strategy_primitives(
        resource_id=captured_resource.resource_id,
        frameworks=candidates,
        domain=req.domain,
        trust_tier=req.trust_tier or captured_resource.trust_tier,
    )
    try:
        intent_event = await intent_task
        _intent_stream.append(intent_event)
        _intent_wiki.ingest_event(intent_event)
    except Exception:
        pass

    print(f"[brain] /distill 鈫?{len(candidates)} framework candidate(s)", flush=True)
    return {
        "ok": True,
        "resource": asdict(captured_resource),
        "candidates": candidates,
        "strategy_primitives": [asdict(item) for item in strategy_primitives],
    }


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
    """JSON API 鈥?full event log + derived context."""
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


@app.get("/visual/{episode_id}")
async def visual_result(episode_id: str):
    """Return a standalone HTML result page for a completed episode."""
    record = _flywheel.load_detail(episode_id)
    if record is None:
        return HTMLResponse(f"<h1>Episode not found</h1><p>{_html_text(episode_id)}</p>", status_code=404)
    return HTMLResponse(_render_visual_page(record, episode_id))




def _render_harness_architecture_page() -> str:
    """Standalone read-only Harness page for Loom agent architecture."""
    script_path = _ROOT / "bridge" / "webview" / "harness-summary.js"
    if script_path.exists():
        summary_script = script_path.read_text(encoding="utf-8")
        summary_script = summary_script.replace("var BRAIN = 'http://127.0.0.1:3002';", "var BRAIN = window.location.origin;")
    else:
        summary_script = "document.body.insertAdjacentHTML('beforeend', '<p>harness-summary.js not found</p>');"

    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loom Harness Architecture</title>
<style>
  :root {
    --bg-1: #f7f8fb;
    --bg-2: #ffffff;
    --bg-3: #eceff4;
    --ink-1: #151722;
    --ink-2: #4c5263;
    --ink-3: #7d8494;
    --accent-iris: #4657d8;
    --success: #1f9d68;
    --warning: #d27c1f;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: var(--bg-1);
    color: var(--ink-1);
    font: 14px/1.5 "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  }
  .harness-hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 24px;
    align-items: end;
    padding: 36px clamp(20px, 5vw, 64px) 22px;
    border-bottom: 1px solid rgba(21, 23, 34, 0.08);
    background: #fff;
  }
  .harness-eyebrow {
    margin: 0 0 6px;
    color: var(--accent-iris);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
  }
  .harness-hero h1 {
    margin: 0;
    font-size: clamp(28px, 4vw, 44px);
    line-height: 1.05;
    letter-spacing: 0;
  }
  .harness-hero p:last-child {
    max-width: 760px;
    margin: 10px 0 0;
    color: var(--ink-2);
  }
  .harness-links {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
  }
  .harness-links a,
  .anc-pill {
    display: inline-flex;
    align-items: center;
    border: 1px solid rgba(21, 23, 34, .10);
    border-radius: 999px;
    background: #fff;
    color: var(--ink-2);
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
    text-decoration: none;
    white-space: nowrap;
  }
  .harness-links a:hover { border-color: rgba(70, 87, 216, .35); color: var(--accent-iris); }
  .harness-shell { width: min(1180px, calc(100vw - 40px)); margin: 24px auto 56px; }
  .anc-section--gc {
    background: var(--bg-2);
    border: 1px solid rgba(21, 23, 34, .10);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 18px 48px -40px rgba(21, 23, 34, .42);
  }
  .anc-pill--done { background: #eaf7f0; color: #127148; }
  .anc-pill--warn { background: #fff4df; color: #9a5a13; }
  .anc-pill--gen { background: #edf0ff; color: #3342b4; }
  .anc-pill--review { background: #eef8f6; color: #0b766b; }
  code { font-family: "Cascadia Mono", Consolas, monospace; }
  @media (max-width: 760px) {
    .harness-hero { grid-template-columns: 1fr; }
    .harness-links { justify-content: flex-start; }
    .harness-shell { width: calc(100vw - 24px); }
  }
</style>
</head>
<body>
<header class="harness-hero">
  <div>
    <p class="harness-eyebrow">Loom Harness</p>
    <h1>Agent Architecture</h1>
    <p>Read-only surface for Brain health, hand agent states, adapter registry, runtime bindings, mounts, model configuration, and recent execution state.</p>
  </div>
  <nav class="harness-links" aria-label="Harness data links">
    <a href="/health">Health JSON</a>
    <a href="/hands/runtime-bindings">Runtime Bindings</a>
    <a href="/adapters">Adapters</a>
    <a href="/intent-stream">Intent Stream</a>
  </nav>
</header>
<main class="harness-shell">
  <section class="anc-section anc-section--gc" data-anc="harness-summary" data-detail-disabled="true"></section>
</main>
<script>
__HARNESS_SUMMARY_SCRIPT__
</script>
</body>
</html>"""
    return page.replace("__HARNESS_SUMMARY_SCRIPT__", summary_script)

@app.get("/harness")
async def harness_page():
    """Read-only Harness page for agent states, configs, and runtime bindings."""
    return HTMLResponse(_render_harness_architecture_page())

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
<title>Intent Stream 鈥?Loom Brain</title>
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

  /* 鈹€鈹€ Header 鈹€鈹€ */
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

  /* 鈹€鈹€ Timeline 鈹€鈹€ */
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

  /* 鈹€鈹€ Sidebar 鈹€鈹€ */
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
    <div id="decision-context" class="decision-context" style="color:var(--ink-muted);font-style:normal">-</div>
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
            <div class="talent-meta">${n.is_active ? 'active' : 'inactive'} 路 conf ${Math.round((n.confidence || 0)*100)}% 路 ev ${n.evidence_count || 0}</div>
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


@app.post("/agent-sessions/run")
async def run_agent_session(req: AgentSessionRequest):
    adapter_id = req.adapter_id or _adapter_registry.get_default_runtime_adapter()
    try:
        session = await _agent_session_service.run(
            adapter_id=adapter_id,
            task=req.task,
            cwd=req.cwd or str(_ROOT),
            context=req.context,
            dangerous=req.dangerous,
            session_key=req.session_key,
        )
    except Exception as exc:
        return {"ok": False, "adapter_id": adapter_id, "error": str(exc)}
    return {"ok": True, **session}


# 鈹€鈹€ Agent Session Registry endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@app.get("/agent-sessions")
async def list_agent_sessions(
    platform: str = "",
    channel_id: str = "",
    user_id: str = "",
):
    sessions = _session_registry.list_sessions(platform, channel_id, user_id)
    return {
        "ok": True,
        "count": len(sessions),
        "sessions": [s.to_dict() for s in sessions],
    }


@app.post("/agent-sessions")
async def start_agent_session(req: AgentSessionStartRequest):
    record = _session_registry.start(
        adapter_id=req.adapter_id,
        platform=req.platform,
        channel_id=req.channel_id,
        user_id=req.user_id,
        label=req.label,
    )
    return {"ok": True, "session": record.to_dict()}


@app.put("/agent-sessions/{session_id}/foreground")
async def set_session_foreground(session_id: str, req: AgentSessionSelectRequest):
    record = _session_registry.set_foreground(
        req.platform or "discord",
        req.channel_id,
        req.user_id,
        session_id,
    )
    if record is None:
        return {"ok": False, "error": f"session not found: {session_id}"}
    return {"ok": True, "session": record.to_dict()}


@app.delete("/agent-sessions/{session_id}")
async def close_agent_session(session_id: str):
    ok = _session_registry.close(session_id)
    return {"ok": ok}



@app.post("/loom/run")
async def loom_run(req: RunRequest):
    """Alias for /run for backward compatibility with harness panel."""
    return await run(req)

@app.post("/run")
async def run(req: RunRequest):
    info = REGISTRY.get(req.hand_id, {})
    context = _with_brain_portfolio_context(req.hand_id, req.context)
    runtime = _runtime_for_hand(req.hand_id, req.runtime)
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
    elif runtime == _DIRECT_CODEX_RUNTIME_ID:
        try:
            artifact = await _run_direct_codex_hand(req.hand_id, req.task, context)
        except Exception as e:
            return {"ok": False, "runtime": runtime, "error": str(e)}
    else:
        # Adapter-based path (cc, codex, sdk-<id>, etc.)
        adapter = _ensure_runtime_adapter(runtime)
        if adapter is None:
            return {"ok": False, "error": f"unknown runtime adapter: {runtime}"}
        wiki_dir = info.get("wiki_dir", "")
        hand_dir = str(Path(wiki_dir).parent) if wiki_dir else ""
        personal = _read_personal_context(req.hand_id)
        # Inject into context so http脳loom _build_snapshot forwards it to cloud agents.
        context_with_personal = {**context}
        if personal:
            context_with_personal["__personal__"] = personal
        envelope = {
            "task": req.task,
            "context": context_with_personal,
            "hand_id": req.hand_id,
            "hand_dir": hand_dir,
            "cwd": str(_ROOT),
            "wiki_dir": wiki_dir,
            "resource_api": "http://127.0.0.1:3001/resources",
            "feedback_log": str(_ROOT / "logs" / "feedback.jsonl"),
            "personal": personal,  # top-level for process脳loom agents (stdin JSON)
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

    return {"ok": True, "hand_id": req.hand_id, "runtime": runtime, "artifact": artifact}


@app.get("/adapters")
async def list_agent_adapters():
    return {
        "ok": True,
        "default_runtime_adapter": _adapter_registry.get_default_runtime_adapter(),
        "adapters": [adapter_public_info(a) for a in _adapter_registry.list()],
        "dynamic_adapter_ids": sorted(_DYNAMIC_ADAPTER_CONFIGS.keys()),
    }


@app.get("/hands/runtime-bindings")
async def list_hand_runtime_bindings():
    return {
        "ok": True,
        "config_path": str(_HAND_RUNTIME_BINDINGS.path),
        "bindings": _HAND_RUNTIME_BINDINGS.list(),
        "hands": [_hand_runtime_state(hand_id) for hand_id in sorted(REGISTRY)],
        "adapters": [adapter_public_info(a) for a in _adapter_registry.list()],
    }


@app.get("/hand/{hand_id}/runtime")
async def get_hand_runtime(hand_id: str):
    if hand_id not in REGISTRY:
        return {"ok": False, "error": f"unknown hand: {hand_id}"}
    return {
        "ok": True,
        **_hand_runtime_state(hand_id),
        "default_runtime_adapter": _adapter_registry.get_default_runtime_adapter(),
        "adapters": [adapter_public_info(a) for a in _adapter_registry.list()],
    }


@app.put("/hand/{hand_id}/runtime")
async def set_hand_runtime(hand_id: str, req: HandRuntimeRequest):
    if hand_id not in REGISTRY:
        return {"ok": False, "error": f"unknown hand: {hand_id}"}
    adapter_id = req.adapter_id.strip()
    if adapter_id in {"", "default"}:
        _HAND_RUNTIME_BINDINGS.remove(hand_id)
    elif adapter_id == "sdk" or _adapter_registry.find_by_id(adapter_id) is not None:
        _HAND_RUNTIME_BINDINGS.set(hand_id, adapter_id)
    else:
        return {"ok": False, "error": f"unknown runtime adapter: {adapter_id}"}
    return {"ok": True, **_hand_runtime_state(hand_id)}


@app.delete("/hand/{hand_id}/runtime")
async def clear_hand_runtime(hand_id: str):
    if hand_id not in REGISTRY:
        return {"ok": False, "error": f"unknown hand: {hand_id}"}
    removed = _HAND_RUNTIME_BINDINGS.remove(hand_id)
    return {"ok": True, "removed": removed, **_hand_runtime_state(hand_id)}


@app.post("/adapters/register")
async def register_agent_adapter(req: AgentAdapterRegisterRequest):
    config = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    try:
        adapter_info = _register_dynamic_adapter_config(
            config,
            persist=bool(config.get("persist", True)),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "adapter": adapter_info,
        "default_runtime_adapter": _adapter_registry.get_default_runtime_adapter(),
    }


@app.post("/adapters/default-runtime")
async def set_default_runtime_adapter(req: DefaultRuntimeAdapterRequest):
    adapter = _adapter_registry.find_by_id(req.adapter_id)
    if adapter is None:
        return {"ok": False, "error": f"unknown adapter: {req.adapter_id}"}
    _adapter_registry.set_default_runtime_adapter(req.adapter_id)
    if req.adapter_id in _DYNAMIC_ADAPTER_CONFIGS:
        for cfg in _DYNAMIC_ADAPTER_CONFIGS.values():
            cfg["set_default_runtime"] = False
        _DYNAMIC_ADAPTER_CONFIGS[req.adapter_id]["set_default_runtime"] = True
        _save_dynamic_adapters()
    return {"ok": True, "default_runtime_adapter": req.adapter_id}


@app.delete("/adapters/{adapter_id}")
async def delete_dynamic_agent_adapter(adapter_id: str):
    if adapter_id not in _DYNAMIC_ADAPTER_CONFIGS:
        return {"ok": False, "error": f"adapter is not dynamic: {adapter_id}"}
    removed = _adapter_registry.unregister(adapter_id)
    _DYNAMIC_ADAPTER_CONFIGS.pop(adapter_id, None)
    cleared_hand_ids = _HAND_RUNTIME_BINDINGS.remove_adapter(adapter_id)
    if _adapter_registry.get_default_runtime_adapter() == adapter_id:
        _adapter_registry.set_default_runtime_adapter("brain-inline")
    _save_dynamic_adapters()
    return {
        "ok": True,
        "adapter_id": adapter_id,
        "removed": removed,
        "cleared_hand_ids": cleared_hand_ids,
    }


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

    scoped = ScopedFeedback.from_event(body)
    if not scoped.episode_id:
        return {"ok": True, "feedback": scoped.to_dict(), "intent_analysis": None}

    detail = _flywheel.load_detail(scoped.episode_id) or {}
    analysis = _contextual_intent_compiler.compile(scoped, episode=detail)
    feedback_event = scoped.to_dict()
    _flywheel.append_feedback_event(scoped.episode_id, feedback_event)
    _flywheel.append_intent_analysis(scoped.episode_id, analysis.to_dict())
    return {
        "ok": True,
        "feedback": feedback_event,
        "intent_analysis": analysis.to_dict(),
        "intent_lens": {
            "summary": analysis.human_readable_summary,
            "affected_objects": analysis.affected_objects,
            "intent_delta": analysis.agent_readable_intent_delta.to_dict(),
            "ambiguities": analysis.ambiguities,
            "confidence": analysis.confidence,
        },
    }
async def _run_episode_repair(req: RepairFeedbackRequest) -> dict:
    detail = _flywheel.load_detail(req.episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {req.episode_id}"}

    from brain_harness.flywheel import HumanFeedback
    feedback = HumanFeedback(
        episode_id=req.episode_id,
        ts=datetime.datetime.utcnow().isoformat() + "Z",
        signal=req.signal,
        comment=req.comment,
        corrected_stance=req.corrected_stance,
    )
    _flywheel.append_human_feedback(req.episode_id, feedback)
    _core.feedback_store.append({
        "type": "repair_feedback",
        "source": req.context.get("source", "api"),
        "episode_id": req.episode_id,
        "hand_id": req.hand_id,
        "target_hands": req.target_hands,
        "signal": req.signal,
        "comment": req.comment,
        "corrected_stance": req.corrected_stance,
        "object_ref": req.object_ref,
        "object_type": req.object_type,
        "social": req.social,
    })

    scoped_feedback = ScopedFeedback(
        episode_id=req.episode_id,
        raw_signal=req.signal,
        comment=req.comment,
        object_ref=req.object_ref or (f"hand:{req.hand_id}" if req.hand_id else ""),
        object_type=req.object_type or ("hand" if req.hand_id else ""),
        ui_selection=req.ui_selection,
        anchor_id=req.anchor_id,
    )
    feedback_event = scoped_feedback.to_dict()
    _flywheel.append_feedback_event(req.episode_id, feedback_event)
    intent_analysis = _contextual_intent_compiler.compile(scoped_feedback, episode=detail)
    _flywheel.append_intent_analysis(req.episode_id, intent_analysis.to_dict())
    repair_intent_delta = req.intent_delta or intent_analysis.agent_readable_intent_delta.to_dict()

    plan = build_repair_plan(
        detail,
        comment=req.comment,
        explicit_hand_id=req.hand_id,
        target_hands=req.target_hands,
    )
    if not plan.target_hands:
        result = {
            "ok": False,
            "episode_id": req.episode_id,
            "error": plan.reason,
            "repair_plan": asdict(plan),
        "feedback": feedback_event,
        "intent_analysis": intent_analysis.to_dict(),
        "intent_delta": repair_intent_delta,
            "artifacts": {},
        }
        _flywheel.append_repair_result(req.episode_id, result)
        return result

    artifacts: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for hand_id in plan.target_hands:
        task = build_repair_task(
            detail,
            hand_id=hand_id,
            comment=req.comment,
            corrected_stance=req.corrected_stance,
            intent_delta=repair_intent_delta,
        )
        repair_context = {
            **req.context,
            "source": "feedback_repair",
            "episode_id": req.episode_id,
            "goal_id": detail.get("goal_id", ""),
            "domain_hint": detail.get("domain", "general"),
            "repair": {
                "signal": req.signal,
                "comment": req.comment,
                "corrected_stance": req.corrected_stance,
                "selection_reason": plan.reason,
                "intent_delta": repair_intent_delta,
                "feedback_id": feedback_event.get("feedback_id", ""),
                "intent_analysis_id": intent_analysis.analysis_id,
            },
        }
        try:
            artifact = await _brain_hand_runner(hand_id, task, repair_context)
            if not isinstance(artifact, dict):
                artifact = {
                    "metadata": {
                        "key_claims": [],
                        "gaps": ["repair adapter returned a non-dict artifact"],
                        "confidence": 0.0,
                    },
                    "narrative": str(artifact),
                }
            meta = artifact.get("metadata") if isinstance(artifact, dict) else None
            if not isinstance(meta, dict):
                artifact["metadata"] = meta = {}
            meta["repair_of_episode_id"] = req.episode_id
            meta["repair_reason"] = plan.reason
            artifacts[hand_id] = artifact
            anchor_id = REGISTRY.get(hand_id, {}).get("anchor_id", hand_id)
            await patch_webview(anchor_id, _render_artifact(artifact, hand_id))
        except Exception as exc:
            errors[hand_id] = str(exc)

    original_artifacts = detail.get("hand_artifacts", {})
    if not isinstance(original_artifacts, dict):
        original_artifacts = {}
    resynthesis_artifacts = {**original_artifacts, **artifacts}
    synthesis = None
    if artifacts and req.resynthesize:
        repair_workflow = {
            "domain": detail.get("domain", "general") or "general",
            "mode": "feedback_repair",
            "hands": list(resynthesis_artifacts.keys()),
            "rationale": f"feedback repair: {plan.reason}",
        }
        try:
            synthesis = await _brain_harness.synthesize(
                detail.get("question", ""),
                resynthesis_artifacts,
                repair_workflow,
                _brain_client,
                _brain_model,
                analysis_plan={"rubrics": []},
                review_result={
                    "follow_up_needed": False,
                    "feedback_repair": True,
                    "comment": req.comment,
                },
            )
            _brain_harness.write_last_synthesis(
                detail.get("question", ""),
                repair_workflow,
                synthesis,
            )
            await patch_webview(
                "brain-synthesis",
                _render_brain_synthesis(
                    synthesis,
                    repair_workflow,
                    False,
                    episode_id=req.episode_id,
                    goal_id=detail.get("goal_id", ""),
                    hand_artifacts=resynthesis_artifacts,
                ),
            )
        except Exception as exc:
            errors["_synthesis"] = str(exc)

    ok = bool(artifacts) and not errors
    result = {
        "ok": ok,
        "episode_id": req.episode_id,
        "repair_plan": asdict(plan),
        "feedback": feedback_event,
        "intent_analysis": intent_analysis.to_dict(),
        "intent_delta": repair_intent_delta,
        "artifacts": artifacts,
        "original_hand_artifact_count": len(original_artifacts),
        "errors": errors,
        "synthesis": synthesis,
    }
    _flywheel.append_repair_result(req.episode_id, result)

    reply_text = summarize_repair_for_reply(result)
    result["reply_text"] = reply_text
    should_send_reply = bool(
        req.send_reply
        or req.reply_webhook_url
        or str(req.context.get("responseMode", "")).lower() in {"reply", "auto_reply"}
        or str(req.context.get("response_mode", "")).lower() in {"reply", "auto_reply"}
    )
    if should_send_reply:
        social = req.social or {}
        platform = str(social.get("platform") or req.context.get("platform") or "generic")
        reply_result = await send_social_reply(
            platform=platform,
            text=reply_text,
            webhook_url=req.reply_webhook_url or str(req.context.get("reply_webhook_url", "")),
            token=req.reply_token or str(req.context.get("reply_token", "")),
            channel_id=str(
                social.get("channel_id")
                or req.context.get("reply_channel_id")
                or req.context.get("channel_id")
                or ""
            ),
            message_id=str(
                social.get("message_id")
                or req.context.get("reply_message_id")
                or req.context.get("message_id")
                or ""
            ),
            receive_id_type=str(req.context.get("receive_id_type") or req.context.get("reply_receive_id_type") or ""),
        )
        result["reply"] = asdict(reply_result)
    else:
        result["reply"] = {"skipped": True}

    asyncio.create_task(_async_capture_intent(
        "feedback",
        req.comment or req.signal,
        extra_context=json.dumps({
            "episode_id": req.episode_id,
            "corrected_stance": req.corrected_stance,
            "target_hands": plan.target_hands,
        }, ensure_ascii=False),
        session_id=str(req.context.get("session_id", "")),
    ))
    return result


@app.post("/feedback/repair")
async def repair_feedback(req: RepairFeedbackRequest):
    return await _run_episode_repair(req)


@app.post("/flywheel/repair")
async def flywheel_repair(req: RepairFeedbackRequest):
    return await _run_episode_repair(req)


@app.get("/hand/{hand_id}/config")
async def get_hand_config(hand_id: str):
    config = _core.hand_config_store.read(hand_id)
    return {"ok": True, "hand_id": hand_id, "config": config}


@app.put("/hand/{hand_id}/config")
async def put_hand_config(hand_id: str, request: Request):
    config = await request.json()
    _core.hand_config_store.write(hand_id, config)
    return {"ok": True, "hand_id": hand_id}


# Connector ID 鈫?tier mapping (for backward compat when no per-claim tier available)
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
        return "authoritative data", "anc-pill--done"
    if has_c or has_d:
        return "news source", "anc-pill--warn"
    if has_e:
        return "company source", "anc-pill--review"
    if has_f:
        return "sentiment source", "anc-pill--edit"
    if has_g:
        return "secondary source", "anc-pill--edit"
    return "unknown source", "anc-pill--edit"


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
            f'{(" 路 " + _html_text(freshness)) if freshness else ""}'
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
            "agents": panel.get("agents", fallback_meta.get("agents", [])),
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


def _agent_responsibility_from_prompt(system_prompt: str, fallback: str) -> str:
    text = (system_prompt or "").strip()
    if not text:
        return fallback
    for prefix in ("You are an ", "You are a ", "You are "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.startswith("You "):
        text = text[len("You "):]
    text = text[:1].upper() + text[1:] if text else fallback
    return text.split("\n", 1)[0].strip() or fallback


def _artifact_agents(artifact: dict, hand_id: str) -> list[dict]:
    meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
    agents = meta.get("agents") or meta.get("hand_agents")
    if isinstance(agents, list) and agents:
        return [a for a in agents if isinstance(a, dict)]
    info = REGISTRY.get(hand_id, {})
    actual_hand = meta.get("hand_id") or hand_id
    executor = meta.get("executor_id") or hand_id
    dimension = meta.get("dimension") or info.get("label") or actual_hand
    fallback = (
        info.get("description")
        or (f"Cover the {dimension} dimension." if dimension else "Provide focused supporting analysis for this card.")
    )
    return [{
        "hand_id": actual_hand,
        "executor_id": executor,
        "task_id": meta.get("task_id", ""),
        "dimension": dimension,
        "capabilities": list(meta.get("capabilities") or []),
        "responsibility": _agent_responsibility_from_prompt(str(meta.get("system_prompt") or ""), fallback),
    }]


def _render_agent_section(artifact: dict, hand_id: str) -> str:
    agents = _artifact_agents(artifact, hand_id)
    if not agents:
        return ""
    rows = []
    for agent in agents[:6]:
        caps = agent.get("capabilities") or []
        cap_html = ""
        if isinstance(caps, list) and caps:
            cap_html = " ".join(f'<span class="anc-pill anc-pill--review">{_html_text(str(c))}</span>' for c in caps[:4])
        dimension = agent.get("dimension") or ""
        executor = agent.get("executor_id") or ""
        task_id = agent.get("task_id") or ""
        meta_bits = " / ".join(_html_text(str(x)) for x in [executor, task_id, dimension] if x)
        rows.append(
            '<li>'
            f'<strong>{_html_text(str(agent.get("hand_id", "")))}</strong>'
            f'{("<small>" + meta_bits + "</small>") if meta_bits else ""}'
            f'<p>{_html_text(str(agent.get("responsibility", "")))}</p>'
            f'{("<div class=\"anc-pill-row\">" + cap_html + "</div>") if cap_html else ""}'
            '</li>'
        )
    return (
        '<section class="anc-detail-section anc-detail-section--hand-eval" '
        'data-detail-section="agents" data-detail-label="Agent" data-layer-type="analysis">'
        '<h3>Agent</h3>'
        '<p>Current card processing hand agents and their compact responsibilities.</p>'
        '<ul class="anc-source-list">'
        + "".join(rows) +
        '</ul></section>'
    )


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
                    f'<div><strong>{source}</strong>{(" 路 " + freshness) if freshness else ""}'
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

    All hand agents 鈥?configured or not 鈥?produce cards measured by the same 5
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
    # Only enrich once 鈥?subsequent calls see a non-error artifact
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
        artifact["narrative"] = f"{label} hand unavailable 鈥?{err}. This card normally contains {description}."
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
                {"claim": "Confidence is 0 鈥?no data was received", "source": "system", "tier": "G"},
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
    # evidence is intentionally left empty 鈥?no data was received
    meta.setdefault("evidence", [])
    return artifact



def _render_visual_page(record: dict, episode_id: str) -> str:
    """Render standalone HTML page for /visual/<episode_id> with full harness data."""
    question = record.get("question", "")
    domain = record.get("domain", "general")
    ts = str(record.get("ts", ""))[:19].replace("T", " ")
    brain = record.get("brain_self_eval", {}) or {}
    stance = brain.get("stance", "n/a")
    confidence = brain.get("confidence", 0.0)
    artifacts = record.get("hand_artifacts", {}) or {}
    orch = record.get("orchestration_snapshot") or {}
    profiles = orch.get("profiles", {}) if isinstance(orch, dict) else {}
    nodes = orch.get("nodes", []) if isinstance(orch, dict) else []
    diagnostics = orch.get("diagnostics", []) if isinstance(orch, dict) else []
    quality_summary = orch.get("quality_summary", {}) if isinstance(orch, dict) else {}

    adapter = _domain_registry.get(domain) if _domain_registry else None
    stance_label = (adapter.stance_labels or {}).get(stance, stance)
    confidence_pct = int(float(confidence) * 100)

    # ---- Quality KPI strip ----
    kpi_html = ""
    if quality_summary:
        ac = quality_summary.get("artifact_count", 0)
        tc = quality_summary.get("total_chars", 0)
        tcl = quality_summary.get("total_claims", 0)
        tg = quality_summary.get("total_gaps", 0)
        acn = quality_summary.get("avg_confidence", 0)
        sr = quality_summary.get("structured_ratio", 0)
        tsr_qs = quality_summary.get("total_sources", 0)
        ec = quality_summary.get("error_count", 0)
        parts = [
            f'<div class="vis-kpi"><span class="vis-kpi-val">{ac}</span><span class="vis-kpi-label">Artifacts</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val">{tc:,}</span><span class="vis-kpi-label">Total Chars</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val">{tcl}</span><span class="vis-kpi-label">Claims</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val" style="color:var(--accent-rose)">{tg}</span><span class="vis-kpi-label">Gaps</span></div>' if tg else f'<div class="vis-kpi"><span class="vis-kpi-val" style="color:var(--accent-lime)">0</span><span class="vis-kpi-label">Gaps</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val">{acn}%</span><span class="vis-kpi-label">Avg Conf</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val">{sr}%</span><span class="vis-kpi-label">Structured</span></div>',
            f'<div class="vis-kpi"><span class="vis-kpi-val">{tsr_qs}</span><span class="vis-kpi-label">Sources</span></div>',
        ]
        if ec:
            parts.append(f'<div class="vis-kpi"><span class="vis-kpi-val" style="color:var(--accent-rose)">{ec}</span><span class="vis-kpi-label">Errors</span></div>')
        kpi_html = f'<div class="vis-kpi-strip">{"".join(parts)}</div>'

    # ---- Hand Profiles ----
    profiles_html = ""
    if profiles:
        cards = []
        for pid, pi in profiles.items():
            if not isinstance(pi, dict):
                continue
            plabel = _html_text(str(pi.get("label", pi.get("agent_id", pid))))
            pdesc = _html_text(str(pi.get("description", ""))[:200])
            pmodel = _html_text(str(pi.get("base_model", "")))
            padapter = _html_text(str(pi.get("adapter_id", "")))
            ptask = _html_text(str(pi.get("task_snippet", ""))[:200])
            pdim = _html_text(str(pi.get("dimension", "")))
            psys = _html_text(str(pi.get("system_prompt_snippet", ""))[:600])
            pcaps = pi.get("capabilities", []) or []
            ptools = pi.get("tools", []) or []
            pmcps = pi.get("mcp_servers", []) or []
            pskills = pi.get("skills", []) or []

            tags = []
            for c in pcaps[:6]:
                tags.append(f'<span class="vis-tag vis-tag--cap">{_html_text(str(c)[:24])}</span>')
            for t in ptools[:5]:
                tags.append(f'<span class="vis-tag vis-tag--tool">&#x1f527; {_html_text(str(t)[:24])}</span>')
            for m in pmcps[:3]:
                tags.append(f'<span class="vis-tag vis-tag--mcp">&#x1f50c; {_html_text(str(m)[:24])}</span>')
            for s in pskills[:3]:
                tags.append(f'<span class="vis-tag vis-tag--skill">&#x26a1; {_html_text(str(s)[:24])}</span>')

            model_badge = f'<span class="vis-model">{pmodel}</span>' if pmodel and pmodel != "unknown" else ""
            adapter_badge = f'<span class="vis-model">via {padapter}</span>' if padapter and padapter not in ("brain-inline", "", plabel) else ""

            prompt_html = ""
            if psys:
                prompt_html = (
                    '<details class="vis-prompt"><summary>System prompt excerpt</summary>'
                    f'<pre class="vis-prompt-body">{psys}</pre></details>'
                )

            card_lines = [
                f'<div class="vis-profile-card">',
                f'<div class="vis-pf-header">',
                f'<span class="vis-pf-label">{plabel}</span>',
            ]
            if model_badge:
                card_lines.append(model_badge)
            if adapter_badge:
                card_lines.append(adapter_badge)
            if pdim:
                card_lines.append(f'<span class="vis-pf-dim">{pdim}</span>')
            card_lines.append('</div>')
            if pdesc:
                card_lines.append(f'<div class="vis-pf-desc">{pdesc}</div>')
            if tags:
                card_lines.append(f'<div class="vis-pf-tags">{"".join(tags)}</div>')
            if ptask:
                card_lines.append(f'<div class="vis-pf-task">{ptask}</div>')
            if prompt_html:
                card_lines.append(prompt_html)
            card_lines.append('</div>')
            cards.append("\n".join(card_lines))

        profiles_html = '\n'.join([
            '<section class="vis-section-body">',
            f'<h2 class="vis-section-title">Hand Profiles ({len(profiles)})</h2>',
            '<div class="vis-profiles-grid">',
            "".join(cards),
            '</div>',
            '</section>',
        ])

    # ---- Orchestration DAG ----
    dag_html = ""
    if nodes:
        groups = {"brain": [], "task": [], "hand": [], "artifact": [], "review": []}
        for n in nodes:
            t = n.get("type", "source")
            if t in groups:
                groups[t].append(n)

        icons = {"brain": "&#x1f9e0;", "task": "&#x2611;", "hand": "&#x270b;", "artifact": "&#x1f4c4;", "review": "&#x1f50d;"}

        def _dag_card(n):
            nt = n.get("type", "?")
            nl = _html_text(str(n.get("label", "?")))
            meta_parts = []
            if nt == "task" and n.get("task"):
                meta_parts.append(f'<div class="vis-dag-meta">{_html_text(str(n["task"])[:80])}</div>')
            if nt == "artifact":
                c = int((n.get("confidence", 0) or 0) * 100)
                cl = n.get("claim_count", 0)
                gp = n.get("gap_count", 0)
                gap_str = f' <span style="color:var(--accent-amber)">{gp}g</span>' if gp else ""
                meta_parts.append(f'<div class="vis-dag-meta">conf {c}% &middot; {cl}c{gap_str}</div>')
            icon = icons.get(nt, "?")
            return f'<div class="vis-dag-node vis-dag--{nt}"><span class="vis-dag-icon">{icon}</span><span class="vis-dag-label">{nl}</span>{"".join(meta_parts)}</div>'

        cols = [
            ("Brain", groups["brain"]),
            ("Tasks", groups["task"]),
            ("Hands", groups["hand"]),
            ("Artifacts", groups["artifact"]),
            ("Review", groups["review"]),
        ]
        active_cols = [(l, n) for l, n in cols if n]
        if active_cols:
            col_html_parts = []
            for i, (label, col_nodes) in enumerate(active_cols):
                cards = "".join(_dag_card(n) for n in col_nodes)
                col_html_parts.append(f'<div class="vis-dag-col"><div class="vis-dag-col-label">{label} ({len(col_nodes)})</div>{cards}</div>')
                if i < len(active_cols) - 1:
                    col_html_parts.append('<div class="vis-dag-arrow">&#x2192;</div>')
            col_html = "".join(col_html_parts)

            diag_html = ""
            if diagnostics:
                diag_items = "".join(
                    f'<div class="vis-diag-item"><span class="vis-diag-ref">{_html_text(str(d.get("object_ref", "")))}</span>{_html_text(str(d.get("message", "")))}</div>'
                    for d in diagnostics[:20]
                )
                diag_html = f'<details class="vis-diag"><summary>Diagnostics ({len(diagnostics)})</summary>{diag_items}</details>'

            goal_line = ""
            if orch.get("goal"):
                goal_line = f'<p class="vis-dag-goal">{_html_text(str(orch["goal"])[:200])}</p>'

            dag_lines = [
                '<section class="vis-section-body">',
                '<h2 class="vis-section-title">Orchestration DAG</h2>',
            ]
            if goal_line:
                dag_lines.append(goal_line)
            dag_lines.append(f'<div class="vis-dag-pipeline">{col_html}</div>')
            if diag_html:
                dag_lines.append(diag_html)
            dag_lines.append('</section>')
            dag_html = "\n".join(dag_lines)

    # ---- Live State Canvas Placeholder ----
    live_state_html = ""
    states = record.get("state_transitions", []) or []
    bottlenecks = record.get("bottlenecks", []) or []
    if states or bottlenecks:
        state_ids = set()
        for s in states:
            if isinstance(s, dict) and s.get("state_id"):
                state_ids.add(s["state_id"])
        live_state_html = '<section class="vis-live-state-section"><h2 class="vis-section-title">Live State Canvas (' + str(len(state_ids)) + ' states, ' + str(len(bottlenecks)) + ' bottlenecks)</h2><div data-anc="live-state-canvas" data-episode-id="' + episode_id + '" class="vis-canvas-placeholder"><p style="color:var(--ink-3);font-size:12px;text-align:center;padding:20px">State canvas mounts here when browser JS is active</p></div></section>'

    # ---- Checkpoint Review Deck Placeholder ----
    checkpoint_html = ""
    vqs = record.get("visual_queries", []) or []
    if vqs:
        checkpoint_html = '<section class="vis-checkpoint-section"><h2 class="vis-section-title">Checkpoint Review Deck (' + str(len(vqs)) + ' queries)</h2><div data-anc="checkpoint-review-deck" data-episode-id="' + episode_id + '" class="vis-canvas-placeholder"><p style="color:var(--ink-3);font-size:12px;text-align:center;padding:20px">Review deck mounts here when browser JS is active</p></div></section>'

    # ---- Artifact Quality Metrics ----
    quality_html = ""
    artifact_nodes = [n for n in nodes if n.get("type") == "artifact" and n.get("quality_metrics")]
    if artifact_nodes:
        def _score_bar(label, val, lo, hi):
            pct = max(0, min(100, ((val - lo) / max(1, hi - lo)) * 100))
            color = "var(--accent-lime)" if pct >= 70 else "var(--accent-amber)" if pct >= 40 else "var(--accent-rose)"
            return f'<div class="vis-score"><span class="vis-score-label">{label}</span><div class="vis-score-bar"><div class="vis-score-fill" style="width:{pct:.0f}%;background:{color}"></div></div><span class="vis-score-val">{val:.1f}</span></div>'

        metric_cards = []
        for an in artifact_nodes[:12]:
            qm = an.get("quality_metrics", {})
            cl = qm.get("claim_count", 0)
            gp = qm.get("gap_count", 0)
            sr = qm.get("source_count", 0)
            sc = qm.get("section_count", 0)
            hc = qm.get("heading_count", 0)
            ev = qm.get("evidence_count", 0)
            wc = qm.get("estimated_words", 0)
            ch = qm.get("char_length", 0)
            cs = int(qm.get("confidence_score", 0) or 0)

            freshness_cls = "vis-flag--good" if qm.get("freshness_flag") == "fresh" else ("vis-flag--warn" if qm.get("freshness_flag") == "stale" else "vis-flag--info")
            consist_cls = "vis-flag--good" if qm.get("consistency_flag") == "clean" else "vis-flag--warn"

            structured_flag = '<span class="vis-flag vis-flag--good">Structured</span>' if qm.get("structured_output") else '<span class="vis-flag vis-flag--info">Free-form</span>'

            gap_color = "var(--accent-rose)" if gp else "var(--accent-lime)"

            card = "\n".join([
                f'<div class="vis-quality-card">',
                f'<div class="vis-qc-header">{_html_text(str(an.get("label", "Artifact")))}</div>',
                '<div class="vis-qc-grid">',
                f'<div class="vis-qc-stat"><span>Chars</span><strong>{ch:,}</strong></div>',
                f'<div class="vis-qc-stat"><span>Words</span><strong>{wc:,}</strong></div>',
                f'<div class="vis-qc-stat"><span>Sections</span><strong>{sc}</strong></div>',
                f'<div class="vis-qc-stat"><span>Claims</span><strong>{cl}</strong></div>',
                f'<div class="vis-qc-stat"><span>Gaps</span><strong style="color:{gap_color}">{gp}</strong></div>',
                f'<div class="vis-qc-stat"><span>Sources</span><strong>{sr}</strong></div>',
                f'<div class="vis-qc-stat"><span>Evidence</span><strong>{ev}</strong></div>',
                f'<div class="vis-qc-stat"><span>Conf</span><strong>{cs}%</strong></div>',
                '</div>',
                '<div class="vis-qc-scores">',
                _score_bar("Richness", min(100, (sc * hc / max(1, wc)) * 100), 3, 10),
                _score_bar("ArgDensity", min(100, (cl / max(1, wc)) * 1000), 5, 20),
                _score_bar("EvidRatio", min(100, (ev / max(1, cl)) * 100), 50, 200),
                _score_bar("Structure", 100 if qm.get("structured_output") else (50 if hc > 0 else 20), 40, 80),
                _score_bar("ConfStab", max(0, 100 - (gp / max(1, cl)) * 100) if cl > 0 else 50, 50, 90),
                '</div>',
                '<div class="vis-qc-flags">',
                f'<span class="vis-flag {freshness_cls}">Fresh: {_html_text(str(qm.get("freshness_flag", "?")))}</span>',
                f'<span class="vis-flag {consist_cls}">Consis: {_html_text(str(qm.get("consistency_flag", "?")))}</span>',
                structured_flag,
                '</div>',
                '</div>',
            ])
            metric_cards.append(card)

        quality_html = "\n".join([
            '<section class="vis-section-body">',
            f'<h2 class="vis-section-title">Artifact Quality ({len(artifact_nodes)})</h2>',
            '<div class="vis-quality-grid">',
            "".join(metric_cards),
            '</div>',
            '</section>',
        ])

    # ---- Synthesis Guard Section ----
    guard_html = ""
    synth_guard = record.get("synthesis_guard_result") or {}
    if synth_guard and isinstance(synth_guard, dict):
        constraints = synth_guard.get("constraints", []) or []
        if constraints:
            guard_items = []
            for c in constraints[:10]:
                ct = _html_text(str(c.get("constraint_type", "?")))
                cm = _html_text(str(c.get("message", "")))
                guard_items.append('<div class="vis-guard-item"><span class="vis-guard-type">' + ct + '</span><span class="vis-guard-msg">' + cm + '</span></div>')
            guard_html = '<section class="vis-section-body"><h2 class="vis-section-title">Synthesis Guard (' + str(len(constraints)) + ')</h2><div class="vis-guard-list">' + "".join(guard_items) + '</div></section>'

    # ---- Hand artifact narratives ----
    hand_blocks = []
    for hand_id, art in artifacts.items():
        if not isinstance(art, dict):
            continue
        meta = art.get("metadata", {}) or {}
        narrative = art.get("narrative", "")
        claims = meta.get("key_claims", []) or []
        gaps = meta.get("gaps", []) or []
        sections = art.get("sections", []) or []

        claims_lines = []
        for c in claims[:8]:
            text = c.get("claim", str(c)) if isinstance(c, dict) else str(c)
            claims_lines.append(f"<li>{_html_text(text)}</li>")
        claims_html = "".join(claims_lines) or "<li>No key claims</li>"

        gaps_lines = []
        for g in gaps[:5]:
            text = g.get("description", str(g)) if isinstance(g, dict) else str(g)
            gaps_lines.append(f"<li>{_html_text(text)}</li>")
        gaps_html = "".join(gaps_lines) or ""

        sections_parts = []
        for sec in (sections or [])[:6]:
            if not isinstance(sec, dict):
                continue
            bullets = sec.get("bullets", []) or []
            bullet_html = "".join(f"<li>{_html_text(str(b))}</li>" for b in bullets[:8])
            sections_parts.append(
                f'<div class="vis-section">'
                f'<h3>{_html_text(sec.get("title", ""))}</h3>'
                f'<p class="vis-section-summary">{_html_text(sec.get("summary", ""))}</p>'
                f'<ul>{bullet_html}</ul>'
                f'</div>'
            )
        sections_html = "".join(sections_parts)

        gap_detail = ""
        if gaps_html:
            gap_detail = f'<details class="vis-detail"><summary>Gaps ({len(gaps)})</summary><ul>{gaps_html}</ul></details>'

        hand_blocks.append("\n".join([
            f'<div class="vis-card">',
            f'<div class="vis-card-header">',
            f'<span class="vis-hand-id">{_html_text(hand_id)}</span>',
            f'<span class="vis-confidence">confidence {confidence:.2f}</span>',
            f'</div>',
            f'<div class="vis-narrative">{_html_text(narrative[:3000])}</div>',
            f'<details class="vis-detail"><summary>Key Claims ({len(claims)})</summary><ul>{claims_html}</ul></details>',
            gap_detail,
            sections_html,
            '</div>',
        ]))

    artifacts_section = "".join(hand_blocks) if hand_blocks else '<div style="text-align:center;padding:40px;color:var(--ink-3)">No hand artifacts</div>'

    # ---- Render ----
    css = """  :root {
    --ink: #1a1a2e; --ink-2: #4a4a6a; --ink-3: #8888aa; --ink-4: #bbbbcc;
    --paper: #f8f7ff; --surface: #fff; --surface-2: #eeeef4;
    --border: #e8e6f0;
    --accent-iris: #7A5AF8; --accent-lime: #84CC16; --accent-rose: #F43F5E;
    --accent-amber: #F59E0B; --accent-sky: #38BDF8;
    --radius-sm: 8px; --radius-md: 14px;
    --font-display: system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-body: system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-mono: "JetBrains Mono", "Cascadia Code", monospace;
    --max-w: 1120px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--font-body); background: var(--paper); color: var(--ink); line-height: 1.6; }
  .vis-header { max-width: var(--max-w); margin: 0 auto; padding: 28px 24px 16px; border-bottom: 1px solid var(--border); }
  .vis-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 8px; line-height: 1.3; }
  .vis-meta { font-size: 13px; color: var(--ink-3); display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
  .vis-pill { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .vis-pill--stance { background: #ede9fe; color: var(--accent-iris); }
  .vis-pill--confidence { background: #dbeafe; color: #1e40af; }
  .vis-pill--domain { background: #f3f4f6; color: #6b7280; }
  .vis-kpi-strip { max-width: var(--max-w); margin: 16px auto 0; padding: 0 24px; display: flex; gap: 12px; flex-wrap: wrap; }
  .vis-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px 18px; text-align: center; min-width: 90px; flex: 1; }
  .vis-kpi-val { display: block; font-size: 22px; font-weight: 700; font-family: var(--font-display); color: var(--ink); }
  .vis-kpi-label { display: block; font-size: 10px; color: var(--ink-3); text-transform: uppercase; margin-top: 2px; }
  .vis-section-body { max-width: var(--max-w); margin: 24px auto 0; padding: 0 24px; }
  .vis-section-title { font-size: 14px; font-weight: 700; color: var(--ink-2); padding-bottom: 8px; border-bottom: 2px solid var(--border); margin-bottom: 14px; }
  .vis-profiles-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
  .vis-profile-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 14px 16px; }
  .vis-pf-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .vis-pf-label { font-weight: 700; font-size: 14px; color: var(--accent-iris); }
  .vis-pf-dim { font-size: 10px; background: var(--surface-2); padding: 2px 8px; border-radius: 4px; color: var(--ink-3); }
  .vis-model { font-size: 10px; background: var(--surface-2); padding: 2px 8px; border-radius: 4px; color: var(--ink-3); font-family: var(--font-mono); }
  .vis-pf-desc { font-size: 12px; color: var(--ink-2); margin-bottom: 8px; line-height: 1.5; }
  .vis-pf-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
  .vis-tag { font-size: 10px; padding: 2px 8px; border-radius: 999px; font-weight: 500; }
  .vis-tag--cap { background: #ede9fe; color: #5b21b6; }
  .vis-tag--tool { background: #dbeafe; color: #1e40af; }
  .vis-tag--mcp { background: #fce7f3; color: #9d174d; }
  .vis-tag--skill { background: #d1fae5; color: #065f46; }
  .vis-pf-task { font-size: 11px; color: var(--ink-2); padding: 6px 10px; background: var(--surface-2); border-radius: 6px; margin-bottom: 6px; }
  .vis-prompt { margin-top: 4px; font-size: 11px; }
  .vis-prompt summary { color: var(--ink-3); cursor: pointer; font-weight: 600; }
  .vis-prompt-body { font-family: var(--font-mono); font-size: 10px; background: #1a1a2e; color: #e2e8f0; padding: 10px 12px; border-radius: 6px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; margin-top: 4px; line-height: 1.5; }
  .vis-dag-goal { font-size: 13px; color: var(--ink-2); margin-bottom: 12px; line-height: 1.4; }
  .vis-dag-pipeline { display: flex; gap: 8px; align-items: flex-start; overflow-x: auto; padding: 4px 0; }
  .vis-dag-col { min-width: 150px; flex: 1; }
  .vis-dag-col-label { font-size: 9px; text-transform: uppercase; letter-spacing: .05em; color: var(--ink-4); margin-bottom: 4px; }
  .vis-dag-node { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; margin: 3px 0; font-size: 11px; display: flex; align-items: center; gap: 6px; background: var(--surface); }
  .vis-dag-icon { font-size: 14px; flex-shrink: 0; }
  .vis-dag-label { font-weight: 500; }
  .vis-dag-meta { font-size: 10px; color: var(--ink-3); margin-top: 2px; }
  .vis-dag-arrow { display: flex; align-items: center; padding: 0 4px; font-size: 18px; color: var(--ink-4); }
  .vis-diag { margin-top: 6px; font-size: 10px; }
  .vis-diag summary { color: var(--ink-3); cursor: pointer; }
  .vis-diag-item { display: flex; gap: 6px; align-items: center; padding: 2px 0; color: var(--ink-2); }
  .vis-diag-ref { font-size: 9px; background: var(--surface-2); border-radius: 4px; padding: 1px 5px; font-family: var(--font-mono); }
  .vis-quality-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
  .vis-quality-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 14px 16px; }
  .vis-qc-header { font-weight: 700; font-size: 13px; color: var(--ink); margin-bottom: 10px; }
  .vis-qc-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 10px; }
  .vis-qc-stat { text-align: center; padding: 6px 4px; background: var(--surface-2); border-radius: 6px; }
  .vis-qc-stat span { display: block; font-size: 9px; color: var(--ink-3); text-transform: uppercase; }
  .vis-qc-stat strong { font-size: 15px; font-family: var(--font-display); }
  .vis-qc-scores { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
  .vis-score { display: flex; align-items: center; gap: 8px; font-size: 10px; }
  .vis-score-label { width: 70px; color: var(--ink-3); text-align: right; flex-shrink: 0; }
  .vis-score-bar { flex: 1; height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
  .vis-score-fill { height: 100%; border-radius: 3px; }
  .vis-score-val { width: 36px; color: var(--ink-2); font-weight: 600; flex-shrink: 0; }
  .vis-qc-flags { display: flex; flex-wrap: wrap; gap: 4px; }
  .vis-flag { font-size: 9px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
  .vis-flag--good { background: #dcfce7; color: #166534; }
  .vis-flag--warn { background: #fef3c7; color: #92400e; }
  .vis-flag--info { background: #dbeafe; color: #1e40af; }
  .vis-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 20px; margin-bottom: 16px; }
  .vis-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .vis-hand-id { font-weight: 700; font-size: 15px; color: var(--accent-iris); }
  .vis-confidence { font-size: 12px; color: var(--ink-3); }
  .vis-narrative { font-size: 14px; line-height: 1.7; white-space: pre-wrap; margin-bottom: 12px; max-width: 80ch; }
  .vis-detail { margin-top: 12px; }
  .vis-detail summary { font-size: 13px; font-weight: 600; color: var(--ink-2); cursor: pointer; padding: 6px 0; }
  .vis-detail ul { padding-left: 20px; font-size: 13px; color: var(--ink-2); }
  .vis-detail li { margin-bottom: 4px; }
  .vis-section { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
  .vis-section h3 { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
  .vis-section-summary { font-size: 13px; color: var(--ink-3); margin-bottom: 8px; }
  .vis-section ul { padding-left: 20px; font-size: 13px; }
  .vis-section li { margin-bottom: 3px; }
  .vis-footer { text-align: center; font-size: 11px; color: var(--ink-3); margin-top: 48px; padding: 24px 0; border-top: 1px solid var(--border); }
  .vis-guard-list { display: flex; flex-direction: column; gap: 6px; }
  .vis-guard-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--surface-2); border-radius: 6px; font-size: 12px; }
  .vis-guard-type { font-weight: 700; font-size: 10px; text-transform: uppercase; background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; min-width: 60px; text-align: center; }
  .vis-live-state-section { max-width: var(--max-w); margin: 24px auto 0; padding: 0 24px; }
  .vis-checkpoint-section { max-width: var(--max-w); margin: 24px auto 0; padding: 0 24px; }
  .vis-canvas-placeholder { background: var(--surface); border: 1px dashed var(--border); border-radius: var(--radius-sm); min-height: 60px; }"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loom - {_html_text(question[:60])}</title>
<style>
{css}
</style>
</head>
<body>
<div class="vis-header">
  <h1>{_html_text(question)}</h1>
  <div class="vis-meta">
    <span class="vis-pill vis-pill--stance">{stance_label}</span>
    <span class="vis-pill vis-pill--confidence">{confidence_pct}% confidence</span>
    <span class="vis-pill vis-pill--domain">{_html_text(domain)}</span>
    <span>{ts}</span>
    <span style="font-size:10px;font-family:var(--font-mono);color:var(--ink-4)">ep: {_html_text(episode_id)}</span>
  </div>
</div>
{kpi_html}
{profiles_html}
{dag_html}
{live_state_html}
{checkpoint_html}
{guard_html}
{quality_html}
{artifacts_section}
<div class="vis-footer">Loom Brain &middot; episode {_html_text(episode_id)}</div>
</body>
</html>""".rstrip("\n") + "\n"
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
            "A": ("authoritative data", "anc-pill--done"), "B": ("market data", "anc-pill--done"),
            "C": ("news source", "anc-pill--warn"), "D": ("industry data", "anc-pill--warn"),
            "E": ("company source", "anc-pill--review"), "F": ("sentiment source", "anc-pill--edit"),
            "G": ("secondary source", "anc-pill--edit"),
        }.get(dist["best_tier"], ("unknown source", "anc-pill--edit"))
        authority_label, auth_class = best_label, best_class
        if dist["mixed"]:
            authority_label += " / mixed tiers"
            auth_class = "anc-pill--warn"
    else:
        authority_label, auth_class = _source_authority(sources_used)

    gaps_html = "".join(f"<li>{_html_text(g)}</li>" for g in gaps) or "<li>No explicit data gaps</li>"
    claims_html = "".join(
        f"<li>{_claim_source_tag(c)}{_html_text(_claim_text(c))}</li>"
        for c in (key_claims or [])
    )
    sources_html = ", ".join(f"<code>{_html_text(s)}</code>" for s in sources_used) or "none"

    info = REGISTRY.get(hand_id, {})
    anchor_id = info.get("anchor_id", hand_id)
    label = info.get("label", hand_id)
    hand_color = _hand_color(hand_id)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    detail_sections_html = _render_artifact_sections(artifact, narrative, claims_html)
    evidence_html = _render_evidence_section(artifact)
    source_notes_html = _render_source_notes(meta, sources_html)
    raw_sources_html = _render_raw_sources(artifact)
    raw_items_html = _render_raw_items(artifact)
    agent_section_html = _render_agent_section(artifact, hand_id)

    # 鈹€鈹€ Density card: L3 visible, L2/L1/L0 progressively revealable 鈹€鈹€鈹€鈹€鈹€鈹€
    l2_parts: list[str] = []
    if detail_sections_html:
        l2_parts.append(detail_sections_html)
    if agent_section_html:
        l2_parts.append(agent_section_html)
    l2_html = "".join(l2_parts) if l2_parts else ""

    l1_parts: list[str] = []
    if evidence_html:
        l1_parts.append(evidence_html)
    if source_notes_html:
        l1_parts.append(
            '<section class="anc-detail-section anc-detail-section--sources" '
            'data-detail-section="sources" data-detail-label="Sources" data-layer-type="analysis">'
            f'<h3>Sources</h3>{source_notes_html}</section>'
        )
    l1_html = "".join(l1_parts) if l1_parts else ""

    l0_parts: list[str] = []
    if raw_sources_html:
        l0_parts.append(raw_sources_html)
    if raw_items_html:
        l0_parts.append(raw_items_html)
    l0_html = "".join(l0_parts) if l0_parts else ""

    l3_extra = ""
    if not overview_only:
        l3_extra = (
            f"{('<h4>Key claims</h4><ul>' + claims_html + '</ul>') if claims_html else ''}"
            f"<h4>Data gaps</h4><ul class=\"risk-list\">{gaps_html}</ul>"
            f"<p>Data sources: {sources_html} / {ts}</p>"
        )

    parts: list[str] = [
        f'<section class="anc-section anc-section--gc anc-density-card" data-anc="{anchor_id}" data-handles="refine" data-has-detail="true">',
        # L3 鈥?always visible
        '<div class="anc-density-layer anc-density-layer--l3" data-density="l3">',
        f'<div class="anc-pill-row">',
        f'<span class="hand-indicator" style="width:10px;height:10px;border-radius:50%;background:{hand_color};display:inline-block;flex-shrink:0" title="{html.escape(hand_id)}"></span>',
        f'<span class="anc-pill anc-pill--gen">AI 鐢熸垚</span>',
        f'<span class="anc-pill {auth_class}">{authority_label}</span>',
        f'</div>',
        f'<h2>{label}</h2>',
        f'<div class="insight-box"><p>{_html_text(narrative)}</p></div>',
        l3_extra,
        '</div>',
    ]
    # L2 鈥?detail sections + agent info
    if l2_html:
        parts.append(f'<div class="anc-density-layer anc-density-layer--l2" data-density="l2">{l2_html}</div>')
    # L1 鈥?evidence table + source notes
    if l1_html:
        parts.append(f'<div class="anc-density-layer anc-density-layer--l1" data-density="l1">{l1_html}</div>')
    # L0 鈥?raw sources + raw items
    if l0_html:
        parts.append(f'<div class="anc-density-layer anc-density-layer--l0" data-density="l0">{l0_html}</div>')
    parts.append(
        '<div class="anc-density-indicator" aria-hidden="true">'
        '<span class="anc-density-dot active" data-density-dot="l3" title="姒傝"></span>'
        f'{"<span class=\"anc-density-dot\" data-density-dot=\"l2\" title=\"鍒嗘瀽\"></span>" if l2_html else ""}'
        f'{"<span class=\"anc-density-dot\" data-density-dot=\"l1\" title=\"璇佹嵁\"></span>" if l1_html else ""}'
        f'{"<span class=\"anc-density-dot\" data-density-dot=\"l0\" title=\"鍘熷鏁版嵁\"></span>" if l0_html else ""}'
        '</div>'
    )
    parts.append('</section>')
    return "\n".join(parts)


@app.get("/episodes/{episode_id}/workspace")
async def episode_workspace(episode_id: str):
    """Return state frame, bottlenecks, visual queries, orchestration snapshot, diagnostics."""
    detail = _flywheel.load_detail(episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {episode_id}"}
    snap = detail.get("orchestration_snapshot")
    if not isinstance(snap, dict) or not snap:
        snap = build_minimal_orchestration_snapshot(
            episode_id=episode_id,
            goal=str(detail.get("question", "")),
            domain=str(detail.get("domain", "general") or "general"),
            workflow={},
            hand_plan={},
            hand_artifacts=detail.get("hand_artifacts", {}) if isinstance(detail.get("hand_artifacts"), dict) else {},
        )
    return {
        "ok": True,
        "episode_id": episode_id,
        "orchestration": snap,
        "states": detail.get("state_transitions", []),
        "bottlenecks": detail.get("bottlenecks", []),
        "visual_queries": detail.get("visual_queries", []),
        "visual_interactions": detail.get("visual_interactions", []),
        "quality_summary": snap.get("quality_summary", {}) if isinstance(snap, dict) else {},
        "diagnostics": snap.get("diagnostics", []) if isinstance(snap, dict) else [],
        "synthesis_guard": detail.get("synthesis_guard_result", {}) if isinstance(detail) else {},
    }


class VisualInteractionRequest(BaseModel):
    episode_id: str
    query_id: str = ""
    anchor_type: str = ""
    anchor_id: str = ""
    gesture: str = "skip"
    comment: str = ""
    visual_context: dict = Field(default_factory=dict)


@app.post("/episodes/{episode_id}/visual-interactions")
async def append_visual_interaction(episode_id: str, req: VisualInteractionRequest):
    """Record a raw visual interaction and return inferred signals."""
    import time
    interaction = {
        "interaction_id": "vi-" + uuid.uuid4().hex[:12],
        "query_id": req.query_id,
        "episode_id": episode_id,
        "anchor_type": req.anchor_type,
        "anchor_id": req.anchor_id,
        "gesture": req.gesture,
        "comment": req.comment,
        "visual_context": req.visual_context,
        "inferred_signals": _infer_signals(req.gesture, req.anchor_type, req.anchor_id),
        "consumed_by": [],
        "ts": time.time(),
    }
    _flywheel.append_visual_interaction(episode_id, interaction)
    return {"ok": True, "interaction": interaction}


@app.post("/episodes/{episode_id}/checkpoint-response")
async def checkpoint_response(episode_id: str, req: VisualInteractionRequest):
    """Visual interaction as checkpoint response; also returns intent_lens if applicable."""
    import time
    interaction = {
        "interaction_id": "vi-" + uuid.uuid4().hex[:12],
        "query_id": req.query_id,
        "episode_id": episode_id,
        "anchor_type": req.anchor_type,
        "anchor_id": req.anchor_id,
        "gesture": req.gesture,
        "comment": req.comment,
        "visual_context": req.visual_context,
        "inferred_signals": _infer_signals(req.gesture, req.anchor_type, req.anchor_id),
        "consumed_by": [],
        "ts": time.time(),
    }
    _flywheel.append_visual_interaction(episode_id, interaction)

    intent_lens = {}
    if req.anchor_id and req.gesture in ("trust", "contest", "expand"):
        try:
            from brain_harness.contextual_intent import ScopedFeedback
            scoped = ScopedFeedback(
                episode_id=episode_id,
                raw_signal=req.gesture,
                comment=req.comment,
                object_ref=req.anchor_id,
                object_type=req.anchor_type,
            )
            analysis = _contextual_intent_compiler.compile(scoped)
            intent_lens = analysis.to_dict()
        except Exception:
            import traceback
            traceback.print_exc()

    return {"ok": True, "interaction": interaction, "intent_lens": intent_lens}


def _infer_signals(gesture, anchor_type, anchor_id):
    """Deterministic weak signal inference from gesture + anchor context."""
    signals = []
    if gesture == "trust" and anchor_type == "state":
        signals.append({"type": "evidence_trust", "target": anchor_id, "confidence": 0.8})
    elif gesture == "contest":
        signals.append({"type": "evidence_distrust", "target": anchor_id, "confidence": 0.7})
    elif gesture == "expand":
        signals.append({"type": "evidence_need", "target": anchor_id, "confidence": 0.9})
    elif gesture == "pin":
        signals.append({"type": "high_salience", "target": anchor_id, "confidence": 0.85})
    elif gesture == "mute":
        signals.append({"type": "low_salience", "target": anchor_id, "confidence": 0.85})
    return signals


@app.get("/episodes/{episode_id}/experience-graph")
async def experience_graph(episode_id: str):
    """Developer/debug view linking state, claim, evidence, gap, task, repair, outcome."""
    detail = _flywheel.load_detail(episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {episode_id}"}
    graph = {
        "episode_id": episode_id,
        "question": str(detail.get("question", "")),
        "domain": str(detail.get("domain", "general")),
        "state_transitions": detail.get("state_transitions", []),
        "bottlenecks": detail.get("bottlenecks", []),
        "visual_queries": detail.get("visual_queries", []),
        "visual_interactions": detail.get("visual_interactions", []),
        "interaction_consumption": detail.get("interaction_consumption", []),
        "hand_evaluations": detail.get("hand_evaluations", []),
        "orchestration_snapshot": detail.get("orchestration_snapshot"),
    }
    return {"ok": True, "graph": graph}


@app.get("/harness/evolution/candidates")
async def evolution_candidates():
    """Stub for controlled self-evolution candidates (empty in MVP)."""
    return {"ok": True, "candidates": []}


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
    adapters_info = [adapter_public_info(a) for a in _adapter_registry.list()]
    return {
        "ok": True,
        "service": "loom-brain",
        "hands": list(HANDS.keys()),
        "adapters": adapters_info,
        "default_runtime_adapter": _adapter_registry.get_default_runtime_adapter(),
        "dynamic_adapter_ids": sorted(_DYNAMIC_ADAPTER_CONFIGS.keys()),
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


@app.get("/orchestration/{episode_id}")
async def get_orchestration(episode_id: str):
    detail = _flywheel.load_detail(episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {episode_id}"}
    snapshot = detail.get("orchestration_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        snapshot = build_minimal_orchestration_snapshot(
            episode_id=episode_id,
            goal=str(detail.get("question", "")),
            domain=str(detail.get("domain", "general") or "general"),
            workflow={},
            hand_plan={},
            hand_artifacts=detail.get("hand_artifacts", {}) if isinstance(detail.get("hand_artifacts"), dict) else {},
        )
    return {"ok": True, "orchestration": snapshot}

@app.get("/flywheel")
async def flywheel_log(limit: int = 50):
    records = _flywheel.read_summary_log(limit=limit)
    return {"ok": True, "count": len(records), "records": records}


class FeedbackRequest(BaseModel):
    episode_id: str
    signal: str = "thumbs_up"
    comment: str = ""
    corrected_stance: str = ""
    object_ref: str = ""
    object_type: str = ""


class ConfirmCorrectionRequest(BaseModel):
    episode_id: str
    analysis_id: str = ""
    repair_id: str = ""
    comment: str = ""
    reuse_scope: str = "task_pattern"
    enabled: bool = True


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



@app.post("/corrections/confirm")
async def confirm_correction(req: ConfirmCorrectionRequest):
    detail = _flywheel.load_detail(req.episode_id)
    if detail is None:
        return {"ok": False, "error": f"episode not found: {req.episode_id}"}
    correction = {
        "correction_id": "cc-" + uuid.uuid4().hex[:12],
        "episode_id": req.episode_id,
        "analysis_id": req.analysis_id,
        "repair_id": req.repair_id,
        "comment": req.comment,
        "reuse_scope": req.reuse_scope or "task_pattern",
        "enabled": bool(req.enabled),
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
    }
    ok = _flywheel.append_confirmed_correction(req.episode_id, correction)
    return {"ok": ok, "correction": correction}


@app.get("/corrections")
async def list_confirmed_corrections(limit: int = 50):
    records = _flywheel.read_summary_log(limit=limit)
    corrections = []
    for record in records:
        episode_id = record.get("episode_id", "")
        detail = _flywheel.load_detail(episode_id) if episode_id else None
        if isinstance(detail, dict):
            corrections.extend(detail.get("confirmed_corrections", []) or [])
    return {"ok": True, "count": len(corrections), "corrections": corrections}

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














