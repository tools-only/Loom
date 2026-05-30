"""Daily harness review — computes resource usage stats and patches webview."""
import asyncio
from collections import Counter, defaultdict
from datetime import datetime

from .eval_log import read_all
from bridge import patch_webview


def compute_review(days: int = 7) -> dict:
    signals = [s for s in read_all(days=days)]
    hand_stats: dict = defaultdict(lambda: {"calls": 0, "used": Counter(), "ignored": Counter()})
    for s in signals:
        h = s.get("hand_id", "?")
        hand_stats[h]["calls"] += 1
        for r in s.get("resources_used", []):
            hand_stats[h]["used"][r] += 1
        for r in s.get("resources_ignored", []):
            hand_stats[h]["ignored"][r] += 1

    summary = {}
    for hand_id, stats in hand_stats.items():
        resource_rates = {}
        for rid, count in stats["used"].items():
            ignored = stats["ignored"].get(rid, 0)
            total = count + ignored
            resource_rates[rid] = {
                "used": count,
                "ignored": ignored,
                "rate": round(count / total, 2) if total else 0,
            }
        for rid, ignored in stats["ignored"].items():
            if rid not in resource_rates:
                resource_rates[rid] = {"used": 0, "ignored": ignored, "rate": 0.0}
        summary[hand_id] = {
            "total_calls": stats["calls"],
            "resource_usage": resource_rates,
        }

    return {
        "days": days,
        "total_signals": len(signals),
        "computed_at": datetime.now().isoformat(),
        "hands": summary,
    }


def render_review_html(review: dict) -> str:
    hands = review.get("hands", {})
    hand_sections = ""
    for hand_id, stats in hands.items():
        calls = stats.get("total_calls", 0)
        res = stats.get("resource_usage", {})
        rows = "".join(
            f"<tr><td><code>{rid}</code></td><td>{d['used']}</td>"
            f"<td>{d['ignored']}</td><td>{int(d['rate'] * 100)}%</td></tr>"
            for rid, d in sorted(res.items(), key=lambda x: -x[1]["rate"])
        )
        table = (
            f"<table><thead><tr><th>资源</th><th>已用</th><th>忽略</th><th>使用率</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if rows
            else "<p>无资源使用记录</p>"
        )
        hand_sections += f"""
<div class="anc-section anc-section--gc" style="margin-bottom:12px">
  <h4>{hand_id} — {calls} 次调用</h4>
  {table}
</div>"""

    ts = review.get("computed_at", datetime.now().isoformat())[:16]
    total = review.get("total_signals", 0)
    days = review.get("days", 7)
    return f"""<section class="anc-section anc-section--gc" data-anc="harness-review" data-handles="refine">
  <h2>Harness 日报</h2>
  <div class="anc-pill-row">
    <span class="anc-pill anc-pill--active">日频</span>
    <span class="anc-pill anc-pill--review">过去 {days} 天 · {total} 次调用</span>
  </div>
  {hand_sections if hand_sections else '<p>尚无数据 — 先运行几次 Hand 分析再查看</p>'}
  <p>生成时间：{ts}</p>
</section>"""


async def run_daily_review():
    review = compute_review(days=7)
    html = render_review_html(review)
    await patch_webview("harness-review", html)
