# Loom Fin Task Pack

Loom Fin is the finance-specific task pack for the current Loom prototype. It covers market judgment, target thesis tracking, sentiment scanning, personal position review, and private trading workflows.

This directory starts as a compatibility boundary. Existing interaction behavior, CSS templates, UI design, color style, and concrete product functions must stay intact during migration.

The manifest records finance task capabilities and maps them to concrete external agents. Loom Core should package human intent into task envelopes, invoke those agents through Loom's adapter/interface, and consume returned artifacts. It should not import, mount, or execute finance business logic directly.
