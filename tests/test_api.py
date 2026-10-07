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
    assert body["demo_provider_count"] >= 4
    assert body["configured_provider_count"] == 0
    assert body["demo_only"] is True


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


def test_provider_connection_test():
    response = client.post("/api/providers/demo-a/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["model"] == "fake-model"


def test_unknown_provider_connection_test_is_404():
    response = client.post("/api/providers/not-real/test")
    assert response.status_code == 404


def test_provider_names():
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "demo-a" in providers
    assert "demo-b" in providers
    assert "demo-critic" in providers
    assert "demo-arbiter" in providers
    descriptors = {item["name"]: item for item in response.json()["descriptors"]}
    assert "reasoning" in descriptors["demo-a"]["capabilities"]
    assert "critical" in descriptors["demo-b"]["capabilities"]


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


def test_auto_select_workspace_uses_smaller_panel_for_simple_question(tmp_path):
    store = WorkspaceStore(tmp_path / "auto-select.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Auto",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "minimum_successes": 1,
            "auto_select_delegates": True,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    preview = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/select",
        json={"question": "What is RAID 10?"},
    )
    assert preview.status_code == 200
    selection = preview.json()
    assert selection["analysis"]["recommended_delegate_count"] == 1
    assert selection["selected"] == ["demo-a"]

    result = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "What is RAID 10?"},
    )
    assert result.status_code == 200
    run_id = result.headers["X-Conclave-Run-ID"]

    saved = workspace_client.get(f"/api/runs/{run_id}").json()
    assert saved["request"]["delegates"] == ["demo-a"]


def test_workspace_rejects_unknown_providers_and_supports_replace_delete(tmp_path):
    store = WorkspaceStore(tmp_path / "crud.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    bad = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Bad",
            "delegates": ["not-configured"],
            "arbiter": "demo-arbiter",
        },
    )
    assert bad.status_code == 422
    assert "not-configured" in bad.json()["detail"]

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Editable",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "minimum_successes": 1,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    replaced = workspace_client.put(
        f"/api/workspaces/{workspace['id']}",
        json={
            "name": "Edited",
            "description": "Changed",
            "delegates": ["demo-a"],
            "arbiter": "demo-arbiter",
            "minimum_successes": 1,
            "auto_select_delegates": True,
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "Edited"
    assert replaced.json()["delegates"] == ["demo-a"]
    assert replaced.json()["auto_select_delegates"] is True

    deleted = workspace_client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 204
    assert workspace_client.get(f"/api/workspaces/{workspace['id']}").status_code == 404


def test_downstream_retry_endpoints_save_new_runs(tmp_path):
    store = WorkspaceStore(tmp_path / "downstream-retry.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    workspace = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Retry",
            "delegates": ["demo-a"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
        },
    ).json()

    first = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "retry downstream"},
    )
    run_id = first.headers["X-Conclave-Run-ID"]

    critic_retry = workspace_client.post(f"/api/runs/{run_id}/critic/retry")
    assert critic_retry.status_code == 200
    critic_run = critic_retry.json()
    assert critic_run["id"] != run_id
    assert critic_run["result"]["critic"]["status"] == "succeeded"
    assert critic_run["result"]["arbiter"]["status"] == "succeeded"

    arbiter_retry = workspace_client.post(
        f"/api/runs/{critic_run['id']}/arbiter/retry"
    )
    assert arbiter_retry.status_code == 200
    arbiter_run = arbiter_retry.json()
    assert arbiter_run["id"] != critic_run["id"]
    assert arbiter_run["result"]["arbiter"]["status"] == "succeeded"


def test_deleted_workspace_run_remains_in_global_history(tmp_path):
    store = WorkspaceStore(tmp_path / "detached-history.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    workspace = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Disposable",
            "delegates": ["demo-a"],
            "arbiter": "demo-arbiter",
        },
    ).json()

    first = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "preserve me"},
    )
    run_id = first.headers["X-Conclave-Run-ID"]

    deleted = workspace_client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 204

    all_runs = workspace_client.get("/api/runs")
    assert all_runs.status_code == 200
    match = next(run for run in all_runs.json() if run["id"] == run_id)
    assert match["workspace_id"] is None
    assert match["question"] == "preserve me"


def test_workspace_validation_rejects_duplicate_delegates_and_unknown_roles(tmp_path):
    store = WorkspaceStore(tmp_path / "validation.db")
    workspace_app = create_app(workspace_store=store)
    workspace_client = TestClient(workspace_app)

    duplicate = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Duplicate",
            "delegates": ["demo-a", "demo-a"],
            "arbiter": "demo-arbiter",
        },
    )
    assert duplicate.status_code == 422
    assert "unique" in duplicate.json()["detail"]

    bad_role = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Bad role",
            "delegates": ["demo-a"],
            "roles": {"demo-b": "Not actually selected"},
            "arbiter": "demo-arbiter",
        },
    )
    assert bad_role.status_code == 422
    assert "non-delegate" in bad_role.json()["detail"]
