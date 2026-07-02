# Loom Agent Output Contract Decoupling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple Loom hand/agent raw work output from the strict L0-L3 UI artifact so Brain and runtime hands keep full agent capability while Loom still renders traceable cards.

**Architecture:** Keep the current structured artifact path as the default for analysis-card workflows. Add an explicit output contract on `AtomicTask`, normalize every hand result into a raw result plus an optional projected Loom artifact, and route free-form or file-producing tasks through the full agent session path instead of forcing them through `run.artifact` schema validation.

**Tech Stack:** Python dataclasses and `unittest`, FastAPI service code in `loom/brain.py`, Brain orchestration in `loom_core/agents/core_agent.py`, hand planning in `loom/brain_harness/*`, adapter/session code in `loom_core/agent_adapters/*` and `loom_core/agent_service.py`.

---

## Current Constraint

The planning side is already flexible: Brain can generate arbitrary runtime hands, dimensions, role prompts, capabilities, priorities, and dependencies.

The limiting point is the output side:

- `LoomCoreAgent._build_hand_task()` tells hands to produce only a JSON artifact.
- `LoomCoreAgent._validate_artifact()` repairs/rejects outputs that do not include `narrative`, `metadata.key_claims`, and `metadata.confidence`.
- `RuntimeHandAdapter` treats a runtime hand as failed when it completes without a `run.artifact`.
- `CodexHandChannel` uses a strict structured output schema with `additionalProperties: false`.
- The social/direct-agent path already bypasses this because the code comments note the structured artifact contract is too rigid for HTML/file output.

The target design is:

```text
hand/agent execution result
  -> raw_result: text, artifact, files, events, diagnostics
  -> optional loom_artifact projection for UI cards
  -> synthesis consumes both raw result and projection metadata
```

## Non-Goals

- Do not remove L0-L3 artifacts.
- Do not weaken source/evidence requirements for market and research cards.
- Do not rewrite the full adapter layer.
- Do not expose raw chain-of-thought or full prompts in the UI.
- Do not make every task free-form. Strict artifact remains the default.

## Output Contract Vocabulary

Use these strings consistently:

```python
OutputContract = Literal["loom_artifact", "agent_result", "file_result"]
```

- `loom_artifact`: current strict card-producing behavior.
- `agent_result`: full agent response text, optional artifact, optional files, projected to a compact Loom card.
- `file_result`: full agent response where created/modified files are the primary deliverable, also projected to a compact Loom card.

---

### Task 1: Add Output Contract to AtomicTask

**Files:**
- Modify: `loom/brain_harness/hand_plan.py`
- Modify: `loom/brain_harness/task_decomposer.py`
- Test: `tests/test_core_agent_task_decomposition.py`

**Step 1: Write the failing test**

Add a test that proves the decomposer preserves `output_contract` from LLM JSON and defaults to `loom_artifact` when omitted.

```python
def test_decomposer_preserves_output_contract():
    client = _MessageClient(
        '{"rationale":"needs free-form agent work","tasks":['
        '{"task_id":"t1","hand_id":"runtime-page-builder","executor_id":"runtime-hand",'
        '"dimension":"page build","task":"Build the HTML page",'
        '"system_prompt":"You are a page builder.",'
        '"capabilities":["workspace.patch"],'
        '"output_contract":"file_result",'
        '"rubrics":[],"priority":0,"depends_on":[]}'
        ']}'
    )
    decomposer = TaskDecomposer(client, "fake")

    plan = asyncio.run(decomposer.decompose("build page", "general", {}))

    assert plan.tasks[0].output_contract == "file_result"
    assert plan.to_dict()["tasks"][0]["output_contract"] == "file_result"
```

Also add a default assertion to an existing test that omits the field:

```python
assert result["hand_plan"]["tasks"][0]["output_contract"] == "loom_artifact"
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition.CoreAgentTaskDecompositionTests
```

Expected: fail because `AtomicTask` has no `output_contract`.

**Step 3: Implement minimal model change**

In `loom/brain_harness/hand_plan.py`, add:

