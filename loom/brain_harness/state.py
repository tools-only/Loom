"""BrainState — structured, queryable Brain state.

Structural distinction from hand harness:
  Hand harness:  loads .md files wholesale → LLM decides relevance
  Brain harness: Brain process owns a queryable state store;
                 synthesize() calls query_rules() before the LLM sees anything.
                 Only matched entries reach the prompt.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class StrategyRule:
    rule_id: str
    condition: str
    action: str
    priority: int = 99
    domains: list[str] = field(default_factory=list)  # empty = all domains


@dataclass
class AnalyticalFramework:
    framework_id: str
    name: str
    key_variables: list[str]
    decision_logic: str
    weight_hints: dict[str, str]
    failure_conditions: list[str]
    confidence: str                 # high | medium | low | untested
    tags: list[str]
    distilled_at: str
    raw_excerpt: str = ""
    source_url: str | None = None
    source_author: str | None = None
    source_date: str | None = None


CONFIDENCE_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1, "untested": 0}


def _extract_variable_tokens(hand_claims: dict) -> set[str]:
    """Extract variable-like tokens from hand key_claims for framework matching.
    Accepts both string[] and {claim:str}[] formats.
    """
    tokens: set[str] = set()
    for claims in hand_claims.values():
        for claim in claims:
            text = claim if isinstance(claim, str) else (claim.get("claim", "") if isinstance(claim, dict) else "")
            # Uppercase abbreviations (VIX, M2, RRP, TGA, CPI) + snake_case vars
            tokens |= set(re.findall(r"[A-Z]{2,}|[a-z][a-z_]{2,}", text.lower()))
    return tokens


@dataclass
class LearnedNote:
    timestamp: str
    domain: str
    note: str
    tags: list[str] = field(default_factory=list)


# ── YAML front-matter parser (no external deps) ────────────────────────────────

def _coerce(s: str):
    s = s.strip().strip("\"'")
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML front-matter from strategy.md without external YAML library."""
    if not text.startswith("---"):
        return {}
    try:
        end = text.index("---", 3)
    except ValueError:
        return {}
    fm = text[3:end]
    result: dict = {}

    # Top-level scalar key: value
    for m in re.finditer(r"^(\w[\w_-]*):\s+(.+)$", fm, re.MULTILINE):
        key, val = m.group(1), m.group(2).strip()
        if not re.match(r"^[\w_-]+:\s", val):  # skip if it looks like a nested block header
            result[key] = _coerce(val)

    # weighting: block  (2-space indented)
    wm = re.search(r"^weighting:\s*\n((?:  \S.*\n?)+)", fm, re.MULTILINE)
    if wm:
        weighting: dict = {}
        for line in wm.group(1).splitlines():
            km = re.match(r"  (\w[\w_-]*):\s*(.*)", line)
            if km:
                weighting[km.group(1)] = _coerce(km.group(2))
        result["weighting"] = weighting

    # position_rules: list
    pm = re.search(r"^position_rules:\s*\n((?:  .*\n?)*)", fm, re.MULTILINE)
    if pm:
        rules: list[dict] = []
        current: dict = {}
        for line in pm.group(1).splitlines():
            lm = re.match(r"  - (\w[\w_-]*):\s*(.*)", line)
            if lm:
                if current:
                    rules.append(current)
                current = {lm.group(1): _coerce(lm.group(2))}
            else:
                cm = re.match(r"    (\w[\w_-]*):\s*(.*)", line)
                if cm and current is not None:
                    current[cm.group(1)] = _coerce(cm.group(2))
        if current:
            rules.append(current)
        result["position_rules"] = rules

    return result


# ── BrainState ─────────────────────────────────────────────────────────────────

