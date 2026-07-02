"""DomainAdapter layer — pluggable domain-specific configuration for Loom Brain.

Each domain (finance, general, etc.) provides a DomainAdapter declaring:
  - Output schema vocabulary (stance values, synthesis fields)
  - Prompt examples (plan rubrics, review coverage)
  - UI vocabulary (stance labels, CSS classes, hand titles)
  - Seed hands to bootstrap at startup
  - Domain routing keywords

These are declarative data, not behavior interfaces. DomainAdapters can be
serialized to JSON and loaded without code changes.
"""

from __future__ import annotations


class DomainAdapter:
    """Declarative configuration for a Loom domain.

    All fields are optional — callers fall back to neutral defaults when absent.
    """

    domain_name: str = "general"

    # ── Identity ──────────────────────────────────────────────────────────
    assistant_branding: str = "Loom"       # e.g. "Loom Fin"
    brain_role_contract_path: str = ""     # override brain.md path (relative to loom/)

    # ── Output schema vocabulary ──────────────────────────────────────────
    stance_values: str = "n/a"             # e.g. "buy|hold|reduce|n/a"
    synthesis_extra_fields: dict[str, str] = {}  # {field_name: inline_description}

    # ── Prompt examples (injected into plan/review user messages) ─────────
    plan_rubric_examples: list[dict] = []
    review_coverage_example: dict[str, str] = {}

    # ── UI vocabulary ─────────────────────────────────────────────────────
    stance_labels: dict[str, str] = {}
    stance_css_classes: dict[str, str] = {}
    default_stance_css_class: str = "anc-pill--edit"
    hand_titles: dict[str, str] = {}

    # ── Seed hands ────────────────────────────────────────────────────────
    default_hands: dict[str, dict] = {}    # hand_id → REGISTRY entry

    # ── Domain routing ────────────────────────────────────────────────────
    domain_keywords: list[str] = []

    # ── Per-hand presentation specs (for core_agent UI rendering) ─────────
    hand_presentation_specs: dict[str, dict] = {}

    # ── Hand harness personal context ─────────────────────────────────────
    skill_path: str = ""                   # relative to project root, e.g. "skills/..."
    personal_file_names: list[str] = []    # files under personal/
    context_snapshot_name: str = "snapshot.md"


class DomainRegistry:
    """Registry of DomainAdapters, keyed by domain name."""

    def __init__(self, default_domain: str = "general") -> None:
        self._adapters: dict[str, DomainAdapter] = {}
        self._default = default_domain

    def register(self, adapter: DomainAdapter) -> None:
        self._adapters[adapter.domain_name] = adapter
        if self._default not in self._adapters:
            self._default = adapter.domain_name

    def get(self, domain: str) -> DomainAdapter:
        return self._adapters.get(domain) or self._adapters.get(self._default, DomainAdapter())

    @property
    def default_adapter(self) -> DomainAdapter:
        return self.get(self._default)

    def keywords_to_domain(self, keyword: str) -> str:
        for name, adapter in self._adapters.items():
            if keyword.lower() in (adapter.domain_keywords or []):
                return name
        return ""
