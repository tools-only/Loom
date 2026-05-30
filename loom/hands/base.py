"""BaseHand — fixed-workflow + LLM-reasoning pattern.

Flow per run():
  1. Receive task + context + resource_menu (ranked by disclosure policy)
  2. LLM loop: Hand can call fetch_resource() to pull connector data
  3. On stop_reason=end_turn: parse the structured artifact
  4. Return { metadata, narrative } with resource tracking metadata merged in
"""
import json
from pathlib import Path
from bridge import get_connector_data
from provider_client import get_client_for_hand

ROOT = Path(__file__).parent.parent

FETCH_RESOURCE_TOOL = {
    "name": "fetch_resource",
    "description": (
        "Fetch recent data from a connector in the resource library. "
        "Returns the latest inbox items from that connector source."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "resource_id": {
                "type": "string",
                "description": "The resource_id from the available resources list",
            },
            "params": {
                "type": "object",
                "description": "Optional query parameters (e.g. {\"ticker\": \"NVDA\"} for finnhub)",
                "default": {},
            },
        },
        "required": ["resource_id"],
    },
}


class BaseHand:
    def __init__(self, hand_id: str):
        self.hand_id = hand_id
        self._prompt_cache: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_cache is None:
            p = ROOT / "hands" / "prompts" / f"{self.hand_id}.md"
            self._prompt_cache = p.read_text(encoding="utf-8")
        return self._prompt_cache

    @staticmethod
    def _format_menu(resource_menu: list[dict]) -> str:
        lines = []
        for r in resource_menu:
            tier = r.get("tier", "?")
            desc = r.get("description", "")
            lines.append(f"- `{r['resource_id']}` (Tier {tier}): {desc}")
        return "\n".join(lines) if lines else "(no resources available)"

    async def run(self, task: str, context: dict, resource_menu: list[dict]) -> dict:
        client, model = get_client_for_hand(self.hand_id)
        system = self._load_prompt()
        shown = [r["resource_id"] for r in resource_menu]
        used: list[str] = []

        menu_text = self._format_menu(resource_menu)
        user_parts = [f"Task: {task}", f"\nAvailable resources:\n{menu_text}"]
        if context:
            user_parts.append(f"\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}")

        messages: list[dict] = [{"role": "user", "content": "\n".join(user_parts)}]
        final_text = ""

        for _ in range(10):
            resp = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                tools=[FETCH_RESOURCE_TOOL],
                messages=messages,
            )

            assistant_content = [b.model_dump() for b in resp.content]
            messages.append({"role": "assistant", "content": assistant_content})

            if resp.stop_reason == "end_turn":
                for block in resp.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                break

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use" and block.name == "fetch_resource":
                        rid = block.input.get("resource_id", "")
                        params = block.input.get("params", {})
                        data = await get_connector_data(rid, params)
                        if rid and rid not in used:
                            used.append(rid)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                json.dumps(data, ensure_ascii=False)
                                if data
                                else json.dumps({"error": "no data available for this connector"})
                            ),
                        })
                messages.append({"role": "user", "content": tool_results})

        artifact = self._parse_artifact(final_text)
        artifact["metadata"]["resources_shown"] = shown
        artifact["metadata"]["resources_used"] = used
        artifact["metadata"]["resources_ignored"] = [r for r in shown if r not in used]
        return artifact

    @staticmethod
    def _parse_artifact(text: str) -> dict:
        """Extract structured artifact from LLM response. Falls back to wrapping plain text."""
        stripped = text.strip()

        # Try direct JSON parse
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting from ```json ... ``` block
        try:
            if "```json" in stripped:
                start = stripped.index("```json") + 7
                end = stripped.index("```", start)
                data = json.loads(stripped[start:end].strip())
                if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                    return data
        except (ValueError, json.JSONDecodeError):
            pass

        # Fallback
        return {
            "metadata": {
                "confidence": 0.5,
                "gaps": ["LLM did not return structured JSON — raw text captured"],
                "key_claims": [],
            },
            "narrative": stripped or "(no output)",
        }
