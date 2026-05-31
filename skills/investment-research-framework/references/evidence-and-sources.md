# Evidence And Sources

## Source Tiers

| Tier | Source Type | Examples | Use |
|---|---|---|---|
| A | Official/original data | Fed, Treasury, BLS, BEA, SEC, CFTC, central banks, election authorities | Fact base |
| B | Market data vendors | Bloomberg, FactSet, Refinitiv, S&P Global, Koyfin, TradingView, ETF.com, EPFR | Structured market, valuation, earnings, and flow data |
| C | Primary financial news | Reuters, Bloomberg News, WSJ, FT, CNBC | Event facts and attribution |
| D | Industry sources | EIA, SEMI, SIA, Gartner, IDC, OPEC, FDA, industry associations | Sector and supply-chain conditions |
| E | Company and filings | IR pages, 10-K, 10-Q, 8-K, transcripts, investor decks | Company fundamentals and guidance |
| F | Sentiment sources | X, Reddit, Stocktwits, Google Trends, YouTube | Sentiment and narrative only |
| G | Secondary commentary | Newsletters, broker strategy, podcasts, blogs, KOLs | Supplemental interpretation only |

## Conflict Handling

- Official and original data establish facts.
- Company filings establish company-specific claims, but management interpretation still needs skepticism.
- News can explain timing, but market attribution needs price, flow, and cross-asset confirmation.
- Social sentiment can explain crowding or narrative velocity, not fundamentals.
- When sources conflict, report the conflict instead of forcing a single clean story.

## Freshness Checks

Always verify current data for:

- Market prices, yields, ETF flows, options, and sector rankings.
- Central-bank decisions and policy guidance.
- Elections, sanctions, tariffs, military conflict, and regulatory actions.
- Earnings dates, guidance updates, and filings.

If current data is unavailable, say what is missing and frame the answer as a reusable analysis plan or historical read.

## Evidence Metadata

Attach these fields mentally or explicitly when the analysis is high-stakes:

```yaml
source:
  name: ""
  tier: "A|B|C|D|E|F|G"
  timestamp: ""
  scope: "market|sector|ticker|policy|theme"
  use_for: "fact|attribution|sentiment|valuation|flow|example"
  confidence: "low|medium|high"
  conflict_policy: "override|corroborate|background-only|ignore"
```

