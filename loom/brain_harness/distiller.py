"""ResourceDistiller — offline distillation of external resources into AnalyticalFramework primitives.

This is a separate LLM call from synthesize():
  - synthesize(): online, per-question, combines hand key_claims × strategy rules × frameworks
  - distill():   offline, per-resource, extracts durable analytical architecture

The distillation output is structured data (framework primitives), not prompt material.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


class ResourceDistiller:
    def __init__(self, project_root: Path, client, model: str) -> None:
        self.root = Path(project_root)
        self._client = client
        self._model = model
        self._system: str = self._load_system()

    def _load_system(self) -> str:
        p = self.root / "loom" / "brain_harness" / "prompts" / "distiller.md"
        return p.read_text("utf-8") if p.exists() else "Extract analytical frameworks from this resource."

    async def distill(
        self,
        text: str,
        source_url: str | None = None,
        source_author: str | None = None,
        source_date: str | None = None,
    ) -> list[dict]:
        """Distill a resource text into AnalyticalFramework candidates.

        Returns a list of framework dicts (not yet persisted — caller presents
        to user for accept/edit/reject before writing to frameworks.json).
        """
        user_msg = f"Resource to distill:\n\n{text[:12000]}"

        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=self._system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

        candidates = self._parse_frameworks(raw)
        now = datetime.now().isoformat()

        # Stamp metadata onto each candidate
        for i, fw in enumerate(candidates):
            fw.setdefault("confidence", "untested")
            fw.setdefault("tags", [])
            fw.setdefault("key_variables", [])
            fw.setdefault("weight_hints", {})
            fw.setdefault("failure_conditions", [])
            fw.setdefault("raw_excerpt", "")
            fw["framework_id"] = f"fw-{now[:10]}-{i:02d}"
            fw["distilled_at"] = now
            fw["source_url"] = source_url
            fw["source_author"] = source_author
            fw["source_date"] = source_date

        return candidates

    @staticmethod
    def _parse_frameworks(text: str) -> list[dict]:
        """Parse JSON array from LLM response, with markdown fence fallback."""
        stripped = text.strip()
        # Try direct
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except (json.JSONDecodeError, ValueError):
            pass
        # Markdown fence
        for fence in ("```json", "```"):
            if fence in stripped:
                try:
                    start = stripped.index(fence) + len(fence)
                    end = stripped.index("```", start)
                    data = json.loads(stripped[start:end].strip())
                    if isinstance(data, list):
                        return [d for d in data if isinstance(d, dict)]
                except (ValueError, json.JSONDecodeError):
                    pass
        return []
