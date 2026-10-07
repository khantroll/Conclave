from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import DeliberationResult, DeliberationRun, Workspace, WorkspaceCreate


class WorkspaceStore:
    """SQLite persistence for workspaces and deliberation history."""

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deliberation_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    question TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deliberation_runs_workspace_created
                ON deliberation_runs(workspace_id, created_at DESC)
                """
            )

    def create(self, request: WorkspaceCreate) -> Workspace:
        now = _now()
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
        return [self._workspace_from_row(row) for row in rows]

    def get(self, workspace_id: str) -> Workspace | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
        return self._workspace_from_row(row) if row else None

    def save_run(
        self,
        *,
        question: str,
        result: DeliberationResult,
        workspace_id: str | None = None,
    ) -> DeliberationRun:
        run = DeliberationRun(
            id=str(uuid4()),
            workspace_id=workspace_id,
            question=question,
            result=result,
            created_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deliberation_runs (
                    id, workspace_id, question, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.workspace_id,
                    run.question,
                    run.result.model_dump_json(),
                    run.created_at,
                ),
            )
        return run

    def list_runs(self, workspace_id: str | None = None) -> list[DeliberationRun]:
        with self._connect() as connection:
            if workspace_id is None:
                rows = connection.execute(
                    "SELECT * FROM deliberation_runs ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM deliberation_runs
                    WHERE workspace_id = ?
                    ORDER BY created_at DESC
                    """,
                    (workspace_id,),
                ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> DeliberationRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM deliberation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row else None

    def _workspace_from_row(self, row: sqlite3.Row) -> Workspace:
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

    def _run_from_row(self, row: sqlite3.Row) -> DeliberationRun:
        return DeliberationRun(
            id=row["id"],
            workspace_id=row["workspace_id"],
            question=row["question"],
            result=DeliberationResult.model_validate_json(row["result_json"]),
            created_at=row["created_at"],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
