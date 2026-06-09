"""BaseHand — fixed-workflow + LLM-reasoning pattern.

Flow per run():
  1. Receive task + context + resource_menu (ranked by disclosure policy)
  2. LLM loop: Hand can call fetch_resource(), web_search(), fetch_url()
  3. On stop_reason=end_turn: parse the structured artifact
  4. Return { metadata, narrative } with resource tracking metadata merged in
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from bridge import get_connector_data
from provider_client import get_client_for_hand, _resolve

import httpx

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

# Anthropic server-side built-in — no input_schema needed, API handles execution.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}

FETCH_URL_TOOL = {
    "name": "fetch_url",
    "description": (
        "Fetch the text content of any public URL — RSS feeds, Yahoo Finance pages, "
        "free financial data APIs (FRED, SEC EDGAR), news articles. "
        "Returns plain text truncated to 8 000 characters."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL to fetch",
            },
        },
        "required": ["url"],
    },
}


async def _fetch_url(url: str, max_chars: int = 8000) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LoomFin/1.0)"})
        if r.status_code != 200:
            return f"HTTP {r.status_code} for {url}"
        text = r.text
        ct = r.headers.get("content-type", "")
        if "html" in ct:
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as e:
        return f"fetch_url error: {e}"


class BaseHand:
    def __init__(self, hand_id: str):
        self.hand_id = hand_id

    def _assemble_prompt(self, context: dict) -> str:
        import time
        parts: list[str] = []

        hand_prompt = ROOT / "loom" / "hands" / "prompts" / f"{self.hand_id}.md"
        if hand_prompt.exists():
            parts.append(hand_prompt.read_text("utf-8"))

        skill_md = ROOT / "skills" / "investment-research-framework" / "SKILL.md"
        if skill_md.exists():
            parts.append("\n\n# Investment Research Framework (skill index)\n\n")
            parts.append(skill_md.read_text("utf-8"))

        personal_dir = ROOT / "hands" / self.hand_id / "personal"
        for fname in ["profile.md", "themes.md", "watchlist.md", "sources.md"]:
            p = personal_dir / fname
            if p.exists() and p.stat().st_size > 0:
                parts.append(f"\n\n## (personal) {fname}\n\n{p.read_text('utf-8')}")

        notes = personal_dir / "learned-notes.md"
        if notes.exists() and notes.stat().st_size > 0:
            txt = notes.read_text("utf-8")
            parts.append(f"\n\n## (personal) learned-notes (tail)\n\n{txt[-4000:]}")

        snap = ROOT / "hands" / self.hand_id / "context" / "regime-snapshot.md"
        if snap.exists() and (time.time() - snap.stat().st_mtime) < 86400:
            parts.append(f"\n\n## (context) regime-snapshot\n\n{snap.read_text('utf-8')}")

        return "".join(parts)

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
        provider = _resolve(self.hand_id).get("provider", "anthropic")

        system = self._assemble_prompt(context)
        shown = [r["resource_id"] for r in resource_menu]
        used: list[str] = []

        # web_search is Anthropic-only built-in; OAI-compat providers skip it
        tools: list[dict] = [FETCH_RESOURCE_TOOL, FETCH_URL_TOOL]
        if provider == "anthropic":
            tools.insert(1, WEB_SEARCH_TOOL)

        menu_text = self._format_menu(resource_menu)
        user_parts = [f"Task: {task}", f"\nAvailable resources:\n{menu_text}"]
        if context:
            user_parts.append(f"\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}")

        messages: list[dict] = [{"role": "user", "content": "\n".join(user_parts)}]
        final_text = ""

        for _ in range(12):
            resp = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                tools=tools,
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
                    if block.type != "tool_use":
                        continue

                    if block.name == "fetch_resource":
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

                    elif block.name == "fetch_url":
                        url = block.input.get("url", "")
                        content = await _fetch_url(url)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                        })

                    elif block.name == "web_search":
                        # Anthropic server-side built-in: API executes search automatically.
                        # Send back an empty tool_result to continue the loop.
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "",
                        })

                if tool_results:
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

        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            if "```json" in stripped:
                start = stripped.index("```json") + 7
                end = stripped.index("```", start)
                data = json.loads(stripped[start:end].strip())
                if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                    return data
        except (ValueError, json.JSONDecodeError):
            pass

        return {
            "metadata": {
                "confidence": 0.5,
                "gaps": ["LLM did not return structured JSON — raw text captured"],
                "key_claims": [],
            },
            "narrative": stripped or "(no output)",
        }
