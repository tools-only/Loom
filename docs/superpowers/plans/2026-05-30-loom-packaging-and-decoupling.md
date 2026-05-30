# Loom Packaging & Core Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Loom 服务打包为跨平台单命令启动，同时将 Loom Core 的 agent backend 解耦为用户可显式配置的 `config/loom-core.json`，无 fallback，失败响亮报错。

**Architecture:** `scripts/setup.js` 做首次安装（扫描 PATH、交互式选择 backend、写 config）；`scripts/start.js` 统一启动三个进程并做健康检查；`loom_core/agent_adapters/core_config_loader.py` 读取 `config/loom-core.json`，验证 active backend 可执行，失败则 `SystemExit(1)`；`providers/__init__.py` 改为薄包装层，调用 loader。

**Tech Stack:** Python 3.11+ (unittest, shutil, pathlib), Node.js 20+ (child_process, readline, fs), 无新 npm 依赖

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `config/loom-core.json` | Create | Core backend 配置模板（git 追踪） |
| `loom_core/agent_adapters/core_config_loader.py` | Create | 读 config → 验证 → 返回 AgentAdapter |
| `tests/test_core_config_loader.py` | Create | core_config_loader 单元测试 |
| `loom_core/agent_adapters/providers/__init__.py` | Modify | 调用 loader，移除硬编码 import |
| `tests/test_agent_provider_registry.py` | Modify | 更新测试以适配新 providers 行为 |
| `scripts/setup.js` | Create | 首次安装：依赖 + Python 探测 + backend 选择 |
| `scripts/start.js` | Create | 统一启动三个进程 + 健康检查 + 开浏览器 |
| `.env.example` | Create | API key 模板 |
| `scripts/start-anchor.bat` | Modify | 改为调用 `node scripts/start.js` |
| `scripts/start-core.bat` | Modify | 去掉硬编码 `D:\conda\python.exe` |

---

## Task 0: 回归基线 — 记录现有测试状态

**目的：** 在任何代码改动前确认所有现有测试通过，并记录基线。Task 4 会破坏
`test_agent_provider_registry.py` 中的 3 个断言（多 provider 假设），必须在同一 commit 内更新。

- [ ] **Step 1: 运行现有 Python 测试套件，记录基线**

```bash
python -m pytest tests/ -v --ignore=tests/test_timing_stats.py 2>&1 | tee /tmp/baseline.txt
echo "EXIT: $?"
```

记录哪些 PASSED / FAILED。后续每个 Task 完成后的测试输出应与此基线一致（Task 4 的测试文件更新除外）。

- [ ] **Step 2: 运行现有 Node 回归测试**

```bash
node --test bridge/webview/styles.regression.test.cjs
```

预期：全部 PASSED。

- [ ] **Step 3: 记录 `test_agent_provider_registry.py` 的具体断言（将在 Task 4 中一同更新）**

```
当前断言（Task 4 后必须更新）：
- providers.get("codex") is not None    → 改为：只检查 active backend 存在
- providers.get("cc") is not None       → 改为：只检查 active backend 存在
- len(registry.list()) >= 2             → 改为：>= 1
- registry.find_by_capability("market.regime.review") → 改为按 active backend capability 验证
```

⚠️ **关键顺序约束：**
- Task 1（创建 `config/loom-core.json`）必须在 Task 4（修改 `providers/__init__.py`）之前 commit
- Task 4 的 `providers/__init__.py` 修改与测试文件更新必须在同一 commit，不能分开

---

## Task 1: 创建 `config/loom-core.json` 模板

**Files:**
- Create: `config/loom-core.json`

- [ ] **Step 1: 创建 config 目录和文件**

```json
{
  "_comment": "active: 当前使用的 backend id（单一激活，无 fallback）。运行 node scripts/setup.js 自动检测并配置。",
  "active": "cc",
  "backends": {
    "cc": {
      "command": ["claude", "-p"],
      "capabilities": ["*"]
    },
    "codex": {
      "command": ["codex", "run"],
      "capabilities": ["*"]
    },
    "opencode": {
      "command": ["opencode", "run"],
      "task_as_arg": true,
      "capabilities": ["*"]
    },
    "herms": {
      "command": ["herms", "run"],
      "capabilities": ["*"]
    }
  }
}
```

写入 `config/loom-core.json`。

- [ ] **Step 2: 确认 config/ 加入 .gitignore 排除规则不影响此文件**

```bash
grep -n "^config" .gitignore || echo "config/ not in gitignore — OK"
```

若 `config/` 被整体忽略，在 `.gitignore` 里加 `!config/loom-core.json` 例外规则。

- [ ] **Step 3: Commit**

```bash
git add config/loom-core.json
git commit -m "feat: add loom-core.json config template for agent backend selection"
```

---

## Task 2: 编写 `core_config_loader` 测试（先写测试）

**Files:**
- Create: `tests/test_core_config_loader.py`

- [ ] **Step 1: 创建测试文件，写第一批失败用例**

