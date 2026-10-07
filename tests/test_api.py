from fastapi.testclient import TestClient

from conclave.api import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider_count"] >= 2


def test_provider_names():
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "demo-a" in providers
    assert "demo-b" in providers


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
