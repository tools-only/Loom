"""Agent session registry — tracks Codex/CC sessions independent of Brain.

Channel messages route to a foreground session directly, without going through
Brain/hand/review/synthesis. The registry is a thin in-memory tracker; agent
process lifecycle and context are fully encapsulated inside Codex/CC.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSessionRecord:
    session_id: str
    adapter_id: str
    platform: str
    channel_id: str
    user_id: str
    label: str = ""
    status: str = "idle"          # idle | running | waiting
    created_at: float = 0.0
    last_activity: float = 0.0
    message_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "adapter_id": self.adapter_id,
            "platform": self.platform,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "label": self.label,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "message_count": self.message_count,
        }


class AgentSessionRegistry:
    """In-memory registry of active agent sessions with foreground tracking."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSessionRecord] = {}
        # (platform, channel_id, user_id) → session_id
        self._foreground: dict[tuple[str, str, str], str] = {}

    @staticmethod
    def _key(platform: str, channel_id: str, user_id: str) -> tuple[str, str, str]:
        return (str(platform), str(channel_id), str(user_id))

    # ── CRUD ─────────────────────────────────────────────────────────────

    def start(
        self,
        adapter_id: str,
        platform: str,
        channel_id: str,
        user_id: str,
        label: str = "",
    ) -> AgentSessionRecord:
        session_id = uuid.uuid4().hex[:12]
        now = time.time()
        record = AgentSessionRecord(
            session_id=session_id,
            adapter_id=adapter_id,
            platform=platform,
            channel_id=channel_id,
            user_id=user_id,
            label=label or adapter_id,
            status="idle",
            created_at=now,
            last_activity=now,
        )
        self._sessions[session_id] = record
        return record

    def get(self, session_id: str) -> AgentSessionRecord | None:
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        platform: str = "",
        channel_id: str = "",
        user_id: str = "",
    ) -> list[AgentSessionRecord]:
        results = list(self._sessions.values())
        if platform:
            results = [r for r in results if r.platform == platform]
        if channel_id:
            results = [r for r in results if r.channel_id == channel_id]
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        results.sort(key=lambda r: r.last_activity, reverse=True)
        return results

    def touch(self, session_id: str) -> None:
        record = self._sessions.get(session_id)
        if record:
            record.last_activity = time.time()
            record.message_count += 1

    def set_status(self, session_id: str, status: str) -> None:
        record = self._sessions.get(session_id)
        if record:
            record.status = status
            record.last_activity = time.time()

    def close(self, session_id: str) -> bool:
        record = self._sessions.pop(session_id, None)
        if record is None:
            return False
        fg_key = self._key(record.platform, record.channel_id, record.user_id)
        if self._foreground.get(fg_key) == session_id:
            self._foreground.pop(fg_key, None)
        return True

    # ── Foreground tracking ───────────────────────────────────────────────

    def get_foreground(
        self, platform: str, channel_id: str, user_id: str
    ) -> AgentSessionRecord | None:
        fg_key = self._key(platform, channel_id, user_id)
        session_id = self._foreground.get(fg_key)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def set_foreground(
        self, platform: str, channel_id: str, user_id: str, session_id: str
    ) -> AgentSessionRecord | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        fg_key = self._key(platform, channel_id, user_id)
        self._foreground[fg_key] = session_id
        return record

    def clear_foreground(self, platform: str, channel_id: str, user_id: str) -> bool:
        fg_key = self._key(platform, channel_id, user_id)
        return self._foreground.pop(fg_key, None) is not None

    # ── Routing ───────────────────────────────────────────────────────────

    def resolve_route(
        self,
        platform: str,
        channel_id: str,
        user_id: str,
        message_text: str,
    ) -> dict[str, Any]:
        """Check if a foreground session should handle this message.

        Returns a dict with:
          route: "session" | "none"
          session_id: str (if route is "session")
          adapter_id: str (if route is "session")
          task: str
        """
        fg = self.get_foreground(platform, channel_id, user_id)
        if fg is None:
            return {"route": "none"}
        return {
            "route": "session",
            "session_id": fg.session_id,
            "adapter_id": fg.adapter_id,
            "task": message_text.strip(),
        }
