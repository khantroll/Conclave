"""P1-11: bounded history, closed connections, a schema version, and a backup before any upgrade."""

from __future__ import annotations

import gc
from contextlib import closing
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.models import (
    RESULT_SCHEMA_VERSION,
    DeliberationResult,
    DelegateResult,
    DelegateStatus,
    PanelResult,
)
from conclave.store import MIGRATION_DESCRIPTIONS, SCHEMA_VERSION, WorkspaceStore

FIXTURE = Path(__file__).parent / "fixtures" / "c2285d6_database.sql"


def _result(question="q", answer="an answer", prompt="a prompt"):
    delegate = DelegateResult(
        name="demo-a", status=DelegateStatus.SUCCEEDED, prompt=prompt, raw_response=answer
    )
    return DeliberationResult(
        panel=PanelResult(
            question=question, delegates=[delegate], successful_count=1, failed_count=0,
            synthesizeable=True,
        ),
        critic=DelegateResult(name="c", status=DelegateStatus.SUCCEEDED, prompt=prompt, raw_response=answer),
        arbiter=DelegateResult(name="a", status=DelegateStatus.SUCCEEDED, prompt=prompt, raw_response=answer),
        estimated_cost_usd=0.01,
    )


def _store_with_runs(tmp_path, count=300, **kwargs):
    store = WorkspaceStore(tmp_path / "t.db")
    ids = [store.save_run(question=f"question {i:03d}", result=_result(f"question {i:03d}"), **kwargs).id for i in range(count)]
    return store, ids


# ----------------------------------------------------------------------------- bounded history


def test_a_list_of_300_runs_returns_50_in_under_100_kb_and_paging_reaches_all_without_repeats(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    ids = [
        store.save_run(question=f"q{i:03d}", result=_result(f"q{i:03d}", answer="long answer " * 400)).id
        for i in range(300)
    ]
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    first = client.get("/api/runs")
    assert first.status_code == 200
    page = first.json()
    assert len(page) == 50 and len(first.content) < 100_000

    seen = [r["id"] for r in page]
    while True:
        more = client.get(f"/api/runs?before={seen[-1]}").json()
        if not more:
            break
        assert len(more) <= 50
        seen += [r["id"] for r in more]
    assert len(seen) == 300 and len(set(seen)) == 300
    assert seen == list(reversed(ids))  # newest first, the whole way


def test_the_size_of_a_list_does_not_grow_with_prompt_or_answer_size(tmp_path):
    small = WorkspaceStore(tmp_path / "s.db")
    big = WorkspaceStore(tmp_path / "b.db")
    for i in range(10):
        small.save_run(question="same question", result=_result(answer="x", prompt="p"))
        big.save_run(question="same question", result=_result(answer="word " * 40_000, prompt="prompt " * 40_000))
    def size(store):
        client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
        return len(client.get("/api/runs").content)
    assert abs(size(big) - size(small)) < 200  # only ids and timestamps differ in length
    assert size(big) < 30_000


def test_a_long_question_is_cut_in_the_summary_and_kept_in_full_in_the_run(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    long_question = "why " * 5000
    run = store.save_run(question=long_question, result=_result())
    [summary] = store.list_run_summaries()
    assert summary.question_truncated is True and len(summary.question) == 300
    assert store.get_run(run.id).question == long_question


def test_a_summary_has_counts_statuses_costs_and_chain_fields_but_no_text_of_answers(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    root = store.save_run(question="q", result=_result())
    child = store.save_run(question="q", result=_result(), parent_run_id=root.id, chain_root_id=root.id)
    [summary] = store.list_run_summaries()
    assert summary.id == child.id and summary.parent_run_id == root.id and summary.chain_root_id == root.id
    assert (summary.delegate_count, summary.successful_count, summary.failed_count) == (1, 1, 0)
    assert (summary.critic_status, summary.arbiter_status, summary.status) == ("succeeded", "succeeded", "complete")
    assert summary.estimated_cost_usd == 0.01
    dumped = json.dumps(summary.model_dump())
    assert "an answer" not in dumped and "a prompt" not in dumped


def test_limit_before_and_the_workspace_variant(tmp_path):
    from conclave.models import WorkspaceCreate

    store = WorkspaceStore(tmp_path / "t.db")
    ws = store.create(WorkspaceCreate(name="w", delegates=["demo-a"], arbiter="demo-a", single_source_mode="return_answer"))
    mine = [store.save_run(question=f"m{i}", result=_result(), workspace_id=ws.id).id for i in range(7)]
    for i in range(5):
        store.save_run(question=f"o{i}", result=_result())
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    path = f"/api/workspaces/{ws.id}/runs"
    page = client.get(f"{path}?limit=3").json()
    assert [r["id"] for r in page] == list(reversed(mine))[:3]
    rest = client.get(f"{path}?limit=10&before={page[-1]['id']}").json()
    assert [r["id"] for r in rest] == list(reversed(mine))[3:]
    assert len(client.get("/api/runs?limit=200").json()) == 12


@pytest.mark.parametrize("limit", [0, -1, 201, "many"])
def test_limit_is_bounded(tmp_path, limit):
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(tmp_path / "t.db")))
    assert client.get(f"/api/runs?limit={limit}").status_code == 422


def test_the_default_limit_is_50_and_the_maximum_200(tmp_path):
    store, _ = _store_with_runs(tmp_path, count=210)
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    assert len(client.get("/api/runs").json()) == 50
    assert len(client.get("/api/runs?limit=200").json()) == 200


def test_an_unknown_before_is_a_404(tmp_path):
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(tmp_path / "t.db")))
    assert client.get("/api/runs?before=nope").status_code == 404


