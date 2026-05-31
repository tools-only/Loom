# Regime: 基本盘 + 大资金流向

## What this layer watches

The regime layer asks a single question: what is the market actually trading right now, and
is large institutional money confirming or contradicting it?

**Indices and breadth.** Start with the broad-market picture — SPX, NDX, RUT, and the
equal-weight S&P (RSP) against its cap-weighted counterpart. A move that shows up in
cap-weight but not equal-weight is concentrated in a handful of mega-caps; that concentration
is itself a signal. Breadth indicators — advancers/decliners, new 52-week highs vs. lows, the
percentage of names trading above their 50- and 200-day moving averages — tell you whether the
market's direction has broad participation or is being pulled by a narrow leadership.

**Volatility and options.** VIX gives the rough fear/complacency read; VVIX tells you whether
VIX itself is moving erratically (a sign of confusion about vol, not just price). The aggregate
put/call ratio and skew reveal how much the options market is paying to protect against
downside. Gamma positioning (whether dealers are long or short gamma) matters for
day-to-day price stability: short-gamma dealers amplify moves; long-gamma dealers absorb them.

**Credit and spreads.** HYG (high-yield ETF) and LQD (investment-grade ETF) are the credit
canaries. When equity rallies but credit spreads are widening — or HYG is underperforming —
the bond market is skeptical of the equity story. CDX indices give a more institutional read
on credit risk appetite. A dislocation between equity exuberance and credit caution has
historically resolved toward credit's skepticism.

**Liquidity.** The plumbing matters more than most narratives acknowledge. Watch the Fed
balance sheet (H.4.1 release), bank reserve levels, the Treasury General Account (TGA) draw-
down vs. rebuild cycle, and overnight reverse repo (RRP) as a measure of excess cash parking.
When TGA is rebuilding via heavy Treasury issuance, it drains reserves from the system and
can create tightening without any Fed action. Conversely, TGA drawdowns inject liquidity.

**Valuation and earnings flow.** Regime context also needs the forward P/E for the index,
the equity risk premium (ERP = earnings yield minus real 10-year yield), and consensus EPS
revision trends. A regime that is "risk-on" but in which EPS revisions are falling and ERP is
compressing has a weaker fundamental underpinning than one where estimates are rising.

**Large-capital flows.** ETF creation/redemption data (net inflows by sector and asset class),
CFTC Commitment of Traders (COT) positioning for S&P futures, and dark-pool/block-print
activity round out the picture. These flows sometimes lead price; they always tell you where
conviction money is positioned.

## Distinguishing noise from signal

A single-day move in SPX accompanied by normal volume and no breadth confirmation is noise
until proven otherwise. A regime shift should show up across at least three dimensions
simultaneously: price direction, breadth, and either credit or liquidity or volatility.

The price / volume / volatility triangle is a useful quick check: a move with expanding volume
and contracting vol (quiet, confident accumulation or distribution) reads differently from a
move on thin volume with spiking vol (panic or short-squeeze). Neither confirms a new regime
alone; they are inputs to a broader picture.

Be especially skeptical of single-indicator regime calls. VIX spiking on an options expiry
is noise. VIX spiking while credit spreads widen, breadth collapses, and equal-weight
underperforms is a regime signal.

## Cross-layer signals

When the regime layer shifts risk-off, it changes which parts of the other two layers matter
most. In a risk-off regime:
- The *sector layer* should show defensives (utilities, staples, health care) outperforming
  cyclicals and growth; if they don't, the regime read may be wrong or the rotation is not yet
  mature.
- The *policy layer* often becomes the dominant story — regime shifts frequently coincide with
  a Fed surprise, a fiscal shock, or a geopolitical event.

When regime is risk-on with broad participation, sector and policy layers become more about
identifying leadership than about risk management.

## When the picture materially shifts

The regime picture has materially shifted when multiple confirming dimensions reverse direction
over several sessions, not just one. The combination of HYG breaking down while VIX makes a
higher high while equal-weight underperforms cap-weight is a meaningful cluster. A single
indicator moving against the current regime interpretation should be noted as a divergence and
watched, but should not immediately overturn the prior read.

What makes a shift "material" for the user specifically depends on the themes and watchlist
in `personal/themes.md` and `personal/watchlist.md`. A liquidity event matters more to a
user tracking interest-rate-sensitive names than to one tracking commodities.

## Reversal cues

- Credit confirms equity: when HYG and SPX both trend up together, the risk-on story has
  structural support. When they diverge for more than a few sessions, the divergence is the
  story.
- Breadth confirmation: a market that rallies but whose breadth is narrowing (fewer names
  above 50-DMA) is deteriorating internally — a precursor to a wider pullback.
- Liquidity reversal: a sudden TGA rebuild (large Treasury issuance calendar) draining reserves
  during an equity rally is a structural headwind that is often underestimated.
- Vol regime change: a VIX that makes a higher low on a rally (doesn't compress as expected)
  signals persistent anxiety beneath the surface.

## What this layer does NOT carry

This layer describes broad market conditions. It does not pick individual sectors as
leaders or identify specific tickers — those belong in the sector-and-chains layer. It does
not explain policy mechanisms — those belong in the policy layer. It does not interpret
options or sentiment readings specific to a single name.
