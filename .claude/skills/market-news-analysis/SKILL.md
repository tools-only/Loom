---
name: market-news-analysis
description: Use when designing, writing, or evaluating market news analysis pages, stock market commentary, sector rotation reports, or ticker-level market briefs for equities such as U.S. stocks.
---

# Market News Analysis

## Overview

Use a three-layer funnel: market environment -> sector direction -> core ticker odds and catalysts. Keep facts, source quality, and interpretation separate. Every conclusion needs evidence and a reversal condition.

This skill is for market-news product design and analysis workflows. It is not financial advice and should not recommend trades or guarantee outcomes.

## Configuration First

This skill is configurable. Before producing an analysis, design, or product spec:

1. Load `config/default.yaml` if available.
2. Apply any project/user override the user provides, such as `market-news-analysis.config.yaml`, a pasted YAML block, or explicit preferences in the prompt.
3. Incorporate user-provided external resources as scoped inputs, not as permanent truth.
4. Use feedback from the current conversation to adjust weights and presentation, then state the effective assumptions when they materially affect the output.

Read `references/configuration.md` when the user asks to tune weights, add external resources, persist preferences, evaluate feedback, or adapt the skill for a specific agent/product.

Configuration precedence:

```text
explicit user instruction > user/project override config > external resource metadata > config/default.yaml > SKILL.md defaults
```

Do not edit this `SKILL.md` for routine preference changes. Put durable tuning into a config override.

## Core Workflow

1. Decide the analysis scope:
   - **Market page**: diagnose the broad market regime.
   - **Sector page**: diagnose rotation, leadership, and industry drivers.
   - **Core ticker page**: diagnose single-stock movement, expectations, valuation, and catalysts.
2. Start with a concise conclusion, then show evidence.
3. Classify each driver: macro, rates, liquidity, earnings, valuation, policy, technicals, options, sentiment, or news event.
4. Rank sources by reliability before using them in the conclusion.
5. End with catalysts, risks, and explicit reversal conditions.

## Weighted Scoring Pattern

When the user wants configurable prioritization, score evidence instead of treating every signal equally:

```text
weighted_signal_score =
  driver_weight
  * source_tier_weight
  * recency_weight
  * confidence_weight
  * conflict_penalty
```

Use the score to rank what appears in the summary, not to fabricate precision. Always surface low-scoring but high-risk contradictory evidence.

## Source Priority

| Tier | Source Type | Examples | Use |
|---|---|---|---|
| A | Official/original data | Fed, Treasury, BLS, BEA, SEC, Cboe, FINRA, company IR | Fact base |
| B | Market data vendors | Bloomberg, FactSet, Refinitiv, S&P Global, Koyfin, TradingView | Structured market, valuation, earnings, flow data |
| C | Mainstream financial news | Reuters, Bloomberg News, WSJ, FT, CNBC | News facts and event attribution |
| D | Industry sources | Gartner, IDC, SEMI, EIA, OPEC, SIA, FDA, industry associations | Sector and industry conditions |
| E | Sentiment sources | X/Twitter, Reddit, Stocktwits, Google Trends, YouTube | Sentiment and narrative only |
| F | Secondary commentary | Newsletters, broker strategy, KOLs, podcasts, blogs | Supplemental interpretation only |

Rules:

- Use A/B sources to establish facts.
- Use C/D sources to explain events.
- Use E/F sources only for sentiment and narrative context.
- Do not let weak social signals override official data or company filings.

## Page 1: Market Regime

Use this page to answer: what is the market trading today?

Default profile: emphasize macro, rates, liquidity, breadth, and earnings/valuation. If the config sets `profiles.market_regime.driver_weights`, use those weights to order modules and evidence.

Analyze:

| Layer | Questions | Signals | Sources |
|---|---|---|---|
| Market state | Risk-on, risk-off, defensive, or mixed? | S&P 500, Nasdaq 100, Dow, Russell 2000, equal-weight vs cap-weight | Yahoo Finance, Bloomberg, Reuters, TradingView, Nasdaq |
| Market breadth | Is the move healthy? | Advancers/decliners, new highs/lows, % above 50/200 DMA | NYSE/Nasdaq breadth, StockCharts, Koyfin |
| Macro data | Is growth/inflation changing? | CPI, PCE, NFP, unemployment, ISM, GDP, retail sales | BLS, BEA, FRED, ISM |
| Rates/Fed/USD | Is valuation pressure rising or falling? | 2Y/10Y yields, real rates, curve, DXY, Fed probabilities | Treasury, FRED, Fed, CME FedWatch |
| Liquidity/credit | Is market liquidity expanding or tightening? | Fed balance sheet, reserves, TGA, RRP, credit spreads, HYG/LQD | Fed H.4.1, Treasury DTS, FRED, ICE/BofA |
| Vol/options | Is fear or complacency dominant? | VIX, VVIX, put/call, skew, 0DTE, gamma | Cboe, OCC, SpotGamma |
| Earnings/valuation | Is the index supported by fundamentals? | EPS revisions, margins, beat rate, forward PE, ERP, FCF yield | FactSet, Refinitiv, S&P Global, company filings |
| Event risk | What could change the view? | CPI, FOMC, NFP, earnings, options expiry, Treasury auctions | Economic calendars, Nasdaq earnings calendar, Treasury |

