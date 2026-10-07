from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import Workspace, WorkspaceCreate


class WorkspaceStore:
    """Small SQLite store for persistent project context and model defaults."""

    def __init__(self, path: str | Path = "conclave.db") -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    context TEXT,
                    delegates_json TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    critic TEXT,
                    arbiter TEXT NOT NULL,
                    minimum_successes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create(self, request: WorkspaceCreate) -> Workspace:
        now = datetime.now(timezone.utc).isoformat()
        workspace = Workspace(
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workspaces (
                    id, name, description, context, delegates_json, roles_json,
                    critic, arbiter, minimum_successes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.id,
                    workspace.name,
                    workspace.description,
                    workspace.context,
                    json.dumps(workspace.delegates),
                    json.dumps(workspace.roles),
                    workspace.critic,
                    workspace.arbiter,
                    workspace.minimum_successes,
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
        return workspace

    def list(self) -> list[Workspace]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workspaces ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, workspace_id: str) -> Workspace | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def _from_row(self, row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            context=row["context"],
            delegates=json.loads(row["delegates_json"]),
            roles=json.loads(row["roles_json"]),
            critic=row["critic"],
            arbiter=row["arbiter"],
            minimum_successes=row["minimum_successes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
