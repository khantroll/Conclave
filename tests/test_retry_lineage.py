"""P1-10: retries are linked into a chain, listed once, and run one at a time."""

from __future__ import annotations

import asyncio
import sqlite3

import httpx
from fastapi.testclient import TestClient

from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.models import DeliberationResult, PanelResult
from conclave.providers.fake import FakeProvider
from conclave.store import WorkspaceStore

BODY = {
    "question": "q", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-a",
    "critic": "demo-critic", "minimum_successes": 1,
}


def _client(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    return TestClient(create_app(config=ConclaveConfig(), workspace_store=store)), store


def _deliberate(client, **extra):
    response = client.post("/api/deliberate", json={**BODY, **extra})
    assert response.status_code == 200, response.text
    return response.headers["X-Conclave-Run-ID"]


def _empty():
    return DeliberationResult(
        panel=PanelResult(question="q", delegates=[], successful_count=0, failed_count=0, synthesizeable=False)
    )


# ---------------------------------------------------------------------------- lineage


def test_a_new_run_is_its_own_chain_root_with_no_parent(tmp_path):
    client, store = _client(tmp_path)
    run_id = _deliberate(client)
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["parent_run_id"] is None and run["chain_root_id"] == run_id


def test_a_retry_records_its_parent_and_the_root(tmp_path):
    client, store = _client(tmp_path)
    root = _deliberate(client)
    first = client.post(f"/api/runs/{root}/arbiter/retry").json()
    second = client.post(f"/api/runs/{first['id']}/critic/retry").json()
    third = client.post(f"/api/runs/{second['id']}/arbiter/retry").json()
    assert (first["parent_run_id"], first["chain_root_id"]) == (root, root)
    assert (second["parent_run_id"], second["chain_root_id"]) == (first["id"], root)
    assert (third["parent_run_id"], third["chain_root_id"]) == (second["id"], root)
    # The stored rows say the same.
    assert store.get_run(third["id"]).parent_run_id == second["id"]


def test_every_run_is_reachable_from_its_chain_root(tmp_path):
    client, store = _client(tmp_path)
    root = _deliberate(client)
    ids = [root]
    for stage in ("arbiter", "critic", "arbiter"):
        ids.append(client.post(f"/api/runs/{ids[-1]}/{stage}/retry").json()["id"])
    chain = client.get(f"/api/runs/{ids[2]}/chain").json()  # asked from the middle
    assert [r["id"] for r in chain] == ids  # root to newest
    by_id = {r["id"]: r for r in chain}
    for run in chain:  # walking parents always arrives at the root
        node = run
        while node["parent_run_id"] is not None:
            node = by_id[node["parent_run_id"]]
        assert node["id"] == root


def test_a_separate_run_is_a_separate_chain(tmp_path):
    client, store = _client(tmp_path)
    one, two = _deliberate(client), _deliberate(client)
    client.post(f"/api/runs/{one}/arbiter/retry")
    assert [r["id"] for r in client.get(f"/api/runs/{two}/chain").json()] == [two]
    assert len(client.get(f"/api/runs/{one}/chain").json()) == 2


def test_order_and_labels_match_across_the_chain(tmp_path):
    client, store = _client(tmp_path)
    root = _deliberate(client, delegates=["demo-a", "demo-b", "demo-critic"], minimum_successes=2)
    a = client.post(f"/api/runs/{root}/arbiter/retry").json()
    b = client.post(f"/api/runs/{a['id']}/critic/retry").json()
    runs = [client.get(f"/api/runs/{root}").json(), a, b]
    assert len({r["request"]["seed"] for r in runs}) == 1  # the chain keeps its seed
    maps = [r["result"]["label_map"] for r in runs]
    assert maps[0] and maps[0] == maps[1] == maps[2]
    assert len({str(r["result"]["positions"]) for r in runs}) == 1


def test_a_run_saved_before_lineage_reads_as_its_own_root_and_retries_into_a_chain(tmp_path):
    path = tmp_path / "old.db"
    store = WorkspaceStore(path, run_log_dir=tmp_path / "logs")
    run = store.save_run(question="q", result=_empty())
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE deliberation_runs SET chain_root_id = NULL, parent_run_id = NULL")
    old = WorkspaceStore(path).get_run(run.id)
    assert old.chain_root_id == run.id and old.parent_run_id is None
    assert [r.id for r in WorkspaceStore(path).list_runs()] == [run.id]
    assert [r.id for r in WorkspaceStore(path).chain_runs(run.id)] == [run.id]


def test_the_lineage_columns_are_added_to_an_older_database(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE deliberation_runs (id TEXT PRIMARY KEY, workspace_id TEXT, question TEXT NOT NULL,"
            " request_json TEXT, result_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO deliberation_runs (id, question, result_json, created_at) VALUES (?, ?, ?, ?)",
            ("legacy", "q", _empty().model_dump_json(), "2026-01-01T00:00:00+00:00"),
        )
    store = WorkspaceStore(path)
    run = store.get_run("legacy")
    assert (run.parent_run_id, run.chain_root_id) == (None, "legacy")


# -------------------------------------------------------------------------------- history


def test_history_lists_the_newest_run_of_each_chain(tmp_path):
    client, store = _client(tmp_path)
    one = _deliberate(client)
    two = _deliberate(client)
    retry = client.post(f"/api/runs/{one}/arbiter/retry").json()["id"]
    newest = client.post(f"/api/runs/{retry}/critic/retry").json()["id"]
    listed = [r["id"] for r in client.get("/api/runs").json()]
    assert listed == [newest, two]  # one chain of three attempts shows once, as its newest
    everything = [r["id"] for r in client.get("/api/runs?all_attempts=true").json()]
    assert set(everything) == {one, two, retry, newest} and len(everything) == 4


def test_the_default_listing_is_stable_when_timestamps_tie(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    root = store.save_run(question="q", result=_empty())
    child = store.save_run(question="q", result=_empty(), parent_run_id=root.id, chain_root_id=root.id)
    with sqlite3.connect(tmp_path / "t.db") as connection:
        connection.execute("UPDATE deliberation_runs SET created_at = '2026-01-01T00:00:00+00:00'")
    assert [r.id for r in store.list_runs()] == [child.id]


def test_a_running_retry_is_listed_as_the_newest_attempt(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    root = store.save_run(question="q", result=_empty())
    running = store.create_run(question="q", parent_run_id=root.id, chain_root_id=root.id)
    assert [r.id for r in store.list_runs()] == [running.id]


# --------------------------------------------------------------- one retry at a time


async def _slow_app(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    app = create_app(config=ConclaveConfig(), workspace_store=store)
    return app, store


def test_a_second_retry_in_the_same_chain_gets_409_while_one_is_running(tmp_path, monkeypatch):
    import conclave.api as api_module

    gate = {"release": None}

    class Slow(FakeProvider):
        async def ask(self, prompt):
            # demo-a is the Arbiter in BODY: once the gate exists, its next call waits.
            if gate["release"] is not None and not gate.get("taken") and self.response.startswith("Delegate A"):
                gate["taken"] = True  # only the retry under test waits; later calls run freely
                await gate["release"].wait()
            return await super().ask(prompt)

    monkeypatch.setattr(api_module, "FakeProvider", lambda response="ok", **kw: Slow(response, **kw))

    async def scenario():
        app, store = await _slow_app(tmp_path)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            root = (await client.post("/api/deliberate", json=BODY)).headers["X-Conclave-Run-ID"]
            gate["release"] = asyncio.Event()
            first = asyncio.ensure_future(client.post(f"/api/runs/{root}/arbiter/retry"))
            await asyncio.sleep(0.1)  # the first retry is now holding the chain
            second = await client.post(f"/api/runs/{root}/critic/retry")
            third = await client.post(f"/api/runs/{root}/arbiter/retry")
            other = await client.post("/api/deliberate", json=BODY)  # another chain is unaffected
            gate["release"].set()
            done = await first
            after = await client.post(f"/api/runs/{root}/arbiter/retry")  # free again
            return second, third, other, done, after, store

    second, third, other, done, after, store = asyncio.run(scenario())
    assert second.status_code == 409 and "already running" in second.json()["detail"]
    assert third.status_code == 409
    assert other.status_code == 200
    assert done.status_code == 200 and after.status_code == 200
    assert not [r for r in store.list_runs(include_all_attempts=True) if r.status == "running"]


def test_the_lock_is_released_when_a_retry_is_refused_or_fails(tmp_path):
    client, store = _client(tmp_path)
    run_id = client.post(
        "/api/deliberate",
        json={"question": "q", "delegates": ["demo-a"], "arbiter": "demo-a", "minimum_successes": 1,
              "allow_single_source": True, "single_source_mode": "return_answer"},
    ).headers["X-Conclave-Run-ID"]
    for _ in range(2):  # a refusal (no Critic on a single-source run) must not leave the chain locked
        assert client.post(f"/api/runs/{run_id}/critic/retry").status_code == 409
    assert client.post(f"/api/runs/{run_id}/arbiter/retry").status_code == 409  # refused, not "running"
    assert "already running" not in client.post(f"/api/runs/{run_id}/critic/retry").text


# ----------------------------------------------------------- retrying a succeeded delegate


def test_retrying_a_succeeded_delegate_needs_force(tmp_path):
    client, store = _client(tmp_path)
    root = _deliberate(client)
    refused = client.post(f"/api/runs/{root}/delegates/demo-a/retry")
    assert refused.status_code == 409 and "already succeeded" in refused.json()["detail"]
    assert len(store.list_runs(include_all_attempts=True)) == 1  # nothing was created or spent
    forced = client.post(f"/api/runs/{root}/delegates/demo-a/retry?force=true")
    assert forced.status_code == 200 and forced.json()["parent_run_id"] == root


def test_retrying_a_failed_delegate_needs_no_force(tmp_path, monkeypatch):
    import conclave.api as api_module

    made = {}

    def make(response="ok", **kwargs):
        made[response] = FakeProvider(response, **kwargs)
        return made[response]

    monkeypatch.setattr(api_module, "FakeProvider", make)
    client, store = _client(tmp_path)
    made["Delegate B response"].error = RuntimeError("down")
    root = _deliberate(client)
    made["Delegate B response"].error = None
    retried = client.post(f"/api/runs/{root}/delegates/demo-b/retry")
    assert retried.status_code == 200
    assert [d["status"] for d in retried.json()["result"]["panel"]["delegates"]] == ["succeeded", "succeeded"]


def test_an_unknown_delegate_is_still_a_404_and_leaves_nothing(tmp_path):
    client, store = _client(tmp_path)
    root = _deliberate(client)
    refused = client.post(f"/api/runs/{root}/delegates/nobody/retry")
    assert refused.status_code == 404
    assert len(store.list_runs(include_all_attempts=True)) == 1


def test_the_lock_covers_the_whole_chain_not_just_the_run_being_retried(tmp_path, monkeypatch):
    import conclave.api as api_module

    gate = {"release": None}

    class Slow(FakeProvider):
        async def ask(self, prompt):
            if gate["release"] is not None and not gate.get("taken") and self.response.startswith("Delegate A"):
                gate["taken"] = True
                await gate["release"].wait()
            return await super().ask(prompt)

    monkeypatch.setattr(api_module, "FakeProvider", lambda response="ok", **kw: Slow(response, **kw))

    async def scenario():
        app, store = await _slow_app(tmp_path)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            root = (await client.post("/api/deliberate", json=BODY)).headers["X-Conclave-Run-ID"]
            child = (await client.post(f"/api/runs/{root}/arbiter/retry")).json()["id"]
            gate["release"] = asyncio.Event()
            running = asyncio.ensure_future(client.post(f"/api/runs/{child}/arbiter/retry"))
            await asyncio.sleep(0.1)
            # A different run of the same chain: still the same chain, so still refused.
            from_root = await client.post(f"/api/runs/{root}/critic/retry")
            gate["release"].set()
            await running
            return from_root

    assert asyncio.run(scenario()).status_code == 409


def test_an_unexpected_failure_interrupts_the_retry_and_frees_the_chain(tmp_path, monkeypatch):
    from conclave.orchestrator import Orchestrator

    client, store = _client(tmp_path)
    root = _deliberate(client)
    real = Orchestrator.retry_arbiter

    async def explode(self, **kwargs):
        raise RuntimeError("the retry blew up")

    monkeypatch.setattr(Orchestrator, "retry_arbiter", explode)
    quiet = TestClient(client.app, raise_server_exceptions=False)
    assert quiet.post(f"/api/runs/{root}/arbiter/retry").status_code == 500
    attempts = store.list_runs(include_all_attempts=True)
    assert sorted(r.status for r in attempts) == ["complete", "interrupted"]
    assert not any(r.status == "running" for r in attempts)

    monkeypatch.setattr(Orchestrator, "retry_arbiter", real)  # the chain is free again
    assert quiet.post(f"/api/runs/{root}/arbiter/retry").status_code == 200


def test_a_cancelled_retry_frees_the_chain_too(tmp_path, monkeypatch):
    from conclave.orchestrator import Orchestrator

    client, store = _client(tmp_path)
    root = _deliberate(client)
    real = Orchestrator.retry_arbiter

    async def cancelled(self, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(Orchestrator, "retry_arbiter", cancelled)
    try:
        client.post(f"/api/runs/{root}/arbiter/retry")
    except BaseException:
        pass
    assert "interrupted" in [r.status for r in store.list_runs(include_all_attempts=True)]
    monkeypatch.setattr(Orchestrator, "retry_arbiter", real)
    assert client.post(f"/api/runs/{root}/arbiter/retry").status_code == 200


def test_the_force_check_looks_at_the_run_being_retried_from(tmp_path, monkeypatch):
    import conclave.api as api_module

    made = {}

    def make(response="ok", **kwargs):
        made[response] = FakeProvider(response, **kwargs)
        return made[response]

    monkeypatch.setattr(api_module, "FakeProvider", make)
    client, store = _client(tmp_path)
    made["Delegate B response"].error = RuntimeError("down")
    failed_run = _deliberate(client)  # demo-b failed here
    made["Delegate B response"].error = None
    fixed = client.post(f"/api/runs/{failed_run}/delegates/demo-b/retry").json()["id"]
    # The retry builds on the run it is sent from: demo-b failed in `failed_run`, so no force is
    # needed there, while in the newer run it succeeded, so force is needed.
    assert client.post(f"/api/runs/{fixed}/delegates/demo-b/retry").status_code == 409
    assert client.post(f"/api/runs/{failed_run}/delegates/demo-b/retry").status_code == 200
    assert client.post(f"/api/runs/{fixed}/delegates/demo-b/retry?force=true").status_code == 200
