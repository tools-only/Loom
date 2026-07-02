# Discord Brain Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Discord users whether Brain received a task, which hands are running or complete, and whether Brain is synthesizing.

**Architecture:** The Discord bridge owns the native typing indicator and creates one status Embed. Brain receives that message ID, projects existing workflow episode events into a compact status model, and edits the same Discord message. Existing final reply behavior remains unchanged.

**Tech Stack:** Node.js Discord Gateway bridge, Python FastAPI, `httpx`, `unittest`, Node test runner.

---

### Task 1: Progress projection

**Files:**
- Create: `loom_core/interaction_protocol/social_progress.py`
- Test: `tests/test_social_progress.py`

- [ ] Write tests for received, dispatched, completed, failed, and synthesizing states.
- [ ] Run `python -m unittest tests.test_social_progress -v` and verify failure.
- [ ] Implement the event-to-status projection and Discord Embed rendering.
- [ ] Re-run the focused tests and verify they pass.

### Task 2: Episode event delivery

**Files:**
- Modify: `loom/brain_harness/workflow_episode.py`
- Modify: `loom_core/agents/core_agent.py`
- Test: `tests/test_workflow_episode.py`

- [ ] Write a test proving every persisted episode event is also delivered to an optional sink.
- [ ] Run the focused test and verify failure.
- [ ] Add the optional sink without changing JSONL persistence.
- [ ] Pass the social progress sink from Core Agent context and re-run tests.

### Task 3: Discord status message lifecycle

**Files:**
- Modify: `bridge/channels/discord-bridge.cjs`
- Modify: `loom_core/interaction_protocol/social_reply.py`
- Modify: `loom/brain.py`
- Test: `bridge/channels/discord-bridge.test.cjs`
- Test: `tests/test_social_reply.py`

- [ ] Write failing tests for Discord typing, initial Embed creation, message ID propagation, and PATCH updates.
- [ ] Implement the bridge typing loop and initial status message.
- [ ] Implement Discord message editing and connect Brain episode events to progress updates.
- [ ] Run focused Node and Python tests, then the affected social-channel suites.

### Task 4: Documentation and verification

**Files:**
- Modify: `docs/loom-channel-adapter-user-guide.md`

- [ ] Document Discord progress behavior and its configuration/defaults.
- [ ] Run syntax checks and all affected tests.
- [ ] Inspect the final diff for unrelated changes.
