# Reversal Trigger Schema

Use this reference when writing reversal conditions in any market analysis output (Market Regime, Sector Rotation, Core Ticker). At `output_depth: deep` or `institutional`, reversal conditions must conform to this typed schema so they can be machine-evaluated in the back-test loop.

At `output_depth: standard` or `concise`, free-text fallback is permitted (`reversal_trigger.allow_text_fallback: true` in `default.yaml`), but prefer the typed schema whenever the trigger is specific enough to express.

## JSON Schema

```json
{
  "indicator": "<string — the specific signal, index, or data series>",
  "operator": "<one of: gt | lt | gte | lte | cross_above | cross_below | pct_change | abs_change | streak>",
  "threshold": <number — the trigger value in the indicator's native units>,
  "lookback": "<string — the period over which the indicator is measured, e.g. '1d', '5d', '1m'>",
  "window": "<string — how long to observe before the trigger expires, e.g. '7d', '30d', '1q'>",
  "severity": "<one of: watch | warn | invalidates>",
  "source_tier": "<one of: A | B | C | D | E | F>"
}
```

## Field Definitions

**`indicator`**: The exact signal name. Use a standardized form where possible (e.g., `"VIX"`, `"2Y Treasury yield"`, `"HYG spread OAS"`, `"NVDA 20DMA"`, `"CPI YoY"`, `"AAPL EPS beat rate"`). Include the ticker or FRED series ID if the indicator is series-specific.

**`operator`**:
| Value | Meaning | Example |
|---|---|---|
| `gt` | Current value > threshold | VIX > 25 |
| `lt` | Current value < threshold | 2Y yield < 4.0% |
| `gte` | Current value ≥ threshold | SPY ≥ 520 |
| `lte` | Current value ≤ threshold | PCE YoY ≤ 2.3% |
| `cross_above` | Value crosses threshold from below | VIX crosses above 20 |
| `cross_below` | Value crosses threshold from above | 10Y yield crosses below 4.0% |
| `pct_change` | Percentage change from reference exceeds threshold | SPX pct_change > -5% in 5d |
| `abs_change` | Absolute change from reference exceeds threshold | NVDA abs_change > -$50 from entry |
| `streak` | Condition holds for N consecutive periods | NFP below expectations for 3 consecutive months |

**`threshold`**: A number in the indicator's native units. For `pct_change`, use decimal (e.g., `-0.05` for -5%). For `streak`, use the count as the threshold (e.g., `3` for 3 consecutive periods).

**`lookback`**: The measurement window for the current value (e.g., `"1d"` = daily close, `"5d"` = 5-day average, `"1m"` = 1-month rolling).

**`window`**: How long this trigger remains active before expiring. After the window passes without triggering, the view should be re-evaluated. Use: `"1d"`, `"7d"`, `"14d"`, `"30d"`, `"1q"`.

**`severity`**:
| Value | Meaning |
|---|---|
| `watch` | Monitor; does not invalidate the view but warrants attention |
| `warn` | Warrants view reassessment; probability of thesis correctness has dropped |
| `invalidates` | Directly contradicts the thesis; view should be revised or closed |

**`source_tier`**: The tier of the data source that would be used to observe the trigger. Prefer A or B tier for triggers used in back-testing.

## Examples

### Market Regime: risk-on view with VIX trigger

```json
{
  "indicator": "VIX",
  "operator": "cross_above",
  "threshold": 22,
  "lookback": "1d",
  "window": "14d",
  "severity": "warn",
  "source_tier": "A"
}
```

Prose reading: "If VIX crosses above 22 on any daily close within the next 14 days, re-evaluate the risk-on regime."

### Market Regime: additional macro trigger

```json
{
  "indicator": "CPI YoY",
  "operator": "gt",
  "threshold": 3.5,
  "lookback": "1m",
  "window": "30d",
  "severity": "invalidates",
  "source_tier": "A"
}
```

Prose reading: "If the monthly CPI YoY print exceeds 3.5% within 30 days, the current risk-on / soft-landing view is invalidated."

### Core Ticker: price structure trigger

```json
{
  "indicator": "NVDA 50DMA",
  "operator": "cross_below",
  "threshold": 0,
  "lookback": "1d",
  "window": "30d",
  "severity": "warn",
  "source_tier": "B"
}
```

Note: For moving-average crosses, threshold `0` means "crossing below the moving average itself." Phrase the indicator as `"NVDA price vs 50DMA"` if clearer.

### Core Ticker: earnings expectation trigger

```json
{
  "indicator": "NVDA forward EPS consensus (FactSet)",
  "operator": "pct_change",
  "threshold": -0.05,
  "lookback": "30d",
  "window": "1q",
  "severity": "invalidates",
  "source_tier": "B"
}
```

Prose reading: "If forward EPS consensus falls more than 5% over 30 days within the next quarter, the valuation thesis is invalidated."

### Sector Rotation: flows divergence trigger

```json
{
  "indicator": "XLK ETF 5-day net flows",
  "operator": "lt",
  "threshold": -500000000,
  "lookback": "5d",
  "window": "14d",
  "severity": "watch",
  "source_tier": "B"
}
```

Prose reading: "If XLK sees net outflows exceeding $500M over any 5-day period in the next 14 days, re-examine the sector rotation thesis."

## Multiple Triggers

Each output page should include 1-3 triggers with different severities:

```json
[
  { "indicator": "VIX", "operator": "cross_above", "threshold": 22, ..., "severity": "warn" },
  { "indicator": "HYG OAS spread", "operator": "gt", "threshold": 400, ..., "severity": "invalidates" },
  { "indicator": "2Y Treasury yield", "operator": "gt", "threshold": 4.8, ..., "severity": "watch" }
]
```

Always order triggers from `watch` → `warn` → `invalidates` in the output.

## Free-Text Fallback

When the trigger cannot be cleanly expressed in the schema (e.g., qualitative management tone shifts, regulatory outcomes, geopolitical events), use:

```json
{
  "indicator": "<description of what to watch>",
  "operator": "qualitative",
  "threshold": null,
  "lookback": null,
  "window": "<time frame>",
  "severity": "watch|warn|invalidates",
  "source_tier": "C",
  "note": "<free-text description of the trigger condition>"
}
```

This preserves machine-readability for fields that can be typed while allowing prose for the trigger definition.