Output shape:

```text
Market view:
The market is [risk-on/risk-off/mixed/defensive], mainly driven by [driver 1], [driver 2], and [driver 3].

Evidence:
1. Index/breadth: [...]
2. Macro/rates: [...]
3. Liquidity/credit: [...]
4. Earnings/valuation: [...]

Reversal condition:
If [indicator/event] changes to [condition], revise the view.
```

## Page 2: Sector Rotation

Use this page to answer: where is capital and narrative leadership moving?

Default profile: emphasize relative strength, flows, earnings revisions, macro sensitivity, and industry conditions. If the config sets `profiles.sector_rotation.driver_weights`, use those weights to order modules and evidence.

Analyze:

| Layer | Questions | Signals | Sources |
|---|---|---|---|
| Heatmap | Which sectors lead or lag? | 11 GICS sectors, sector ETFs, contribution to index move | S&P sector indices, XL* ETFs, TradingView |
| Relative strength | Is the move a trend or bounce? | Sector/SPY, momentum rank, 20/50/200 DMA, RSI | Koyfin, TradingView, Bloomberg |
| Flows | Are flows confirming price? | Sector ETF flows, volume, active fund positioning | ETF.com, FactSet, EPFR |
| Earnings revision | Is leadership backed by fundamentals? | EPS revisions, revenue growth, margins, beat/miss | FactSet, Refinitiv, Bloomberg |
| Valuation | Is the sector priced for perfection? | Forward PE, EV/EBITDA, P/S, FCF yield, historical percentile | S&P Global, FactSet, Koyfin |
| Macro sensitivity | What factor drives the sector? | Rates, USD, oil, credit, GDP, PMI | FRED, Treasury, EIA, BLS, BEA |
| Industry conditions | Is the industry improving? | Orders, inventories, pricing, capacity, capex, supply/demand | Industry associations, company guidance, PMI, Gartner, IDC, SEMI, EIA |
| Policy/regulation | Is policy helping or hurting? | Antitrust, drug pricing, bank capital rules, export controls, energy policy | SEC, FTC, DOJ, FDA, EPA, Commerce Department |
| Internal structure | Is breadth strong inside the sector? | Equal-weight vs cap-weight, leaders vs laggards, subsector dispersion | GICS data, ETF holdings, Koyfin |

Sector style buckets:

- **Growth offensive**: technology, communication services, consumer discretionary; driven by rates, earnings revisions, AI/cloud/ad narratives.
- **Cyclical recovery**: industrials, materials, energy, financials; driven by GDP, PMI, commodities, credit, yield curve.
- **Defensive cash flow**: utilities, staples, health care; driven by risk aversion, dividends, slowdown.
- **Rate-sensitive**: real estate, utilities, banks, long-duration growth; driven by long rates and real rates.
- **Policy-sensitive**: health care, energy, defense, semiconductors, banks; driven by regulation and fiscal policy.

Output shape:

```text
Sector view:
[Sector A] is leading because of [driver]. [Sector B] is lagging because of [risk].

Flow confirmation:
ETF flows and volume show [confirmation/divergence], implying [persistence judgment].

Rotation view:
The market favors [growth/cyclical/defensive/value]. Watch [candidate sectors] if [condition] continues.
```

## Page 3: Core Ticker

Use this page to answer: why did this stock move, and what would reprice it next?

Default profile: emphasize move attribution, earnings/guidance, expectations, valuation, trading structure, and catalysts. If the config sets `profiles.core_ticker.driver_weights`, use those weights to order modules and evidence.

Analyze:

