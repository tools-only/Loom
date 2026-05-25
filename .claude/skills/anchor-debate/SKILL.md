---
name: anchor-debate
description: Use when the user wants to launch a structured adversarial debate (Host + Proposer vs GPT-5 Reviewer) to produce a high-quality PRD or product decision document. Trigger via /debate <topic> or the UI Debate button.
---

# Anchor Debate Skill

## What this is

A structured multi-round adversarial debate that produces a high-quality PRD. A Host agent organizes the discussion, a Proposer (Claude Sonnet) constructs the affirmative position, and a Reviewer (GPT-5 via codex-bridge) critiques it. Debates run for up to 14 rounds and converge to a four-layer consensus document.

## When to invoke

- User types `/debate <topic>` in CC CLI
- User clicks the Debate button in the webview UI
- **Never** auto-trigger — debate must be explicitly initiated

## Four-Layer Structure

Every debate progresses through exactly these layers in order:

1. **Problem Definition** (问题定义) — What is the actual problem? Who are the stakeholders? What constraints exist?
2. **Ideal State** (理想态) — What does success look like? What properties must the solution have?
3. **Gap Analysis** (差距分析) — What is the delta between current state and ideal? What causes the gap?
4. **Strategy** (策略) — What is the approach? What are the KPIs? What are the risks and rollback conditions?

Do not skip layers. Do not move to Strategy before Problem is fully committed.

## Retro-Mapping Rule

Every time the scope changes layers or the focus shifts significantly, the Host MUST map the new scope back to previously confirmed commitments. This prevents context decay — "what was agreed in round 3 must still hold in round 11."

See `references/retro-mapping-checklist.md` for the enforcement protocol.

## Output

- `output/debates/<debate_id>/spec.md` — four-layer PRD document
- `output/debates/<debate_id>/transcript.json` — full debate transcript
- Webview: real-time dual-column overlay (Proposer left, Reviewer right)
- Webview: Debates history drawer with links to past specs

## Termination

The debate terminates when:
- Host judges `converged` for 2 consecutive rounds AND all four layers have commitments
- 14 rounds reached (hard cap)
- 60 minutes elapsed (wall clock)
- User clicks Abort in the overlay

## Role Models

| Role | Model | Purpose |
|---|---|---|
| Host | claude-opus-4-7 (or available opus) | Orchestration, scope control, judgment |
| Proposer | claude-sonnet-4-6 | Affirmative construction |
| Reviewer | GPT-5 via codex-bridge | Critical adversarial review |

## Quality Rules

- Official data and prior commitments establish facts; avoid drifting into speculation
- Every conclusion needs evidence + a statement of what would invalidate it
- Conflicting evidence must be surfaced, not hidden
- Stale or missing definitions must be labeled and resolved before progressing
