# Evolution Loop

Use this reference when the user gives feedback, corrections, examples of strong research, or asks to improve the skill.

## Feedback Classification

| Input Type | Example | Action |
|---|---|---|
| Fact correction | "This ticker is not upstream; it is a downstream customer." | Correct current answer; consider adding a chain rule if repeatable. |
| Source preference | "Prefer official ETF flow data over commentary." | Add or update source weighting in config. |
| Weighting preference | "Capital flow should dominate sector ranking." | Adjust profile weights if durable. |
| Style preference | "Give me watchlist hypotheses, not long essays." | Store output preference if durable. |
| Strategy pattern | "This rotation framework from X is useful." | Extract trigger, mechanism, indicator, invalidation, and limits. |
| Failure case | "The framework missed the policy implementation delay." | Add a guardrail or checklist item. |

## Strategy Ingestion

When absorbing an excellent investment strategy or framework:

1. Name the strategy pattern in plain language.
2. Identify the market condition where it applies.
3. Extract required indicators and source tiers.
4. Define the decision it improves: ranking, attribution, risk flag, timing, or output format.
5. Define failure modes and when not to use it.
6. Add it to config or a reference only if it is reusable across future research.

Use this schema for durable strategy notes:

```yaml
strategy_pattern:
  name: ""
  applies_when: ""
  improves: "ranking|attribution|risk|timing|format"
  indicators: []
  source_requirements: []
  output_change: ""
  failure_modes: []
  confidence: "low|medium|high"
```

## Durable Change Rules

Make a durable change only when:

- The user explicitly asks to update the skill or project framework.
- The same feedback appears repeatedly.
- A correction fixes a factual taxonomy error.
- A strategy example is concrete enough to express as indicators, triggers, and invalidation conditions.

For one-off feedback, adapt the current answer and state the temporary assumption instead of changing the skill.

## Forward Test

After changing the framework, test it with at least one realistic prompt:

```text
Use $investment-research-framework to analyze today's market regime, the hottest sector, upstream/downstream tickers, and policy risks. Keep it concise and include reversal conditions.
```

Check that the response:

- Separates fact from inference.
- Includes large-flow confirmation or missing-data caveat.
- Maps at least one upstream and downstream chain.
- Mentions policy/geopolitical/monetary transmission when relevant.
- Ends with watch items and invalidation conditions.