```python
OutputContract = Literal["loom_artifact", "agent_result", "file_result"]
```

Add the field to `AtomicTask`:

```python
output_contract: OutputContract = "loom_artifact"
```

Add it to `to_dict()`:

```python
"output_contract": self.output_contract,
```

In `TaskDecomposer._llm_decompose()`, extend the prompt JSON example:

```python
'"output_contract":"loom_artifact",'
```

Add rules:

```text
- output_contract defaults to "loom_artifact".
- Use "agent_result" for deep free-form analysis where the raw answer matters.
- Use "file_result" when the hand is expected to create or modify files.
```

When parsing each task:

```python
raw_contract = str(item.get("output_contract") or "loom_artifact").strip()
if raw_contract not in {"loom_artifact", "agent_result", "file_result"}:
    raw_contract = "loom_artifact"
```

Pass `output_contract=raw_contract` into `AtomicTask`.

**Step 4: Run test to verify it passes**

Run the same unittest command.

Expected: pass.

**Step 5: Commit**

```powershell
git add loom\brain_harness\hand_plan.py loom\brain_harness\task_decomposer.py tests\test_core_agent_task_decomposition.py
git commit -m "feat: add hand output contract"
```

---

### Task 2: Introduce a Normalized Hand Result Shape

**Files:**
- Create: `loom_core/agents/hand_result.py`
- Test: `tests/test_hand_result_projection.py`

**Step 1: Write the failing tests**

Create `tests/test_hand_result_projection.py`.

```python
import unittest

from loom_core.agents.hand_result import normalize_hand_result


class HandResultProjectionTests(unittest.TestCase):
    def test_dict_artifact_stays_strict_artifact(self):
        artifact = {
            "metadata": {"confidence": 0.8, "key_claims": ["claim"], "gaps": []},
            "narrative": "Structured card.",
            "sections": [],
            "evidence": [],
        }

        result = normalize_hand_result(
            artifact,
            hand_id="runtime-evidence",
            task_id="t1",
            output_contract="loom_artifact",
        )

        self.assertEqual(artifact, result["artifact"])
        self.assertEqual("", result["text"])
        self.assertEqual("loom_artifact", result["output_contract"])

    def test_text_result_projects_to_minimal_artifact(self):
        result = normalize_hand_result(
            {"text": "Created report.html with the requested layout.", "files": ["report.html"]},
            hand_id="runtime-builder",
            task_id="t2",
            output_contract="file_result",
        )

        self.assertEqual("file_result", result["output_contract"])
        self.assertEqual(["report.html"], result["files"])
        self.assertEqual("Created report.html with the requested layout.", result["text"])
        self.assertEqual("Created report.html with the requested layout.", result["artifact"]["narrative"])
        self.assertIn("agent result projected", result["artifact"]["metadata"]["gaps"][0])
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_hand_result_projection
```

Expected: fail because `loom_core.agents.hand_result` does not exist.

**Step 3: Implement minimal helper**

Create `loom_core/agents/hand_result.py`:

