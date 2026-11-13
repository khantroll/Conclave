"""P1-13 interim rule: there is no Critic default. Saving a workspace must state the choice."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.store import WorkspaceStore

BASE = {"name": "w", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-arbiter", "single_source_mode": "return_answer"}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(tmp_path / "t.db")))


def test_a_workspace_without_a_critic_choice_is_refused(client):
    refused = client.post("/api/workspaces", json=BASE)
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert "critic is required" in detail and "null for no Critic" in detail and "not been measured" in detail
    assert client.get("/api/workspaces").json() == []  # nothing was saved


def test_an_explicit_null_is_a_valid_choice(client):
    created = client.post("/api/workspaces", json={**BASE, "critic": None})
    assert created.status_code == 201 and created.json()["critic"] is None


def test_a_provider_name_is_a_valid_choice(client):
    created = client.post("/api/workspaces", json={**BASE, "critic": "demo-critic"})
    assert created.status_code == 201 and created.json()["critic"] == "demo-critic"


def test_an_unknown_critic_provider_is_still_refused(client):
    refused = client.post("/api/workspaces", json={**BASE, "critic": "nobody"})
    assert refused.status_code == 422 and "nobody" in refused.text


def test_replacing_a_workspace_must_choose_again(client):
    created = client.post("/api/workspaces", json={**BASE, "critic": "demo-critic"}).json()
    refused = client.put(f"/api/workspaces/{created['id']}", json=BASE)
    assert refused.status_code == 422 and "critic is required" in refused.json()["detail"]
    assert client.get(f"/api/workspaces/{created['id']}").json()["critic"] == "demo-critic"  # unchanged
    kept = client.put(f"/api/workspaces/{created['id']}", json={**BASE, "critic": None})
    assert kept.status_code == 200 and kept.json()["critic"] is None


def test_the_choice_is_checked_before_the_other_choices_are(client):
    # Both are missing: the Critic is reported first, then (once given) the single-source mode.
    body = {"name": "w", "delegates": ["demo-a"], "arbiter": "demo-arbiter"}
    assert "critic is required" in client.post("/api/workspaces", json=body).json()["detail"]
    assert "single_source_mode is required" in client.post("/api/workspaces", json={**body, "critic": None}).json()["detail"]


def test_workspaces_saved_before_this_rule_still_load_and_run(tmp_path):
    from conclave.models import WorkspaceCreate

    store = WorkspaceStore(tmp_path / "t.db")
    legacy = store.create(WorkspaceCreate(name="old", delegates=["demo-a", "demo-b"], arbiter="demo-arbiter"))
    assert legacy.critic is None  # stored without a stated choice; reading it is unchanged
    app_client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    assert app_client.get(f"/api/workspaces/{legacy.id}").status_code == 200
    run = app_client.post(f"/api/workspaces/{legacy.id}/deliberate", json={"question": "q"})
    assert run.status_code == 200
