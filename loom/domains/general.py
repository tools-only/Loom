"""LoomGeneralAdapter — domain-neutral defaults for non-finance Loom usage.

Used when WorkflowResolver classifies a question as "general".
Provides neutral output schemas and vocabulary — no buy/hold/reduce stance,
no finance-specific terminology.
"""

from __future__ import annotations
from pathlib import Path
from . import DomainAdapter

_ROOT = Path(__file__).parent.parent  # loom/


class LoomGeneralAdapter(DomainAdapter):
    domain_name = "general"

    assistant_branding = "Loom"

    # No stance — general tasks don't produce trading decisions
    stance_values = "n/a"
    stance_labels = {"n/a": "无明确立场"}
    stance_css_classes = {"n/a": "anc-pill--edit"}

    # No finance-specific synthesis fields
    synthesis_extra_fields = {}

    # Generic rubric examples
    plan_rubric_examples = [
        {"dimension": "综合分析", "requirements": "请根据问题维度组织分析"},
    ]
    review_coverage_example = {
        "综合分析": "covered|partial|missing",
    }

    # Canvas hand is domain-agnostic
    default_hands = {
        "canvas": {
            "label": "Canvas 协作",
            "description": "自由白板 co-design：生成、重排、连接内容卡片",
            "prompt": str(
                _ROOT.parent / "domains" / "loom-human-ag" / "hands" / "canvas" / "CLAUDE.md"
            ),
            "anchor_id": "canvas-root",
            "runtime": "canvas",
            "domains": ["general"],
            "wiki_dir": str(_ROOT.parent / "skills" / "canvas-codesign"),
            "config_schema": {},
            "preferred_resources": [],
        },
    }

    domain_keywords = ["general", "gen"]

    # No per-hand presentation specs — uses generic fallback
    hand_presentation_specs = {}

    # No domain-specific skill
    skill_path = ""
    personal_file_names = []
    context_snapshot_name = "snapshot.md"