```python
from __future__ import annotations

from typing import Any, Literal

OutputContract = Literal["loom_artifact", "agent_result", "file_result"]


def normalize_hand_result(
    value: Any,
    *,
    hand_id: str,
    task_id: str,
    output_contract: OutputContract = "loom_artifact",
) -> dict[str, Any]:
    if output_contract == "loom_artifact" and isinstance(value, dict):
        return {
            "output_contract": output_contract,
            "hand_id": hand_id,
            "task_id": task_id,
            "artifact": value,
            "text": "",
            "files": [],
            "raw": value,
        }

    raw = value if isinstance(value, dict) else {"text": str(value)}
    text = str(raw.get("text") or raw.get("message") or raw.get("narrative") or "").strip()
    files = list(raw.get("files") or [])
    if not text and isinstance(raw.get("artifact"), dict):
        text = str(raw["artifact"].get("narrative") or "").strip()

    artifact = raw.get("artifact") if isinstance(raw.get("artifact"), dict) else None
    if artifact is None:
        artifact = project_agent_result_to_artifact(
            text=text,
            files=files,
            hand_id=hand_id,
            task_id=task_id,
            output_contract=output_contract,
        )

    return {
        "output_contract": output_contract,
        "hand_id": hand_id,
        "task_id": task_id,
        "artifact": artifact,
        "text": text,
        "files": files,
        "raw": raw,
    }


def project_agent_result_to_artifact(
    *,
    text: str,
    files: list[str],
    hand_id: str,
    task_id: str,
    output_contract: OutputContract,
) -> dict[str, Any]:
    narrative = text or "Agent completed without a textual summary."
    file_claims = [f"Produced file: {path}" for path in files]
    return {
        "metadata": {
            "confidence": 0.5,
            "key_claims": file_claims or ["Agent result captured."],
            "gaps": ["agent result projected into Loom artifact; inspect raw_result for full output"],
            "resources_used": [],
            "source_notes": [],
            "hand_id": hand_id,
            "task_id": task_id,
            "output_contract": output_contract,
        },
        "narrative": narrative,
        "sections": [
            {
                "id": "agent_result",
                "title": "Agent Result",
                "summary": narrative,
                "bullets": file_claims or [narrative],
            }
        ],
        "evidence": [],
        "raw_items": [],
        "raw_sources": [],
    }
```

**Step 4: Run test to verify it passes**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_hand_result_projection
```

Expected: pass.

**Step 5: Commit**

```powershell
git add loom_core\agents\hand_result.py tests\test_hand_result_projection.py
git commit -m "feat: normalize hand execution results"
```

---

### Task 3: Let Core Agent Preserve Raw Results While Rendering Artifacts

**Files:**
- Modify: `loom_core/agents/core_agent.py`
- Test: `tests/test_core_agent_task_decomposition.py`

**Step 1: Write the failing test**

Add a test where an `agent_result` task returns text instead of an artifact.

```python
def test_agent_result_task_preserves_raw_output_and_projects_card(self):
    seen = {}

    async def hand_runner(hand_id, task, context):
        seen["context"] = context
        return {"text": "Built report.html successfully.", "files": ["report.html"]}

    client = _MessageClient(
        '{"rationale":"file output","tasks":['
        '{"task_id":"t1","hand_id":"runtime-builder","executor_id":"runtime-hand",'
        '"dimension":"file build","task":"Build report.html",'
        '"system_prompt":"You are a file builder.","capabilities":["workspace.patch"],'
        '"output_contract":"file_result",'
        '"rubrics":[],"priority":0,"depends_on":[]}'
        ']}'
    )
    agent = LoomCoreAgent(_AgenticHarness(), _FakeDispatcher(), hand_runner, client=client, model="fake")

    result = asyncio.run(agent.analyze("build report", {}))

    self.assertEqual("file_result", seen["context"]["agentic_hand_spec"]["output_contract"])
    self.assertEqual("Built report.html successfully.", result["hand_results"]["t1"]["text"])
    self.assertEqual(["report.html"], result["hand_results"]["t1"]["files"])
    self.assertEqual("Built report.html successfully.", result["hand_artifacts"]["t1"]["narrative"])
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition.CoreAgentTaskDecompositionTests.test_agent_result_task_preserves_raw_output_and_projects_card
```

Expected: fail because context lacks `output_contract`, raw result is treated as malformed artifact, and `hand_results` is absent.

**Step 3: Thread output_contract through `_run_one()`**

In `LoomCoreAgent.analyze()`, import:

```python
from loom_core.agents.hand_result import normalize_hand_result
```

Extend `_run_one()` signature:

```python
output_contract: str = "loom_artifact",
```

Add to `agentic_hand_spec`:

```python
"output_contract": output_contract,
```

Pass each `AtomicTask.output_contract` when calling `_run_one()`.

**Step 4: Normalize result before validation**

Replace direct artifact handling:

```python
raw_value = await self._hand_runner(run_executor_id, task_str, hand_context)
normalized = normalize_hand_result(
    raw_value,
    hand_id=hand_id,
    task_id=task_id or "",
    output_contract=output_contract,
)
artifact = normalized["artifact"]
```

Only run strict schema repair for `loom_artifact`:

```python
if output_contract == "loom_artifact":
    issues = self._validate_artifact(artifact)
