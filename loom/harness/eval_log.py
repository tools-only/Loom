"""Eval signal logger — records resource usage per Hand invocation."""
import json
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
LOG_FILE = ROOT / "logs" / "loom-eval-log.jsonl"


def append_signal(
    hand_id: str,
    task: str,
    context_tags: list[str],
    resources_shown: list[str],
    resources_used: list[str],
):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "hand_id": hand_id,
        "task": task,
        "tags": context_tags,
        "resources_shown": resources_shown,
        "resources_used": resources_used,
        "resources_ignored": [r for r in resources_shown if r not in resources_used],
        "ts": time.time(),
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_all(days: int = 90) -> list[dict]:
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
