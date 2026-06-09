"""WorkflowResolver — domain-aware hand dispatch strategy.

Priority order for domain resolution:
  1. context["domain_hint"]  — caller-provided, skips all inference
  2. Keyword match           — cheap regex scan over workflows
  3. LLM classification      — one cheap LLM call as fallback
"""
from __future__ import annotations

import json
import re
from pathlib import Path



class WorkflowResolver:
    def __init__(self, project_root: Path, registry: dict, client, model: str):
        self._root = Path(project_root)
        self._registry = registry
        self._client = client
        self._model = model
        self._builtin: dict = json.loads(
            (self._root / "loom" / "brain_harness" / "workflows.json").read_text("utf-8")
        )

    def _load_user_overrides(self) -> dict:
        """Load user workflow overrides from brain/personal/workflows.json."""
        path = self._root / "brain" / "personal" / "workflows.json"
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _merged(self) -> dict:
        return {**self._builtin, **self._load_user_overrides()}

    def _materialize(self, domain: str, cfg: dict, rationale: str) -> dict:
        mode = cfg.get("mode", "dynamic")
        if mode == "full_fanout":
            hands = cfg.get("hands") or [
                hid for hid, info in self._registry.items()
                if domain in info.get("domains", [])
            ]
        else:
            hands = cfg.get("hands_pool") or list(self._registry.keys())
        return {
            "domain": domain,
            "mode": mode,
            "hands": [h for h in hands if h in self._registry],
            "rationale": rationale,
        }

    async def resolve(self, question: str, context: dict) -> dict:
        """Return {domain, mode, hands, rationale}."""
        merged = self._merged()

        # 1. Explicit hint
        hint = context.get("domain_hint", "")
        if hint and hint in merged:
            return self._materialize(hint, merged[hint], rationale=f"caller domain_hint={hint!r}")

        # 2. Keyword match
        for domain, cfg in merged.items():
            for kw in cfg.get("trigger_keywords", []):
                if re.search(kw, question, re.IGNORECASE):
                    return self._materialize(
                        domain, cfg, rationale=f"keyword match: {kw!r}"
                    )

        # 3. Explicit hand list in context
        if context.get("hands"):
            hands = [h for h in context["hands"] if h in self._registry]
            if hands:
                return {
                    "domain": "explicit",
                    "mode": "explicit",
                    "hands": hands,
                    "rationale": "caller-provided hand list",
                }

        # 4. LLM classification
        domain = await self._classify_llm(question, list(merged.keys()))
        cfg = merged.get(domain, merged.get("general", {"mode": "dynamic"}))
        return self._materialize(domain, cfg, rationale="LLM domain classification")

    async def _classify_llm(self, question: str, domains: list[str]) -> str:
        domains_str = ", ".join(f'"{d}"' for d in domains)
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=16,
            system=(
                "You classify user questions into task domains. "
                f"Valid domains: {domains_str}. "
                "Reply with ONLY the domain name, nothing else."
            ),
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(
            b.text for b in resp.content if hasattr(b, "text")
        ).strip().strip('"').lower()
        return text if text in domains else "general"
