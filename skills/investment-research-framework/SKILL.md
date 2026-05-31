---
name: investment-research-framework
description: Reference this skill index when conducting investment research inside a Loom Fin hand — including regime analysis (基本盘 + 大资金流向), sector heat and supply-chain mapping (板块热度 + 上下游产业链), or policy-layer impact assessment (货币 / 财政 / 监管 / 地缘 / 选举 / 国际宏观). Triggers include: a /run task on a market/sentiment/target/position hand, a manual review of pushed connector data, or any task where the user references regime, sector rotation, supply chains, or policy transmission. Deeper references are opened only on demand via filesystem read.
---

# Investment Research Framework

This skill scaffolds investment research for a Loom Fin hand. It carries the
user's individual preferences and accumulated experience — not textbook finance
knowledge. Read user-layer files (`personal/*.md`) before forming any conclusion;
they encode what this specific user cares about right now.

This skill does not produce financial advice. Separate facts, inference,
uncertainty, and reversal conditions. When a `personal/*` or `context/*` file
materially changed your conclusion, name which file in the narrative. Never
silently override user-curated `personal/*` content.

## Available references (open only when relevant)

- `regime.md` — 基本盘 + 大资金流向: how to read indices, breadth, vol, credit, liquidity, and institutional flows; when a regime has truly shifted vs. when it is noise.
- `sector-and-chains.md` — 板块热度 + 上下游产业链: how to judge sector heat quality, walk a supply chain from a theme to candidate tickers, and distinguish fundamental leadership from narrative momentum.
- `policy.md` — 政策层: six dimensions (货币 / 财政 / 监管 / 地缘 / 选举 / 国际宏观), how each transmits to equity prices, and how to track the announcement-to-implementation pipeline.
- `evidence-and-sources.md` — how to weigh competing sources; freshness rules; conflict resolution when tiers disagree.
- `industry-chain-map.md` — reference map of upstream / midstream / downstream segments by sector (used alongside sector-and-chains).
- `evolution-loop.md` — six classes of user feedback as a judgment framework (not a schema); used when deciding whether to record a learned-note.
- `loop.md` — what counts as a durable learning worth recording to `personal/learned-notes.md`, and how to write it.

## User state lives in (read these first)

- `personal/profile.md` — research style, time horizon, risk preference
- `personal/themes.md` — current themes the user is actively tracking
- `personal/watchlist.md` — tickers and the reason each one matters
- `personal/sources.md` — KOLs, media, and custom RSS the user trusts
- `personal/learned-notes.md` — accumulated prose feedback (read the tail)

## Fresh context lives in (read if present and < 24h old)

- `context/regime-snapshot.md` — most recent macro/regime snapshot written by a connector
- `context/*.md` — other dated snapshots

## Path convention

Personal and context files live at `hands/<hand_id>/personal/` and
`hands/<hand_id>/context/` relative to the project root. The skill index and
references live at `skills/investment-research-framework/`.