```python
"""Tests for loom_core.agent_adapters.core_config_loader."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile


def _write_config(config_dir: Path, data: dict) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "loom-core.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


class LoadCoreConfigTests(unittest.TestCase):

    def test_raises_when_config_file_missing(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                load_core_config(Path(tmp))

    def test_raises_when_active_key_missing(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {"backends": {"cc": {"command": ["claude", "-p"], "capabilities": ["*"]}}})
            with self.assertRaises(SystemExit):
                load_core_config(Path(tmp))

    def test_raises_when_active_id_not_in_backends(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "nonexistent",
                "backends": {"cc": {"command": ["claude", "-p"], "capabilities": ["*"]}}
            })
            with self.assertRaises(SystemExit):
                load_core_config(Path(tmp))

    def test_raises_when_command_not_in_path(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "cc",
                "backends": {"cc": {"command": ["claude", "-p"], "capabilities": ["*"]}}
            })
            with patch("shutil.which", return_value=None):
                with self.assertRaises(SystemExit):
                    load_core_config(Path(tmp))

    def test_raises_when_http_transport_specified(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "cloud",
                "backends": {
                    "cloud": {
                        "transport": "http",
                        "endpoint": "http://localhost:9000",
                        "capabilities": ["*"]
                    }
                }
            })
            with patch("shutil.which", return_value="/usr/bin/something"):
                with self.assertRaises(SystemExit):
                    load_core_config(Path(tmp))

    def test_returns_adapter_with_correct_id(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        from loom_core.agent_adapters.adapter import AgentAdapter
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "codex",
                "backends": {"codex": {"command": ["codex", "run"], "capabilities": ["*"]}}
            })
            with patch("shutil.which", return_value="/usr/local/bin/codex"):
                adapter = load_core_config(Path(tmp))
        self.assertIsInstance(adapter, AgentAdapter)
        self.assertEqual(adapter.id, "codex")

    def test_star_capabilities_expanded_to_core_list(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config, CORE_CAPABILITIES
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "cc",
                "backends": {"cc": {"command": ["claude", "-p"], "capabilities": ["*"]}}
            })
            with patch("shutil.which", return_value="/usr/bin/claude"):
                adapter = load_core_config(Path(tmp))
        self.assertEqual(set(adapter.capabilities), set(CORE_CAPABILITIES))

    def test_explicit_capabilities_used_as_is(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "cc",
                "backends": {"cc": {"command": ["claude", "-p"], "capabilities": ["market.analysis"]}}
            })
            with patch("shutil.which", return_value="/usr/bin/claude"):
                adapter = load_core_config(Path(tmp))
        self.assertEqual(adapter.capabilities, ["market.analysis"])

    def test_task_as_arg_passed_to_adapter(self):
        from loom_core.agent_adapters.core_config_loader import load_core_config
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), {
                "active": "opencode",
                "backends": {
                    "opencode": {
                        "command": ["opencode", "run"],
                        "task_as_arg": True,
                        "capabilities": ["*"]
                    }
                }
            })
            with patch("shutil.which", return_value="/usr/bin/opencode"):
                adapter = load_core_config(Path(tmp))
        self.assertTrue(adapter._task_as_arg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认全部 ImportError（模块不存在）**

```bash
python -m pytest tests/test_core_config_loader.py -v 2>&1 | head -30
```

预期：`ImportError: cannot import name 'load_core_config'`

---

## Task 3: 实现 `core_config_loader.py`

**Files:**
- Create: `loom_core/agent_adapters/core_config_loader.py`

- [ ] **Step 1: 创建文件**

```python
"""Reads config/loom-core.json and returns the single active AgentAdapter.

No fallback. If config is missing or invalid, exits with a clear message.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from loom_core.agent_adapters.adapter import AgentAdapter

CORE_CAPABILITIES: list[str] = [
    "market.analysis",
    "sentiment.scan",
    "target.thesis",
    "position.review",
]

_CONFIG_FILENAME = "loom-core.json"


def load_core_config(config_dir: Path | None = None) -> AgentAdapter:
    """Load active core agent from config/loom-core.json.

    Raises SystemExit(1) on any error — missing file, bad active id,
    command not in PATH, or http transport requested.
    """
    if config_dir is None:
        config_dir = Path(__file__).resolve().parents[3] / "config"

    cfg_path = config_dir / _CONFIG_FILENAME
    if not cfg_path.exists():
        _die(
            f"Config file not found: {cfg_path}\n"
            "Run 'node scripts/setup.js' to configure your agent backend."
        )

    try:
        raw: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {cfg_path}: {exc}")

    active_id: str = raw.get("active", "")
    if not active_id:
        _die(f"'active' field missing or empty in {cfg_path}")

    backends: dict[str, Any] = raw.get("backends", {})
    if active_id not in backends:
        _die(
            f"Active backend '{active_id}' not found in backends dict.\n"
            f"Available: {list(backends.keys())}"
        )

    backend = backends[active_id]

    # HTTP transport is not allowed for the core real-time loop.
    if backend.get("transport") == "http":
        _die(
            f"Backend '{active_id}' uses transport='http', which is not allowed "
            "for Loom Core (real-time op loop requires process transport).\n"
            "HTTP backends are only valid for hand agents."
        )

    command: list[str] = backend.get("command", [])
    if not command:
        _die(f"Backend '{active_id}' has no 'command' field.")

    if shutil.which(command[0]) is None:
        _die(
            f"Command '{command[0]}' not found in PATH (backend: '{active_id}').\n"
            "Install the agent or run 'node scripts/setup.js' to pick a different one."
        )

    raw_caps: list[str] = backend.get("capabilities", ["*"])
    capabilities = CORE_CAPABILITIES if raw_caps == ["*"] else raw_caps

    task_as_arg: bool = backend.get("task_as_arg", False)

    print(
        f"[loom-core] active agent: {active_id} ({' '.join(command)})",
        flush=True,
    )

    return AgentAdapter(
        adapter_id=active_id,
        transport="process",
        protocol="loom",
        command=command,
        task_as_arg=task_as_arg,
        capabilities=capabilities,
    )


def _die(message: str) -> None:
    print(f"[loom-core] ERROR: {message}", file=sys.stderr, flush=True)
    sys.exit(1)
```

- [ ] **Step 2: 运行测试，确认全部通过**

```bash
python -m pytest tests/test_core_config_loader.py -v
```

预期：9 tests PASSED

- [ ] **Step 3: Commit**

```bash
git add loom_core/agent_adapters/core_config_loader.py tests/test_core_config_loader.py
git commit -m "feat(loom-core): add core_config_loader — explicit backend selection, no fallback"
```

---

## Task 4: 更新 `providers/__init__.py`

**Files:**
- Modify: `loom_core/agent_adapters/providers/__init__.py`

- [ ] **Step 1: 替换文件内容**

```python
"""Provider registry — loads the single active core agent from config/loom-core.json."""

from __future__ import annotations

from typing import Any


def create_providers(config_dir=None) -> dict[str, dict[str, Any]]:
    """Return dict of {adapter_id: provider_info} for the active core backend.

    Raises SystemExit(1) if config is missing or the configured backend is unavailable.
    """
    from loom_core.agent_adapters.core_config_loader import load_core_config

    adapter = load_core_config(config_dir)
    return {
        adapter.id: {
            "id": adapter.id,
            "label": adapter.id.upper() + " Agent",
            "capabilities": adapter.capabilities,
            "instance": adapter,
        }
    }
```

- [ ] **Step 2: 运行现有 provider registry 测试，确认哪些需要更新**

```bash
python -m pytest tests/test_agent_provider_registry.py -v 2>&1
```

预期：多个测试失败（硬编码了 cc/codex 期望）。

- [ ] **Step 3: 更新 `tests/test_agent_provider_registry.py`**

```python
"""Tests for loom_core.agent_adapters.providers after config-driven refactor."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile


def _write_config(config_dir: Path, active: str, command: list) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "loom-core.json").write_text(json.dumps({
        "active": active,
        "backends": {
            active: {"command": command, "capabilities": ["*"]}
        }
    }), encoding="utf-8")


class ProviderRegistryTests(unittest.TestCase):

    def test_create_providers_returns_dict(self):
        from loom_core.agent_adapters.providers import create_providers
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), "cc", ["claude", "-p"])
            with patch("shutil.which", return_value="/usr/bin/claude"):
                providers = create_providers(Path(tmp))
        self.assertIsInstance(providers, dict)

    def test_returns_single_active_backend(self):
        from loom_core.agent_adapters.providers import create_providers
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), "codex", ["codex", "run"])
            with patch("shutil.which", return_value="/usr/bin/codex"):
                providers = create_providers(Path(tmp))
        self.assertEqual(list(providers.keys()), ["codex"])

    def test_provider_has_required_fields(self):
        from loom_core.agent_adapters.providers import create_providers
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), "cc", ["claude", "-p"])
            with patch("shutil.which", return_value="/usr/bin/claude"):
                providers = create_providers(Path(tmp))
        cc = providers["cc"]
        self.assertEqual(cc["id"], "cc")
        self.assertIn("capabilities", cc)
        self.assertIn("instance", cc)

    def test_providers_can_be_registered_in_registry(self):
        from loom_core.agent_adapters.providers import create_providers
        from loom_core.agent_adapters.registry import create_adapter_registry
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), "cc", ["claude", "-p"])
            with patch("shutil.which", return_value="/usr/bin/claude"):
                providers = create_providers(Path(tmp))
        registry = create_adapter_registry()
        for pid, info in providers.items():
            registry.register(info["instance"])
        self.assertEqual(len(registry.list()), 1)

    def test_registry_resolves_active_backend_by_core_capability(self):
        from loom_core.agent_adapters.providers import create_providers
        from loom_core.agent_adapters.registry import create_adapter_registry
        with tempfile.TemporaryDirectory() as tmp:
            _write_config(Path(tmp), "herms", ["herms", "run"])
            with patch("shutil.which", return_value="/usr/bin/herms"):
                providers = create_providers(Path(tmp))
        registry = create_adapter_registry()
        for info in providers.values():
            registry.register(info["instance"])
        self.assertIsNotNone(registry.find_by_capability("market.analysis"))

    def test_raises_when_no_config(self):
        from loom_core.agent_adapters.providers import create_providers
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                create_providers(Path(tmp))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行全部相关测试**

```bash
python -m pytest tests/test_core_config_loader.py tests/test_agent_provider_registry.py -v
```

预期：全部 PASSED（15 tests 左右）

- [ ] **Step 5: 运行完整测试套件，确认无回归**

```bash
python -m pytest tests/ -v --ignore=tests/test_timing_stats.py
```

预期：全部 PASSED（test_timing_stats 可能依赖 loom/ 目录，单独排查）

- [ ] **Step 6: Commit**

```bash
git add loom_core/agent_adapters/providers/__init__.py tests/test_agent_provider_registry.py
git commit -m "refactor(providers): replace hardcoded imports with config-driven core_config_loader"
```

---

## Task 5: 创建 `.env.example` 和 `config/agents.json`

**Files:**
- Create: `.env.example`
- Create: `config/agents.json`

- [ ] **Step 1: 创建 `.env.example`**

```bash
# Loom Core — copy to .env.local and fill in your keys
# Hand agent API keys (used by loom/loom-config.json hands)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# HTTP hand agent tokens (used by config/agents.json)
OPENCLAW_TOKEN=
NANOBOT_TOKEN=

# Optional: override ports
# ANCHOR_PORT=3000
# LOOM_CORE_PORT=3001
# LOOM_BRAIN_PORT=3002
```

写入 `.env.example`。

- [ ] **Step 2: 创建 `config/agents.json`（hand agent HTTP 配置模板）**

