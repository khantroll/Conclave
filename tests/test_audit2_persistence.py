"""Second audit, findings 1 and 2: cancelled work is kept and recoverable, in runs and in retries."""

from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

import conclave.api as api_module
from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.providers.fake import FakeProvider
from conclave.store import WorkspaceStore

BODY = {"question": "Should we ship?", "delegates": ["demo-a", "demo-b"], "critic": "demo-critic",
        "arbiter": "demo-arbiter", "single_source_mode": "arbiter_single_source", "minimum_successes": 2}


def app_with(monkeypatch, store, slow=()):
    def make(response="ok", **kwargs):
        return FakeProvider(response, delay_seconds=5 if response in slow else 0, **kwargs)

    monkeypatch.setattr(api_module, "FakeProvider", make)
    return create_app(config=ConclaveConfig(), workspace_store=store)


async def cancelled(app, method, url, timeout=1.0, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as http:
        try:
            await asyncio.wait_for(http.request(method, url, **kw), timeout)
        except asyncio.TimeoutError:
            return
    raise AssertionError("request was not cancelled")


def test_a_cancelled_slot_stays_recoverable_and_its_retry_inserts_the_result(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "t.db")
    asyncio.run(cancelled(app_with(monkeypatch, store, {"Delegate A response"}), "POST", "/api/deliberate", json=BODY))
    [run] = store.list_runs(include_all_attempts=True)
    by = {d.name: d for d in run.result.panel.delegates}
    assert run.status == "interrupted"
    assert by["demo-b"].status.value == "succeeded" and by["demo-b"].raw_response  # completed work kept
    assert (by["demo-a"].status.value, by["demo-a"].error_kind) == ("failed", "cancelled")  # a visible, recoverable slot

    client = TestClient(app_with(monkeypatch, store), base_url="http://127.0.0.1")
    retried = client.post(f"/api/runs/{run.id}/delegates/demo-a/retry")
    assert retried.status_code == 200
    after = {d["name"]: d for d in retried.json()["result"]["panel"]["delegates"]}
    assert after["demo-a"]["status"] == "succeeded" and after["demo-a"]["raw_response"]  # inserted, not dropped
    assert after["demo-b"]["raw_response"] == by["demo-b"].raw_response  # the kept answer was not re-run
    assert retried.json()["result"]["arbiter"]["status"] == "succeeded"
    assert retried.json()["parent_run_id"] == run.id


def test_a_cancelled_critic_retry_keeps_the_new_critic_and_its_lineage(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "t.db")
    first = TestClient(app_with(monkeypatch, store), base_url="http://127.0.0.1").post("/api/deliberate", json=BODY)
    root = first.headers["X-Conclave-Run-ID"]
    # Now the Arbiter is slow: the retry's Critic completes, then its Arbiter is cancelled.
    asyncio.run(cancelled(app_with(monkeypatch, store, {"Synthesized demo response"}), "POST", f"/api/runs/{root}/critic/retry"))
    runs = store.list_runs(include_all_attempts=True)
    retry = next(r for r in runs if r.id != root)
    assert retry.status == "interrupted"
    assert retry.parent_run_id == root and retry.chain_root_id == root  # lineage survives
    assert retry.result.critic is not None and retry.result.critic.status.value == "succeeded"  # the new Critic is kept
    assert retry.result.arbiter is None
    assert len(retry.result.panel.delegates) == 2  # the panel it builds on
    rows = store.calls_for_run(retry.id)
    assert [r.stage for r in rows] == ["critic", "arbiter"] and rows[-1].outcome == "cancelled"
    assert store.get_run(root).status == "complete"  # the original is untouched


def test_a_cancelled_arbiter_retry_before_it_answers_leaves_the_panel_and_critic(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "t.db")
    root = TestClient(app_with(monkeypatch, store), base_url="http://127.0.0.1").post("/api/deliberate", json=BODY).headers["X-Conclave-Run-ID"]
    asyncio.run(cancelled(app_with(monkeypatch, store, {"Synthesized demo response"}), "POST", f"/api/runs/{root}/arbiter/retry"))
    retry = next(r for r in store.list_runs(include_all_attempts=True) if r.id != root)
    assert retry.status == "interrupted" and retry.parent_run_id == root
    assert len(retry.result.panel.delegates) == 2  # not an empty shell
