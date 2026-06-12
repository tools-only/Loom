"""WorkflowResolver - domain-aware state scope and executor discovery.

The resolver deliberately does not decide the task breakdown. It identifies a
broad domain, state scope, and executor shells available to Brain's planner.
Brain then derives dimensions/rubrics/tasks from state.
"""
from __future__ import annotations

import json
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
        return {
            "domain": domain,
            "mode": cfg.get("mode", "state_driven"),
            "state_scope": cfg.get("state_scope", [domain]),
            "rationale": rationale,
        }

    async def resolve(self, question: str, context: dict) -> dict:
        """Return {domain, mode, state_scope, rationale}."""
        merged = self._merged()

        hint = context.get("domain_hint", "")
        if hint and hint in merged:
            return self._materialize(hint, merged[hint], rationale=f"caller domain_hint={hint!r}")

        domain = await self._classify_llm(question, list(merged.keys()))
        cfg = merged.get(domain, merged.get("general", {"mode": "state_driven"}))
        return self._materialize(domain, cfg, rationale="LLM domain classification")

    async def _classify_llm(self, question: str, domains: list[str]) -> str:
        domains_str = ", ".join(f'"{d}"' for d in domains)
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=16,
            system=(
                "You classify user questions into broad state domains. "
                f"Valid domains: {domains_str}. "
                "Reply with ONLY the domain name, nothing else."
            ),
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(
            b.text for b in resp.content if hasattr(b, "text")
        ).strip().strip('"').lower()
        return text if text in domains else "general"
