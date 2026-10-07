from fastapi.testclient import TestClient

from conclave.api import app, create_app
from conclave.store import WorkspaceStore

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider_count"] >= 4


def test_provider_names():
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "demo-a" in providers
    assert "demo-b" in providers
    assert "demo-critic" in providers
    assert "demo-arbiter" in providers


def test_demo_deliberation_runs_panel_critic_and_arbiter():
    response = client.post(
        "/api/deliberate",
        json={
            "question": "Should Conclave survive partial failures?",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "roles": {
                "demo-a": "Focus on reliability.",
                "demo-b": "Challenge the architecture.",
            },
            "workspace_context": "Conclave is a deterministic multi-model orchestrator.",
            "minimum_successes": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["panel"]["successful_count"] == 2
    assert body["critic"]["status"] == "succeeded"
    assert body["critic"]["raw_response"] == "Critic demo response"
    assert body["arbiter"]["status"] == "succeeded"
    assert body["arbiter"]["raw_response"] == "Synthesized demo response"


def test_deliberation_skips_critic_and_arbiter_without_quorum():
    response = client.post(
        "/api/deliberate",
        json={
            "question": "test",
            "delegates": ["missing-provider", "demo-a"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "minimum_successes": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["panel"]["synthesizeable"] is False
    assert body["critic"] is None
    assert body["arbiter"] is None


def test_workspace_persists_defaults_and_runs_deliberation(tmp_path):
    store = WorkspaceStore(tmp_path / "test.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "HomeLedger",
            "description": "Personal finance project",
            "context": "Local-first; preserve privacy.",
            "delegates": ["demo-a", "demo-b"],
            "roles": {"demo-b": "Act as the skeptical reviewer."},
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "minimum_successes": 1,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    listed = workspace_client.get("/api/workspaces")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "HomeLedger"

    result = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "Should we add forecasting?"},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["panel"]["successful_count"] == 2
    assert body["critic"]["status"] == "succeeded"
    assert body["arbiter"]["status"] == "succeeded"
