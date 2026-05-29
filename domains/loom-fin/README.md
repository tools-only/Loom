# Loom Fin Domain Pack

Loom Fin is the finance-specific domain pack for the current Loom prototype. It covers market judgment, target thesis tracking, sentiment scanning, personal position review, and private trading workflows.

This directory starts as a compatibility boundary. The current working implementation still lives in legacy paths such as `loom/`, `mcp/connectors/`, `trading/`, and `branches/`. Those files are not moved in the first migration step because existing interaction behavior, CSS templates, UI design, color style, and concrete product functions must stay intact.

The manifest records the routes and capabilities that belong to Loom Fin so Loom Core can eventually load them through a domain-pack interface instead of hardcoding finance concepts in core runtime files.
