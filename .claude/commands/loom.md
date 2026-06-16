Route a task into Loom without opening a visualization by default.

**Task:** $ARGUMENTS

Use this when the user wants Loom as a general task entry point from the host agent CLI. The current Claude Code or Codex main agent is the Brain.

Do not call `loom_prompt`.
Do not call Brain HTTP APIs such as `/analyze`.
Do not call a standalone LLM API or spawn another Brain process.

Handle the task directly in this main agent session. Use available MCP tools only as Hands or output surfaces when needed.

Routing rules:

- Default task family is `general`.
- Do not route this command to fixed finance tasks. Market, targets, and portfolio belong to Loom Fin.
- Visualization is disabled unless the user explicitly asks to see a UI.
- Preserve Loom's Brain-Hand separation: this main agent is Brain; tools, files, MCP calls, and render surfaces are Hands.
- Do not rewrite Loom Brain, Hand, or harness internals.

Examples:

```text
/loom summarize today's work log
/loom compare Claude Code and Codex for this repo workflow
/loom turn these notes into next actions
```
