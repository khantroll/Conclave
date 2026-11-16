from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .ledger import summarize
from .models import (
    MAX_SUMMARY_QUESTION_CHARS,
    RESULT_SCHEMA_VERSION,
    CallRow,
    CostSummary,
    DeliberationRequest,
    DeliberationResult,
    DeliberationRun,
    PanelResult,
    RunSummary,
    Workspace,
    WorkspaceCreate,
    WorkspaceReplace,
)


# The database schema, in numbered steps. A database records the newest step it has had applied.
SCHEMA_VERSION = 3
MIGRATION_DESCRIPTIONS = {
    1: "original tables and early columns",
    2: "call ledger (provider_calls)",
    3: "retry lineage (parent_run_id, chain_root_id)",
}


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
        # Where the database was copied before an upgrade, when this start upgraded one.
        self.last_backup: Path | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """Create or upgrade the database to ``SCHEMA_VERSION``, one numbered step at a time.

        Any file that already has content is copied to a verified backup before its first step
        runs, and a database that is already current is left untouched. The version check, the
        backup and every step happen while holding SQLite's write lock, in one transaction, so
        two starts at once cannot both migrate, and a failure part-way changes nothing.
        """
        path = Path(self.path)
        in_memory = self.path == ":memory:"
        existing = not in_memory and path.exists() and path.stat().st_size > 0
        # Autocommit mode, so the transaction below is explicit. A long timeout lets a second
        # start wait for the first to finish instead of failing.
        connection = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._schema_version(connection)
                if current > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"{self.path} is schema version {current}, newer than this Conclave "
                        f"understands ({SCHEMA_VERSION}). Upgrade Conclave; the file was not "
                        "changed."
                    )
                if current == SCHEMA_VERSION:
                    connection.execute("ROLLBACK")
                    return
                if existing and not in_memory:
                    # Another connection reads the file as it is now; nothing is written yet.
                    self.last_backup = self._backup(from_version=current)
                for version in range(current + 1, SCHEMA_VERSION + 1):
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_version (
                            version INTEGER PRIMARY KEY,
                            applied_at TEXT NOT NULL,
                            description TEXT
                        )
                        """
                    )
                    MIGRATIONS[version](self, connection)
                    connection.execute(
                        "INSERT INTO schema_version (version, applied_at, description) "
                        "VALUES (?, ?, ?)",
                        (version, _now(), MIGRATION_DESCRIPTIONS[version]),
                    )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()

    def _schema_version(self, connection: sqlite3.Connection) -> int:
        """The newest applied step, 0 for a database with no version table. Read-only: the file
        must not change before its backup has been made."""
        has_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if not has_table:
            return 0
        row = connection.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] or 0

    @staticmethod
    def _backup_stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _reserve_backup_path(self, from_version: int) -> Path:
        """A backup path nobody else holds, claimed atomically so two starts cannot share one."""
        stamp = self._backup_stamp()
        counter = 1
        while True:
            suffix = "" if counter == 1 else f"-{counter}"
            target = Path(f"{self.path}.bak-{from_version}-{stamp}{suffix}")
            try:
                with open(target, "xb"):
                    return target
            except FileExistsError:
                counter += 1

    def _backup(self, *, from_version: int) -> Path:
        """Copy the database aside, with SQLite's online backup, before it is migrated.

        The copy is taken from a separate read connection (the file still has no change in it,
        and SQLite's backup includes anything still only in a write-ahead log) and verified with
        ``PRAGMA integrity_check``. If it cannot be made or does not verify, nothing is migrated
        and no partial copy is left behind.
        """
        target = self._reserve_backup_path(from_version)
        try:
            with closing(sqlite3.connect(self.path, timeout=60)) as source, closing(
                sqlite3.connect(target)
            ) as copy:
                source.backup(copy)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        problem = self._check_backup(target)
        if problem is not None:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"the backup of {self.path} failed its integrity check: {problem}")
        return target

    @staticmethod
    def _check_backup(target: Path) -> str | None:
        """None when the copy opens and passes SQLite's integrity check."""
        with closing(sqlite3.connect(target)) as copy:
            verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
        return None if verdict == "ok" else str(verdict)

    # -- numbered migration steps. Each is idempotent, so a half-applied step can run again.

    def _migration_1(self, connection: sqlite3.Connection) -> None:
        """The original tables, and the columns added to them before versioning."""
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
        self._ensure_column(
            connection,
            table="workspaces",
            column="allow_single_source",
            definition="INTEGER NOT NULL DEFAULT 0",
        )
        self._ensure_column(
            connection,
            table="workspaces",
            column="single_source_mode",
            definition="TEXT NOT NULL DEFAULT 'return_answer'",
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

    def _migration_2(self, connection: sqlite3.Connection) -> None:
        """The call ledger (P1-9)."""
        # The call ledger: one row per provider request. A new table, so an older database
        # simply gains it; nothing existing is rewritten. run_id is null for connectivity tests.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_calls (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                chain_root_id TEXT,
                stage TEXT NOT NULL,
                provider TEXT NOT NULL,
                configured_model TEXT,
                reported_model TEXT,
                attempt_no INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                http_status INTEGER,
                started_at TEXT NOT NULL,
                latency_ms INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                usage_json TEXT,
                price_in_per_million REAL,
                price_out_per_million REAL,
                estimated_cost_usd REAL,
                reported_cost_usd REAL,
                reported_cost_source TEXT,
                possibly_billed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_provider_calls_run ON provider_calls(run_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_provider_calls_chain ON provider_calls(chain_root_id)"
        )


    def _migration_3(self, connection: sqlite3.Connection) -> None:
        """Retry lineage (P1-10). Older rows keep NULL here and read as their own chain root."""
        self._ensure_column(
            connection, table="deliberation_runs", column="parent_run_id", definition="TEXT"
        )
        self._ensure_column(
            connection, table="deliberation_runs", column="chain_root_id", definition="TEXT"
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliberation_runs_chain
            ON deliberation_runs(chain_root_id)
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
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO workspaces (
                    id, name, description, context, delegates_json, roles_json,
                    critic, critic_fallbacks_json, arbiter, arbiter_fallbacks_json,
                    minimum_successes, auto_select_delegates, allow_single_source,
                    single_source_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if workspace.allow_single_source else 0,
                    workspace.single_source_mode or "return_answer",
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
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE workspaces
                SET name = ?, description = ?, context = ?, delegates_json = ?,
                    roles_json = ?, critic = ?, critic_fallbacks_json = ?,
                    arbiter = ?, arbiter_fallbacks_json = ?, minimum_successes = ?,
                    auto_select_delegates = ?, allow_single_source = ?,
                    single_source_mode = ?, updated_at = ?
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
                    1 if updated.allow_single_source else 0,
                    updated.single_source_mode or "return_answer",
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated

    def delete(self, workspace_id: str) -> bool:
        if self.get(workspace_id) is None:
            return False
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE deliberation_runs SET workspace_id = NULL WHERE workspace_id = ?",
                (workspace_id,),
            )
            connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        return True

    def list(self) -> list[Workspace]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM workspaces ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def get(self, workspace_id: str) -> Workspace | None:
        with closing(self._connect()) as connection, connection:
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
        run_id: str | None = None,
        parent_run_id: str | None = None,
        chain_root_id: str | None = None,
    ) -> DeliberationRun:
        """Insert a finished run in one step. ``run_id`` lets a caller fix the id beforehand,
        so the calls made to produce the run can already be in the ledger under it."""
        run = self._insert_run(
            question=question,
            result=result,
            request=request,
            workspace_id=workspace_id,
            status="complete",
            run_id=run_id,
            parent_run_id=parent_run_id,
            chain_root_id=chain_root_id,
        )
        run.chain_cost = self.chain_cost(run.id)
        self._write_run_log(run)
        return run

    def create_run(
        self,
        *,
        question: str,
        request: DeliberationRequest | None = None,
        workspace_id: str | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        chain_root_id: str | None = None,
    ) -> DeliberationRun:
        """Insert a ``running`` row before any provider is called."""
        empty = DeliberationResult(
            schema_version=RESULT_SCHEMA_VERSION,
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
            run_id=run_id,
            parent_run_id=parent_run_id,
            chain_root_id=chain_root_id,
        )

    def _insert_run(
        self,
        *,
        question: str,
        result: DeliberationResult,
        request: DeliberationRequest | None,
        workspace_id: str | None,
        status: str,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        chain_root_id: str | None = None,
    ) -> DeliberationRun:
        now = _now()
        new_id = run_id or str(uuid4())
        run = DeliberationRun(
            id=new_id,
            parent_run_id=parent_run_id,
            # A run that is not a retry starts its own chain.
            chain_root_id=chain_root_id or new_id,
            workspace_id=workspace_id,
            question=question,
            request=request,
            result=result,
            created_at=now,
            status=status,
            updated_at=now,
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO deliberation_runs (
                    id, workspace_id, question, request_json, result_json,
                    created_at, status, updated_at, parent_run_id, chain_root_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.parent_run_id,
                    run.chain_root_id,
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
        with closing(self._connect()) as connection, connection:
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

    def discard_run(self, run_id: str) -> None:
        """Remove a run that never started (only a still-``running`` row is removed)."""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM deliberation_runs WHERE id = ? AND status = 'running'", (run_id,)
            )

    def mark_interrupted(self, run_id: str) -> None:
        """Mark a run interrupted, keeping every stage already stored."""
        self._mark_interrupted(run_id=run_id)

    def mark_interrupted_runs(self) -> int:
        """Mark every ``running`` row interrupted. Call at startup."""
        return self._mark_interrupted(run_id=None)

    def _mark_interrupted(self, *, run_id: str | None) -> int:
        where = "status = 'running'" + (" AND id = ?" if run_id else "")
        params: tuple = (run_id,) if run_id else ()
        with closing(self._connect()) as connection, connection:
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

    def list_runs(
        self, workspace_id: str | None = None, *, include_all_attempts: bool = False
    ) -> list[DeliberationRun]:
        """Runs, newest first. By default only the newest run of each retry chain is listed;
        every attempt is still stored and reachable from its chain root."""
        params: list = []
        scope = ""
        if workspace_id is not None:
            scope = "WHERE workspace_id = ?"
            params.append(workspace_id)
        if include_all_attempts:
            sql = f"SELECT * FROM deliberation_runs {scope} ORDER BY created_at DESC, rowid DESC"
        else:
            # Number each chain's attempts newest-first and keep the first (rowid breaks ties).
            sql = f"""
                SELECT * FROM (
                    SELECT r.*, r.rowid AS run_rowid, ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(r.chain_root_id, r.id)
                        ORDER BY r.created_at DESC, r.rowid DESC
                    ) AS attempt_rank
                    FROM deliberation_runs r {scope}
                ) WHERE attempt_rank = 1
                ORDER BY created_at DESC, run_rowid DESC
            """
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._run_from_row(row) for row in rows]

    def list_run_summaries(
        self,
        workspace_id: str | None = None,
        *,
        include_all_attempts: bool = False,
        limit: int = 50,
        before: str | None = None,
    ) -> list[RunSummary]:
        """A bounded page of run summaries, newest first.

        ``before`` is a run id: only runs older than it are returned (keyset paging, so a page
        never repeats or skips a run even while new runs arrive). Raises ``KeyError`` for an
        unknown ``before``. By default only the newest run of each retry chain is listed.
        """
        cursor: tuple[str, int] | None = None
        if before is not None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT created_at, rowid AS run_rowid FROM deliberation_runs WHERE id = ?",
                    (before,),
                ).fetchone()
            if row is None:
                raise KeyError(before)
            cursor = (row["created_at"], row["run_rowid"])
        params: list = []
        scope = ""
        if workspace_id is not None:
            scope = "WHERE workspace_id = ?"
            params.append(workspace_id)
        after = ""
        if cursor is not None:
            after = "AND (created_at, run_rowid) < (?, ?)" if not include_all_attempts else ""
        if include_all_attempts:
            clauses = [scope.removeprefix("WHERE ")] if scope else []
            if cursor is not None:
                clauses.append("(created_at, rowid) < (?, ?)")
                params.extend(cursor)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = (
                f"SELECT * FROM deliberation_runs {where} "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?"
            )
        else:
            sql = f"""
                SELECT * FROM (
                    SELECT r.*, r.rowid AS run_rowid, ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(r.chain_root_id, r.id)
                        ORDER BY r.created_at DESC, r.rowid DESC
                    ) AS attempt_rank
                    FROM deliberation_runs r {scope}
                ) WHERE attempt_rank = 1 {after}
                ORDER BY created_at DESC, run_rowid DESC LIMIT ?
            """
            if cursor is not None:
                params.extend(cursor)
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [summarize_run(self._run_from_row(row)) for row in rows]

    def chain_runs(self, chain_root_id: str) -> list[DeliberationRun]:
        """Every attempt in a retry chain, oldest first."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM deliberation_runs "
                "WHERE COALESCE(chain_root_id, id) = ? ORDER BY created_at, rowid",
                (chain_root_id,),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> DeliberationRun | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM deliberation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        run = self._run_from_row(row)
        run.chain_cost = self.chain_cost(run_id)
        return run

    # ------------------------------------------------------------------ the call ledger

    def record_call(self, row: CallRow) -> None:
        """Write one ledger row. Called as each provider request ends, so nothing is lost if a
        run is later cancelled or the process stops."""
        columns = list(CallRow.model_fields)
        values = [int(v) if isinstance(v, bool) else v for v in (getattr(row, c) for c in columns)]
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO provider_calls ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )

    def calls_for_run(self, run_id: str) -> list[CallRow]:
        return self._calls("run_id = ?", (run_id,))

    def calls_for_chain(self, chain_root_id: str) -> list[CallRow]:
        return self._calls("chain_root_id = ?", (chain_root_id,))

    def connectivity_calls(self) -> list[CallRow]:
        return self._calls("run_id IS NULL", ())

    def _calls(self, where: str, params: tuple) -> list[CallRow]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM provider_calls WHERE {where} ORDER BY started_at, rowid", params
            ).fetchall()
        return [
            CallRow.model_validate({**dict(row), "possibly_billed": bool(row["possibly_billed"])})
            for row in rows
        ]

    def provider_activity(self) -> dict[str, dict]:
        """Per provider, from the ledger: the last ok call and the last failed call.

        Only what the ledger recorded. A provider with no rows has no activity, which is
        reported as such and never as healthy.
        """
        activity: dict[str, dict] = {}
        with closing(self._connect()) as connection:
            for row in connection.execute(
                "SELECT provider, MAX(started_at) AS at FROM provider_calls "
                "WHERE outcome = 'ok' GROUP BY provider"
            ):
                activity.setdefault(row["provider"], {})["last_success_at"] = row["at"]
            for row in connection.execute(
                "SELECT provider, outcome, http_status, started_at AS at FROM ("
                " SELECT provider, outcome, http_status, started_at, ROW_NUMBER() OVER ("
                "  PARTITION BY provider ORDER BY started_at DESC, rowid DESC) AS rn"
                " FROM provider_calls WHERE outcome != 'ok') WHERE rn = 1"
            ):
                entry = activity.setdefault(row["provider"], {})
                entry["last_failure_at"] = row["at"]
                entry["last_failure_outcome"] = row["outcome"]
                entry["last_failure_http_status"] = row["http_status"]
        return activity

    def ledger_overview(self, since_iso: str) -> CostSummary | None:
        """Totals over every ledger row since a time (UTC ISO string); None when there are none."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM provider_calls WHERE started_at >= ?", (since_iso,)
            ).fetchall()
        calls = [
            CallRow.model_validate({**dict(r), "possibly_billed": bool(r["possibly_billed"])})
            for r in rows
        ]
        return summarize(calls) if calls else None

    def chain_root_of(self, run_id: str) -> str:
        """The root of the retry chain a run belongs to (the run itself when it is not a retry,
        or is unknown)."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT chain_root_id FROM deliberation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return row["chain_root_id"] if row and row["chain_root_id"] else run_id

    def chain_cost(self, run_id: str) -> CostSummary | None:
        """Totals over every call in a run's retry chain, or None when none were recorded."""
        rows = self.calls_for_chain(self.chain_root_of(run_id))
        return summarize(rows) if rows else None

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
            allow_single_source=bool(row["allow_single_source"]),
            single_source_mode=row["single_source_mode"] or "return_answer",
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
            parent_run_id=row["parent_run_id"] if "parent_run_id" in row.keys() else None,
            chain_root_id=(
                row["chain_root_id"]
                if "chain_root_id" in row.keys() and row["chain_root_id"]
                else row["id"]
            ),
        )


def summarize_run(run: DeliberationRun) -> RunSummary:
    result, panel = run.result, run.result.panel
    question = run.question
    truncated = len(question) > MAX_SUMMARY_QUESTION_CHARS
    return RunSummary(
        id=run.id,
        workspace_id=run.workspace_id,
        question=question[:MAX_SUMMARY_QUESTION_CHARS] if truncated else question,
        question_truncated=truncated,
        created_at=run.created_at,
        updated_at=run.updated_at,
        status=run.status,
        parent_run_id=run.parent_run_id,
        chain_root_id=run.chain_root_id,
        delegate_count=len(panel.delegates),
        successful_count=panel.successful_count,
        failed_count=panel.failed_count,
        independent_source_count=panel.independent_source_count,
        quorum_status=panel.quorum.status if panel.quorum else None,
        critic_status=result.critic.status.value if result.critic else None,
        arbiter_status=result.arbiter.status.value if result.arbiter else None,
        single_source=result.single_source,
        insufficient_evidence=result.insufficient_evidence,
        estimated_cost_usd=result.estimated_cost_usd,
        cost=result.cost,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS = {
    1: WorkspaceStore._migration_1,
    2: WorkspaceStore._migration_2,
    3: WorkspaceStore._migration_3,
}