else:
    issues = []
```

Return the normalized result from `_run_one()`:

```python
return hand_id, artifact, normalized
```

Update callers to keep:

```python
hand_artifacts[tid] = artifact
hand_results[tid] = normalized
```

Initialize `hand_results = {}` near `hand_artifacts = {}` and include it in the final response:

```python
"hand_results": hand_results,
```

**Step 5: Run targeted test**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition.CoreAgentTaskDecompositionTests.test_agent_result_task_preserves_raw_output_and_projects_card
```

Expected: pass.

**Step 6: Run full core agent task tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition
```

Expected: pass.

**Step 7: Commit**

```powershell
git add loom_core\agents\core_agent.py tests\test_core_agent_task_decomposition.py
git commit -m "feat: preserve raw hand results in brain pipeline"
```

---

### Task 4: Route Non-Artifact Runtime Tasks Through Full Agent Session

**Files:**
- Modify: `loom/brain.py`
- Test: `tests/test_brain_codex_hand_route.py`
- Test: `tests/test_agent_service.py`

**Step 1: Write failing route test**

Add a test proving `_brain_hand_runner()` uses `_agent_session_service.run()` for `file_result` runtime hands.

```python
def test_brain_generated_file_result_routes_through_agent_session(self):
    context = {
        "agentic_hand_spec": {
            "executor_id": "runtime-hand",
            "output_contract": "file_result",
            "system_prompt": "Create the requested file.",
        }
    }
    session_result = {
        "run_id": "run-1",
        "adapter_id": "runtime-hand",
        "status": "completed",
        "text": "Created report.html",
        "artifact": None,
    }

    with (
        patch.object(brain._agent_session_service, "run", AsyncMock(return_value=session_result)) as run_agent,
        patch.object(brain, "_run_direct_codex_hand", side_effect=AssertionError("strict codex channel must not be used")),
    ):
        result = asyncio.run(
            brain._brain_hand_runner("runtime-builder", "Build report.html", context)
        )

    self.assertEqual("Created report.html", result["text"])
    run_agent.assert_awaited_once()
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_codex_hand_route.BrainCodexHandRouteTests.test_brain_generated_file_result_routes_through_agent_session
```

Expected: fail because non-registered runtime hands still route through strict artifact adapter logic.

**Step 3: Implement routing branch**

In `_brain_hand_runner()`, after reading `spec`, add:

```python
output_contract = str(spec.get("output_contract") or "loom_artifact")
if output_contract in {"agent_result", "file_result"}:
    adapter_id = _adapter_registry.resolve_runtime_adapter(spec.get("executor_id") or "runtime-hand")
    session = await _agent_session_service.run(
        adapter_id=adapter_id,
        task=task,
        cwd=str(_ROOT),
        context={**dict(ctx or {}), "agentic_hand_spec": spec},
        dangerous=bool(spec.get("dangerous", False)),
        session_key=str(ctx.get("session_id") or ""),
    )
    return {
        "text": session.get("text", ""),
        "artifact": session.get("artifact"),
        "files": session.get("files", []),
        "run_id": session.get("run_id", ""),
        "adapter_id": session.get("adapter_id", adapter_id),
    }
```

Keep current `_run_direct_codex_hand()` path only for `loom_artifact`.

**Step 4: Run targeted route test**

Run the same unittest command.

Expected: pass.

**Step 5: Run related tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_brain_codex_hand_route tests.test_agent_service
```

Expected: pass.

**Step 6: Commit**

```powershell
git add loom\brain.py tests\test_brain_codex_hand_route.py tests\test_agent_service.py
git commit -m "feat: route file-result hands through agent sessions"
```

---

### Task 5: Capture Created HTML/File Outputs in AgentSessionService

**Files:**
- Modify: `loom_core/agent_service.py`
- Test: `tests/test_agent_service.py`

**Step 1: Write failing test**

Add a test with a fake full agent adapter that emits a final message and creates a file under a temp workspace.

