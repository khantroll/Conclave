from fastapi.testclient import TestClient

from conclave.api import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