```json
{
  "_comment": "HTTP-transport hand agents. Tokens come from .env.local. Process-based backends go in loom-core.json.",
  "adapters": {}
}
```

写入 `config/agents.json`。

- [ ] **Step 3: 确认 `.env.local` 在 `.gitignore`**

```bash
grep "\.env\.local" .gitignore || echo "MISSING — add .env.local to .gitignore"
```

若缺失，在 `.gitignore` 末尾追加：
```
.env.local
```

- [ ] **Step 4: Commit**

```bash
git add .env.example config/agents.json .gitignore
git commit -m "feat: add .env.example and config/agents.json templates"
```

---

## Task 6: 创建 `scripts/setup.js`

**Files:**
- Create: `scripts/setup.js`

- [ ] **Step 1: 创建文件**

```js
#!/usr/bin/env node
/**
 * Loom first-time setup:
 *   1. Detect Python executable
 *   2. npm install in mcp/
 *   3. pip install in loom/
 *   4. Scan PATH for known agent backends
 *   5. Interactive selection if multiple found
 *   6. Write config/loom-core.json
 *   7. Copy .env.example → .env.local if missing
 */

const { execSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const ROOT = path.resolve(__dirname, '..');

const BACKENDS = [
  { id: 'cc',       cmd: 'claude',   label: 'Claude Code' },
  { id: 'codex',    cmd: 'codex',    label: 'Codex' },
  { id: 'opencode', cmd: 'opencode', label: 'OpenCode', task_as_arg: true },
  { id: 'herms',    cmd: 'herms',    label: 'Herms' },
];

// ── Cross-platform PATH search ──────────────────────────────────────────────
function findInPath(cmd) {
  const dirs = (process.env.PATH || '').split(path.delimiter);
  const exts = process.platform === 'win32'
    ? (process.env.PATHEXT || '.EXE;.CMD;.BAT').split(';')
    : [''];
  for (const dir of dirs) {
    for (const ext of exts) {
      const full = path.join(dir, cmd + ext);
      try { fs.accessSync(full, fs.constants.X_OK); return full; } catch {}
    }
  }
  return null;
}

// ── Detect Python ───────────────────────────────────────────────────────────
function detectPython() {
  for (const candidate of ['python3', 'python']) {
    const found = findInPath(candidate);
    if (found) {
      const result = spawnSync(found, ['--version'], { encoding: 'utf8' });
      if (result.status === 0) {
        console.log(`[setup] Python: ${found} (${result.stdout.trim() || result.stderr.trim()})`);
        return found;
      }
    }
  }
  console.error('[setup] ERROR: Python not found. Install Python 3.11+ and retry.');
  process.exit(1);
}

// ── Run shell command, exit on failure ──────────────────────────────────────
function run(label, cmd, opts = {}) {
  console.log(`[setup] ${label}...`);
  const result = spawnSync(cmd[0], cmd.slice(1), {
    stdio: 'inherit',
    cwd: opts.cwd || ROOT,
    shell: process.platform === 'win32',
  });
  if (result.status !== 0) {
    console.error(`[setup] ERROR: '${label}' failed (exit ${result.status})`);
    process.exit(1);
  }
}

// ── Interactive prompt ───────────────────────────────────────────────────────
function prompt(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(question, answer => { rl.close(); resolve(answer.trim()); }));
}

// ── Write loom-core.json ────────────────────────────────────────────────────
function writeLoomCoreConfig(activeId) {
  const configDir = path.join(ROOT, 'config');
  fs.mkdirSync(configDir, { recursive: true });
  const configPath = path.join(configDir, 'loom-core.json');

  const backendsObj = {};
  for (const b of BACKENDS) {
    const entry = { command: [b.cmd, ...(b.id === 'cc' ? ['-p'] : ['run'])], capabilities: ['*'] };
    if (b.task_as_arg) entry.task_as_arg = true;
    backendsObj[b.id] = entry;
  }
  // Fix cc command
  backendsObj.cc.command = ['claude', '-p'];

  const config = { _comment: 'active: chosen backend. Edit to switch. Run setup.js again to re-detect.', active: activeId, backends: backendsObj };
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8');
  console.log(`[setup] Written: config/loom-core.json (active: ${activeId})`);
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log('[setup] Loom setup starting...\n');

  const python = detectPython();

  run('npm install (mcp/)', ['npm', 'install'], { cwd: path.join(ROOT, 'mcp') });
  run('pip install (loom/)', [python, '-m', 'pip', 'install', '-r', 'requirements.txt'], { cwd: path.join(ROOT, 'loom') });

  // Scan PATH for backends
  const found = BACKENDS.filter(b => findInPath(b.cmd));
  console.log('');

  let activeId;
  if (found.length === 0) {
    console.error('[setup] ERROR: No agent backends found in PATH.');
    console.error('Install at least one: claude (Claude Code), codex, opencode, or herms.');
    process.exit(1);
  } else if (found.length === 1) {
    activeId = found[0].id;
    console.log(`[setup] Found 1 backend: ${found[0].label} (${found[0].cmd})`);
    console.log(`[setup] Using: ${activeId}`);
  } else {
    console.log('[setup] Found multiple backends:');
    found.forEach((b, i) => console.log(`  ${i + 1}. ${b.id.padEnd(10)} — ${b.label} (${b.cmd})`));
    let choice = '';
    while (!found.find(b => b.id === choice)) {
      choice = await prompt(`\nWhich backend should Loom Core use? (${found.map(b => b.id).join('/')}): `);
      if (!found.find(b => b.id === choice)) {
        console.log(`Invalid choice. Enter one of: ${found.map(b => b.id).join(', ')}`);
      }
    }
    activeId = choice;
  }

  writeLoomCoreConfig(activeId);

  // Copy .env.example → .env.local if missing
  const envLocal = path.join(ROOT, '.env.local');
  const envExample = path.join(ROOT, '.env.example');
  if (!fs.existsSync(envLocal) && fs.existsSync(envExample)) {
    fs.copyFileSync(envExample, envLocal);
    console.log('[setup] Created .env.local from .env.example — fill in your API keys.');
  }

  console.log('\n[setup] Done. Run: node scripts/start.js');
}

main().catch(e => { console.error(e); process.exit(1); });
```

- [ ] **Step 2: 手动测试（dry run，不改 config）**

```bash
node scripts/setup.js --help 2>&1 || node scripts/setup.js
```

检查输出：应打印 `[setup] Loom setup starting...` 并探测 Python。

- [ ] **Step 3: Commit**

```bash
git add scripts/setup.js
git commit -m "feat: add setup.js — cross-platform setup with interactive backend selection"
```

---

## Task 7: 创建 `scripts/start.js`

**Files:**
- Create: `scripts/start.js`

- [ ] **Step 1: 创建文件**

```js
#!/usr/bin/env node
/**
 * Unified Loom launcher — starts all 3 services and waits for health checks.
 *   :3000  Anchor Service   (node mcp/server.cjs)
 *   :3001  Loom Core        (python -m loom_core)
 *   :3002  Loom Brain       (python loom/main.py)
 */

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');

// ── Load .env.local into process.env ────────────────────────────────────────
function loadEnv() {
  const envPath = path.join(ROOT, '.env.local');
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq < 1) continue;
    const key = trimmed.slice(0, eq).trim();
    const val = trimmed.slice(eq + 1).trim();
    if (key && !(key in process.env)) process.env[key] = val;
  }
}

// ── Detect Python ────────────────────────────────────────────────────────────
function detectPython() {
  const dirs = (process.env.PATH || '').split(path.delimiter);
  const exts = process.platform === 'win32'
    ? (process.env.PATHEXT || '.EXE;.CMD;.BAT').split(';') : [''];
  for (const candidate of ['python3', 'python']) {
    for (const dir of dirs) {
      for (const ext of exts) {
        const full = path.join(dir, candidate + ext);
        try {
          fs.accessSync(full, fs.constants.X_OK);
          const r = spawnSync(full, ['--version'], { encoding: 'utf8' });
          if (r.status === 0) return full;
        } catch {}
      }
    }
  }
  console.error('[start] ERROR: Python not found. Run node scripts/setup.js first.');
  process.exit(1);
}

// ── Colored log prefixes ─────────────────────────────────────────────────────
const COLORS = { anchor: '\x1b[36m', core: '\x1b[33m', brain: '\x1b[32m', reset: '\x1b[0m' };
function makeLogger(name) {
  const color = COLORS[name] || '';
  const prefix = `${color}[${name}]${COLORS.reset} `;
  return (data) => data.toString().split('\n').filter(Boolean)
    .forEach(line => process.stdout.write(prefix + line + '\n'));
}

// ── Spawn a service ──────────────────────────────────────────────────────────
function startService(name, cmd, args, opts = {}) {
  const log = makeLogger(name);
  const proc = spawn(cmd, args, {
    cwd: opts.cwd || ROOT,
    env: { ...process.env, ...opts.env },
    shell: process.platform === 'win32',
  });
  proc.stdout.on('data', log);
  proc.stderr.on('data', log);
  proc.on('exit', code => {
    if (code !== 0 && code !== null) {
      console.error(`\n[start] ${name} exited with code ${code}`);
    }
  });
  return proc;
}

// ── Poll health endpoint ─────────────────────────────────────────────────────
function waitForHealth(port, name, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    function attempt() {
      const req = http.get(`http://127.0.0.1:${port}/health`, res => {
        if (res.statusCode < 400) { resolve(); return; }
        retry();
      });
      req.on('error', retry);
      req.setTimeout(1000, () => { req.destroy(); retry(); });
    }
    function retry() {
      if (Date.now() > deadline) { reject(new Error(`${name} health check timed out`)); return; }
      setTimeout(attempt, 500);
    }
    attempt();
  });
}

