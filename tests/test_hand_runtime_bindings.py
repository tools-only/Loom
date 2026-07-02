import json

import pytest

from loom_core.agent_adapters.runtime_bindings import (
    HandRuntimeBindingStore,
    hand_runtime_config_path,
    resolve_hand_runtime,
)


def test_binding_store_round_trip_and_cleanup(tmp_path):
    path = tmp_path / "config" / "hand-runtimes.json"
    store = HandRuntimeBindingStore(path)

    assert store.list() == {}
    store.set("sentiment", "codex-app-server")
    store.set("market", "codex-app-server")
    store.set("target", "sdk")

    assert store.get("sentiment") == "codex-app-server"
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert store.remove("target") is True
    assert store.remove("target") is False
    assert store.remove_adapter("codex-app-server") == ["market", "sentiment"]
    assert store.list() == {}


def test_binding_store_validates_ids(tmp_path):
    store = HandRuntimeBindingStore(tmp_path / "bindings.json")
    with pytest.raises(ValueError, match="hand_id"):
        store.set("", "sdk")
    with pytest.raises(ValueError, match="adapter_id"):
        store.set("market", "")


def test_runtime_precedence():
    values = dict(bound="codex", mounted="external", declared="sdk")
    assert resolve_hand_runtime(explicit="one-shot", **values) == "one-shot"
    assert resolve_hand_runtime(**values) == "codex"
    assert resolve_hand_runtime(bound="", mounted="external", declared="sdk") == "external"
    assert resolve_hand_runtime(bound="", mounted="", declared="canvas") == "canvas"


def test_default_config_path(tmp_path):
    assert hand_runtime_config_path(tmp_path) == tmp_path / "config" / "hand-runtimes.json"