class BrainState:
    """Structured Brain state — NOT loaded wholesale into LLM context.

    query_rules() and query_notes() run in the Brain process.
    Only matched entries are forwarded to the synthesis prompt.
    This is what separates Brain harness from hand harness structurally:
    the selection logic is Python code, not delegated to the LLM.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.default_style: str = "risk-adjusted"
        self.weighting: dict[str, float] = {}
        self._rules: list[StrategyRule] = []
        self._notes: list[LearnedNote] = []
        self._frameworks: list[AnalyticalFramework] = []
        self._state_version: int = 0
        self._reload()

    def get_state_version(self) -> int:
        return self._state_version

    def bump_state_version(self) -> int:
        self._state_version += 1
        return self._state_version

    # ── Loading ────────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        self._load_strategy()
        self._load_notes()
        self._load_frameworks()

    def _load_strategy(self) -> None:
        path = self.root / "brain" / "personal" / "strategy.md"
        if not path.exists():
            return
        fm = _parse_frontmatter(path.read_text("utf-8"))
        if not fm:
            return
        self.default_style = str(fm.get("default_style", "risk-adjusted"))
        self.weighting = {k: float(v) for k, v in fm.get("weighting", {}).items()}
        self._rules = [
            StrategyRule(
                rule_id=r.get("id", f"rule-{i}"),
                condition=str(r.get("condition", "")),
                action=str(r.get("action", "")),
                priority=int(r.get("priority", 99)),
                domains=list(r.get("domains", [])),
            )
            for i, r in enumerate(fm.get("position_rules", []))
            if isinstance(r, dict)
        ]

    def _load_notes(self) -> None:
        path = self.root / "brain" / "personal" / "learned-notes.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            self._notes = [
                LearnedNote(
                    timestamp=n.get("ts", ""),
                    domain=n.get("domain", "general"),
                    note=n.get("note", ""),
                    tags=n.get("tags", []),
                )
                for n in data
                if isinstance(n, dict)
            ]
        except (json.JSONDecodeError, ValueError):
            pass

    def _load_frameworks(self) -> None:
        path = self.root / "brain" / "personal" / "frameworks.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            self._frameworks = [
                AnalyticalFramework(
                    framework_id=f.get("framework_id", f"fw-{i}"),
                    name=f.get("name", ""),
                    key_variables=f.get("key_variables", []),
                    decision_logic=f.get("decision_logic", ""),
                    weight_hints=f.get("weight_hints", {}),
                    failure_conditions=f.get("failure_conditions", []),
                    confidence=f.get("confidence", "untested"),
                    tags=f.get("tags", []),
                    distilled_at=f.get("distilled_at", ""),
                    raw_excerpt=f.get("raw_excerpt", ""),
                    source_url=f.get("source_url"),
                    source_author=f.get("source_author"),
                    source_date=f.get("source_date"),
                )
                for i, f in enumerate(data)
                if isinstance(f, dict)
            ]
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Queries (Brain process, not LLM) ──────────────────────────────────────

    def query_rules(self, domain: str, question: str = "") -> list[StrategyRule]:
        """Return rules applicable to this domain, sorted by priority.

        Runs in the Brain process. Only matched rules reach the LLM prompt.
        Universal rules (empty domains list) always match.
        """
        matched = [
            r for r in self._rules
            if not r.domains or domain in r.domains
        ]
        matched.sort(key=lambda r: r.priority)
        return matched

    def query_notes(self, domain: str, n: int = 5) -> list[LearnedNote]:
        """Return n most recent notes for this domain (or domain='general')."""
        relevant = [note for note in self._notes if note.domain in (domain, "general")]
        return sorted(relevant, key=lambda x: x.timestamp, reverse=True)[:n]

    def query_frameworks(
        self,
        domain: str,
        hand_claims: dict[str, list[str]] | None = None,
        min_confidence: str = "medium",
    ) -> list[AnalyticalFramework]:
        """Return frameworks relevant to this domain + hand context.

        Three-gate filter (all must pass):
        1. Confidence >= min_confidence threshold
        2. Domain tag match (empty tags = universal)
        3. Variable overlap: framework.key_variables ∩ context tokens

        Runs in the Brain process. Only matched frameworks reach the LLM prompt.
        """
        threshold = CONFIDENCE_RANK.get(min_confidence, 0)
        ctx_vars = _extract_variable_tokens(hand_claims or {})

        matched: list[AnalyticalFramework] = []
        for fw in self._frameworks:
            # Gate 1: confidence
            if CONFIDENCE_RANK.get(fw.confidence, 0) < threshold:
                continue
            # Gate 2: domain tag (empty tags = universal)
            if fw.tags and domain not in fw.tags:
                continue
            # Gate 3: variable overlap (empty key_variables = always match)
            # Split snake_case vars into components: rrp_balance → {rrp, balance}
            fw_vars: set[str] = set()
            for v in fw.key_variables:
                fw_vars.update(p for p in re.split(r"[_\s]+", v.lower()) if len(p) >= 2)
            if fw_vars and not (fw_vars & ctx_vars):
                continue
            matched.append(fw)

        matched.sort(
            key=lambda f: (-CONFIDENCE_RANK.get(f.confidence, 0), f.distilled_at)
        )
        return matched

    # ── Mutations ─────────────────────────────────────────────────────────────

    def append_framework(self, fw_dict: dict) -> None:
        """Persist an accepted framework to frameworks.json and reload in-memory."""
        path = self.root / "brain" / "personal" / "frameworks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        # Deduplicate by framework_id
        fw_id = fw_dict.get("framework_id", "")
        existing = [f for f in existing if f.get("framework_id") != fw_id]
        existing.append(fw_dict)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        self._load_frameworks()
        self.bump_state_version()

    def append_note(self, domain: str, note: str, tags: list[str] | None = None) -> None:
        """Append a structured note to learned-notes.json."""
        path = self.root / "brain" / "personal" / "learned-notes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        existing.append({
            "ts": datetime.now().isoformat(),
            "domain": domain,
            "note": note,
            "tags": tags or [],
        })
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        self._load_notes()
        self.bump_state_version()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        return not self._rules and not self.weighting

    def format_rules(self, rules: list[StrategyRule]) -> str:
        """Compact text representation for LLM prompt injection."""
        lines = [
            f"  [{r.rule_id}] IF {r.condition} THEN {r.action} (priority={r.priority})"
            for r in rules
        ]
        return "\n".join(lines)

    def format_notes(self, notes: list[LearnedNote]) -> str:
        lines = [f"  [{n.timestamp[:10]}] ({n.domain}) {n.note}" for n in notes]
        return "\n".join(lines)

    def format_frameworks(self, frameworks: list[AnalyticalFramework]) -> str:
        """Format frameworks for LLM prompt injection — structured lens cards."""
        parts: list[str] = []
        for fw in frameworks:
            src = fw.source_author or fw.source_url or "unknown"
            date = fw.source_date or fw.distilled_at[:10]
            failure_text = "\n".join(f"  - {c}" for c in fw.failure_conditions) or "  (none specified)"
            vars_text = ", ".join(fw.key_variables) or "(none)"
            hints_text = "; ".join(f"{k}={v}" for k, v in fw.weight_hints.items()) if fw.weight_hints else ""
            card = (
                f"### {fw.name}  [{src} | {date} | confidence: {fw.confidence}]\n"
                f"variables: {vars_text}\n"
                f"logic: {fw.decision_logic}\n"
                + (f"weight hints: {hints_text}\n" if hints_text else "")
                + f"failure when:\n{failure_text}"
            )
            if fw.raw_excerpt:
                card += f"\nexcerpt: \"{fw.raw_excerpt[:200]}\""
            parts.append(card)
        return "\n\n".join(parts)
