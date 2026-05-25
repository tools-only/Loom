# Cross-Asset Confirmation Matrix

Use this reference when producing a Market Regime (Page 1) analysis. Check whether SPX's direction is confirmed or contradicted by related assets before assigning a regime label.

## How to Use

1. Observe the directional state of each confirming asset (↑/↓/flat) over the relevant lookback (intraday or 1-5 day).
2. Match the pattern to the closest row in the matrix below.
3. Include the regime label in the output. If assets diverge from a clean pattern, flag the divergence explicitly — a mixed signal is a regime signal in itself.
4. When more than two confirming assets conflict with the implied regime, label the regime as `risk_on_unconfirmed` or `defensive_rotation` rather than forcing a clean label.

## The Matrix

| Regime label | SPX | HYG (HY credit) | DXY (USD) | 2Y yield | Oil | VIX |
|---|---|---|---|---|---|---|
| `risk_on_confirmed` | ↑ | ↑ | ↓ | stable or modest ↑ | ↑ | ↓ |
| `risk_on_unconfirmed` | ↑ | flat or ↓ | ↑ | sharply ↑ | mixed | elevated or ↑ |
| `risk_off_confirmed` | ↓ | ↓ | ↑ | ↓ (flight to safety) | ↓ | ↑ |
| `defensive_rotation` | ↓ modest or flat | flat | flat | ↓ modest | flat | modest ↑ |
| `liquidity_squeeze` | ↓ | ↓ sharply | ↑ sharply | ↑ sharply | volatile | ↑ sharply |

### Regime Descriptions

**`risk_on_confirmed`**: Equities and credit rising together, USD falling, VIX declining. The cleanest risk-on signal. All major asset classes confirm the same story.

**`risk_on_unconfirmed`**: Equities rising but credit not confirming, or USD strengthening alongside equities (often USD-strength-driven rather than genuine risk appetite). Treat with caution — single-leg rallies are more fragile.

**`risk_off_confirmed`**: Equities and credit falling, USD rising (safe haven), Treasuries bid (2Y yield falling on flight). The cleanest risk-off signal.

**`defensive_rotation`**: Equities declining modestly while credit and USD stay stable; money rotating into defensives (utilities, staples, gold, Treasuries) without a full risk-off. Often precedes a regime shift.

**`liquidity_squeeze`**: Both equities AND credit selling off sharply, USD spiking, rates spiking — a funding/liquidity event rather than a fundamental re-rating. Historically short but severe (March 2020, Oct 2022 UK Gilt crisis, Mar 2023 SVB).

## Output Format

Include this block in the Market Regime output after the Evidence section:

```text
Cross-asset confirmation:
Regime: [label from the 5-value enum above]
Confirming: HYG [↑/↓/flat, current spread or ETF move], DXY [↑/↓/flat, level], 2Y [yield move], Oil [↑/↓/flat], VIX [level, ↑/↓]
Divergences: [list any asset that contradicts the regime label, or "none"]
```

## Common Divergence Patterns and Their Meaning

| Divergence | Likely interpretation |
|---|---|
| SPX ↑ but HYG ↓ (credit not confirming) | Equity short covering or index flows; fundamentals may not support the rally |
| SPX ↑ and DXY ↑ together | USD exceptionalism or carry unwind; check if non-US assets are selling |
| 2Y ↑ sharply while SPX ↑ | Market pricing in more Fed tightening; duration-sensitive sectors at risk |
| VIX ↑ while SPX flat | Hedging demand rising; smart money buying protection ahead of event |
| Oil ↑ sharply while equities ↑ | Demand-led if early-cycle; supply shock if late-cycle — context matters |
| Credit spreads tightening while equities falling | Short-term equity factor noise; credit's verdict is more reliable directionally |

## Source Tiers for Confirming Assets

| Asset | Preferred sources | Tier |
|---|---|---|
| HYG price / HY OAS spread | iShares, ICE BofA HY Index (FRED: BAMLH0A0HYM2) | A/B |
| DXY | ICE (FRED: DEXUSEU proxy), TradingView | A/B |
| 2Y Treasury yield | Treasury.gov, FRED: DGS2 | A |
| WTI / Brent crude | EIA (FRED: DCOILWTICO), CME futures | A |
| VIX / VVIX | Cboe | A |

Always cite the source tier when referencing these in the output.

## Historical Regime Examples (Reference Only)

| Date | Regime | Notes |
|---|---|---|
| Nov 2023 | `risk_on_confirmed` | Powell pivot expectations; HYG, SPX, oil all up; DXY fell; VIX collapsed |
| Mar 2023 (SVB) | `liquidity_squeeze` | SPX ↓, HYG ↓, 2Y ↓ (flight but dislocated), DXY ↑, VIX ↑ sharply |
| Oct 2022 | `risk_off_confirmed` → `liquidity_squeeze` | Terminal rate pricing peak; UK Gilt crisis amplified; credit and equity sold simultaneously |
| Aug 2024 | `risk_off_confirmed` → `defensive_rotation` | Carry unwind (JPY spike), VIX flash to 65, credit held relatively; regime quickly reversed |

These examples are for calibration only — do not extrapolate patterns directly to new situations without checking current data.
