"""DataFlywheel — structured episode record persistence for BrainStateEngine (L5).

Write-only in P0; FlywheelAnalyzer (read + derive signals) is P4.

Each /analyze call produces one FlywheelRecord written to:
  brain/flywheel/records.jsonl   — append-only master log
  brain/flywheel/<episode_id>.json — per-episode detail (for selective reads)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class BrainSelfEval:
    """Brain's own post-synthesis quality assessment."""
    episode_id: str
    confidence: float                  # synthesis.confidence
    stance: str                        # synthesis.stance
    key_driver_count: int = 0
    has_reversal_condition: bool = False
    cold_start: bool = False
    hand_count: int = 0
    overall_quality: float = 0.0       # placeholder; computed by FlywheelAnalyzer in P4


@dataclass
class HandEval:
    """Evaluation of a single hand's artifact quality."""
    hand_id: str
    artifact_present: bool
    claim_count: int = 0
    gap_count: int = 0
    source_tier: str = "unknown"       # A/B/C/E/F derived from resources_used


@dataclass
class PhaseTrace:
    phase: int
    hands_invoked: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class HumanFeedback:
    """Async human feedback injected after an episode completes."""
    episode_id: str
    ts: str
    signal: str                        # thumbs_up / thumbs_down / correction / ignore
    comment: str = ""
    corrected_stance: str = ""


@dataclass
class FlywheelRecord:
    """One entry in the data flywheel — one per /analyze call."""
    episode_id: str
    goal_id: str
    ts: str
    question: str
    domain: str
    brain_self_eval: BrainSelfEval
    hand_evaluations: list[HandEval] = field(default_factory=list)
    orchestration_trace: list[PhaseTrace] = field(default_factory=list)
    human_feedback: list[HumanFeedback] = field(default_factory=list)
    # Derived in P4 by FlywheelAnalyzer:
    profile_signals: list[dict] = field(default_factory=list)
    strategy_signals: list[dict] = field(default_factory=list)

    @staticmethod
    def new(
        goal_id: str,
        question: str,
        domain: str,
        synthesis: dict,
        hand_artifacts: dict,
        cold_start: bool = False,
    ) -> "FlywheelRecord":
        episode_id = _new_episode_id()
        hand_evals = []
        for hand_id, art in (hand_artifacts or {}).items():
            meta = art.get("metadata", {}) if isinstance(art, dict) else {}
            claim_count = len(meta.get("key_claims", []))
            gap_count = len(meta.get("gaps", []))
            sources = meta.get("resources_used", [])
            hand_evals.append(HandEval(
                hand_id=hand_id,
                artifact_present=bool(art),
                claim_count=claim_count,
                gap_count=gap_count,
                source_tier=_infer_tier(sources),
            ))

        brain_eval = BrainSelfEval(
            episode_id=episode_id,
            confidence=synthesis.get("confidence", 0.0) if synthesis else 0.0,
            stance=synthesis.get("stance", "n/a") if synthesis else "n/a",
            key_driver_count=len(synthesis.get("key_drivers", [])) if synthesis else 0,
            has_reversal_condition=bool(synthesis.get("reversal_condition")) if synthesis else False,
            cold_start=cold_start,
            hand_count=len(hand_artifacts or {}),
        )

        return FlywheelRecord(
            episode_id=episode_id,
            goal_id=goal_id,
            ts=_now(),
            question=question,
            domain=domain,
            brain_self_eval=brain_eval,
            hand_evaluations=hand_evals,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> dict:
        """Compact dict for the JSONL master log (no per-hand detail)."""
        return {
            "episode_id": self.episode_id,
            "goal_id": self.goal_id,
            "ts": self.ts,
            "domain": self.domain,
            "stance": self.brain_self_eval.stance,
            "confidence": self.brain_self_eval.confidence,
            "hand_count": self.brain_self_eval.hand_count,
            "cold_start": self.brain_self_eval.cold_start,
        }


class FlywheelWriter:
    """Append-only writer for FlywheelRecord objects."""

    def __init__(self, root: Path) -> None:
        self._dir = root / "brain" / "flywheel"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log = self._dir / "records.jsonl"

    def append_record(self, record: FlywheelRecord) -> None:
        # Compact summary line to master JSONL
        line = json.dumps(record.summary_line(), ensure_ascii=False)
        with self._log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        # Full detail JSON for per-episode reads
        detail_path = self._dir / f"{record.episode_id}.json"
        detail_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_human_feedback(self, episode_id: str, feedback: HumanFeedback) -> bool:
        """Inject human feedback into an existing episode detail file."""
        detail_path = self._dir / f"{episode_id}.json"
        if not detail_path.exists():
            return False
        try:
            d = json.loads(detail_path.read_text("utf-8"))
            d.setdefault("human_feedback", []).append(asdict(feedback))
            detail_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
            return True
        except Exception:
            return False

    def read_summary_log(self, limit: int = 100) -> list[dict]:
        if not self._log.exists():
            return []
        lines = self._log.read_text("utf-8").splitlines()
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out


# ── helpers ───────────────────────────────────────────────────────────────

_TIER_A_B = {"fred", "sec-edgar", "finnhub", "yahoo-finance", "cftc-cot", "investing-calendar"}
_TIER_C = {"reuters-rss", "marketwatch-rss", "cnbc-rss"}
_TIER_E_F = {"fear-greed", "aaii", "naaim", "stocktwits", "reddit", "kol-rss"}


def _infer_tier(sources: list) -> str:
    s = set(sources)
    if s & _TIER_A_B:
        return "A/B"
    if s & _TIER_C:
        return "C"
    if s & _TIER_E_F:
        return "E/F"
    return "unknown"


def _new_episode_id() -> str:
    return f"ep-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"
