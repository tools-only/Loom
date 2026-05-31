# Sector and Chains: 板块热度 + 上下游产业链

## What this layer watches

The sector-and-chains layer asks two questions: which parts of the market are attracting
capital and narrative attention right now, and given a hot sector or theme, which specific
companies in the supply chain are worth examining?

**Sector heat.** The eleven GICS sectors are the primary lens. Start with relative performance
over multiple time horizons: one day, one week, one month, and three months. A sector that
leads on the short horizon but lags on the longer one is bouncing, not rotating. A sector that
leads across all horizons has a persistent bid. The ratio of the sector ETF to SPY (e.g.,
XLK/SPY, XLE/SPY) on a chart tells you more about durable leadership than raw performance
numbers.

Inside the sector, the equal-weight vs. cap-weight split reveals whether heat is broad or
concentrated. Technology sector heat that is almost entirely driven by a few mega-caps is
fragile; heat that spreads to mid-caps and thematic ETFs is more structural.

**Flow confirmation.** Price performance without flow confirmation is tentative. ETF creation
and redemption data tells you whether investors are actually putting money in (creation) or
taking it out (redemption). High-volume days in a sector ETF with a net creation are stronger
signals than price-only moves. Options activity — unusually elevated open interest or call
buying in sector ETFs — can precede institutional positioning.

**Earnings support.** Hot sectors that are also seeing upward EPS estimate revisions are in
a virtuous cycle: better earnings expectations pull more capital in. Hot sectors where earnings
estimates are actually falling (pure-narrative or momentum-driven) are vulnerable to the
moment when narrative runs out of new buyers. Check consensus EPS revision direction, not
just the absolute number.

**Valuation context.** A sector at a historic valuation percentile of 90+ can still work, but
it has no cushion for disappointment. Note where the sector's forward P/E or EV/EBITDA sits
relative to its own 5-year range and relative to the broad market. This is not a
sell signal on its own, but it changes the risk/reward math.

## Supply chain mapping

Once a hot sector or theme is identified, the most valuable next step is walking the supply
chain — upstream, midstream, and downstream — to find companies with concentrated exposure
to the theme before the consensus narrative arrives.

A supply chain walk follows this rough sequence: What is the physical or digital good or
service at the center of the theme? Who makes the raw materials or fundamental components
(upstream)? Who assembles, manufactures, or provides the infrastructure (midstream)? Who
sells the end product or service to the end customer (downstream)? Who enables all of them
(enablers: software, equipment, services)? Who could substitute for any link?

For reference on specific industry chains, see `industry-chain-map.md`, which carries upstream
/ midstream / downstream segment maps for major industries. Use it as a starting skeleton,
not as a definitive list — supply chains evolve.

**Policy sensitivity** should be noted per chain link. Some upstream links are exposed to
export controls (semiconductors, rare earths); some downstream links are sensitive to
regulation (pharma end markets, bank lending). Flag these before surfacing tickers.

## Picking candidate tickers

Not all supply chain nodes are equally worth tracking. The useful filters:

*Liquidity*: a name that trades less than a few million dollars a day cannot absorb
institutional sizing and will respond to the theme only after the move is largely over.

*Revenue exposure (pure-play)*: a conglomerate that derives 5% of revenue from the hot theme
will move less than a company that derives 80%. Prefer higher revenue purity when the goal is
theme exposure.

*Catalyst proximity*: a company with an earnings report, product launch, or contract
announcement within the next few weeks has a discrete event to anchor the thesis. A company
with no near-term catalyst relies entirely on the theme sustaining momentum.

*Alignment with the user's watchlist and themes*: before naming any ticker, check
`personal/watchlist.md` and `personal/themes.md`. If the user is already tracking a name in
this chain, that is context for how to present it. If the user has explicitly passed on a
chain link before (check `personal/learned-notes.md`), note that prior decision rather than
repeating the recommendation.

## Cross-layer signals

Sector leadership that aligns with the regime layer is more durable. Growth/technology
leading in a risk-on regime with broad breadth is structurally sound. The same sector leading
in a risk-off regime where credit is stressed is anomalous and probably short-lived.

The policy layer can flip a sector's leadership quickly. A regulatory announcement, export
control, or subsidy program can reprice an entire supply chain overnight. Hot sectors
particularly exposed to policy risk (semiconductors, energy, health care, financials) warrant
a policy-layer check before committing to a chain walk.

## When the picture materially shifts

Sector heat is material when it persists across multiple time horizons and is backed by both
flow confirmation and earnings revision support. A single-session outperformance on news
is interesting but not yet a regime. For the user specifically, heat becomes material when it
intersects with a theme or ticker already in `personal/themes.md` or `personal/watchlist.md`.

## Reversal cues

- The sector outperforms on price but ETF flows are negative (redemptions exceeding creations):
  price is being driven by short-covering or index rebalancing, not new money coming in.
- Breadth inside the sector is narrowing: only the two or three largest caps are holding up;
  mid-cap and small-cap names in the sector are already rolling over.
- EPS revisions turn negative while price is still elevated: the narrative has run ahead of
  the fundamentals, and the next earnings cycle will be the test.
- A key policy headwind emerges in the policy layer for this sector's supply chain.

## What this layer does NOT carry

This layer identifies sector and chain-level opportunity and risk. It does not make
portfolio-level position sizing decisions. It does not provide a complete fundamental
analysis of individual tickers — the thesis hand handles single-stock deep dives. It does
not replace regime context: sector heat that contradicts the regime layer should be flagged
as anomalous, not treated as a standalone buy signal.
