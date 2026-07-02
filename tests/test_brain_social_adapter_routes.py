from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAIN = (ROOT / "loom" / "brain.py").read_text(encoding="utf-8")


def test_brain_exposes_social_ingress_routes():
    assert '@app.post("/social/ingress")' in BRAIN
    assert '@app.post("/social/{platform}/ingress")' in BRAIN
    assert '@app.get("/social/channels")' in BRAIN
    assert '@app.get("/social/channels/config")' in BRAIN
    assert '@app.put("/social/channels/config")' in BRAIN
    assert '@app.post("/social/channels/register")' in BRAIN
    assert '@app.post("/social/channels/default")' in BRAIN
    assert '@app.delete("/social/channels/{channel_id}")' in BRAIN
    assert "SocialChannelRegisterRequest" in BRAIN
    assert "SocialChannelsConfigRequest" in BRAIN
    assert "channel_adapter_id" in BRAIN
    assert "_select_social_channel" in BRAIN
    assert "social_channel_from_config" in BRAIN
    assert "available_social_channel_types" in BRAIN
    assert "social_channel_config_path" in BRAIN
    assert "allowFrom" in BRAIN
    assert "normalize_social_payload" in BRAIN
    assert "build_analyze_request_from_social" in BRAIN
    assert "render_analysis_reply" in BRAIN
    assert "send_social_reply" in BRAIN
    assert "verify_social_request" in BRAIN
    assert "_verify_social_or_response" in BRAIN
    assert "_route_social_message" in BRAIN
    assert "get_client_for_social_router" in BRAIN
    assert "_social_router_client.messages.create" in BRAIN
    assert "_SOCIAL_DYNAMIC_ROUTER_SYSTEM" in BRAIN
    assert "is_explicit_loom_command" in BRAIN
    assert 'quick_reply|complex_task|clarify' in BRAIN
    assert "_SOCIAL_PENDING_CONFIRMATIONS" in BRAIN
    assert "parse_yes_no" in BRAIN
    assert "obvious_quick_reply" not in BRAIN
    assert '"route": "router_error"' in BRAIN
    assert 'dynamic router failed' not in BRAIN
    assert "not _social_bridge_managed_reply(channel_context)" in BRAIN
    assert "AgentSessionService" in BRAIN
    assert "resolve_social_agent_request" in BRAIN
    assert "_run_social_agent" in BRAIN


def test_brain_exposes_dynamic_agent_adapter_routes():
    assert '@app.get("/adapters")' in BRAIN
    assert '@app.post("/adapters/register")' in BRAIN
    assert '@app.post("/adapters/default-runtime")' in BRAIN
    assert '@app.delete("/adapters/{adapter_id}")' in BRAIN
    assert "adapter_from_config" in BRAIN
    assert "persistable_adapter_config" in BRAIN
    assert "_DYNAMIC_ADAPTER_PATH" in BRAIN
    assert "auth_token_env" in BRAIN
    assert "codex_backend" in BRAIN
    assert '@app.post("/agent-sessions/run")' in BRAIN
    assert "AgentSessionRequest" in BRAIN


def test_brain_exposes_hand_runtime_binding_routes():
    assert '@app.get("/hands/runtime-bindings")' in BRAIN
    assert '@app.get("/hand/{hand_id}/runtime")' in BRAIN
    assert '@app.put("/hand/{hand_id}/runtime")' in BRAIN
    assert '@app.delete("/hand/{hand_id}/runtime")' in BRAIN
    assert '"default_runtime_adapter": _adapter_registry.get_default_runtime_adapter()' in BRAIN
    assert "HandRuntimeBindingStore" in BRAIN
    assert "_runtime_for_hand(req.hand_id, req.runtime)" in BRAIN
    assert "remove_adapter(adapter_id)" in BRAIN


def test_brain_exposes_feedback_repair_routes():
    assert '@app.post("/feedback/repair")' in BRAIN
    assert '@app.post("/flywheel/repair")' in BRAIN
    assert "build_repair_plan" in BRAIN
    assert "build_repair_task" in BRAIN
    assert "append_repair_result" in BRAIN
