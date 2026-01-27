"""
SQLite storage for hub data persistence.

Stores:
- Agent history (past connections)
- Task history (completed tasks)
- Event log (workflow events)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from galangal_hub.models import AgentInfo, EventType, TaskState, WorkflowEvent


class HubStorage:
    """SQLite-based storage for hub data."""

    def __init__(self, db_path: Path | str = "hub.db"):
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._create_tables()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        if not self._db:
            return

        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                project_name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                agent_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                task_name TEXT NOT NULL,
                task_description TEXT,
                task_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                final_stage TEXT,
                success INTEGER,
                github_issue INTEGER,
                github_repo TEXT,
                metadata TEXT,
                FOREIGN KEY (agent_id) REFERENCES agents (agent_id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                task_name TEXT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT,
                FOREIGN KEY (agent_id) REFERENCES agents (agent_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks (agent_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_started ON tasks (started_at);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
            """
        )
        await self._db.commit()

    async def upsert_agent(self, info: AgentInfo) -> None:
        """Insert or update an agent record."""
        if not self._db:
            return

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO agents (agent_id, hostname, project_name, project_path, agent_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                hostname = excluded.hostname,
                project_name = excluded.project_name,
                project_path = excluded.project_path,
                agent_name = excluded.agent_name,
                last_seen = excluded.last_seen
            """,
            (
                info.agent_id,
                info.hostname,
                info.project_name,
                info.project_path,
                info.agent_name,
                now,
                now,
            ),
        )
        await self._db.commit()

    async def update_agent_seen(self, agent_id: str) -> None:
        """Update the last_seen time for an agent."""
        if not self._db:
            return

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE agents SET last_seen = ? WHERE agent_id = ?",
            (now, agent_id),
        )
        await self._db.commit()

    async def record_task_start(self, agent_id: str, state: TaskState) -> int:
        """
        Record a new task starting.

        Returns:
            The task ID.
        """
        if not self._db:
            return -1

        cursor = await self._db.execute(
            """
            INSERT INTO tasks (agent_id, task_name, task_description, task_type, started_at, github_issue, github_repo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                state.task_name,
                state.task_description,
                state.task_type,
                state.started_at,
                state.github_issue,
                state.github_repo,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid or -1

    async def record_task_complete(
        self,
        agent_id: str,
        task_name: str,
        final_stage: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a task completion."""
        if not self._db:
            return

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            UPDATE tasks
            SET completed_at = ?, final_stage = ?, success = ?, metadata = ?
            WHERE agent_id = ? AND task_name = ? AND completed_at IS NULL
            """,
            (
                now,
                final_stage,
                1 if success else 0,
                json.dumps(metadata) if metadata else None,
                agent_id,
                task_name,
            ),
        )
        await self._db.commit()

    async def record_event(self, event: WorkflowEvent) -> None:
        """Record a workflow event."""
        if not self._db:
            return

        await self._db.execute(
            """
            INSERT INTO events (agent_id, task_name, event_type, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.agent_id,
                event.task_name,
                event.event_type.value,
                event.timestamp.isoformat(),
                json.dumps(event.data) if event.data else None,
            ),
        )
        await self._db.commit()

    async def get_recent_tasks(
        self,
        limit: int = 50,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent tasks, optionally filtered by agent."""
        if not self._db:
            return []

        if agent_id:
            cursor = await self._db.execute(
                """
                SELECT * FROM tasks
                WHERE agent_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM tasks
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            )

        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_recent_events(
        self,
        limit: int = 100,
        agent_id: str | None = None,
        event_type: EventType | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent events with optional filters."""
        if not self._db:
            return []

        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def get_agent_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get agent history."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            """
            SELECT * FROM agents
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]


# Global storage instance
storage = HubStorage()
