"""Resource disclosure — ranks resource library by Hand-specific usage history.

LEGACY: disclosure strategy (rank-by-usage) belongs to each hand agent, not Core.
This module is retained only to support the sdk_legacy adapter path.
New runtimes (cc, codex) should not use this — hands self-manage via their wiki.
"""
import json
from collections import Counter
from pathlib import Path
import time

ROOT = Path(__file__).parent
LIBRARY_FILE = ROOT / "resource_library.json"
LOG_FILE = ROOT.parent / "logs" / "loom-eval-log.jsonl"


def load_library() -> dict:
    try:
        return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_recent_signals(days: int = 30) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    cutoff = time.time() - days * 86400
    signals = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            if e.get("ts", 0) > cutoff:
                signals.append(e)
        except Exception:
            pass
    return signals


def get_menu_for_hand(hand_id: str, context_tags: list[str] = []) -> list[dict]:
    library = load_library()
    signals = read_recent_signals(days=30)
    hand_signals = [s for s in signals if s.get("hand_id") == hand_id]

    usage_count: Counter = Counter()
    ignore_count: Counter = Counter()
    for s in hand_signals:
        for r in s.get("resources_used", []):
            usage_count[r] += 1
        for r in s.get("resources_ignored", []):
            ignore_count[r] += 1

    def score(rid: str) -> float:
        used = usage_count[rid]
        ignored = ignore_count[rid]
        total = used + ignored
        return 0.5 if total == 0 else used / total

    resources = [{"resource_id": rid, **meta} for rid, meta in library.items()]
    resources.sort(key=lambda r: score(r["resource_id"]), reverse=True)
    return resources[:10]