def test_paging_never_skips_or_repeats_when_a_run_arrives_between_pages(tmp_path):
    store, ids = _store_with_runs(tmp_path, count=12)
    first = store.list_run_summaries(limit=5)
    store.save_run(question="arrived later", result=_result())
    second = store.list_run_summaries(limit=5, before=first[-1].id)
    third = store.list_run_summaries(limit=5, before=second[-1].id)
    seen = [r.id for r in (*first, *second, *third)]
    assert seen == list(reversed(ids)) and len(set(seen)) == 12  # the late arrival is on page "0"


def test_paging_with_every_attempt_and_with_chains(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    root = store.save_run(question="q", result=_result())
    kids = [store.save_run(question="q", result=_result(), parent_run_id=root.id, chain_root_id=root.id) for _ in range(3)]
    other = store.save_run(question="other", result=_result())
    default = [r.id for r in store.list_run_summaries(limit=1)]
    assert default == [other.id]
    assert [r.id for r in store.list_run_summaries(limit=5, before=other.id)] == [kids[-1].id]  # newest of the chain
    everything = []
    cursor = None
    while True:
        page = store.list_run_summaries(include_all_attempts=True, limit=2, before=cursor)
        if not page:
            break
        everything += [r.id for r in page]
        cursor = page[-1].id
    assert everything == [other.id, *reversed([k.id for k in kids]), root.id]


def test_full_detail_is_still_available(tmp_path):
    store, ids = _store_with_runs(tmp_path, count=2)
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    run = client.get(f"/api/runs/{ids[0]}").json()
    assert run["result"]["arbiter"]["raw_response"] == "an answer" and run["result"]["arbiter"]["prompt"] == "a prompt"


# ------------------------------------------------------------------------------ connections


def test_connections_are_closed_so_the_file_can_be_removed_at_once(tmp_path):
    path = tmp_path / "t.db"
    store = WorkspaceStore(path)
    from conclave.models import WorkspaceCreate

    ws = store.create(WorkspaceCreate(name="w", delegates=["a"], arbiter="a", single_source_mode="return_answer"))
    run = store.save_run(question="q", result=_result(), workspace_id=ws.id)
    store.update_run(run.id, _result(), "complete")
    store.get(ws.id), store.list(), store.get_run(run.id), store.list_runs(), store.list_run_summaries()
    store.mark_interrupted_runs()
    store.delete(ws.id)
    gc.collect()
    os.remove(path)  # fails on Windows while any connection is still open
    assert not path.exists()


def test_a_second_store_opens_the_same_file_while_the_first_is_in_use(tmp_path):
    path = tmp_path / "t.db"
    one, two = WorkspaceStore(path), WorkspaceStore(path)
    one.save_run(question="q", result=_result())
    assert len(two.list_runs()) == 1


# --------------------------------------------------------------------------- schema version


def test_a_new_database_has_every_step_recorded_and_no_backup(tmp_path):
    path = tmp_path / "t.db"
    store = WorkspaceStore(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT version, description FROM schema_version ORDER BY version").fetchall()
    assert rows == [(v, MIGRATION_DESCRIPTIONS[v]) for v in range(1, SCHEMA_VERSION + 1)]
    assert store.last_backup is None and list(tmp_path.glob("*.bak-*")) == []


def test_results_carry_a_schema_version(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    created = store.create_run(question="q")
    assert store.get_run(created.id).result.schema_version == RESULT_SCHEMA_VERSION
    legacy = DeliberationResult.model_validate(
        {"panel": {"question": "q", "delegates": [], "successful_count": 0, "failed_count": 0, "synthesizeable": False}}
    )
    assert legacy.schema_version is None  # an old row is not mislabelled as current


def test_a_run_saved_through_the_orchestrator_has_the_result_schema_version(tmp_path):
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(tmp_path / "t.db")))
    body = {"question": "q", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-a", "minimum_successes": 1}
    run_id = client.post("/api/deliberate", json=body).headers["X-Conclave-Run-ID"]
    assert client.get(f"/api/runs/{run_id}").json()["result"]["schema_version"] == RESULT_SCHEMA_VERSION


# ----------------------------------------------------------------------- upgrading a database


def _old_database(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_really_is_an_unversioned_old_database(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)
    with sqlite3.connect(path) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        run_columns = {r[1] for r in connection.execute("PRAGMA table_info(deliberation_runs)")}
    assert tables == {"deliberation_runs", "workspaces"}
    assert "status" not in run_columns and "parent_run_id" not in run_columns


def test_a_c2285d6_database_migrates_with_a_backup_and_everything_stays_readable(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)
    before = path.read_bytes()

    store = WorkspaceStore(path)
    backups = list(tmp_path.glob("old.db.bak-*"))
    assert len(backups) == 1 and store.last_backup == backups[0]
    assert backups[0].name.startswith("old.db.bak-0-")  # from schema 0: it had no version
    # The backup is a faithful, openable copy of the database as it was.
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM deliberation_runs").fetchone()[0] == 4
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # The copy is of the database as it was: still unversioned.
        assert "schema_version" not in {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}
    with sqlite3.connect(backups[0]) as connection:
        run_columns = {r[1] for r in connection.execute("PRAGMA table_info(deliberation_runs)")}
    assert "status" not in run_columns  # the copy was taken before any step ran
    assert path.read_bytes() != before  # the original was migrated

    workspaces = store.list()
    assert [w.name for w in workspaces] == ["Legacy workspace"]
    assert workspaces[0].delegates == ["demo-a", "demo-b"] and workspaces[0].roles == {"demo-a": "skeptic"}
    assert workspaces[0].allow_single_source is False and workspaces[0].single_source_mode in (None, "return_answer")
    runs = store.list_runs(include_all_attempts=True)
    assert len(runs) == 4
    assert {r.question for r in runs} == {"Legacy question 1", "Legacy question 2", "Legacy question 3", "Detached legacy run"}
    for run in runs:
        assert run.status == "complete" and run.chain_root_id == run.id and run.parent_run_id is None
        assert run.result.schema_version is None and run.result.panel.successful_count == 2
    summaries = store.list_run_summaries()
    assert len(summaries) == 4 and all(s.delegate_count == 2 for s in summaries)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION


def test_a_migrated_database_works_end_to_end_through_the_app(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(path)))
    runs = client.get("/api/runs").json()
    assert len(runs) == 4
    detail = client.get(f"/api/runs/{runs[0]['id']}").json()
    assert detail["result"]["arbiter"]["status"] == "succeeded"
    # A legacy run has no request snapshot of the newer kind but is retryable only if it has one.
    body = {"question": "q", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-a", "minimum_successes": 1}
    assert client.post("/api/deliberate", json=body).status_code == 200
    assert len(client.get("/api/runs").json()) == 5


def test_a_second_start_does_nothing(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)
    WorkspaceStore(path)
    backups = sorted(tmp_path.glob("old.db.bak-*"))
    with sqlite3.connect(path) as connection:
        applied = connection.execute("SELECT version, applied_at FROM schema_version ORDER BY version").fetchall()
    snapshot = path.read_bytes()
    again = WorkspaceStore(path)
    assert again.last_backup is None  # no new backup
    assert sorted(tmp_path.glob("old.db.bak-*")) == backups
    assert path.read_bytes() == snapshot  # not even touched
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version, applied_at FROM schema_version ORDER BY version").fetchall() == applied


def test_a_database_with_current_tables_but_no_version_is_backed_up_once_and_versioned(tmp_path):
    path = tmp_path / "t.db"
    WorkspaceStore(path).save_run(question="q", result=_result())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE schema_version")  # as left by a build from before versioning
    store = WorkspaceStore(path)
    assert store.last_backup is not None and store.last_backup.exists()
    assert len(store.list_runs()) == 1
    assert WorkspaceStore(path).last_backup is None


def test_each_step_runs_in_turn_from_wherever_the_database_is(tmp_path):
    path = tmp_path / "t.db"
    WorkspaceStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM schema_version WHERE version >= 3")
        connection.execute("DROP INDEX idx_deliberation_runs_chain")
        connection.execute("ALTER TABLE deliberation_runs DROP COLUMN parent_run_id")
        connection.execute("ALTER TABLE deliberation_runs DROP COLUMN chain_root_id")
    store = WorkspaceStore(path)
    assert store.last_backup is not None and ".bak-2-" in store.last_backup.name
    with sqlite3.connect(path) as connection:
        assert {r[1] for r in connection.execute("PRAGMA table_info(deliberation_runs)")} >= {"parent_run_id", "chain_root_id"}
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION


def test_migrating_never_happens_without_a_backup(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _old_database(path)
    before = path.read_bytes()

    def broken_backup(self, *, from_version):
        raise OSError("disk full")

    monkeypatch.setattr(WorkspaceStore, "_backup", broken_backup)
    with pytest.raises(OSError, match="disk full"):
        WorkspaceStore(path)
    assert path.read_bytes() == before  # not one step ran
    with sqlite3.connect(path) as connection:
        assert "provider_calls" not in {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}


def test_a_backup_that_fails_verification_stops_the_migration_and_is_removed(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _old_database(path)
    before = path.read_bytes()
    monkeypatch.setattr(WorkspaceStore, "_check_backup", staticmethod(lambda target: "page 3 is corrupt"))
    with pytest.raises(RuntimeError, match="failed its integrity check: page 3 is corrupt"):
        WorkspaceStore(path)
    assert list(tmp_path.glob("old.db.bak-*")) == []  # the bad copy is not left behind
    assert path.read_bytes() == before  # and nothing was migrated


def test_a_database_from_a_newer_conclave_is_refused_untouched(tmp_path):
    path = tmp_path / "t.db"
    WorkspaceStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO schema_version VALUES (?, ?, ?)", (SCHEMA_VERSION + 1, "x", "future"))
    snapshot = path.read_bytes()
    with pytest.raises(RuntimeError, match="newer than this Conclave"):
        WorkspaceStore(path)
    assert path.read_bytes() == snapshot and list(tmp_path.glob("*.bak-*")) == []


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _old_database(path)
    monkeypatch.setattr(WorkspaceStore, "_backup_stamp", staticmethod(lambda: "20260101T000000Z"))
    made = [WorkspaceStore(path).last_backup]
    for _ in range(2):
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM schema_version")
        made.append(WorkspaceStore(path).last_backup)
    assert len(set(made)) == 3 and all(m.exists() for m in made)
    assert made[0].name == "old.db.bak-0-20260101T000000Z"
    assert made[1].name.endswith("-2") and made[2].name.endswith("-3")


def test_every_connection_the_store_opens_is_closed(tmp_path, monkeypatch):
    """Not merely collected later: closed by the operation that opened it."""
    opened = []

    class Tracked(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    real = sqlite3.connect

    def connect(target, *args, **kwargs):
        connection = real(target, *args, factory=Tracked, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr("conclave.store.sqlite3.connect", connect)
    from conclave.models import WorkspaceCreate, WorkspaceReplace

    path = tmp_path / "old.db"
    _old_database(path)  # so the upgrade and its backup are exercised too
    store = WorkspaceStore(path)
    ws = store.create(WorkspaceCreate(name="w", delegates=["a"], arbiter="a", single_source_mode="return_answer"))
    store.replace(ws.id, WorkspaceReplace(name="w2", delegates=["a"], arbiter="a", single_source_mode="return_answer"))
    run = store.save_run(question="q", result=_result(), workspace_id=ws.id)
    created = store.create_run(question="q2")
    store.update_run(created.id, _result(), "running")
    store.mark_interrupted(created.id)
    store.mark_interrupted_runs()
    store.discard_run(created.id)
    store.get(ws.id), store.list(), store.get_run(run.id), store.list_runs(include_all_attempts=True)
    store.list_runs(ws.id), store.list_run_summaries(), store.list_run_summaries(ws.id, include_all_attempts=True)
    store.chain_runs(run.id), store.chain_root_of(run.id), store.chain_cost(run.id)
    store.calls_for_run(run.id), store.calls_for_chain(run.id), store.connectivity_calls()
    store.delete(ws.id)
    assert len(opened) > 20
    assert [c for c in opened if not c.closed] == []


# --------------------------------------------- any existing file, WAL, failure and concurrency


def test_any_non_empty_file_is_backed_up_whatever_it_contains(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE something_else (x TEXT)")
        connection.execute("INSERT INTO something_else VALUES ('keep me')")
    store = WorkspaceStore(path)
    assert store.last_backup is not None
    with closing(sqlite3.connect(store.last_backup)) as backup:
        assert backup.execute("SELECT x FROM something_else").fetchall() == [("keep me",)]
        assert "workspaces" not in {r[0] for r in backup.execute("SELECT name FROM sqlite_master")}
    with closing(sqlite3.connect(path)) as migrated:
        assert migrated.execute("SELECT x FROM something_else").fetchall() == [("keep me",)]  # untouched


def test_a_file_that_is_not_a_database_is_left_alone(tmp_path):
    path = tmp_path / "t.db"
    path.write_bytes(b"this is not a sqlite database " * 20)
    before = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        WorkspaceStore(path)
    assert path.read_bytes() == before and list(tmp_path.glob("*.bak-*")) == []


def test_an_empty_file_is_a_new_database_with_nothing_to_back_up(tmp_path):
    path = tmp_path / "t.db"
    path.write_bytes(b"")
    store = WorkspaceStore(path)
    assert store.last_backup is None and store.list() == []


def test_a_wal_database_with_unmerged_changes_is_backed_up_completely(tmp_path):
    path = tmp_path / "old.db"
    _old_database(path)
    holder = sqlite3.connect(path)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("PRAGMA wal_autocheckpoint=0")  # keep new rows in the -wal file
    holder.execute("INSERT INTO workspaces (id, name, delegates_json, roles_json, arbiter, minimum_successes, created_at, updated_at) "
                   "VALUES ('wal-ws', 'only in the WAL', '[\"a\"]', '{}', 'a', 1, 't', 't')")
    holder.commit()
    assert Path(f"{path}-wal").exists() and Path(f"{path}-wal").stat().st_size > 0
    try:
        store = WorkspaceStore(path)
    finally:
        holder.close()
    with closing(sqlite3.connect(store.last_backup)) as backup:
        names = {r[0] for r in backup.execute("SELECT name FROM workspaces")}
        assert "only in the WAL" in names and backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM deliberation_runs").fetchone()[0] == 4
    assert "only in the WAL" in {w.name for w in WorkspaceStore(path).list()}


def test_a_failed_step_changes_nothing_and_the_next_start_succeeds(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _old_database(path)
    before = path.read_bytes()
    real = WorkspaceStore._migration_3

    def explode(self, connection):
        raise RuntimeError("step 3 failed")

    monkeypatch.setitem(__import__("conclave.store", fromlist=["MIGRATIONS"]).MIGRATIONS, 3, explode)
    with pytest.raises(RuntimeError, match="step 3 failed"):
        WorkspaceStore(path)
    assert path.read_bytes() == before  # steps 1 and 2 were rolled back with it
    with closing(sqlite3.connect(path)) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master")}
        assert "provider_calls" not in tables and "schema_version" not in tables
    assert len(list(tmp_path.glob("old.db.bak-*"))) == 1  # the backup was made first

    monkeypatch.setitem(__import__("conclave.store", fromlist=["MIGRATIONS"]).MIGRATIONS, 3, real)
    store = WorkspaceStore(path)
    assert len(store.list_runs(include_all_attempts=True)) == 4
    assert len(list(tmp_path.glob("old.db.bak-*"))) == 2  # and a new one for the second attempt


def test_two_starts_at_once_migrate_once_with_one_backup(tmp_path):
    import threading

    path = tmp_path / "old.db"
    _old_database(path)
    barrier = threading.Barrier(4)
    stores, errors = [], []

    def start():
        try:
            barrier.wait()
            stores.append(WorkspaceStore(path))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(stores) == 4
    assert len(list(tmp_path.glob("old.db.bak-*"))) == 1  # exactly one start upgraded it
    assert sum(1 for s in stores if s.last_backup is not None) == 1
    with closing(sqlite3.connect(path)) as connection:
        versions = [r[0] for r in connection.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == list(range(1, SCHEMA_VERSION + 1))
    assert len(stores[0].list_runs(include_all_attempts=True)) == 4
