---
schema_version: 1
default_style: risk-adjusted
position_rules:
  - id: rule-001
    condition: "VIX > 25"
    action: no_new_beta
    priority: 1
  - id: rule-002
    condition: "position_pct > 0.08"
    action: hold_only
    priority: 2
weighting:
  earnings_guide: 0.4
  macro_regime: 0.35
  sentiment: 0.25
---

# 自由文本策略备注

科技股估值：forward P/E + growth rate 组合估值，不用 trailing P/E。

宏观敏感期：优先看 Fed dot plot 走向，其次 CPI 环比变化趋势。
