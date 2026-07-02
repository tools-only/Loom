"""LoomFinanceAdapter -- finance-domain configuration for Loom Brain.

All finance-specific prompts, labels, schemas, and seed hands live here.
The core Brain/harness code reads from this adapter when domain="finance".
"""

from __future__ import annotations
from pathlib import Path
from . import DomainAdapter


_ROOT = Path(__file__).parent.parent  # loom/


# Reuse provenance requirements from core_agent
_PROVENANCE = [
    "all information units require provenance, not only numerical data",
    "source",
    "source_tier",
    "freshness",
    "confidence",
    "claim/support separation",
    "mark derived interpretation as derived and identify the input it was derived from",
    "explicit gap when source is missing or stale",
]


class LoomFinanceAdapter(DomainAdapter):
    domain_name = "finance"

    # Identity
    assistant_branding = "Loom Fin"
    brain_role_contract_path = "brain_harness/prompts/brain.md"

    # Output schema vocabulary
    stance_values = "buy|hold|reduce|n/a"
    synthesis_extra_fields = {
        "regime_relevance": "why current regime makes this question weight unusual (<=10 chars)",
        "watch_conditions": "variables/events to monitor, 2-3 items, empty array if none",
        "priority_signal": "highest priority signal from this analysis, one line",
    }

    # Prompt examples
    plan_rubric_examples = [
        {"dimension": "macro aspects", "requirements": "rate, inflation, employment data"},
        {"dimension": "capital aspects", "requirements": "institution holdings, sector capital flow"},
    ]
    review_coverage_example = {
        "macro aspects": "covered|partial|missing",
        "capital aspects": "covered|partial|missing",
        "sentiment aspects": "covered|partial|missing",
    }

    # UI vocabulary
    stance_labels = {
        "buy": "Buy",
        "hold": "Hold",
        "reduce": "Reduce",
        "n/a": "N/A",
    }
    stance_css_classes = {
        "buy": "anc-pill--active",
        "hold": "anc-pill--review",
        "reduce": "anc-pill--warn",
        "n/a": "anc-pill--edit",
    }
    hand_titles = {
        "position": "Position",
    }

    # Seed hands
    default_hands = {
        "position": {
            "label": "Position Mgmt",
            "description": "Position report: exposure, cost, P&L, stops, concentration",
            "prompt": str(_ROOT / "hands" / "prompts" / "position.md"),
            "anchor_id": "loom-position",
            "runtime": "sdk",
            "domains": ["finance"],
            "wiki_dir": str(_ROOT.parent / "hands" / "position" / "wiki"),
            "config_schema": {
                "positions": {"type": "list", "label": "Position Data"},
                "risk_profile": {"type": "str", "label": "Risk Profile"},
            },
        },
    }

    # Domain routing
    domain_keywords = [
        "fin", "finance", "market", "sentiment", "target", "position",
    ]

    # Per-hand presentation specs
    hand_presentation_specs = {
        "position": {
            "visible_role": "portfolio and exposure implication",
            "detail_requirements": [
                "exposure concentration",
                "P/L and risk drivers",
                "sizing or review trigger",
                "action constraints",
            ],
            "evidence_requirements": [
                "position exposure",
                "risk concentration",
                "performance driver",
                "source freshness",
            ],
            "provenance_requirements": _PROVENANCE,
        },
    }

    # Hand harness personal context
    skill_path = "skills/investment-research-framework"
    personal_file_names = ["profile.md", "themes.md", "watchlist.md", "sources.md"]
    context_snapshot_name = "regime-snapshot.md"
