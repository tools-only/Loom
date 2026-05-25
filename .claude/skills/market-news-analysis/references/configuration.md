# Configuring Market News Analysis

Use this reference when the user wants the skill to adapt over time through weights, feedback, external data, or product-specific preferences.

## Config Layers

Apply configuration in this order:

```text
explicit user instruction
> user/project override config
> external resource metadata
> config/default.yaml
> SKILL.md defaults
```

Routine tuning should happen in config files, not in `SKILL.md`.

## Recommended Override File

Use a file such as `market-news-analysis.config.yaml` in the project or user workspace:

```yaml
version: 1
extends: skills/market-news-analysis/config/default.yaml

defaults:
  market: us_equities
  time_horizon: intraday
  output_depth: deep
  output_format: dashboard_spec

profiles:
  market_regime:
    driver_weights:
      rates: 1.10
      liquidity: 1.05
      sentiment: 0.20

  core_ticker:
    required_modules:
      - earnings_guidance
      - expectations
      - valuation
      - options_sentiment

sources:
  preferred:
    - SEC EDGAR
    - Federal Reserve
    - Cboe
    - FactSet
  rejected:
    - unsourced social media posts

watchlists:
  core_tickers:
    - NVDA
    - MSFT
    - AAPL
  sectors:
    - semiconductors
    - software
    - banks

feedback_harness:
  notes:
    - User prefers source-backed attribution over narrative commentary.
    - User wants liquidity and rates elevated on market-regime pages.
```

## Weight Semantics

Weights are relative priorities, not objective probabilities.

- `> 1.00`: emphasize more than default.
- `1.00`: default priority.
- `0.50-0.90`: include but de-emphasize.
- `< 0.50`: only use when directly relevant.
- `0`: disable unless explicitly requested.

Use weights to order modules, rank evidence, and decide summary emphasis. Do not use weights to hide high-risk contradictory evidence.

## External Resource Metadata

When the user provides a file, feed, URL, article, transcript, or preferred source, normalize it like this:

```yaml
external_resources:
  - id: user-fed-liquidity-model
    type: data_feed
    scope: market
    trust_tier: B_market_data_vendor
    recency_rule: weekly
    use_for:
      - liquidity
      - market_regime
    conflict_policy: corroborate
    notes: User-provided liquidity composite.
```

Resource types:

- `data_feed`: prices, fundamentals, options, flows, macro series.
- `document_source`: filing, transcript, research note, company deck, policy document.
- `news_source`: article, wire, newsletter, live blog.
- `user_preference`: watchlist, tone, excluded source, time horizon.
- `feedback_signal`: correction, preference, example output, rejected behavior.

Conflict policies:

- `override`: use only when the user explicitly wants the resource to supersede defaults.
- `corroborate`: use as supporting or challenging evidence.
- `background_only`: context only, not a basis for conclusions.
- `ignore`: do not use.

## Feedback Harness

Convert feedback into durable config changes:

| Feedback | Config action |
|---|---|
| "Too macro-heavy" | Lower `profiles.market_regime.driver_weights.macro` |
| "Always show liquidity first" | Raise `liquidity`; add it to required modules |
| "Do not cite social media" | Set sentiment weight lower; add sources to rejected |
| "Use my watchlist" | Add `watchlists.core_tickers` |
| "Need deeper single-stock analysis" | Set `defaults.output_depth: deep`; add ticker required modules |
| "This source is unreliable" | Demote or reject that source |

For repeated feedback, propose a small config patch and explain what behavior will change.

## Output Adaptation

Map `output_format` to structure:

- `news_brief`: short conclusion, evidence bullets, risks.
- `dashboard_spec`: page modules, fields, source mapping, component states.
- `research_memo`: thesis, evidence, counter-evidence, catalysts, risks.
- `json_schema`: entities, fields, enums, scoring keys.
- `ui_component_plan`: components, layout, states, interactions.

Map `output_depth` to detail:

- `concise`: top conclusion plus 3-5 bullets.
- `standard`: conclusion, evidence by layer, risks.
- `deep`: full layered analysis with source mapping and counter-evidence.
- `institutional`: deep plus assumptions, methodology, data gaps, and scenario table.