// ── Open browser ─────────────────────────────────────────────────────────────
function openBrowser(url) {
  const cmd = process.platform === 'win32' ? 'start' :
    process.platform === 'darwin' ? 'open' : 'xdg-open';
  spawnSync(cmd, [url], { shell: true });
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  loadEnv();
  const python = detectPython();
  const children = [];

  console.log('[start] Starting Anchor Service (:3000)...');
  children.push(startService('anchor', 'node', ['mcp/server.cjs'], {
    env: { ANCHOR_USE_AUTOEXEC: '1', ANCHOR_DISABLE_ENRICHMENT: '1' },
  }));

  console.log('[start] Starting Loom Core (:3001)...');
  children.push(startService('core', python, ['-m', 'loom_core']));

  console.log('[start] Starting Loom Brain (:3002)...');
  children.push(startService('brain', python, ['main.py'], { cwd: path.join(ROOT, 'loom') }));

  // Graceful shutdown on Ctrl+C
  process.on('SIGINT', () => {
    console.log('\n[start] Shutting down...');
    children.forEach(p => { try { p.kill(); } catch {} });
    process.exit(0);
  });
  process.on('SIGTERM', () => {
    children.forEach(p => { try { p.kill(); } catch {} });
    process.exit(0);
  });

  console.log('[start] Waiting for services to be ready...');
  try {
    await Promise.all([
      waitForHealth(3000, 'Anchor'),
      waitForHealth(3001, 'Loom Core'),
      waitForHealth(3002, 'Loom Brain'),
    ]);
  } catch (err) {
    console.error(`[start] ERROR: ${err.message}`);
    children.forEach(p => { try { p.kill(); } catch {} });
    process.exit(1);
  }

  console.log('\n[start] All services ready.');
  console.log('[start]   Anchor:     http://localhost:3000');
  console.log('[start]   Loom Core:  http://localhost:3001');
  console.log('[start]   Loom Brain: http://localhost:3002\n');

  if (!process.env.LOOM_NO_BROWSER) openBrowser('http://localhost:3000');
}

main().catch(e => { console.error(e); process.exit(1); });
```

- [ ] **Step 2: 手动验证语法**

```bash
node --check scripts/start.js && echo "syntax OK"
```

预期：`syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/start.js
git commit -m "feat: add start.js — unified cross-platform launcher with health checks"
```

---

## Task 8: 更新 `.bat` 启动脚本

**Files:**
- Modify: `scripts/start-anchor.bat`
- Modify: `scripts/start-core.bat`

- [ ] **Step 1: 更新 `scripts/start-anchor.bat`**

替换全部内容：

```bat
@echo off
REM Loom unified launcher — delegates to Node.js start.js
REM For cross-platform use: node scripts/start.js

cd /d "%~dp0.."
node scripts\start.js
```

- [ ] **Step 2: 更新 `scripts/start-core.bat`**

替换全部内容：

```bat
@echo off
REM Start Loom Core Python daemon (port 3001)
REM Prefers: python3, falls back to python in PATH
REM Run 'node scripts/setup.js' first if this fails.

cd /d "%~dp0.."
where python3 >nul 2>&1 && (
  python3 -m loom_core
) || (
  python -m loom_core
)
if %ERRORLEVEL% NEQ 0 (
  echo [loom-core] Failed. Run: node scripts/setup.js
  pause
  exit /b 1
)
```

- [ ] **Step 3: 验证 bat 文件语法（Windows）**

```bash
node -e "const fs=require('fs'); ['scripts/start-anchor.bat','scripts/start-core.bat'].forEach(f => console.log(f, fs.existsSync(f) ? 'OK' : 'MISSING'))"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/start-anchor.bat scripts/start-core.bat
git commit -m "fix: remove hardcoded D:\\conda\\python.exe, delegate to node scripts/start.js"
```

---

## Task 9: Brain Agent 解耦

**Files:**
- Create: `config/brain-agent.json`
- Modify: `mcp/server.cjs` (add `loadBrainAgentConfig()` + `buildBrainSpawnArgs()`, wire into `spawnProcessorPartition()`)
- Modify: `scripts/setup.js` (add brain agent detection block)

**Background:** `spawnProcessorPartition()` currently hardcodes two CC-specific assumptions:
1. `ANCHOR_CLAUDE_BIN || 'claude'` as the binary (line 2191)
2. `-p "$p" --dangerously-skip-permissions` as the flags (line 2200)

A `config/brain-agent.json` captures the full invocation pattern; `setup.js` auto-detects candidates and lets the user pick.

- [ ] **Step 1: 创建 `config/brain-agent.json` 模板**

```json
{
  "_comment": "Brain agent for Anchor op processing (spawn mode). protocol: 'cc'=prompt via -p flag, 'task_as_arg'=prompt as positional arg, 'stdin'=prompt piped to stdin. Run node scripts/setup.js to configure.",
  "command": "claude",
  "protocol": "cc",
  "extra_flags": ["--dangerously-skip-permissions"]
}
```

写入 `config/brain-agent.json`。

- [ ] **Step 2: 在 `mcp/server.cjs` 中添加 `loadBrainAgentConfig()` 和 `buildBrainSpawnArgs()`**

在 `function buildProcessorPrompt` (line ~2048) 之前插入：

```js
// ── Brain agent config ───────────────────────────────────────────────────────
// Reads config/brain-agent.json; falls back to CC defaults for backward compat.
function loadBrainAgentConfig() {
  const defaults = {
    command: process.env.ANCHOR_CLAUDE_BIN || 'claude',
    protocol: 'cc',
    extra_flags: ['--dangerously-skip-permissions'],
  };
  const cfgPath = path.join(ROOT, 'config', 'brain-agent.json');
  if (!fs.existsSync(cfgPath)) return defaults;
  try {
    const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    return {
      command:     raw.command     || defaults.command,
      protocol:    raw.protocol    || defaults.protocol,
      extra_flags: raw.extra_flags ?? defaults.extra_flags,
    };
  } catch (e) {
    log('[brain-agent] config parse error: ' + e.message + ' — using CC defaults');
    return defaults;
  }
}

