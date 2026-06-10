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
try:
    from bridge import get_connector_data
except ImportError:
    from loom.bridge import get_connector_data

try:
    from provider_client import get_client_for_hand, _resolve
except ImportError:
    from loom.provider_client import get_client_for_hand, _resolve

import httpx

ROOT = Path(__file__).resolve().parents[2]

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
        user_parts.append(
            "\nOutput contract:\n"
            "Return ONLY one JSON object with this shape:\n"
            "{\n"
            '  "metadata": {\n'
            '    "confidence": 0.0,\n'
            '    "key_claims": [\n'
            '      {"claim":"specific claim","source":"FRED 30Y","tier":"A","freshness":"2026-06-09"},\n'
            '      {"claim":"another claim","source":"Reuters","tier":"C","freshness":"2026-06-08"}\n'
            '    ],\n'
            '    "gaps": ["missing/stale data"],\n'
            '    "source_notes": [{"source":"...", "tier":"A|B|C|D|E|F|G|unknown", "freshness":"...", "note":"..."}]\n'
            "  },\n"
            '  "narrative": "2-4 sentence high-level judgment for the visible Loom card.",\n'
            '  "sections": [\n'
            '    {"id":"summary", "title":"High-level judgment", "summary":"...", "bullets":["string bullet", {"claim":"sourced bullet","source":"FRED","tier":"A"}]},\n'
            '    {"id":"evidence", "title":"Evidence and data support", "summary":"...", "bullets":[...]},\n'
            '    {"id":"analysis", "title":"Detailed analysis", "summary":"...", "bullets":[...]},\n'
            '    {"id":"gaps", "title":"Coverage gaps", "summary":"...", "bullets":[...]}\n'
            "  ],\n"
            '  "evidence": [{"claim":"...", "support":"...", "source":"...", "source_tier":"A|B|C|D|E|F|G|unknown", "freshness":"...", "confidence":0.0}]\n'
            "}\n"
            "Minimum information density:\n"
            "- metadata.key_claims: 3-5 data-backed claims, each with source and tier.\n"
            "- metadata.source_notes: at least 3 source notes when any source/data was available.\n"
            "- sections: at least 4 sections, each with summary plus at least 3 bullets.\n"
            "- evidence: at least 5 evidence rows when data was available.\n"
            "- If data was unavailable, fill gaps with the exact missing data and explain what could not be expanded.\n"
            "The visible narrative must be short. Put the deeper support in sections/evidence."
        )

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
        density_gaps = self._artifact_density_gaps(artifact, used, shown)
        if density_gaps:
            artifact = await self._repair_low_density_artifact(
                client=client,
                model=model,
                system=system,
                tools=tools,
                messages=messages,
                artifact=artifact,
                density_gaps=density_gaps,
                used_resources=used,
                shown_resources=shown,
            )
            density_gaps = self._artifact_density_gaps(artifact, used, shown)
            if density_gaps:
                artifact.setdefault("metadata", {}).setdefault("gaps", [])
                artifact["metadata"]["gaps"].extend(density_gaps)
        artifact["metadata"]["resources_shown"] = shown
        artifact["metadata"]["resources_used"] = used
        artifact["metadata"]["resources_ignored"] = [r for r in shown if r not in used]
        return artifact

    async def _repair_low_density_artifact(
        self,
        *,
        client,
        model: str,
        system: str,
        tools: list[dict],
        messages: list[dict],
        artifact: dict,
        density_gaps: list[str],
        used_resources: list[str],
        shown_resources: list[str],
    ) -> dict:
        """Give the hand one chance to expand a thin artifact before it reaches UI."""
        repair_prompt = (
            "Your previous JSON artifact is too low-density for Loom's drill-down UI.\n"
            "Rewrite it as one JSON object using only the facts, tool results, and resource data already in this conversation.\n"
            "Do not invent missing data. If detail is unavailable, put the precise missing detail in metadata.gaps and the gaps section.\n"
            f"Density gaps to fix: {json.dumps(density_gaps, ensure_ascii=False)}\n"
            f"Resources shown: {json.dumps(shown_resources, ensure_ascii=False)}\n"
            f"Resources used: {json.dumps(used_resources, ensure_ascii=False)}\n"
            "Required minimums: 3-5 metadata.key_claims, at least 4 sections, at least 3 bullets per section, "
            "at least 5 evidence rows when data was available, and source_notes covering used resources.\n"
            "Keep narrative short for the visible card. Put expansion material in sections/evidence/source_notes.\n"
            "Return ONLY the corrected JSON object."
        )

        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                tools=tools,
                messages=messages + [{"role": "user", "content": repair_prompt}],
            )
        except Exception:
            return artifact

        if getattr(resp, "stop_reason", None) != "end_turn":
            return artifact

        final_text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                final_text = block.text
        candidate = self._parse_artifact(final_text)
        if self._density_score(candidate) > self._density_score(artifact):
            return candidate
        return artifact

    @staticmethod
    def _artifact_density_gaps(artifact: dict, used_resources: list[str], shown_resources: list[str]) -> list[str]:
        gaps: list[str] = []
        meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
        sections = artifact.get("sections", []) if isinstance(artifact, dict) else []
        evidence = artifact.get("evidence", []) if isinstance(artifact, dict) else []

        claims = meta.get("key_claims", []) or []
        if len(claims) < 3:
            gaps.append("Artifact density low: fewer than 3 key_claims returned")
        else:
            unsourced = [str(i) for i, c in enumerate(claims) if isinstance(c, dict) and not c.get("source")]
            if unsourced:
                gaps.append(f"Artifact quality: key_claims [{','.join(unsourced[:3])}] missing source annotation")
        if shown_resources and used_resources and len(meta.get("source_notes", []) or []) < min(3, len(used_resources)):
            gaps.append("Artifact density low: source_notes did not cover used resources")
        if len(sections or []) < 4:
            gaps.append("Artifact density low: fewer than 4 drill-down sections returned")
        else:
            sparse = [
                str(sec.get("id") or sec.get("title") or idx)
                for idx, sec in enumerate(sections)
                if isinstance(sec, dict) and len(sec.get("bullets", []) or []) < 3
            ]
            if sparse:
                gaps.append("Artifact density low: sparse section bullets in " + ", ".join(sparse[:4]))
        if used_resources and len(evidence or []) < 5:
            gaps.append("Artifact density low: fewer than 5 evidence rows returned despite resource usage")
        return gaps

    @staticmethod
    def _density_score(artifact: dict) -> int:
        if not isinstance(artifact, dict):
            return 0
        meta = artifact.get("metadata", {}) if isinstance(artifact.get("metadata", {}), dict) else {}
        sections = artifact.get("sections", []) if isinstance(artifact.get("sections", []), list) else []
        evidence = artifact.get("evidence", []) if isinstance(artifact.get("evidence", []), list) else []
        claims = meta.get("key_claims", []) or []
        score = min(len(claims), 3)
        score += 1 if any(isinstance(c, dict) and c.get("source") for c in claims) else 0
        score += min(len(meta.get("source_notes", []) or []), 3)
        score += min(len(sections), 4)
        score += min(
            sum(len(sec.get("bullets", []) or []) for sec in sections if isinstance(sec, dict)),
            12,
        )
        score += min(len(evidence), 5)
        return score

    @staticmethod
    def _normalize_artifact(data: dict) -> dict:
        """Normalize key_claims and section bullets to support both string and object formats.

        Strings → {"claim": <string>} so downstream always works with structured items.
        """
        meta = data.get("metadata", {})
        if isinstance(meta, dict):
            raw = meta.get("key_claims", [])
            if isinstance(raw, list):
                meta["key_claims"] = [
                    {"claim": item} if isinstance(item, str) else item
                    for item in raw
                ]
            source_notes = meta.get("source_notes", [])
            if isinstance(source_notes, list):
                for sn in source_notes:
                    if isinstance(sn, dict) and "tier" in sn and "source_tier" not in sn:
                        sn["source_tier"] = sn["tier"]
        sections = data.get("sections", [])
        if isinstance(sections, list):
            for sec in sections:
                if isinstance(sec, dict):
                    raw_bullets = sec.get("bullets", [])
                    if isinstance(raw_bullets, list):
                        sec["bullets"] = [
                            {"claim": b} if isinstance(b, str) else b
                            for b in raw_bullets
                        ]

        # ── layers ↔ sections backward-compat shim ────────────────────────
        has_layers = isinstance(data.get("layers"), list) and bool(data.get("layers"))
        has_sections = isinstance(data.get("sections"), list) and bool(data.get("sections"))

        _LAYER_TYPE_MAP = {
            "summary": "summary", "evidence": "evidence",
            "analysis": "analysis", "gaps": "gaps",
        }

        if has_layers and not has_sections:
            sections_from_layers: list[dict] = []
            evidence_from_layers: list[dict] = []
            for layer in data["layers"]:
                if not isinstance(layer, dict):
                    continue
                lt = layer.get("layer_type", "summary")
                if lt == "evidence":
                    evidence_from_layers.extend(layer.get("items") or [])
                else:
                    sections_from_layers.append({
                        "id": layer.get("layer_id") or lt,
                        "title": layer.get("title") or lt,
                        "summary": layer.get("summary") or "",
                        "bullets": [
                            {"claim": item} if isinstance(item, str) else item
                            for item in (layer.get("items") or [])
                        ],
                    })
            data["sections"] = sections_from_layers
            if evidence_from_layers and not data.get("evidence"):
                data["evidence"] = evidence_from_layers

        elif has_sections and not has_layers:
            layers_from_sections: list[dict] = []
            for sec in data.get("sections") or []:
                if not isinstance(sec, dict):
                    continue
                sid = sec.get("id") or ""
                lt = _LAYER_TYPE_MAP.get(sid, "summary")
                layers_from_sections.append({
                    "layer_id": sid or lt,
                    "layer_type": lt,
                    "title": sec.get("title") or sid,
                    "summary": sec.get("summary") or "",
                    "items": [
                        {"claim": b} if isinstance(b, str) else b
                        for b in (sec.get("bullets") or [])
                    ],
                })
            data["layers"] = layers_from_sections

        # ── raw defaults ──────────────────────────────────────────────────
        data.setdefault("raw_sources", [])
        data.setdefault("raw_items", [])

        return data

    @staticmethod
    def _parse_artifact(text: str) -> dict:
        """Extract structured artifact from LLM response. Falls back to wrapping plain text."""
        stripped = text.strip()

        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                data.setdefault("sections", [])
                data.setdefault("evidence", [])
                return BaseHand._normalize_artifact(data)
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            if "```json" in stripped:
                start = stripped.index("```json") + 7
                end = stripped.index("```", start)
                data = json.loads(stripped[start:end].strip())
                if isinstance(data, dict) and "metadata" in data and "narrative" in data:
                    data.setdefault("sections", [])
                    data.setdefault("evidence", [])
                    return BaseHand._normalize_artifact(data)
        except (ValueError, json.JSONDecodeError):
            pass

        return BaseHand._normalize_artifact({
            "metadata": {
                "confidence": 0.5,
                "gaps": ["LLM did not return structured JSON — raw text captured"],
                "key_claims": [],
            },
            "narrative": stripped or "(no output)",
            "sections": [
                {
                    "id": "raw",
                    "title": "Raw hand output",
                    "summary": "The hand did not return the structured artifact contract.",
                    "bullets": [{"claim": stripped or "(no output)"}],
                }
            ],
            "evidence": [],
        })
