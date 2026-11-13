from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import (
    DeliberationRequest,
    DeliberationResult,
    DeliberationRun,
    PanelResult,
    Workspace,
    WorkspaceCreate,
    WorkspaceReplace,
)


class WorkspaceStore:
    """SQLite persistence for workspaces and deliberation history."""

    def __init__(
        self,
        path: str | Path = "conclave.db",
        *,
        run_log_dir: str | Path | None = None,
    ) -> None:
        self.path = str(path)
        self.run_log_dir = Path(run_log_dir) if run_log_dir else None
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
                    critic_fallbacks_json TEXT NOT NULL DEFAULT '[]',
                    arbiter TEXT NOT NULL,
                    arbiter_fallbacks_json TEXT NOT NULL DEFAULT '[]',
                    minimum_successes INTEGER NOT NULL,
                    auto_select_delegates INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                connection,
                table="workspaces",
                column="auto_select_delegates",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                table="workspaces",
                column="critic_fallbacks_json",
                definition="TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                connection,
                table="workspaces",
                column="arbiter_fallbacks_json",
                definition="TEXT NOT NULL DEFAULT '[]'",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deliberation_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    question TEXT NOT NULL,
                    request_json TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                )
                """
            )
            self._ensure_column(
                connection,
                table="deliberation_runs",
                column="request_json",
                definition="TEXT",
            )
            self._ensure_column(
                connection,
                table="deliberation_runs",
                column="status",
                definition="TEXT NOT NULL DEFAULT 'complete'",
            )
            self._ensure_column(
                connection,
                table="deliberation_runs",
                column="updated_at",
                definition="TEXT",
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deliberation_runs_workspace_created
                ON deliberation_runs(workspace_id, created_at DESC)
                """
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
                    critic, critic_fallbacks_json, arbiter, arbiter_fallbacks_json,
                    minimum_successes, auto_select_delegates, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.id,
                    workspace.name,
                    workspace.description,
                    workspace.context,
                    json.dumps(workspace.delegates),
                    json.dumps(workspace.roles),
                    workspace.critic,
                    json.dumps(workspace.critic_fallbacks),
                    workspace.arbiter,
                    json.dumps(workspace.arbiter_fallbacks),
                    workspace.minimum_successes,
                    1 if workspace.auto_select_delegates else 0,
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
        return workspace

    def replace(self, workspace_id: str, request: WorkspaceReplace) -> Workspace | None:
        existing = self.get(workspace_id)
        if existing is None:
            return None

        updated = Workspace(
            id=existing.id,
            created_at=existing.created_at,
            updated_at=_now(),
            **request.model_dump(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE workspaces
                SET name = ?, description = ?, context = ?, delegates_json = ?,
                    roles_json = ?, critic = ?, critic_fallbacks_json = ?,
                    arbiter = ?, arbiter_fallbacks_json = ?, minimum_successes = ?,
                    auto_select_delegates = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.description,
                    updated.context,
                    json.dumps(updated.delegates),
                    json.dumps(updated.roles),
                    updated.critic,
                    json.dumps(updated.critic_fallbacks),
                    updated.arbiter,
                    json.dumps(updated.arbiter_fallbacks),
                    updated.minimum_successes,
                    1 if updated.auto_select_delegates else 0,
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated

    def delete(self, workspace_id: str) -> bool:
        if self.get(workspace_id) is None:
            return False
        with self._connect() as connection:
            connection.execute(
                "UPDATE deliberation_runs SET workspace_id = NULL WHERE workspace_id = ?",
                (workspace_id,),
            )
            connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        return True

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
        request: DeliberationRequest | None = None,
        workspace_id: str | None = None,
    ) -> DeliberationRun:
        """Insert a finished run in one step."""
        run = self._insert_run(
            question=question,
            result=result,
            request=request,
            workspace_id=workspace_id,
            status="complete",
        )
        self._write_run_log(run)
        return run

    def create_run(
        self,
        *,
        question: str,
        request: DeliberationRequest | None = None,
        workspace_id: str | None = None,
    ) -> DeliberationRun:
        """Insert a ``running`` row before any provider is called."""
        empty = DeliberationResult(
            panel=PanelResult(
                question=question,
                delegates=[],
                successful_count=0,
                failed_count=0,
                synthesizeable=False,
            )
        )
        return self._insert_run(
            question=question,
            result=empty,
            request=request,
            workspace_id=workspace_id,
            status="running",
        )

    def _insert_run(
        self,
        *,
        question: str,
        result: DeliberationResult,
        request: DeliberationRequest | None,
        workspace_id: str | None,
        status: str,
    ) -> DeliberationRun:
        now = _now()
        run = DeliberationRun(
            id=str(uuid4()),
            workspace_id=workspace_id,
            question=question,
            request=request,
            result=result,
            created_at=now,
            status=status,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deliberation_runs (
                    id, workspace_id, question, request_json, result_json,
                    created_at, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.workspace_id,
                    run.question,
                    run.request.model_dump_json() if run.request else None,
                    run.result.model_dump_json(),
                    run.created_at,
                    run.status,
                    run.updated_at,
                ),
            )
        return run

    def update_run(
        self,
        run_id: str,
        result: DeliberationResult,
        status: str,
    ) -> None:
        """Store the result so far. The run log is written once the run ends."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE deliberation_runs
                SET result_json = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (result.model_dump_json(), status, _now(), run_id),
            )
        if status != "running":
            run = self.get_run(run_id)
            if run is not None:
                self._write_run_log(run)

    def mark_interrupted(self, run_id: str) -> None:
        """Mark a run interrupted, keeping every stage already stored."""
        self._mark_interrupted(run_id=run_id)

    def mark_interrupted_runs(self) -> int:
        """Mark every ``running`` row interrupted. Call at startup."""
        return self._mark_interrupted(run_id=None)

    def _mark_interrupted(self, *, run_id: str | None) -> int:
        where = "status = 'running'" + (" AND id = ?" if run_id else "")
        params: tuple = (run_id,) if run_id else ()
        with self._connect() as connection:
            ids = [
                row["id"]
                for row in connection.execute(
                    f"SELECT id FROM deliberation_runs WHERE {where}", params
                ).fetchall()
            ]
            connection.execute(
                "UPDATE deliberation_runs SET status = 'interrupted', updated_at = ? "
                f"WHERE {where}",
                (_now(), *params),
            )
        for item in ids:
            run = self.get_run(item)
            if run is not None:
                self._write_run_log(run)
        return len(ids)

    def _write_run_log(self, run: DeliberationRun) -> None:
        if self.run_log_dir is None:
            return

        try:
            self.run_log_dir.mkdir(parents=True, exist_ok=True)
            created = datetime.fromisoformat(run.created_at)
            stamp = created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = self.run_log_dir / f"{stamp}_{run.id}.json"
            temp = target.with_suffix(".json.tmp")
            workspace = self.get(run.workspace_id) if run.workspace_id else None
            payload = {
                "schema_version": 1,
                "exported_at": _now(),
                "workspace": workspace.model_dump(mode="json") if workspace else None,
                "run": run.model_dump(mode="json"),
            }
            temp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temp.replace(target)
        except OSError:
            logging.exception("Could not write automatic run log for %s", run.id)

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
            critic_fallbacks=json.loads(row["critic_fallbacks_json"] or "[]"),
            arbiter=row["arbiter"],
            arbiter_fallbacks=json.loads(row["arbiter_fallbacks_json"] or "[]"),
            minimum_successes=row["minimum_successes"],
            auto_select_delegates=bool(row["auto_select_delegates"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _run_from_row(self, row: sqlite3.Row) -> DeliberationRun:
        request_json = row["request_json"] if "request_json" in row.keys() else None
        return DeliberationRun(
            id=row["id"],
            workspace_id=row["workspace_id"],
            question=row["question"],
            request=(
                DeliberationRequest.model_validate_json(request_json)
                if request_json
                else None
            ),
            result=DeliberationResult.model_validate_json(row["result_json"]),
            created_at=row["created_at"],
            status=row["status"] if "status" in row.keys() else "complete",
            updated_at=row["updated_at"] if "updated_at" in row.keys() else None,
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