// Build bash spawn args for the brain agent based on protocol.
// promptFile = temp file containing the full prompt text.
// Protocols:
//   cc          → bin -p "$prompt" [extra_flags]  (Claude Code style)
//   task_as_arg → bin "$prompt" [extra_flags]
//   stdin       → bin [extra_flags] < promptFile
function buildBrainSpawnArgs(promptFile, cfg) {
  const { command, protocol, extra_flags } = cfg;
  // Shell-quote each extra flag (simple: wrap in single-quotes, escape existing ones)
  const quotedExtra = extra_flags.map(f => `'${f.replace(/'/g, "'\\''")}'`).join(' ');
  let script;
  switch (protocol) {
    case 'task_as_arg':
      script = `p=$(cat "$0"); "$1" "$p" ${quotedExtra} < /dev/null`;
      break;
    case 'stdin':
      script = `"$1" ${quotedExtra} < "$0"`;
      break;
    case 'cc':
    default:
      script = `p=$(cat "$0"); "$1" -p "$p" ${quotedExtra} < /dev/null`;
  }
  return { spawnBin: 'bash', spawnArgs: ['-c', script, promptFile, command] };
}
```

- [ ] **Step 3: 在 `spawnProcessorPartition()` 中使用新函数**

在 `mcp/server.cjs` 找到 `spawnProcessorPartition()` 内的这两行（lines ~2191, 2198-2200）：

```js
  const claudeBin = process.env.ANCHOR_CLAUDE_BIN || 'claude';

  // Use bash on all platforms (including Windows with Git Bash / MSYS2).
  // Write prompt to a temp file to avoid shell quoting issues with large prompts.
  let spawnBin, spawnArgs, promptFile;
  promptFile = path.join(ROOT, 'output', `proc-${Date.now()}.txt`);
  try { fs.writeFileSync(promptFile, prompt, 'utf8'); } catch {}
  spawnBin  = 'bash';
  // $0 = promptFile, $1 = claudeBin — avoids all shell quoting issues with spaces/special chars
  spawnArgs = ['-c', 'p=$(cat "$0"); "$1" -p "$p" --dangerously-skip-permissions < /dev/null', promptFile, claudeBin];
```

替换为：

```js
  const brainCfg = loadBrainAgentConfig();

  // Use bash on all platforms (including Windows with Git Bash / MSYS2).
  // Write prompt to a temp file to avoid shell quoting issues with large prompts.
  let spawnBin, spawnArgs, promptFile;
  promptFile = path.join(ROOT, 'output', `proc-${Date.now()}.txt`);
  try { fs.writeFileSync(promptFile, prompt, 'utf8'); } catch {}
  ({ spawnBin, spawnArgs } = buildBrainSpawnArgs(promptFile, brainCfg));
```

- [ ] **Step 4: 验证 server.cjs 语法**

```bash
node --check mcp/server.cjs && echo "syntax OK"
```

预期：`syntax OK`

- [ ] **Step 5: 在 `scripts/setup.js` 中追加 Brain Agent 检测块**

在 `main()` 函数里，`writeLoomCoreConfig(activeId)` 调用之后，`.env.local` 复制之前，插入：

```js
  // ── Brain agent detection ────────────────────────────────────────────────
  const BRAIN_CANDIDATES = [
    { cmd: 'claude',   label: 'Claude Code', protocol: 'cc',          extra_flags: ['--dangerously-skip-permissions'] },
    { cmd: 'codex',    label: 'Codex',       protocol: 'task_as_arg', extra_flags: [] },
    { cmd: 'opencode', label: 'OpenCode',    protocol: 'task_as_arg', extra_flags: [] },
    { cmd: 'herms',    label: 'Herms',       protocol: 'stdin',       extra_flags: [] },
  ];

  console.log('\n[setup] Scanning PATH for brain agent candidates...');
  const foundBrain = BRAIN_CANDIDATES.filter(b => findInPath(b.cmd));
  if (foundBrain.length === 0) {
    console.error('[setup] ERROR: No brain agent found in PATH (claude / codex / opencode / herms).');
    console.error('         Install at least one and re-run node scripts/setup.js.');
    process.exit(1);
  }

  let activeBrain;
  if (foundBrain.length === 1) {
    activeBrain = foundBrain[0];
    console.log(`[setup] Found: ${activeBrain.label} (${activeBrain.cmd}) — using as brain agent.`);
    const confirm = await ask(`Use ${activeBrain.label} as brain agent? [Y/n] `);
    if (confirm.trim().toLowerCase() === 'n') {
      console.error('[setup] Cancelled. Install your preferred brain agent and re-run.');
      process.exit(1);
    }
  } else {
    console.log('[setup] Multiple brain agents found:');
    foundBrain.forEach((b, i) => console.log(`  ${i + 1}. ${b.label} (${b.cmd})`));
    const answer = await ask('Select brain agent [1]: ');
    const idx = (parseInt(answer.trim(), 10) || 1) - 1;
    if (idx < 0 || idx >= foundBrain.length) {
      console.error('[setup] Invalid selection.');
      process.exit(1);
    }
    activeBrain = foundBrain[idx];
  }

  const brainConfig = {
    _comment: 'Brain agent for Anchor op processing. protocol: cc/task_as_arg/stdin.',
    command: activeBrain.cmd,
    protocol: activeBrain.protocol,
    extra_flags: activeBrain.extra_flags,
  };
  fs.writeFileSync(
    path.join(ROOT, 'config', 'brain-agent.json'),
    JSON.stringify(brainConfig, null, 2) + '\n',
    'utf8'
  );
  console.log(`[setup] Wrote config/brain-agent.json (brain agent: ${activeBrain.label}).`);
```

- [ ] **Step 6: 验证 setup.js 语法**

```bash
node --check scripts/setup.js && echo "syntax OK"
```

预期：`syntax OK`

- [ ] **Step 7: 手动测试 config 加载（dry run，不需要实际运行 server）**

```bash
node -e "
const path = require('path');
const fs = require('fs');
const ROOT = path.resolve('.');
// Simulate loadBrainAgentConfig reading the template
const cfg = JSON.parse(fs.readFileSync('config/brain-agent.json','utf8'));
console.log('command:', cfg.command);
console.log('protocol:', cfg.protocol);
console.log('extra_flags:', cfg.extra_flags);
"
```

预期输出：
```
command: claude
protocol: cc
extra_flags: [ '--dangerously-skip-permissions' ]
```

- [ ] **Step 8: Commit**

```bash
git add config/brain-agent.json mcp/server.cjs scripts/setup.js
git commit -m "feat: decouple brain agent — config/brain-agent.json + protocol-aware spawn"
```

---

## Task 10: Processor Prompt 提取 — `resource/brain-agent/processor-prompt.md`

**Background:** `buildProcessorPrompt()` 中的 Anchor 协议和 Bloom 规范对 CC 是冗余的（CC 自动读 CLAUDE.md），但对非 CC agent 是唯一上下文来源。将这部分提取为独立文件，非 CC agent 通过 `context_file` 字段注入。

**Files:**
- Create: `resource/brain-agent/processor-prompt.md`
- Modify: `config/brain-agent.json` (CC preset: `context_file: null`，其他 preset 指向此文件)
- Modify: `mcp/server.cjs` (`loadBrainAgentConfig()` 增加 `context_file` 字段；`buildProcessorPrompt()` 前置注入)

- [ ] **Step 1: 创建 `resource/brain-agent/processor-prompt.md`**

```markdown
# Anchor Op Processor — System Context

You are a short-lived processor spawned by the Anchor service to handle browser UI ops.
Do NOT answer the user directly. Do NOT print HTML to stdout.
Your only output channel is the MCP tools listed below.

## MCP Tools Available

| Tool | Signature | When to use |
|------|-----------|-------------|
| `anchor_get_pending_op()` | `() → {pending, op}` | Drain one op at a time; loop until `pending:false` |
| `anchor_patch(patches)` | `({patches:[{anchor_id, html_fragment}]})` | Replace a node's outerHTML in-place |
| `anchor_render(html)` | `(html: string)` | Full page push — only for `initial_render` ops |
| `anchor_get_html()` | `() → string` | Read current page — use before refinement pass |
| `anchor_emit_event(type, payload)` | emit decision/partial_render/error events | Optional progress signals |

Never call `anchor_await_op` from a spawned processor.

## Op Processing Loop

1. Call `anchor_get_pending_op()`.
2. If `{pending: false}` → stop with one-line summary.
3. If `{pending: true, op}`:
   - `op.intent.op` — operation type
   - `op.intent.target_ref` — anchor id of target element
   - `op.intent.instruction` — user instruction
   - `op.render_state.relevant_subtree.target_html` — current outerHTML
4. For `initial_render`: call `anchor_render(html)`, then do a refinement pass (see below).
5. For all other ops: generate modified outerHTML → `anchor_patch({patches:[{anchor_id, html_fragment}]})`.
6. If `op.context_bundle.subagent_id` is set: call `Agent(subagent_type=<id>, prompt=...)` to generate the patch, then `anchor_patch`.
7. Go to step 1.

