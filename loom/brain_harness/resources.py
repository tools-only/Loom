"""Resource sidecar for rubric evaluation.

Resources captured by the user are durable evaluator material, not generation
prompt material. This registry keeps raw metadata and distilled strategy
primitives queryable so rubric compilation can become resource-aware without
inflating Brain context.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_TIER_RANK: dict[str, int] = {
    "A": 6,
    "B": 5,
    "C": 4,
    "D": 3,
    "E": 2,
    "F": 1,
    "G": 0,
}


@dataclass
class ResourceMetadata:
    resource_id: str
    domain: str
    kind: str
    title: str
    url: str = ""
    text: str = ""
    tags: list[str] = field(default_factory=list)
    source_platform: str = ""
    source_author: str = ""
    source_date: str = ""
    trust_tier: str = "F"
    user_signal: dict[str, Any] = field(default_factory=dict)
    market_scope: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    status: str = "captured"
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())


@dataclass
class StrategyPrimitive:
    primitive_id: str
    name: str
    domain: str
    hypothesis: str
    variables: list[str]
    triggers: list[str]
    invalidation: list[str]
    evidence_requirements: list[str]
    failure_modes: list[str]
    source_resource_ids: list[str]
    source_tier: str = "F"
    confidence: str = "untested"
    tags: list[str] = field(default_factory=list)
    status: str = "candidate"
    distilled_at: str = field(default_factory=lambda: _now())


class ResourceRegistry:
    """Append-friendly resource wiki and strategy primitive store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "brain" / "resource_wiki"
        self.resources_path = self.dir / "resources.json"
        self.strategy_path = self.dir / "strategy_primitives.json"

    def capture(self, payload: dict[str, Any]) -> ResourceMetadata:
        """Normalize and persist one resource metadata entry."""
        resource = self._normalize_resource(payload)
        resources = self._resources(include_channel=False)
        match_index = self._find_existing_resource(resources, resource)
        if match_index >= 0:
            existing = resources[match_index]
            resource.resource_id = str(existing.get("resource_id") or resource.resource_id)
            resource.created_at = str(existing.get("created_at") or resource.created_at)
            resources[match_index] = {**existing, **asdict(resource)}
        else:
            resources.insert(0, asdict(resource))
        self._write_json(self.resources_path, {"version": 1, "resources": resources})
        return resource

    def add_strategy_primitives(
        self,
        *,
        resource_id: str,
        frameworks: list[dict[str, Any]],
        domain: str = "",
        trust_tier: str = "",
    ) -> list[StrategyPrimitive]:
        """Mirror distilled framework candidates as evaluator-side primitives."""
        primitives = self._strategy_primitives()
        existing_by_id = {item.get("primitive_id"): item for item in primitives}
        created: list[StrategyPrimitive] = []
        for framework in frameworks:
            primitive = self._primitive_from_framework(
                resource_id=resource_id,
                framework=framework,
                domain=domain,
                trust_tier=trust_tier,
            )
            existing_by_id[primitive.primitive_id] = asdict(primitive)
            created.append(primitive)
        ordered = sorted(
            existing_by_id.values(),
            key=lambda item: str(item.get("distilled_at", "")),
            reverse=True,
        )
        self._write_json(self.strategy_path, {"version": 1, "strategy_primitives": ordered})
        return created

    def list_resources(self, *, include_channel: bool = True) -> list[dict[str, Any]]:
        return self._resources(include_channel=include_channel)

    def list_strategy_primitives(self) -> list[dict[str, Any]]:
        return self._strategy_primitives()

    def query_rubric_context(
        self,
        *,
        domain: str,
        question: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Return compact sidecar evidence for rubric compilation."""
        terms = _keywords(f"{domain} {question}")
        resources = self._ranked_resources(domain=domain, terms=terms, limit=limit)
        resource_ids = {str(item.get("resource_id")) for item in resources}
        primitives = self._ranked_primitives(
            domain=domain,
            terms=terms,
            resource_ids=resource_ids,
            limit=limit,
        )
        return {
            "version": 1,
            "domain": domain or "general",
            "query_terms": sorted(terms)[:16],
            "resources": resources,
            "strategy_primitives": primitives,
        }

    def _normalize_resource(self, payload: dict[str, Any]) -> ResourceMetadata:
        now = _now()
        url = _clean(payload.get("url"), 1000)
        title = _clean(payload.get("title") or payload.get("source") or url or "Captured resource", 180)
        text = _clean(payload.get("text") or payload.get("description") or payload.get("note") or title, 4000)
        tags = _tags(payload.get("tags"))
        domain = _clean(payload.get("domain") or _infer_domain(tags) or "general", 80)
        kind = _slug(payload.get("kind") or payload.get("resource_kind") or ("link" if url else "note"), "note")
        trust_tier = _tier(payload.get("trust_tier") or payload.get("tier"))
        content_hash = _hash_text("\n".join([url, title, text]))
        resource_id = _clean(payload.get("resource_id"), 120) or f"res_{content_hash[:16]}"
        user_signal = payload.get("user_signal") if isinstance(payload.get("user_signal"), dict) else {}
        if not user_signal:
            user_signal = {
                "intent_hint": _clean(payload.get("intent_hint"), 500),
                "saved_reason": _clean(payload.get("saved_reason") or payload.get("note"), 500),
                "value_signal": _clean(payload.get("value_signal") or payload.get("intent_hint"), 300),
            }
        market_scope = payload.get("market_scope") if isinstance(payload.get("market_scope"), dict) else {}
        return ResourceMetadata(
            resource_id=resource_id,
            domain=domain,
            kind=kind,
            title=title,
            url=url,
            text=text,
            tags=tags,
            source_platform=_clean(payload.get("source_platform") or payload.get("channel"), 80),
            source_author=_clean(payload.get("source_author") or payload.get("author") or payload.get("source"), 160),
            source_date=_clean(payload.get("source_date") or payload.get("published_at"), 80),
            trust_tier=trust_tier,
            user_signal={k: v for k, v in user_signal.items() if v},
            market_scope=market_scope,
            content_hash=content_hash,
            status=_clean(payload.get("status") or "captured", 40),
            created_at=_clean(payload.get("created_at"), 80) or now,
            updated_at=now,
        )

    def _primitive_from_framework(
        self,
        *,
        resource_id: str,
        framework: dict[str, Any],
        domain: str,
        trust_tier: str,
    ) -> StrategyPrimitive:
        framework_id = str(framework.get("framework_id") or framework.get("name") or "")
        primitive_id = "sp_" + _hash_text(f"{resource_id}:{framework_id}")[:16]
        variables = _string_list(framework.get("key_variables") or framework.get("variables"))
        failure_conditions = _string_list(
            framework.get("failure_conditions")
            or framework.get("invalidation")
            or framework.get("failure_modes")
        )
        evidence = _string_list(framework.get("evidence_requirements"))
        if not evidence:
            evidence = [f"Verify {var}" for var in variables[:4]]
        return StrategyPrimitive(
            primitive_id=primitive_id,
            name=_clean(framework.get("name") or "Distilled strategy primitive", 180),
            domain=_clean(domain or _infer_domain(_tags(framework.get("tags"))) or "general", 80),
            hypothesis=_clean(
                framework.get("hypothesis") or framework.get("decision_logic") or framework.get("raw_excerpt"),
                1000,
            ),
            variables=variables,
            triggers=_string_list(framework.get("triggers") or framework.get("weight_hints")),
            invalidation=failure_conditions,
            evidence_requirements=evidence,
            failure_modes=failure_conditions,
            source_resource_ids=[resource_id] if resource_id else [],
            source_tier=_tier(trust_tier or framework.get("trust_tier")),
            confidence=_clean(framework.get("confidence") or "untested", 40),
            tags=_tags(framework.get("tags")),
            status=_clean(framework.get("status") or "candidate", 40),
            distilled_at=_clean(framework.get("distilled_at"), 80) or _now(),
        )

    def _ranked_resources(self, *, domain: str, terms: set[str], limit: int) -> list[dict[str, Any]]:
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._resources(include_channel=True):
            score = _resource_score(item, domain=domain, terms=terms)
            if score <= 0:
                continue
            scored.append((score, _compact_resource(item)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _ranked_primitives(
        self,
        *,
        domain: str,
        terms: set[str],
        resource_ids: set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._strategy_primitives():
            score = _primitive_score(item, domain=domain, terms=terms, resource_ids=resource_ids)
            if score <= 0:
                continue
            scored.append((score, _compact_primitive(item)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _resources(self, *, include_channel: bool) -> list[dict[str, Any]]:
        own = self._read_json(self.resources_path, {"resources": []}).get("resources", [])
        resources = [item for item in own if isinstance(item, dict)]
        if include_channel:
            resources.extend(self._channel_resources())
        deduped: dict[str, dict[str, Any]] = {}
        for item in resources:
            key = str(item.get("resource_id") or item.get("content_hash") or item.get("url") or "")
            if not key:
                continue
            deduped[key] = {**deduped.get(key, {}), **item}
        return list(deduped.values())

    def _channel_resources(self) -> list[dict[str, Any]]:
        path = self.root / "logs" / "workspace" / "channel-resources.json"
        data = self._read_json(path, {"resources": []})
        out: list[dict[str, Any]] = []
        for item in data.get("resources", []):
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_resource({
                "resource_id": item.get("resource_id"),
                "domain": item.get("domain") or _infer_domain(_tags(item.get("tags"))),
                "kind": item.get("resource_kind"),
                "title": item.get("title"),
                "url": item.get("url"),
                "text": item.get("text") or item.get("description"),
                "tags": item.get("tags"),
                "source_platform": item.get("channel"),
                "source_author": item.get("source"),
                "trust_tier": item.get("trust_tier"),
                "intent_hint": item.get("intent_hint"),
                "value_signal": item.get("value_signal"),
                "created_at": item.get("created_at"),
                "status": "channel_resource",
            })
            out.append(asdict(normalized))
        return out

    def _strategy_primitives(self) -> list[dict[str, Any]]:
        data = self._read_json(self.strategy_path, {"strategy_primitives": []})
        return [item for item in data.get("strategy_primitives", []) if isinstance(item, dict)]

    @staticmethod
    def _find_existing_resource(resources: list[dict[str, Any]], resource: ResourceMetadata) -> int:
        for index, item in enumerate(resources):
            if item.get("resource_id") == resource.resource_id:
                return index
            if resource.url and item.get("url") == resource.url:
                return index
            if item.get("content_hash") == resource.content_hash:
                return index
        return -1

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return default
        return data if isinstance(data, dict) else default

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _resource_score(item: dict[str, Any], *, domain: str, terms: set[str]) -> float:
    text = " ".join(
        str(item.get(key, ""))
        for key in ("title", "url", "text", "source_author", "source_platform")
    )
    text += " " + " ".join(_string_list(item.get("tags")))
    item_terms = _keywords(text)
    overlap = len(terms & item_terms)
    domain_bonus = 1.0 if _domain_match(item.get("domain"), domain, item.get("tags")) else 0.0
    if overlap == 0 and domain_bonus == 0.0 and not item.get("user_signal"):
        return 0.0
    tier_bonus = SOURCE_TIER_RANK.get(_tier(item.get("trust_tier")), 1) / 6
    signal_bonus = 0.4 if item.get("user_signal") else 0.0
    return overlap + domain_bonus + tier_bonus + signal_bonus


def _primitive_score(
    item: dict[str, Any],
    *,
    domain: str,
    terms: set[str],
    resource_ids: set[str],
) -> float:
    text = " ".join(
        str(item.get(key, ""))
        for key in ("name", "hypothesis", "confidence", "source_tier")
    )
    for key in ("variables", "triggers", "invalidation", "evidence_requirements", "failure_modes", "tags"):
        text += " " + " ".join(_string_list(item.get(key)))
    item_terms = _keywords(text)
    linked = len(resource_ids & set(_string_list(item.get("source_resource_ids"))))
    overlap = len(terms & item_terms)
    domain_bonus = 1.0 if _domain_match(item.get("domain"), domain, item.get("tags")) else 0.0
    if overlap == 0 and linked == 0 and domain_bonus == 0.0:
        return 0.0
    tier_bonus = SOURCE_TIER_RANK.get(_tier(item.get("source_tier")), 1) / 6
    return overlap + linked + domain_bonus + tier_bonus


def _compact_resource(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": item.get("resource_id", ""),
        "domain": item.get("domain", "general"),
        "kind": item.get("kind", item.get("resource_kind", "")),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "tags": _string_list(item.get("tags"))[:8],
        "source_platform": item.get("source_platform", item.get("channel", "")),
        "source_author": item.get("source_author", item.get("source", "")),
        "source_date": item.get("source_date", ""),
        "trust_tier": _tier(item.get("trust_tier")),
        "user_signal": item.get("user_signal", {}),
    }


def _compact_primitive(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "primitive_id": item.get("primitive_id", ""),
        "name": item.get("name", ""),
        "domain": item.get("domain", "general"),
        "hypothesis": item.get("hypothesis", ""),
        "variables": _string_list(item.get("variables"))[:8],
        "triggers": _string_list(item.get("triggers"))[:6],
        "invalidation": _string_list(item.get("invalidation"))[:6],
        "evidence_requirements": _string_list(item.get("evidence_requirements"))[:6],
        "source_resource_ids": _string_list(item.get("source_resource_ids"))[:8],
        "source_tier": _tier(item.get("source_tier")),
        "confidence": item.get("confidence", "untested"),
        "tags": _string_list(item.get("tags"))[:8],
    }


def _domain_match(value: Any, domain: str, tags: Any = None) -> bool:
    wanted = str(domain or "general").lower()
    if wanted in ("", "general"):
        return True
    candidates = {str(value or "").lower(), *[tag.lower() for tag in _string_list(tags)]}
    if wanted in candidates:
        return True
    if wanted == "finance" and "loom-fin" in candidates:
        return True
    if wanted == "loom-fin" and "finance" in candidates:
        return True
    return False


def _infer_domain(tags: list[str]) -> str:
    lowered = {tag.lower() for tag in tags}
    if "loom-fin" in lowered:
        return "loom-fin"
    if lowered & {"finance", "market", "equities", "stock", "macro"}:
        return "finance"
    return ""


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]{2,}", str(text).lower())
    stop = {"the", "and", "for", "with", "this", "that", "from", "into", "user", "resource"}
    return {word for word in words if word not in stop}


def _tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    out: list[str] = []
    for item in raw:
        tag = _slug(item, "")
        if tag and tag not in out:
            out.append(tag)
        if len(out) >= 16:
            break
    return out


def _string_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [f"{k}: {v}" for k, v in value.items()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _tier(value: Any) -> str:
    tier = str(value or "").strip().upper()
    return tier if tier in SOURCE_TIER_RANK else "F"


def _slug(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff_-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:80] or fallback


def _clean(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ResourceMetadata",
    "ResourceRegistry",
    "StrategyPrimitive",
    "SOURCE_TIER_RANK",
]
