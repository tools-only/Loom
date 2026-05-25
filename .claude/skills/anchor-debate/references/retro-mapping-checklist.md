# Retro-Mapping Checklist

Use this checklist whenever the debate scope changes layer or the focus shifts significantly.

## When to apply

Apply retro-mapping when any of these occur:
- The `scope.layer` changes (e.g., moving from `problem` to `ideal`)
- The `scope.focus` changes substantially within the same layer
- A Reviewer raises a concern that pulls the debate back to a previous layer
- The Host is about to judge `converged` on a layer for the first time

## Procedure

For each item in the new scope, the Host MUST:

1. **Find the anchor commitment**: Locate the prior commitment from `commitments[]` that this item builds on
2. **Check consistency**: Does the new scope item contradict or silently expand any prior commitment?
3. **Flag new introductions**: Any item that cannot be mapped back to a prior commitment must be explicitly flagged with `introducing_new: true` and a justification

## Output format

```json
[
  {
    "new_scope_item": "The session context is the primary workspace boundary",
    "maps_to_commitment": "round 2: 'Working context is defined by the active session'",
    "introducing_new": false
  },
  {
    "new_scope_item": "Support cross-session persistence for long-running tasks",
    "maps_to_commitment": null,
    "introducing_new": true,
    "justification": "Proposer identified this as a gap in round 4; not previously committed but consistent with ideal state"
  }
]
```

## Red flags (Host must call out)

- An item from Strategy that was never grounded in Problem Definition
- A KPI that contradicts a constraint identified in Problem Definition
- A scope reduction (scope narrowed) without acknowledging what was dropped
- More than 2 `introducing_new: true` items in a single scope change — this suggests a layer was skipped

## After mapping

If `introducing_new` items exist:
1. Emit a `decision` event flagging `retro_warning: true` with the list of new items
2. Give the next round's Proposer explicit instructions to defend or retract the new items
3. If fundamental scope creep is detected, pull the debate back to the layer where the inconsistency originated