## Anchor HTML Protocol

Annotate semantic elements with `data-anc` (stable dot-separated id), `data-handles` (allowed ops), `data-deps` (dependencies):

```html
<section class="anc-section anc-section--gc" data-anc="findings" data-handles="refine,expand,lock">
  <h2>Findings</h2>
  <p data-anc="findings.summary" data-handles="refine,shorten,edit">Revenue grew 23% YoY…</p>
</section>
```

**Rules:**
- Every patched fragment MUST preserve existing `data-anc`, `data-handles`, `data-deps`, and CSS classes unless the op explicitly changes structure.
- Never write inline `style=""` beyond layout corrections.
- Never reference external CSS or icon libraries (Bloom tokens + Phosphor Icons are pre-loaded).

## Bloom Design System — Key Classes

**Section cards:**
```html
<section class="anc-section anc-section--gc">          <!-- neutral outer -->
  <div class="anc-kpi-grid">
    <div class="anc-kpi anc-kpi--aurora">              <!-- colored inner -->
      <div class="kpi-top"><div class="kpi-label-top">Label</div></div>
      <div class="kpi-bottom"><div class="kpi-value">$1.2T</div><div class="kpi-unit">市场规模</div></div>
    </div>
  </div>
</section>
```

Do NOT nest colored `anc-kpi--*` cards inside colored `anc-section--*` sections.

**KPI color themes:** `--warm` `--cool` `--aurora` `--ocean` `--berry` `--arctic` `--flame` `--sunset` `--forest` `--dusk`

**Buttons:** `btn btn--brand` / `btn btn--ghost` / `btn btn--sm` / `btn btn--icon`

**Status pills:** `anc-pill anc-pill--active` / `--gen` / `--draft` / `--done` / `--warn` / `--lock`

**Typography:** Use standard HTML tags (`h1`–`h4`, `p`, `ul`, `li`, `strong`, `code`). Headings use Bricolage Grotesque, body uses Plus Jakarta Sans.

**CSS tokens:** Always use `var(--pastel-*)`, `var(--accent-*)`, `var(--ink)`, `var(--paper)` — never hard-code colors, radii, or shadows.

## Layout Contract

- Use only existing classes; never invent new ones.
- KPI cards: short label in `kpi-label-top`, one compact value in `kpi-value`, supporting text in `kpi-unit`. No long prose inside cards.
- For 6 KPI cards: use `anc-kpi-grid` and let CSS wrap (3 per row) — do NOT force 4+2 or fixed column counts.
- Long analysis → `p`/`li` or nested `anc-section` blocks, not inside KPI cards.
- Avoid inline widths, fixed heights, negative letter-spacing, tiny font sizes.

## UI Refinement Pass (after `initial_render`)

