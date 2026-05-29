# Loom Core

Loom Core is the Python-first framework for local human-agent interaction, rendered workspaces, harness data, task routing, and external agent orchestration.

## Language Boundary

Core framework code belongs in Python:

- runtime orchestration
- task registry and adapter interface
- interaction and render protocols
- harness and feedback compilation
- local storage
- agent adapter contracts

JavaScript remains the boundary layer for places where it is required or practical:

- Electron shell
- browser/webview interaction
- static asset serving
- local HTTP/WebSocket gateway compatibility
- existing routes that must stay stable during migration

New core behavior should be implemented in Python unless it is browser, Electron, or gateway specific.

## Compatibility Principle

The Core / Fin split must preserve the current Loom experience:

- existing CSS templates
- existing UI design language
- existing color system
- existing concrete product functions
- existing `data-anc` and `data-handles` semantics
- existing patch behavior

The first migration phase creates boundaries and contracts. It does not move working finance code into Core.

## Task Packs

Loom Fin is the first task pack. Its manifest lives at `domains/loom-fin/manifest.json` and declares finance tasks that should be routed to concrete external agents through Loom's adapter/interface.

Core should not import or execute finance business logic directly. It should package human intent into task envelopes, invoke the chosen agent adapter, receive the returned artifact, patch the workspace, and record harness signals.
