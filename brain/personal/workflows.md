# Workflow Overrides

Machine-readable overrides live in `brain/personal/workflows.json`.
This file is documentation only — edit `workflows.json` to customize dispatch.

## Built-in workflows (`loom/brain_harness/workflows.json`)

| Domain  | Mode        | Hands triggered                              |
|---------|-------------|----------------------------------------------|
| finance | full_fanout | market, sentiment, target, position (always) |
| general | dynamic     | LLM selects from available hands             |

## How to add a custom domain (`workflows.json`)

```json
{
  "research": {
    "mode": "dynamic",
    "trigger_keywords": ["综述", "论文", "research", "调研"],
    "hands_pool": ["canvas"],
    "rationale": "调研任务动态选 hand"
  }
}
```

The `finance` workflow always fires all 4 finance hands — macroeconomic,
sentiment, ticker thesis, and position are interdependent for investment decisions.
