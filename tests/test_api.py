from fastapi.testclient import TestClient

from conclave.api import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider_count"] >= 3


def test_provider_names():
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "demo-a" in providers
    assert "demo-b" in providers
    assert "demo-arbiter" in providers


def test_demo_panel():
    response = client.post(
        "/api/panel",
        json={
            "question": "test",
            "delegates": [
                {"name": "demo-a", "prompt": "one"},
                {"name": "demo-b", "prompt": "two"},
            ],
            "minimum_successes": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["successful_count"] == 2
    assert body["synthesizeable"] is True
    assert body["delegates"][0]["model"] == "fake-model"


def test_demo_deliberation_runs_panel_then_arbiter():
    response = client.post(
        "/api/deliberate",
        json={
            "question": "Should Conclave survive partial failures?",
            "delegates": ["demo-a", "demo-b"],
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
    assert body["panel"]["synthesizeable"] is True
    assert body["arbiter"]["status"] == "succeeded"
    assert body["arbiter"]["raw_response"] == "Synthesized demo response"


def test_deliberation_skips_arbiter_without_quorum():
    response = client.post(
        "/api/deliberate",
        json={
            "question": "test",
            "delegates": ["missing-provider", "demo-a"],
            "arbiter": "demo-arbiter",
            "minimum_successes": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["panel"]["synthesizeable"] is False
    assert body["arbiter"] is None
