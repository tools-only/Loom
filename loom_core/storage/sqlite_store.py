"""SQLite-backed local store for structured data."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


class SqliteStore:
    """Local SQLite store with minimal schema."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                artifact_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                claim_type TEXT NOT NULL,
                content TEXT,
                confidence REAL,
                evidence_ids TEXT,
                created_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def list_tables(self) -> list[str]:
        if self._conn is None:
            return []
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row[0] for row in cur.fetchall()]

    def insert_event(self, event_type: str, payload: dict) -> str:
        if self._conn is None:
            raise RuntimeError("SqliteStore not initialized")
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (event_id, event_type, json.dumps(payload), now),
        )
        self._conn.commit()
        return event_id

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_event(self, event_id: str) -> dict | None:
        if self._conn is None:
            return None
        cur = self._conn.execute(
            "SELECT id, event_type, payload, created_at FROM events WHERE id = ?",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        }
