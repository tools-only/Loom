"""GoalContext — per-goal accumulating context for BrainStateEngine (L4).

Persistence: one JSON file per goal at brain/goal_context/<goal_id>.json
Each file is a self-contained snapshot of a research goal's lifecycle.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


GoalType = Literal["market_research", "position_review", "target_tracking", "ad_hoc"]
GoalStatus = Literal["open", "investigating", "concluded"]


@dataclass
class Finding:
    finding_id: str
    claim: str
    hand_id: str
    confidence: float
    ts: str
    episode_id: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class SynthesisSnapshot:
    episode_id: str
    ts: str
    stance: str
    confidence: float
    key_drivers: list[str] = field(default_factory=list)
    reversal_condition: str = ""


@dataclass
class Contradiction:
    episode_id: str
    ts: str
    hand_a: str
    hand_b: str
    description: str
    resolved: bool = False


@dataclass
class GoalContext:
    goal_id: str
    goal_type: GoalType
    created_at: str
    updated_at: str
    status: GoalStatus = "open"
    title: str = ""
    context_summary: str = ""
    key_findings: list[Finding] = field(default_factory=list)
    synthesis_history: list[SynthesisSnapshot] = field(default_factory=list)
    contradiction_log: list[Contradiction] = field(default_factory=list)
    episode_ids: list[str] = field(default_factory=list)

    @staticmethod
    def new(goal_type: GoalType = "ad_hoc", title: str = "") -> "GoalContext":
        now = _now()
        return GoalContext(
            goal_id=f"goal-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
            goal_type=goal_type,
            created_at=now,
            updated_at=now,
            title=title,
        )

    def record_episode(self, episode_id: str) -> None:
        if episode_id and episode_id not in self.episode_ids:
            self.episode_ids.append(episode_id)
        self.updated_at = _now()

    def upsert_finding(self, finding: Finding) -> None:
        existing = next((f for f in self.key_findings if f.finding_id == finding.finding_id), None)
        if existing:
            idx = self.key_findings.index(existing)
            self.key_findings[idx] = finding
        else:
            self.key_findings.append(finding)
        self.updated_at = _now()

    def append_synthesis(self, snapshot: SynthesisSnapshot) -> None:
        self.synthesis_history.append(snapshot)
        # Keep last 20 to bound file size
        if len(self.synthesis_history) > 20:
            self.synthesis_history = self.synthesis_history[-20:]
        self.updated_at = _now()

    def log_contradiction(self, contradiction: Contradiction) -> None:
        self.contradiction_log.append(contradiction)
        self.updated_at = _now()

    def conclude(self, summary: str = "") -> None:
        self.status = "concluded"
        if summary:
            self.context_summary = summary
        self.updated_at = _now()

    def latest_stance(self) -> str:
        if self.synthesis_history:
            return self.synthesis_history[-1].stance
        return "n/a"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "GoalContext":
        key_findings = [Finding(**f) for f in d.pop("key_findings", [])]
        synthesis_history = [SynthesisSnapshot(**s) for s in d.pop("synthesis_history", [])]
        contradiction_log = [Contradiction(**c) for c in d.pop("contradiction_log", [])]
        return GoalContext(
            **d,
            key_findings=key_findings,
            synthesis_history=synthesis_history,
            contradiction_log=contradiction_log,
        )


class GoalContextStore:
    """CRUD store for GoalContext objects backed by JSON files."""

    def __init__(self, root: Path) -> None:
        self._dir = root / "brain" / "goal_context"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, goal_id: str) -> Path:
        return self._dir / f"{goal_id}.json"

    def save(self, goal: GoalContext) -> None:
        self._path(goal.goal_id).write_text(
            json.dumps(goal.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, goal_id: str) -> GoalContext | None:
        p = self._path(goal_id)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text("utf-8"))
            return GoalContext.from_dict(d)
        except Exception:
            return None

    def create(self, goal_type: GoalType = "ad_hoc", title: str = "") -> GoalContext:
        goal = GoalContext.new(goal_type=goal_type, title=title)
        self.save(goal)
        return goal

    def update(self, goal: GoalContext) -> GoalContext:
        """Persist a goal that was already modified in memory."""
        self.save(goal)
        return goal

    def list_open(self) -> list[GoalContext]:
        goals = []
        for p in sorted(self._dir.glob("goal-*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text("utf-8"))
                if d.get("status") != "concluded":
                    goals.append(GoalContext.from_dict(d))
            except Exception:
                pass
        return goals

    def list_all(self, limit: int = 50) -> list[GoalContext]:
        goals = []
        for p in sorted(self._dir.glob("goal-*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]:
            try:
                goals.append(GoalContext.from_dict(json.loads(p.read_text("utf-8"))))
            except Exception:
                pass
        return goals


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"
