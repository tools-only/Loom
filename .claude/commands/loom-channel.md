Register an external resource channel into Loom.

**Resource:** $ARGUMENTS

Use this when the user wants Loom to remember an external source, social/media channel, document, feed, account, or pasted resource as context for future work. The current Claude Code or Codex main agent is the Brain.

Call `loom_channel_connect` with the resource details you can infer from `$ARGUMENTS`:

```json
{
  "channel": "social",
  "source": "$ARGUMENTS",
  "url": "",
  "title": "$ARGUMENTS",
  "intent_hint": "Why this source matters to the user",
  "tags": ["general"]
}
```

Rules:

- This is an adapter entry for external resources and intent_wiki cultivation.
- Do not call Brain HTTP APIs such as `/analyze`.
- Do not call a standalone LLM API or spawn another Brain process.
- Do not rewrite Loom Brain, Hand, or harness internals.
- Treat the registered item as user-provided external resource evidence, not permanent truth.

Examples:

```text
/loom-channel follow this X account for AI agent product signals: https://x.com/example
/loom-channel use this Reddit thread as recurring user-research context: https://reddit.com/r/...
/loom-channel remember this research doc as a preferred source for coding-agent UX decisions
```
