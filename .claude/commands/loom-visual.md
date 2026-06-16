Route a task into Loom and force the visual UI path.

**Task:** $ARGUMENTS

Use this when the user wants Loom to produce or update the visual surface. The current Claude Code or Codex main agent is the Brain.

Call `loom_prompt` only to prepare the visual surface:

```json
{
  "text": "$ARGUMENTS",
  "route": "general",
  "visualize": true
}
```

Routing rules:

- Default task family is `general`.
- Do not route this command to fixed finance tasks. Market, targets, and portfolio belong to Loom Fin.
- Visualization is enabled regardless of the webview toggle.
- `loom_prompt` only prepares a dynamic `/loom-visual/<visual_id>` webview; it does not run Brain inference.
- After preparation, this main agent must perform the Brain work directly.
- Render the visual result through `anchor_render` with the returned `visual_id`:

```json
{
  "visual_id": "<returned visual_id>"
}
```

- The visual surface is the independent dynamic `/loom-visual/<visual_id>` page, not the Loom Fin root page or any shared Loom Visual page.
- Do not call Brain HTTP APIs such as `/analyze`.
- Do not call a standalone LLM API or spawn another Brain process.
- Do not rewrite Loom Brain, Hand, or harness internals.

Examples:

```text
/loom-visual map this product research into a canvas
/loom-visual turn this planning thread into a visual workspace
/loom-visual organize these implementation options into a decision map
```
