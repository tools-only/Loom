# Loop: When to Record a Learned Note

## What this reference is for

`personal/learned-notes.md` is a prose accumulation of durable knowledge about how this
specific user thinks, what they have learned from past analysis, and what approaches have
worked or failed. It is not a trade log. It is not a data feed. It is the memory of a
trusted analyst who has worked with this user for a long time.

This reference helps decide: should I write something to learned-notes right now, and if so,
what should I write?

## What is "durable"

A learned-note is worth writing when the insight will still be useful in a future session
that has no memory of this one. Ask: if a different analyst read this note six months from
now with no other context, would it help them understand how to work well with this user?

Examples of durable insights:
- The user consistently discounts sentiment surveys (AAII, NAAIM) as lagging indicators.
  Future sessions should not lead with sentiment data unless the user explicitly asks.
- The user treats credit spread widening as a higher-quality signal than VIX spikes, because
  they believe options markets are more easily gamed.
- The user has a strong prior that fiscal policy timelines are always longer than consensus
  expects. They want analysis to assume delayed implementation.
- A supply chain walk for AI infrastructure names produced a thesis the user found genuinely
  useful; the upstream → chip design → foundry → packaging → system integration structure
  resonated.
- The user asked for a policy analysis and found the "announcement vs. implementation pipeline"
  framing particularly clarifying; they want future policy analysis to lead with that.

Examples of things that are NOT durable:
- "The user seemed satisfied with today's market brief." (Ephemeral reaction, not a pattern.)
- "NVDA is on the watchlist." (That lives in watchlist.md, not here.)
- "CPI came in at 3.1% today." (Data, not user preference or learned strategy.)
- "The user asked me to summarize the Fed meeting." (Task, not a preference about how to work.)

## Deciding using evolution-loop.md's six classes

`references/evolution-loop.md` lists six classes of feedback. Use them as a judgment lens,
not as a categorization requirement:

- **Fact correction**: the user corrected a specific data point or interpretation. This is
  usually NOT worth a learned-note — the correction is local to that analysis. Write a note
  only if the correction reveals a systematic bias (e.g., "I consistently over-estimate the
  speed of regulatory implementation").
- **Source preference**: the user prefers or distrusts a specific source. This IS worth a
  note if it is persistent (they have expressed it more than once or with strong emphasis).
- **Weighting preference**: the user wants more or less emphasis on a category of evidence.
  Worth a note if it reflects a genuine philosophical view, not just preference about today's
  analysis.
- **Style preference**: the user prefers a certain way of presenting information. Worth a
  note if it keeps recurring.
- **Strategy pattern**: a research approach that worked well or failed spectacularly. Highly
  worth recording — these make future analysis materially better.
- **Failure case**: an analysis that was clearly wrong. Worth recording if there is a
  structural lesson (e.g., "I anchored too heavily on Fed language and missed the credit
  signal entirely").

## How to write a good learned-note

A useful learned-note has three parts in one paragraph:

1. **The triggering situation** — briefly, what happened or what was observed.
2. **The durable insight** — what this means for how to work with this user going forward.
3. **The application** — in what future situations should this change behavior?

Example:

> 2026-05-15. User pushed back on a sector-rotation analysis that ranked financials as a
> leader based on recent price performance alone. They pointed out that ETF flows and earnings
> revisions were both negative for the sector, making the price move a short-squeeze rather
> than a real rotation. Going forward: always confirm sector heat with flow and earnings
> revision data before calling leadership; price performance alone is insufficient for this
> user.

Keep notes concise — two to four sentences. Append at the bottom. Do not restructure, re-sort,
or delete prior notes (that history is the value). The tail of the file is what gets read
in context, so the most recent notes are naturally the most accessible.

## When not to write

- When the user's reaction is polite acknowledgment but no substantive engagement.
- When the insight is already captured in `personal/profile.md`, `themes.md`, or `watchlist.md`.
- When you are uncertain whether the insight reflects a durable preference or just the mood
  of today's session. If uncertain, skip it — a low-quality note is worse than no note.