| Layer | Questions | Signals | Sources |
|---|---|---|---|
| Ticker snapshot | Why is this stock important today? | Price move, volume, news trigger, theme, index contribution | Nasdaq, NYSE, Yahoo Finance, Bloomberg, Reuters |
| Price structure | Trend, breakout, pullback, or event shock? | Gap, volume, support/resistance, relative strength vs sector | TradingView, Koyfin |
| Options/sentiment | Is the trade crowded? | IV rank, put/call, gamma, max pain, short interest | Cboe, OCC, Ortex, S3, FINRA, SpotGamma |
| Fundamentals | Is quality changing? | Revenue growth, margins, FCF, ROIC, balance sheet | SEC EDGAR, 10-K, 10-Q, company IR |
| Earnings/guidance | What changed in the latest print? | EPS/revenue beat, guidance, orders, backlog, margins, management tone | Earnings releases, transcripts, Nasdaq calendar |
| Expectations | Is there a positive or negative surprise? | Analyst revisions, target changes, consensus EPS, whisper numbers | FactSet, Refinitiv, Bloomberg, Zacks |
| Valuation | What growth is implied? | Forward PE, PEG, EV/Sales, EV/EBITDA, FCF yield, DCF sensitivity | FactSet, Koyfin, Capital IQ |
| Competitive position | Is the moat improving or eroding? | Share, pricing power, customer concentration, substitutes, supplier power | 10-K risks, industry reports, competitor filings |
| Capital actions | What is management doing with capital? | Buybacks, dividends, M&A, debt, issuance, dilution | SEC 8-K/10-Q/10-K, company announcements |
| Ownership/regulatory | What non-operating risks matter? | Form 4, 13F, institutions, lawsuits, antitrust, FDA, export controls | SEC, DOJ, FTC, FDA, court filings |
| Catalysts | What can reprice the stock next? | Earnings, product launches, investor day, ex-dividend, macro windows | Company IR, Nasdaq earnings calendar, economic calendar |

Output shape:

```text
Ticker view:
[Ticker] moved because of [driver], best classified as [fundamental/valuation/sentiment/technical/options] driven.

Evidence:
1. Fundamentals: [...]
2. Expectations: [...]
3. Valuation: [...]
4. Trading structure: [...]

Next catalysts:
[Catalyst] could extend the move; [reversal condition] would weaken the view.
```

## Product/UI Guidance

Use these components when designing a market-news page:

- `MarketStatusBar`: state, risk level, timestamp, data freshness.
- `DriverTags`: macro, earnings, liquidity, policy, technical, sentiment.
- `SourceBadge`: official, data-vendor, news, industry, social.
- `EvidencePanel`: expandable proof behind a conclusion.
- `RiskCalendar`: upcoming high-impact events.
- `NewsTimeline`: event feed grouped by driver.
- `ConfidenceMeter`: low, medium, high confidence.
- `ReversalCondition`: what would invalidate the view.

Page-specific components:

- Market: `IndexSummaryCards`, `MarketBreadthPanel`, `RatesAndFedPanel`, `LiquidityDashboard`, `VolatilityOptionsPanel`, `EarningsValuationPanel`.
- Sector: `SectorHeatmap`, `SectorRankingTable`, `SectorFlowPanel`, `RelativeStrengthChart`, `RotationMap`.
- Ticker: `TickerHero`, `MoveAttributionPanel`, `FundamentalsSnapshot`, `EarningsExpectationPanel`, `OptionsSentimentPanel`, `CatalystRiskTimeline`.

Design tone:

- Dense, professional, scan-friendly.
- Prefer compact tables, heatmaps, timelines, and expandable evidence panels.
- Avoid marketing-style hero layouts, decorative gradients, and unsupported claims.

## External Resource Adaptation

When users provide external resources, classify each one before using it:

- **Data feed**: prices, fundamentals, flows, macro series, options data.
- **Document source**: SEC filing, transcript, research note, company deck, policy document.
- **News source**: article, wire story, newsletter, live blog.
- **User preference**: watchlist, favored indicators, excluded sources, tone, time horizon.
- **Feedback signal**: corrections, likes/dislikes, examples of good/bad output.

Attach resource metadata:

- `scope`: market, sector, ticker, theme, or global.
- `trust_tier`: A, B, C, D, E, or F.
- `recency_rule`: intraday, daily, weekly, quarterly, stale-after date, or evergreen.
- `use_for`: facts, attribution, sentiment, layout, user preference, or examples.
- `conflict_policy`: override, corroborate, background-only, or ignore.

Never allow an external resource to silently override official data. If a user-supplied source conflicts with an A-tier source, mention the conflict and prefer the official source unless the user explicitly asks for an alternative scenario.

## Feedback Harness

When the user gives feedback, convert it into one of these durable knobs:

- Increase/decrease driver weights.
- Promote/demote source tiers or specific sources.
- Change page depth: concise, standard, deep, or institutional.
- Change output format: news brief, dashboard spec, JSON schema, research memo, or UI component plan.
- Add/remove required modules.
- Add watchlists, sectors, themes, time horizons, or excluded asset classes.

For repeated feedback, propose a config override rather than editing the skill body. Keep the skill stable; let configs carry personalization.

## Quality Checklist

Before finalizing any page or report, verify:

- The top conclusion is specific, not generic.
- Each major claim has at least one source or measurable signal.
- Official data and company filings outrank social or commentary sources.
- Conflicting evidence is shown, not hidden.
- The output separates facts, interpretation, and uncertainty.
- The page includes catalysts and reversal conditions.
- Missing or stale data is labeled rather than silently ignored.
- Effective config choices are reflected in module order, evidence ranking, and output depth.
- User-provided external resources are labeled with scope, trust tier, and conflict policy.