After `anchor_render(html)`:
1. Call `anchor_get_html()` to inspect the rendered page.
2. Call `anchor_patch()` to fix: uneven KPI grid distribution, text misalignment, inadequate spacing, visual hierarchy gaps.
3. Only patch what needs changing.
```

写入 `resource/brain-agent/processor-prompt.md`。确保目录存在：

```bash
mkdir -p resource/brain-agent
```

- [ ] **Step 2: 更新 `config/brain-agent.json` — 增加 `context_file` 字段**

CC preset：`context_file` 为 `null`（CC 自动读 CLAUDE.md，无需注入）。

```json
{
  "_comment": "Brain agent for Anchor op processing. protocol: cc/task_as_arg/stdin. context_file: prepended for non-CC agents (null = agent reads its own CLAUDE.md/AGENTS.md).",
  "command": "claude",
  "protocol": "cc",
  "extra_flags": ["--dangerously-skip-permissions"],
  "context_file": null
}
```

对于 Codex 用户，`context_file` 改为 `"resource/brain-agent/processor-prompt.md"`：

```json
{
  "command": "codex",
  "protocol": "task_as_arg",
  "extra_flags": [],
  "context_file": "resource/brain-agent/processor-prompt.md"
}
```

- [ ] **Step 3: 修改 `mcp/server.cjs` — `loadBrainAgentConfig()` 增加 `context_file` 字段**

在 Task 9 中已添加的 `loadBrainAgentConfig()` 函数里，`defaults` 和 `return` 中补充 `context_file`：

```js
function loadBrainAgentConfig() {
  const defaults = {
    command:      process.env.ANCHOR_CLAUDE_BIN || 'claude',
    protocol:     'cc',
    extra_flags:  ['--dangerously-skip-permissions'],
    context_file: null,  // null = agent reads its own instruction file (e.g. CLAUDE.md for CC)
  };
  const cfgPath = path.join(ROOT, 'config', 'brain-agent.json');
  if (!fs.existsSync(cfgPath)) return defaults;
  try {
    const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    return {
      command:      raw.command      || defaults.command,
      protocol:     raw.protocol     || defaults.protocol,
      extra_flags:  raw.extra_flags  ?? defaults.extra_flags,
      context_file: raw.context_file ?? defaults.context_file,
    };
  } catch (e) {
    log('[brain-agent] config parse error: ' + e.message + ' — using CC defaults');
    return defaults;
  }
}
```

- [ ] **Step 4: 修改 `mcp/server.cjs` — `buildProcessorPrompt()` 前置注入 `context_file`**

在 `buildProcessorPrompt(ops)` 函数（line ~2048）开头，读取 context_file 并前置：

```js
function buildProcessorPrompt(ops) {
  const brainCfg = loadBrainAgentConfig();
  let contextPrefix = '';
  if (brainCfg.context_file) {
    const ctxPath = path.join(ROOT, brainCfg.context_file);
    try {
      contextPrefix = fs.readFileSync(ctxPath, 'utf8').trim() + '\n\n---\n\n';
    } catch (e) {
      log('[brain-agent] context_file not found: ' + ctxPath);
    }
  }

  // ... 现有 buildProcessorPrompt 逻辑不变 ...
  const processorPrompt = contextPrefix + [
    '[ANCHOR SINGLE-PASS OP PROCESSOR]',
    // ... 其余内容不变
  ].join('\n');
  return processorPrompt;
}
```

- [ ] **Step 5: 验证语法**

```bash
node --check mcp/server.cjs && echo "syntax OK"
```

预期：`syntax OK`

- [ ] **Step 6: Commit**

```bash
git add resource/brain-agent/processor-prompt.md config/brain-agent.json mcp/server.cjs
git commit -m "feat: extract processor-prompt.md, inject as context_file for non-CC brain agents"
```

---

## Task 11: Brain Agent 配置 UI 面板

**Files:**
- Create: `bridge/webview/brain-agent-panel.js`
- Modify: `bridge/webview/index.html` (引入脚本 + 添加触发按钮)
- Modify: `mcp/server.cjs` (添加 4 个 `/api/brain-agent/*` 路由)

**UI 结构（参考 hand-settings-panel.js 模式）：**

浮层面板，从工具栏 "Brain Agent" 按钮触发。包含：
1. Agent 预设选择器 + 状态 badge
2. Spawn 配置（command / protocol / extra_flags）
3. Context 文件路径 + 内联编辑区
4. 保存按钮

- [ ] **Step 1: 在 `mcp/server.cjs` 中添加 Brain Agent API 路由**

在现有 `/api/` 路由区域追加：

```js
// ── Brain Agent config API ────────────────────────────────────────────────────
app.get('/api/brain-agent/config', (req, res) => {
  const cfg = loadBrainAgentConfig();
  // Detect if command is reachable in PATH
  const { spawnSync } = require('child_process');
  const whichCmd = process.platform === 'win32' ? 'where' : 'which';
  const probe = spawnSync(whichCmd, [cfg.command], { encoding: 'utf8', shell: true });
  cfg.status = probe.status === 0 ? 'ok' : 'not_found';
  res.json(cfg);
});

app.post('/api/brain-agent/config', express.json(), (req, res) => {
  const { command, protocol, extra_flags, context_file } = req.body;
  if (!command || !protocol) return res.status(400).json({ error: 'command and protocol required' });
  const allowed = ['cc', 'task_as_arg', 'stdin'];
  if (!allowed.includes(protocol)) return res.status(400).json({ error: 'invalid protocol' });
  const cfg = {
    _comment: 'Brain agent for Anchor op processing. protocol: cc/task_as_arg/stdin.',
    command,
    protocol,
    extra_flags: Array.isArray(extra_flags) ? extra_flags : [],
    context_file: context_file || null,
  };
  try {
    writeJsonFile(path.join(ROOT, 'config', 'brain-agent.json'), cfg);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/brain-agent/context', (req, res) => {
  const cfg = loadBrainAgentConfig();
  if (!cfg.context_file) return res.json({ content: null, path: null });
  const ctxPath = path.join(ROOT, cfg.context_file);
  try {
    res.json({ content: fs.readFileSync(ctxPath, 'utf8'), path: cfg.context_file });
  } catch {
    res.json({ content: '', path: cfg.context_file });
  }
});

app.post('/api/brain-agent/context', express.json(), (req, res) => {
  const cfg = loadBrainAgentConfig();
  if (!cfg.context_file) return res.status(400).json({ error: 'no context_file configured' });
  const ctxPath = path.join(ROOT, cfg.context_file);
  try {
    fs.mkdirSync(path.dirname(ctxPath), { recursive: true });
    fs.writeFileSync(ctxPath, req.body.content || '', 'utf8');
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 2: 验证路由语法**

```bash
node --check mcp/server.cjs && echo "syntax OK"
```

- [ ] **Step 3: 创建 `bridge/webview/brain-agent-panel.js`**

```js
// Brain Agent config panel — triggered by toolbar button.
// Reads/writes http://127.0.0.1:3000/api/brain-agent/*
// Bloom tokens only. No new CSS.

(function () {
  const API = 'http://127.0.0.1:3000/api/brain-agent';

  const PRESETS = {
    cc:       { label: 'Claude Code', command: 'claude',   protocol: 'cc',          extra_flags: ['--dangerously-skip-permissions'], context_file: null },
    codex:    { label: 'Codex',       command: 'codex',    protocol: 'task_as_arg', extra_flags: [],                                context_file: 'resource/brain-agent/processor-prompt.md' },
    opencode: { label: 'OpenCode',    command: 'opencode', protocol: 'task_as_arg', extra_flags: [],                                context_file: 'resource/brain-agent/processor-prompt.md' },
    herms:    { label: 'Herms',       command: 'herms',    protocol: 'stdin',       extra_flags: [],                                context_file: 'resource/brain-agent/processor-prompt.md' },
    custom:   { label: 'Custom',      command: '',         protocol: 'cc',          extra_flags: [],                                context_file: 'resource/brain-agent/processor-prompt.md' },
  };

  // ── Panel HTML ──────────────────────────────────────────────────────────────
  function createPanel() {
    const overlay = document.createElement('div');
    overlay.id = 'bap-overlay';
    overlay.style.cssText = [
      'display:none;position:fixed;inset:0;z-index:9000',
      'background:rgba(0,0,0,.35);backdrop-filter:blur(2px)',
    ].join(';');

    overlay.innerHTML = `
      <div id="bap-panel" style="
        position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
        width:min(540px,90vw);max-height:80vh;overflow-y:auto;
        background:var(--paper);border-radius:16px;padding:24px;
        box-shadow:0 8px 32px rgba(0,0,0,.18);">

        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
          <div style="display:flex;align-items:center;gap:10px">
            <i class="ph-bold ph-robot" style="font-size:20px;color:var(--accent-iris,#7A5AF8)"></i>
            <span style="font-size:16px;font-weight:700;color:var(--ink)">Brain Agent 配置</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span id="bap-status-badge" style="font-size:12px;padding:3px 10px;border-radius:999px;background:var(--surface-1);color:var(--ink-3)">检测中…</span>
            <button id="bap-close" class="btn btn--icon btn--sm" style="color:var(--ink-3)"><i class="ph-bold ph-x"></i></button>
          </div>
        </div>

        <!-- Preset selector -->
        <div style="margin-bottom:16px">
          <label style="font-size:12px;font-weight:700;color:var(--ink-2);display:block;margin-bottom:6px">Agent 预设</label>
          <div id="bap-presets" style="display:flex;flex-wrap:wrap;gap:6px">
            ${Object.entries(PRESETS).map(([k, v]) =>
              `<button class="btn btn--ghost btn--sm bap-preset" data-preset="${k}">${v.label}</button>`
            ).join('')}
          </div>
        </div>

        <!-- Command -->
        <div style="margin-bottom:12px">
          <label style="font-size:12px;font-weight:700;color:var(--ink-2);display:block;margin-bottom:6px">
            命令 <span style="font-weight:400;color:var(--ink-3)">(PATH 中可执行文件名)</span>
          </label>
          <input id="bap-command" type="text" placeholder="claude"
            style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);font-family:monospace;box-sizing:border-box">
        </div>

        <!-- Protocol -->
        <div style="margin-bottom:12px">
          <label style="font-size:12px;font-weight:700;color:var(--ink-2);display:block;margin-bottom:6px">Prompt 传递方式</label>
          <select id="bap-protocol"
            style="padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink)">
            <option value="cc">-p 参数（Claude Code 风格）</option>
            <option value="task_as_arg">位置参数（Codex / OpenCode 风格）</option>
            <option value="stdin">stdin 管道输入</option>
          </select>
        </div>

        <!-- Extra flags -->
        <div style="margin-bottom:16px">
          <label style="font-size:12px;font-weight:700;color:var(--ink-2);display:block;margin-bottom:6px">
            额外 flags <span style="font-weight:400;color:var(--ink-3)">(逗号分隔)</span>
          </label>
          <input id="bap-flags" type="text" placeholder="--dangerously-skip-permissions"
            style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:13px;color:var(--ink);font-family:monospace;box-sizing:border-box">
        </div>

        <hr class="anc-divider" style="margin:16px 0">

        <!-- Context file -->
        <div style="margin-bottom:8px;display:flex;align-items:center;justify-content:space-between">
          <div>
            <span style="font-size:12px;font-weight:700;color:var(--ink-2)">处理器上下文文件</span>
            <span id="bap-ctx-note" style="font-size:11px;color:var(--ink-3);margin-left:6px"></span>
          </div>
          <button id="bap-ctx-toggle" class="btn btn--ghost btn--sm" style="display:none">编辑</button>
        </div>
        <div style="margin-bottom:12px">
          <input id="bap-ctx-path" type="text" placeholder="resource/brain-agent/processor-prompt.md"
            style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:12px;color:var(--ink-2);font-family:monospace;box-sizing:border-box">
        </div>
        <div id="bap-ctx-editor" style="display:none;margin-bottom:12px">
          <textarea id="bap-ctx-content" rows="12"
            style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--surface-2,rgba(0,0,0,.12));background:var(--paper);font-size:12px;color:var(--ink);font-family:monospace;resize:vertical;box-sizing:border-box"></textarea>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button id="bap-ctx-save" class="btn btn--brand btn--sm">保存上下文</button>
            <span id="bap-ctx-status" style="font-size:12px;color:var(--ink-3);align-self:center;display:none"></span>
          </div>
        </div>

        <hr class="anc-divider" style="margin:16px 0">

        <!-- Action row -->
        <div style="display:flex;gap:8px;align-items:center">
          <button id="bap-save" class="btn btn--brand">保存配置</button>
          <button id="bap-cancel" class="btn btn--ghost">取消</button>
          <span id="bap-save-status" style="font-size:12px;color:var(--ink-3);display:none;margin-left:4px"></span>
        </div>
      </div>
    `;
    return overlay;
  }

  // ── State helpers ───────────────────────────────────────────────────────────
  function getFormValues() {
    return {
      command:      document.getElementById('bap-command').value.trim(),
      protocol:     document.getElementById('bap-protocol').value,
      extra_flags:  document.getElementById('bap-flags').value.split(',').map(s => s.trim()).filter(Boolean),
      context_file: document.getElementById('bap-ctx-path').value.trim() || null,
    };
  }

  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    document.getElementById('bap-command').value  = p.command;
    document.getElementById('bap-protocol').value = p.protocol;
    document.getElementById('bap-flags').value    = p.extra_flags.join(', ');
    document.getElementById('bap-ctx-path').value = p.context_file || '';
    updateContextNote(p.context_file);
    document.querySelectorAll('.bap-preset').forEach(b =>
      b.classList.toggle('btn--brand', b.dataset.preset === key));
  }

  function updateContextNote(ctxFile) {
    const note = document.getElementById('bap-ctx-note');
    const toggle = document.getElementById('bap-ctx-toggle');
    if (!ctxFile) {
      note.textContent = '自动读取 CLAUDE.md（CC 模式）';
      toggle.style.display = 'none';
    } else {
      note.textContent = '';
      toggle.style.display = '';
    }
  }

  function setStatus(text, ok) {
    const badge = document.getElementById('bap-status-badge');
    badge.textContent = text;
    badge.style.background = ok ? 'var(--pastel-mint,#e8f8f1)' : 'var(--pastel-rose,#fde8ed)';
    badge.style.color = ok ? 'var(--accent-emerald,#22c55e)' : 'var(--accent-rose,#f43f5e)';
  }

  // ── Init ────────────────────────────────────────────────────────────────────
  function init() {
    const overlay = createPanel();
    document.body.appendChild(overlay);

    // Close
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.style.display = 'none'; });
    document.getElementById('bap-close').onclick   = () => { overlay.style.display = 'none'; };
    document.getElementById('bap-cancel').onclick  = () => { overlay.style.display = 'none'; };

    // Preset buttons
    document.querySelectorAll('.bap-preset').forEach(btn =>
      btn.addEventListener('click', () => applyPreset(btn.dataset.preset)));

    // Context editor toggle
    document.getElementById('bap-ctx-toggle').onclick = async () => {
      const editor = document.getElementById('bap-ctx-editor');
      const isOpen = editor.style.display !== 'none';
      if (isOpen) {
        editor.style.display = 'none';
        document.getElementById('bap-ctx-toggle').textContent = '编辑';
      } else {
        // Load context content
        try {
          const r = await fetch(API + '/context');
          const data = await r.json();
          document.getElementById('bap-ctx-content').value = data.content || '';
          editor.style.display = 'block';
          document.getElementById('bap-ctx-toggle').textContent = '收起';
        } catch { /* ignore */ }
      }
    };

    // Save context
    document.getElementById('bap-ctx-save').onclick = async () => {
      const status = document.getElementById('bap-ctx-status');
      const content = document.getElementById('bap-ctx-content').value;
      status.style.display = 'inline';
      status.textContent = '保存中…';
      try {
        const r = await fetch(API + '/context', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        });
        status.textContent = r.ok ? '已保存' : '保存失败';
        setTimeout(() => { status.style.display = 'none'; }, 2000);
      } catch { status.textContent = '保存失败'; }
    };

    // Save config
    document.getElementById('bap-save').onclick = async () => {
      const status = document.getElementById('bap-save-status');
      status.style.display = 'inline';
      status.textContent = '保存中…';
      try {
        const r = await fetch(API + '/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(getFormValues()),
        });
        if (r.ok) {
          status.textContent = '已保存，重启 Anchor 服务后生效';
          setTimeout(() => { status.style.display = 'none'; }, 3000);
        } else {
          const e = await r.json();
          status.textContent = '错误: ' + (e.error || r.status);
        }
      } catch (e) { status.textContent = '保存失败: ' + e.message; }
    };
  }

  // ── Open panel ──────────────────────────────────────────────────────────────
  window.openBrainAgentPanel = async function () {
    const overlay = document.getElementById('bap-overlay');
    overlay.style.display = 'block';
    setStatus('检测中…', true);
    try {
      const r = await fetch(API + '/config');
      const cfg = await r.json();
      document.getElementById('bap-command').value  = cfg.command || '';
      document.getElementById('bap-protocol').value = cfg.protocol || 'cc';
      document.getElementById('bap-flags').value    = (cfg.extra_flags || []).join(', ');
      document.getElementById('bap-ctx-path').value = cfg.context_file || '';
      updateContextNote(cfg.context_file);
      // Highlight matching preset
      const matchedKey = Object.entries(PRESETS).find(([, v]) => v.command === cfg.command)?.[0];
      if (matchedKey) applyPreset(matchedKey);
      setStatus(cfg.status === 'ok' ? `${cfg.command} 可达` : `${cfg.command} 未找到`, cfg.status === 'ok');
    } catch {
      setStatus('无法连接 Anchor 服务', false);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

写入 `bridge/webview/brain-agent-panel.js`。

- [ ] **Step 4: 在 `bridge/webview/index.html` 中引入脚本并添加触发按钮**

在 `index.html` 中找到工具栏区域（含 Debate 等按钮的 `<div>`），追加触发按钮：

```html
<button class="btn btn--ghost btn--sm" onclick="openBrainAgentPanel()" title="Brain Agent 配置">
  <i class="ph-bold ph-robot"></i>
</button>
```

在 `</body>` 前引入脚本（与其他 webview JS 并列）：

```html
<script src="brain-agent-panel.js"></script>
```

- [ ] **Step 5: 手动验证（需要 Anchor 服务运行）**

```bash
# 启动服务
node mcp/server.cjs &

# 测试 GET /api/brain-agent/config
curl http://127.0.0.1:3000/api/brain-agent/config

# 测试 POST /api/brain-agent/config
curl -X POST http://127.0.0.1:3000/api/brain-agent/config \
  -H "Content-Type: application/json" \
  -d '{"command":"claude","protocol":"cc","extra_flags":["--dangerously-skip-permissions"],"context_file":null}'

# 测试 GET /api/brain-agent/context
curl http://127.0.0.1:3000/api/brain-agent/context
```

预期：全部返回合法 JSON，无 500 错误。然后在浏览器 http://localhost:3000 点击工具栏 robot 图标，验证面板弹出并正确显示当前配置。

- [ ] **Step 6: Commit**

```bash
git add bridge/webview/brain-agent-panel.js bridge/webview/index.html mcp/server.cjs
git commit -m "feat: brain agent config UI — preset selector, context editor, /api/brain-agent routes"
```

---

## Self-Review

### Spec Coverage Check

| Spec 要求 | 对应 Task |
|-----------|-----------|
| 单一 active，无 fallback | Task 3 (loader exit(1)) |
| exit(1) + 明确报错 | Task 3 (_die 函数) |
| PATH 扫描发现，用户决定 | Task 6 (interactive prompt) |
| HTTP transport 禁用于 core loop | Task 3 (transport check) |
| `["*"]` 展开为 CORE_CAPABILITIES | Task 3 + Task 2 (test) |
| `core_config_loader` 与 `cloud_config.py` 分离 | Task 3/4（独立文件，不合并） |
| setup.js 跨平台 Python 探测 | Task 6 (detectPython) |
| start.js 三进程统一启动 | Task 7 |
| start.js 健康检查后开浏览器 | Task 7 (waitForHealth + openBrowser) |
| .bat 去硬编码路径 | Task 8 |
| .env.example 模板 | Task 5 |
| Brain agent spawn 解耦 | Task 9 (loadBrainAgentConfig + buildBrainSpawnArgs) |
| Brain agent 用户可配置协议 | Task 9 (BRAIN_CANDIDATES scan in setup.js) |
| Processor 上下文文件（非 CC agent 的 CLAUDE.md 等价物）| Task 10 (processor-prompt.md + context_file 注入) |
| Brain agent 配置 UI 面板 | Task 11 (brain-agent-panel.js + API 路由) |
| UI 面板：preset 选择 + context 编辑 | Task 11 (PRESETS + bap-ctx-editor) |

### Placeholder Scan

无 TBD / TODO / "实现细节" — 所有 Task 均含完整代码。

### Type Consistency

- `load_core_config(config_dir: Path | None) -> AgentAdapter` — Task 2 测试与 Task 3 实现一致
- `create_providers(config_dir=None) -> dict[str, dict]` — Task 4 实现与 Task 4 Step 3 测试一致
- `AgentAdapter` 构造参数 `adapter_id, transport, protocol, command, task_as_arg, capabilities` — 与 `loom_core/agent_adapters/adapter.py` 现有 Protocol 一致
- `loadBrainAgentConfig() -> {command, protocol, extra_flags, context_file}` — Task 9/10 定义与 Task 11 API 路由使用一致
- `buildBrainSpawnArgs(promptFile, cfg)` — Task 9 定义，cfg 结构与 `loadBrainAgentConfig()` 返回值一致
- `openBrainAgentPanel()` — Task 11 挂载到 `window`，index.html 按钮调用一致

---

*Plan saved to `docs/superpowers/plans/2026-05-30-loom-packaging-and-decoupling.md`*
