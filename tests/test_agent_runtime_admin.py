import json
from pathlib import Path
from unittest.mock import patch

from loom_core.agent_runtime_admin import run


def test_cli_registers_codex_and_binds_hand(tmp_path):
    assert run([
        "--root", str(tmp_path),
        "register", "codex-app-server",
        "--protocol", "codex",
        "--codex-backend", "sdk",
        "--bind-hand", "sentiment",
    ]) == 0

    adapters = json.loads((tmp_path / "loom" / "agent-adapters.json").read_text("utf-8"))
    codex = adapters["adapters"]["codex-app-server"]
    assert codex["protocol"] == "codex"
    assert codex["codex_backend"] == "sdk"
    assert codex["command"] == []

    bindings = json.loads((tmp_path / "config" / "hand-runtimes.json").read_text("utf-8"))
    assert bindings["bindings"] == {"sentiment": "codex-app-server"}


def test_cli_bind_and_unbind(tmp_path):
    assert run(["--root", str(tmp_path), "bind", "market", "sdk"]) == 0
    assert run(["--root", str(tmp_path), "unbind", "market"]) == 0
    path = tmp_path / "config" / "hand-runtimes.json"
    assert json.loads(path.read_text("utf-8"))["bindings"] == {}


def test_tui_registers_codex_app_server(tmp_path):
    answers = iter(["1", "codex-local", "sdk", "target", "q"])
    with patch("builtins.input", side_effect=lambda _prompt="": next(answers)):
        assert run(["--root", str(tmp_path), "tui"]) == 0
    path = Path(tmp_path) / "config" / "hand-runtimes.json"
    assert json.loads(path.read_text("utf-8"))["bindings"]["target"] == "codex-local"
