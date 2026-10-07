from fastapi.testclient import TestClient

from conclave.api import app, create_app
from conclave.store import WorkspaceStore

client = TestClient(app)


def test_web_console_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Conclave" in response.text
    assert "/static/app.js" in response.text


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider_count"] >= 4


def test_request_analysis_recommends_panel_for_complex_question():
    response = client.post(
        "/api/analyze",
        json={
            "question": (
                "Compare two architecture strategies, identify implementation risks, "
                "failure modes, tradeoffs, and recommend a roadmap with evidence."
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommended_delegate_count"] >= 3
    assert body["complexity"] in {"complex", "deep"}


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


def test_workspace_persists_defaults_run_and_history(tmp_path):
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

    result = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "Should we add forecasting?"},
    )
    assert result.status_code == 200
    assert result.headers["X-Conclave-Run-ID"]
    body = result.json()
    assert body["panel"]["successful_count"] == 2
    assert body["critic"]["status"] == "succeeded"
    assert body["arbiter"]["status"] == "succeeded"

    history = workspace_client.get(f"/api/workspaces/{workspace['id']}/runs")
    assert history.status_code == 200
    runs = history.json()
    assert len(runs) == 1
    assert runs[0]["id"] == result.headers["X-Conclave-Run-ID"]
    assert runs[0]["question"] == "Should we add forecasting?"

    fetched = workspace_client.get(f"/api/runs/{runs[0]['id']}")
    assert fetched.status_code == 200
    saved = fetched.json()
    assert saved["result"]["arbiter"]["status"] == "succeeded"
    assert saved["request"]["delegates"] == ["demo-a", "demo-b"]

    retried = workspace_client.post(
        f"/api/runs/{runs[0]['id']}/delegates/demo-a/retry"
    )
    assert retried.status_code == 200
    retry_run = retried.json()
    assert retry_run["id"] != runs[0]["id"]
    assert retry_run["result"]["panel"]["successful_count"] == 2
    assert retry_run["result"]["arbiter"]["status"] == "succeeded"

    history_after_retry = workspace_client.get(
        f"/api/workspaces/{workspace['id']}/runs"
    )
    assert len(history_after_retry.json()) == 2
