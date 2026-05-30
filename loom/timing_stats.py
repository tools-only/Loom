"""Timing statistics.

Compute the interaction waterfall from raw timing data.
Called by brain.py at POST /timing/stages, or imported standalone.
"""

from __future__ import annotations

from typing import Any


def _valid_ms(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(round(value))


def _diff_ms(end: Any, start: Any) -> int | None:
    if not isinstance(end, (int, float)) or not isinstance(start, (int, float)):
        return None
    value = end - start
    return int(round(value)) if value >= 0 else None


def compute_stages(timing: dict) -> dict:
    """Build timing waterfall stages, server timings, DOM detail, and total."""

    t = timing or {}
    srv = t.get("server") or {}

    t0 = _valid_ms(t.get("t0_click"))
    t1 = _valid_ms(t.get("t1_built"))
    t2 = _valid_ms(t.get("t2_sent"))
    t3 = _valid_ms(t.get("t3_ack"))
    t4 = _valid_ms(t.get("t4_thinking"))
    t5 = _valid_ms(t.get("t5_patch"))
    t6 = _valid_ms(t.get("t6_dom"))

    total = _diff_ms(t6, t0)

    stages: list[dict] = []

    def push(name: str, ms: int | None, color: str, emphasis: bool = False) -> None:
        if ms is None or ms < 0:
            return
        item = {"name": name, "ms": ms, "color": color}
        if emphasis:
            item["emphasis"] = True
        stages.append(item)

    push("Build Envelope", _diff_ms(t1, t0), "#5B8FF9")
    push("WS -> Server ACK", _diff_ms(t3, t2), "#5B8FF9")
    push("ACK -> Thinking", _diff_ms(t4, t3), "#5B8FF9")

    pd = t.get("_patch_detail") or {}
    dom_detail: list[dict] = []
    for label, key in [
        ("outerHTML replace", "outerhtml_ms"),
        ("inject handles", "inject_handles_ms"),
        ("serialize HTML", "serialize_html_ms"),
    ]:
        ms = _valid_ms(pd.get(key))
        if ms is not None and ms > 0:
            dom_detail.append({"name": label, "ms": ms})

    ms_hand = _valid_ms(srv.get("ms_hand_agent"))
    ms_loom = _valid_ms(srv.get("ms_loom_agent"))
    ms_bc = _valid_ms(srv.get("ms_broadcast"))
    if ms_hand is not None or ms_loom is not None:
        if ms_hand is not None:
            push("Hand Agent", ms_hand, "#FFD700")
        if ms_loom is not None:
            push("Loom Agent -> Browser", ms_loom, "#F6AD55")
        if ms_bc is not None:
            push("broadcast patches", ms_bc, "#555")
    else:
        ms_gen = _valid_ms(srv.get("ms_claude_gen"))
        if ms_gen is not None:
            ms_resolve = _valid_ms(srv.get("ms_op_to_resolve"))
            if ms_resolve is not None:
                push("op recv -> CC dispatched", ms_resolve, "#555")
            push("CC dispatch -> anchor_patch", ms_gen, "#F6AD55")
            if ms_bc is not None:
                push("broadcast patches", ms_bc, "#555")

    push("Patch -> DOM Done", _diff_ms(t6, t5), "#5B8FF9")

    return {
        "stages": stages,
        "dom_detail": dom_detail,
        "server_timings": [],
        "total": total or 0,
        "op": t.get("op", "?"),
        "target": t.get("target", "?"),
        "agent_context": srv.get("agent_context") or t.get("_agentContext") or "",
    }