```python
def test_agent_session_reports_recent_html_files(self):
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "report.html").write_text("<html>ok</html>", encoding="utf-8")
        registry = _Registry(_FakeRuntimeAdapter("runtime-hand", "Created report.html"))
        service = AgentSessionService(registry)

        result = asyncio.run(service.run(
            adapter_id="runtime-hand",
            task="build report",
            cwd=tmp,
            context={},
        ))

    self.assertIn("report.html", result["files"])
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_service
```

Expected: fail because the service does not return `files`.

**Step 3: Add conservative file discovery**

In `AgentSessionService.run()`, after adapter completion and before return:

```python
files = _recent_agent_files(resolved_cwd)
```

Add helper:

```python
def _recent_agent_files(root: str, *, limit: int = 20) -> list[str]:
    base = Path(root)
    if not base.exists():
        return []
    allowed = {".html", ".md", ".txt", ".json", ".csv", ".png", ".jpg", ".jpeg", ".svg"}
    candidates = []
    now = time.time()
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > 600:
            continue
        candidates.append((stat.st_mtime, path.relative_to(base).as_posix()))
    candidates.sort(reverse=True)
    return [rel for _mtime, rel in candidates[:limit]]
```

Return it:

```python
"files": files,
```

**Step 4: Run test**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_agent_service
```

Expected: pass.

**Step 5: Commit**

```powershell
git add loom_core\agent_service.py tests\test_agent_service.py
git commit -m "feat: report files from full agent sessions"
```

---

### Task 6: Keep Strict Artifact Validation for Existing Card Workflows

**Files:**
- Modify: `tests/test_core_agent_task_decomposition.py`
- Modify: `tests/test_codex_hand_channel.py`
- Modify: `tests/test_hand_artifact_density.py`

**Step 1: Add regression assertions**

Add or strengthen tests that prove:

```python
self.assertEqual("loom_artifact", result["hand_plan"]["tasks"][0]["output_contract"])
self.assertIn("metadata", result["hand_artifacts"]["t1"])
self.assertIn("confidence", result["hand_artifacts"]["t1"]["metadata"])
```

Keep `test_validation_rejects_incomplete_evidence_and_untraceable_raw_data` unchanged for direct Codex.

**Step 2: Run regression tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_core_agent_task_decomposition tests.test_codex_hand_channel tests.test_hand_artifact_density
```

Expected: pass.

**Step 3: Fix only compatibility breaks**

If failures come from adding `output_contract` to serialized task dicts, update expected dicts to include:

```python
"output_contract": "loom_artifact"
```

Do not loosen direct Codex schema in this task.

**Step 4: Commit**

```powershell
git add tests\test_core_agent_task_decomposition.py tests\test_codex_hand_channel.py tests\test_hand_artifact_density.py
git commit -m "test: preserve strict artifact regressions"
```

---

### Task 7: Expose Raw Result Metadata in Episode and API Output

**Files:**
- Modify: `loom/brain_harness/flywheel.py`
- Modify: `loom/brain.py`
- Test: `tests/test_flywheel.py`
- Test: `tests/test_brain_presentation.py`

**Step 1: Write failing persistence test**

Add a test that an episode detail can store `hand_results` without losing `hand_artifacts`.

```python
detail = {
    "episode_id": "ep-test",
    "hand_artifacts": {"t1": {"narrative": "Projected", "metadata": {"confidence": 0.5, "key_claims": [], "gaps": []}}},
    "hand_results": {"t1": {"text": "Raw full answer", "files": ["report.html"]}},
}
```

Expected assertion:

```python
self.assertEqual("Raw full answer", loaded["hand_results"]["t1"]["text"])
self.assertEqual("Projected", loaded["hand_artifacts"]["t1"]["narrative"])
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_flywheel
```

Expected: fail if flywheel detail serialization drops unknown fields.

**Step 3: Persist and return hand_results**

Where `analyze()` constructs the response and flywheel detail, include:

```python
hand_results=result.get("hand_results", {})
```

For API responses, include a compact version only:

