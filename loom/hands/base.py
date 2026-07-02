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
import urllib.parse
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

        # Domain adapter config injected by brain.py _brain_hand_runner
        domain_cfg = context.get("_domain_adapter_config", {}) or {}

        # Skill index
        skill_path = domain_cfg.get("skill_path") or "skills/investment-research-framework"
        skill_md = ROOT / skill_path / "SKILL.md" if skill_path else None
        if skill_md and skill_md.exists():
            parts.append("\n\n# Skill Index\n\n")
            parts.append(skill_md.read_text("utf-8"))
        elif not domain_cfg:  # backward compat
            fallback = ROOT / "skills" / "investment-research-framework" / "SKILL.md"
            if fallback.exists():
                parts.append("\n\n# Investment Research Framework (skill index)\n\n")
                parts.append(fallback.read_text("utf-8"))

        # Personal context files
        personal_dir = ROOT / "hands" / self.hand_id / "personal"
        fnames = domain_cfg.get("personal_file_names") or ["profile.md", "themes.md", "watchlist.md", "sources.md"]
        for fname in fnames:
            p = personal_dir / fname
            if p.exists() and p.stat().st_size > 0:
                parts.append(f"\n\n## (personal) {fname}\n\n{p.read_text('utf-8')}")

        notes = personal_dir / "learned-notes.md"
        if notes.exists() and notes.stat().st_size > 0:
            txt = notes.read_text("utf-8")
            parts.append(f"\n\n## (personal) learned-notes (tail)\n\n{txt[-4000:]}")

        # Context snapshot
        snap_name = domain_cfg.get("context_snapshot_name") or "regime-snapshot.md"
        snap = ROOT / "hands" / self.hand_id / "context" / snap_name
        if snap.exists() and (time.time() - snap.stat().st_mtime) < 86400:
            parts.append(f"\n\n## (context) {snap_name}\n\n{snap.read_text('utf-8')}")

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
        raw_sources: list[dict] = []
        depth = context.get("depth", "normal") if isinstance(context, dict) else "normal"

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
            '      {"claim":"specific claim","source":"FRED 30Y","tier":"A","freshness":"2026-06-09","rubric":"宏观面"},\n'
            '      {"claim":"another claim","source":"Reuters","tier":"C","freshness":"2026-06-08"}\n'
            '    ],\n'
            '    "gaps": ["missing/stale data"],\n'
            '    "source_notes": [{"source":"...", "tier":"A|B|C|D|E|F|G|unknown", "freshness":"...", "note":"..."}]\n'
            "  },\n"
            '  "narrative": "2-4 sentence high-level judgment for the visible Loom card.",\n'
            '  "layers": [\n'
            '    {"layer_id":"summary",  "layer_type":"summary",  "title":"High-level judgment",  "summary":"...", "items":[{"claim":"sourced bullet","source":"FRED","tier":"A"}]},\n'
            '    {"layer_id":"evidence", "layer_type":"evidence", "title":"Evidence and data",     "summary":"...", "items":[{"claim":"...","support":"...","source":"...","source_tier":"A","freshness":"..."}]},\n'
            '    {"layer_id":"analysis", "layer_type":"analysis", "title":"Detailed analysis",     "summary":"...", "items":[{"claim":"...","source":"...","tier":"B"}]},\n'
            '    {"layer_id":"gaps",     "layer_type":"gaps",     "title":"Coverage gaps",         "summary":"...", "items":[{"claim":"gap description"}]}\n'
            "  ],\n"
            '  "raw_items": [\n'
            '    {"item_type":"data_point","label":"10Y Treasury","value":"4.52%","source":"FRED","tier":"A","freshness":"2026-06-10","relevance":"rate regime anchor"},\n'
            '    {"item_type":"news","title":"Fed holds rates","source":"Reuters","tier":"C","published_at":"2026-06-10","summary":"首句摘要","relevance":"regime signal","url":"https://reuters.com/article/fed-2026-06-10"},\n'
            '    {"item_type":"tweet","author":"@handle","text":"原文","source":"web_search","tier":"E","published_at":"","relevance":"sentiment signal"},\n'
            '    {"item_type":"search_snippet","title":"标题","summary":"snippet","source":"web_search","tier":"C","published_at":"","relevance":"context"}\n'
            "  ]\n"
            "}\n"
            "Information density by level (L0-L3, from surface to raw):\n"
            "  L3 — Overview (narrative + key_claims): 2-4 sentence narrative, 3-5 sourced claims with source+tier.\n"
            "  L2 — Analysis (layers/sections): at least 4 layers (summary/analysis/gaps), each with summary plus at least 3 items.\n"
            "       source_notes: at least 3 covering used resources.\n"
            "  L1 — Evidence (evidence[]): at least 5 rows when data available, each with claim/support/source/source_tier/freshness.\n"
            "  L0 — Raw data (raw_items[]): at least 5 entries covering sources; data_point must have value; all entries must have relevance and a populated url field (clickable link).\n"
            "Optional: tag key_claims, evidence rows, and layer items with a `rubric` field "
            "(dimension name matching Brain analysis rubrics) for cross-referencing.\n"
            "The visible L3 narrative must be short. Put deeper support in L2-L0 layers."
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
                        import datetime as _dt
                        raw_sources.append({
                            "resource_id": rid,
                            "fetched_at": _dt.datetime.utcnow().isoformat() + "Z",
                            "content_type": "json",
                            "summary": BaseHand._summarize_raw(data),
                            "raw": data,
                        })
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
                        import datetime as _dt
                        raw_sources.append({
                            "resource_id": "fetch_url",
                            "url": url,
                            "fetched_at": _dt.datetime.utcnow().isoformat() + "Z",
                            "content_type": "html",
                            "summary": BaseHand._summarize_raw(content),
                            "raw": content,
                        })
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

        # Capture web_search queries by companion fetch to preserve source metadata
        import datetime as _dt2
        seen_queries = set()
        for msg in messages:
            content = msg.get("content") if isinstance(msg, dict) else []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "web_search":
                        q = (block.get("input") or {}).get("query", "")
                        if q and q not in seen_queries:
                            seen_queries.add(q)
                            search_url = f"https://www.google.com/search?q={urllib.parse.quote(q)}"
                            search_content = await _fetch_url(search_url)
                            raw_sources.append({
                                "resource_id": "web_search",
                                "url": search_url,
                                "query": q,
                                "fetched_at": _dt2.datetime.utcnow().isoformat() + "Z",
                                "content_type": "search_results",
                                "summary": BaseHand._summarize_raw(search_content),
                                "raw": search_content,
                            })

        artifact = self._parse_artifact(final_text)
        artifact["raw_sources"] = raw_sources
        density_gaps = self._artifact_density_gaps(artifact, used, shown, depth=depth)
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
            density_gaps = self._artifact_density_gaps(artifact, used, shown, depth=depth)
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
            "L0-L3 density targets:\n"
            "  L3: 3-5 key_claims, narrative of 2+ sentences\n"
            "  L2: at least 4 sections, at least 3 bullets per section, source_notes covering used resources\n"
            "  L1: at least 5 evidence rows when data was available\n"
            "  L0: at least 5 raw_items when data was available\n"
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
    def _artifact_density_gaps(artifact: dict, used_resources: list[str], shown_resources: list[str], depth: str = "normal") -> list[str]:
        gaps: list[str] = []
        meta = artifact.get("metadata", {}) if isinstance(artifact, dict) else {}
        sections = artifact.get("sections", []) if isinstance(artifact, dict) else []
        evidence = artifact.get("evidence", []) if isinstance(artifact, dict) else []

        # Depth-aware thresholds
        _thresh = {"deep": {"claims": 5, "sections": 6, "bullets": 4, "evidence": 8, "raw_items": 10, "source_notes": 4},
                   "normal": {"claims": 3, "sections": 4, "bullets": 3, "evidence": 5, "raw_items": 5, "source_notes": 3},
                   "light":  {"claims": 2, "sections": 3, "bullets": 2, "evidence": 3, "raw_items": 3, "source_notes": 2}}
        t = _thresh.get(depth, _thresh["normal"])

        # L3: Overview density (narrative + key_claims)
        claims = meta.get("key_claims", []) or []
        if len(claims) < t["claims"]:
            gaps.append(f"L3 density low: fewer than {t['claims']} key_claims")
        else:
            unsourced = [str(i) for i, c in enumerate(claims) if isinstance(c, dict) and not c.get("source")]
            if unsourced:
                gaps.append(f"L3 quality: key_claims [{','.join(unsourced[:3])}] missing source annotation")
        if not artifact.get("narrative"):
            gaps.append("L3 density low: narrative is missing")

        # L2: Analysis density (sections + source_notes)
        if shown_resources and used_resources and len(meta.get("source_notes", []) or []) < min(t["source_notes"], len(used_resources)):
            gaps.append("L2 density low: source_notes did not cover used resources")
        if len(sections or []) < t["sections"]:
            gaps.append(f"L2 density low: fewer than {t['sections']} drill-down sections")
        else:
            sparse = [
                str(sec.get("id") or sec.get("title") or idx)
                for idx, sec in enumerate(sections)
                if isinstance(sec, dict) and len(sec.get("bullets", []) or []) < t["bullets"]
            ]
            if sparse:
                gaps.append(f"L2 density low: sparse section bullets (min {t['bullets']} each) in " + ", ".join(sparse[:4]))

        # L1: Evidence density
        if used_resources and len(evidence or []) < t["evidence"]:
            gaps.append(f"L1 density low: fewer than {t['evidence']} evidence rows despite resource usage")

        # L0: Raw data density
        raw_items = artifact.get("raw_items", []) or []
        if used_resources and len(raw_items) < t["raw_items"]:
            gaps.append(f"L0 density low: fewer than {t['raw_items']} annotated raw items despite resource usage")
        elif raw_items:
            urlless = [i for i in raw_items if not i.get("url")]
            if len(urlless) / len(raw_items) > 0.5:
                gaps.append("L0 quality: more than 50% of raw_items missing url field")
        return gaps

    @staticmethod
    def _density_score(artifact: dict) -> int:
        if not isinstance(artifact, dict):
            return 0
        meta = artifact.get("metadata", {}) if isinstance(artifact.get("metadata", {}), dict) else {}
        sections = artifact.get("sections", []) if isinstance(artifact.get("sections", []), list) else []
        evidence = artifact.get("evidence", []) if isinstance(artifact.get("evidence", []), list) else []
        claims = meta.get("key_claims", []) or []
        # L3: narrative + claims
        score = (3 if artifact.get("narrative") else 0)
        score += min(len(claims), 5) * 2
        # L2: sections weighted highest (carry analytical value)
        score += min(len(sections), 6) * 3
        score += min(len(meta.get("source_notes", []) or []), 3)
        score += min(
            sum(len(sec.get("bullets", []) or []) for sec in sections if isinstance(sec, dict)),
            12,
        )
        # L1: evidence
        score += min(len(evidence), 8) * 2
        # L0: raw_items bonus
        score += min(len(artifact.get("raw_items", []) or []), 8)
        return score

    @staticmethod
    def _summarize_raw(data) -> str:
        text = (
            json.dumps(data, ensure_ascii=False)
            if not isinstance(data, str)
            else data
        )
        return text[:200].rstrip() + ("…" if len(text) > 200 else "")

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
