---
name: brain-coordination
description: Brain agent 的 meta-skill 索引 —— brain-hand 协调、human-agent 交互、策略沉淀。触发条件：Brain agent 在 /analyze 调用中需要决定 dispatch 策略、整合多 hand 输出、回应用户反馈。不含 domain 知识（domain 知识在 investment-research-framework，由 hand 使用）。
---

# Brain Coordination Skill

This skill defines how the Brain agent **coordinates hands** and **interacts with the human**.
It is the meta-level counterpart to `skills/investment-research-framework/` — that skill
is for hand agents doing domain analysis; this skill is for Brain doing orchestration.

**The Brain does NOT use this skill to analyze markets.** That's a hand's job.
The Brain uses this skill to:
- Orchestrate which hands to fire (and why)
- Integrate multi-hand `key_claims` under the user's personal strategy
- Decide when to ask the user for clarification vs commit to an answer
- (Phase 2) Identify and distill new strategy insights back to `brain/personal/`

## Available references (open on demand)

- `dispatch.md` — how to choose workflow mode; when finance = full_fanout vs general = dynamic;
                  how to handle ambiguous questions that span domains
- `integration.md` — how to fuse multi-hand key_claims under a user strategy;
                     conflict resolution (authority hierarchy, freshness weighting);
                     how to cite strategy rules in key_drivers
- `clarification.md` — when to ask the user for clarification vs commit to an answer;
                       how to phrase clarifying questions without exposing implementation
- `distillation.md` — (Phase 2) how to identify distillable strategy patterns from interaction;
                      how to write meta-lessons to learned-notes.md

## User state lives in (read these first)

- `brain/personal/strategy.md` — investment strategy (YAML front-matter + free text)
- `brain/personal/workflows.md` — per-domain workflow overrides
- `brain/personal/learned-notes.md` — meta-learning from past human-Brain interactions (read tail)
- `brain/personal/distilled-skills.md` — KOL/article distilled reasoning patterns (Phase 2)
- `brain/personal/locked-beliefs.md` — non-negotiable user judgments (Phase 2)

## Fresh context lives in (read if < 24h old)

- `brain/context/last-synthesis.md` — most recent synthesis output + user reaction

## Path convention

Brain personal state: `brain/personal/` and `brain/context/` (project root)
Brain harness code: `loom/brain_harness/`
Skill body files: `skills/brain-coordination/`

## Key invariants

1. Brain never fetches raw data — that's a hand's job
2. Every `key_driver` in synthesis must cite a strategy rule + a hand's specific claim
3. When cold (no strategy.md), declare it rather than silently use defaults
4. `learned-notes.md` accumulates coordination lessons, not domain facts