```python
"hand_results": {
    key: {
        "output_contract": value.get("output_contract"),
        "text": value.get("text", "")[:2000],
        "files": value.get("files", []),
        "run_id": value.get("raw", {}).get("run_id", ""),
    }
    for key, value in result.get("hand_results", {}).items()
}
```

Do not render raw text by default in `_render_artifact()`.

**Step 4: Run tests**

Run:

```powershell
D:\conda\python.exe -m unittest tests.test_flywheel tests.test_brain_presentation
```

Expected: pass.

**Step 5: Commit**

```powershell
git add loom\brain_harness\flywheel.py loom\brain.py tests\test_flywheel.py tests\test_brain_presentation.py
git commit -m "feat: expose raw hand result metadata"
```

---

### Task 8: Update Docs for the New Output Boundary

**Files:**
- Modify: `docs/loom-hand-agent-guide.md`
- Modify: `docs/loom-social-and-agent-adapters.md`
- Optional Modify: `loom_core/README.md`

**Step 1: Add docs section**

Add a section named:

```markdown
## Hand Output Contracts
```

Document:

```markdown
Loom supports three hand output contracts:

- `loom_artifact`: strict L0-L3 card artifact; default for analysis cards.
- `agent_result`: free-form agent response preserved as raw result and projected into a compact card.
- `file_result`: full agent session where files are the primary deliverable; files are preserved in `hand_results` and summarized in a card.
```

Add guidance:

```markdown
Use `loom_artifact` for market/research/evidence cards.
Use `agent_result` when the raw prose or long reasoning artifact is the deliverable.
Use `file_result` when the hand creates files, HTML pages, patches, or other workspace artifacts.
```

**Step 2: Add migration note**

Add:

```markdown
Existing hands do not need to change. If `output_contract` is omitted, Brain treats the task as `loom_artifact`.
```

**Step 3: No code test required**

Run a quick grep:

```powershell
rg -n "Hand Output Contracts|output_contract|file_result|agent_result" docs loom_core
```

Expected: new docs references are present.

**Step 4: Commit**

```powershell
git add docs\loom-hand-agent-guide.md docs\loom-social-and-agent-adapters.md loom_core\README.md
git commit -m "docs: document hand output contracts"
```

---

## Final Verification

Run the focused Python test set:

```powershell
D:\conda\python.exe -m unittest `
  tests.test_hand_result_projection `
  tests.test_core_agent_task_decomposition `
  tests.test_brain_codex_hand_route `
  tests.test_agent_service `
  tests.test_codex_hand_channel `
  tests.test_hand_artifact_density `
  tests.test_flywheel
```

Expected: all pass.

Run a smoke `/analyze` request after starting Brain:

```powershell
cd loom
D:\conda\python.exe -m uvicorn brain:app --host 127.0.0.1 --port 3002
```

In another terminal:

```powershell
curl.exe -s -X POST http://127.0.0.1:3002/analyze `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"Test structured Loom artifact path\",\"domain_hint\":\"general\"}"
```

Expected:

- Response includes `ok: true`.
- Existing `hand_artifacts` are still present.
- New `hand_results` is present.
- Existing card UI still renders from projected artifacts.

Run a manual free-form route check by forcing a decomposer fixture or direct hand runner test; expected result:

- `hand_results[t1].text` contains raw agent output.
- `hand_artifacts[t1]` contains a compact projection.
- No strict artifact repair is triggered for `agent_result` or `file_result`.

## Rollback Plan

If the change destabilizes the Brain pipeline:

1. Leave `AtomicTask.output_contract` in place.
2. Force all parsed values to `loom_artifact` in `TaskDecomposer`.
3. Keep `hand_result.py` unused.
4. Re-run strict artifact tests.

This restores current behavior without reverting schema-compatible fields.

## Design Checkpoint

Before implementing Task 4, confirm one product decision:

```text
Should `/analyze` ever be allowed to create or modify files through `file_result`,
or should `file_result` be limited to social/direct-agent routes?
```

Recommended default: allow it only when Brain explicitly generates `output_contract="file_result"` and the selected executor is a full runtime adapter. Keep ordinary analysis cards on `loom_artifact`.
