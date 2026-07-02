"""Project Brain workflow events into compact social-channel progress."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


_STAGE_BY_STATE = {
    "Planning": "planning", "Dispatching": "dispatching", "Reviewing": "reviewing",
    "Repairing": "repairing", "Synthesizing": "synthesizing", "Persisted": "complete",
    "Failed": "failed", "Interrupted": "failed",
}
_TITLE_BY_STAGE = {
    "received": "Loom 已接收任务", "planning": "Brain 正在规划",
    "dispatching": "Hand agents 正在处理", "reviewing": "Brain 正在检查结果",
    "repairing": "Brain 正在补充证据", "synthesizing": "Brain 正在汇总",
    "complete": "Loom 任务已完成", "failed": "Loom 任务失败",
}


@dataclass
class DiscordProgress:
    episode_id: str = ""
    stage: str = "received"
    hands: dict[str, dict[str, Any]] = field(default_factory=dict)
    failure_phase: str = ""
    error_message: str = ""
    direct_reply: bool = False
    awaiting_confirmation: bool = False
    session_mode: bool = False  # True when message routes to an agent session

    def apply(self, event: dict[str, Any]) -> None:
        self.episode_id = str(event.get("episode_id") or self.episode_id)
        event_type = str(event.get("type") or "")
        hand_id = str(event.get("hand_id") or "")
        task_id = str(event.get("task_id") or "__default__")
        if event_type == "state.transition":
            if str(event.get("to") or "") == "Failed":
                self.failure_phase = str(event.get("from") or self.failure_phase)
            self.stage = _STAGE_BY_STATE.get(str(event.get("to") or ""), self.stage)
        elif event_type == "episode.error":
            self.error_message = str(event.get("message") or "")
        elif event_type == "dispatch.sent" and hand_id:
            hand = self.hands.setdefault(hand_id, {"tasks": {}})
            hand["dimension"] = str(event.get("dimension") or hand.get("dimension") or "")
            hand["tasks"][task_id] = "running"
            hand["status"] = "running"
        elif event_type == "dispatch.artifact" and hand_id:
            hand = self.hands.setdefault(hand_id, {"tasks": {}})
            hand["tasks"][task_id] = "completed"
            hand["status"] = self._hand_status(hand["tasks"])
        elif event_type == "dispatch.error" and hand_id:
            hand = self.hands.setdefault(hand_id, {"tasks": {}})
            hand["tasks"][task_id] = "failed"
            hand["status"] = self._hand_status(hand["tasks"])
            hand["message"] = str(event.get("message") or "")

    @staticmethod
    def _hand_status(tasks: dict[str, str]) -> str:
        statuses = set(tasks.values())
        if "running" in statuses:
            return "running"
        if "failed" in statuses:
            return "failed"
        return "completed"

    def snapshot(self) -> dict[str, Any]:
        grouped = {
            status: sorted(hand_id for hand_id, item in self.hands.items() if item.get("status") == status)
            for status in ("running", "completed", "failed")
        }
        return {"episode_id": self.episode_id, "stage": self.stage, "hand_count": len(self.hands), **grouped}

    def discord_embed(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        fields = []
        for status, label in (("running", "处理中"), ("completed", "已完成"), ("failed", "失败")):
            hands = snapshot[status]
            if hands:
                fields.append({"name": f"{label} ({len(hands)})", "value": "\n".join(f"• {hand}" for hand in hands), "inline": True})
        if not fields and self.awaiting_confirmation:
            fields.append({
                "name": "等待用户回答",
                "value": "请回答是或否；确认前不会启动任务编排。",
                "inline": False,
            })
        elif not fields and self.direct_reply:
            fields.append({
                "name": "Brain 直接回复",
                "value": "该消息不需要完整任务编排，未派发 Hand Agent。",
                "inline": False,
            })
        elif not fields and self.stage == "failed":
            phase_labels = {
                "Planning": "规划",
                "Dispatching": "派发",
                "Reviewing": "检查",
                "Repairing": "修复",
                "Synthesizing": "汇总",
            }
            phase = phase_labels.get(self.failure_phase, self.failure_phase or "任务")
            fields.append({
                "name": f"{phase}失败",
                "value": (self.error_message or "未提供错误详情")[:1024],
                "inline": False,
            })
        elif not fields:
            fields.append({"name": "状态", "value": "等待 Brain 派发任务", "inline": False})
        return {
            "title": (
                "Loom 需要确认"
                if self.awaiting_confirmation
                else _TITLE_BY_STAGE.get(self.stage, _TITLE_BY_STAGE["received"])
            ),
            "description": (
                "🤖 Session Mode — 直接路由到 agent，绕过 Brain"
                if self.session_mode
                else "等待明确的是/否决定"
                if self.awaiting_confirmation
                else "🧠 Brain Mode — Loom 多 hand 分析"
                if self.direct_reply
                else f"🧠 Brain Mode — 已派发 {snapshot['hand_count']} 个 hand agent"
            ),
            "color": (
                0x3B82F6 if self.session_mode
                else 0x22C55E if self.stage == "complete"
                else 0xEF4444 if self.stage == "failed"
                else 0xF59E0B
            ),
            "fields": fields,
            "footer": {"text": f"episode {self.episode_id}" if self.episode_id else "Loom Brain"},
        }


class DiscordProgressReporter:
    """Coalesce workflow events into rate-limit-friendly Embed updates."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], Awaitable[Any]],
        *,
        debounce_seconds: float = 0.75,
    ) -> None:
        self._publish = publish
        self._debounce_seconds = debounce_seconds
        self._progress = DiscordProgress()
        self._dirty = False
        self._task: asyncio.Task | None = None

    def notify(self, event: dict[str, Any]) -> None:
        self._progress.apply(event)
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._publish_later())

    async def _publish_later(self) -> None:
        await asyncio.sleep(self._debounce_seconds)
        await self._publish_latest()

    async def _publish_latest(self) -> None:
        if not self._dirty:
            return
        try:
            await self._publish(self._progress.discord_embed())
        except Exception:
            self._dirty = True
            raise
        else:
            self._dirty = False

    async def flush(self) -> None:
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                # A failed background edit leaves _dirty set so the final
                # synchronous flush below can retry the latest snapshot.
                pass
            self._task = None
        await self._publish_latest()
