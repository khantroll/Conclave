import pytest
from fastapi.testclient import TestClient

from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.store import WorkspaceStore

# Every endpoint that spends provider calls without needing a request body.
BODYLESS_POSTS = [
    "/api/providers/test-all",
    "/api/providers/demo-a/test",
    "/api/runs/any-run/delegates/demo-a/retry",
    "/api/runs/any-run/critic/retry",
    "/api/runs/any-run/arbiter/retry",
]


@pytest.fixture
def make_client(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")

    def build(base_url, allowed_hosts=()):
        app = create_app(
            config=ConclaveConfig(), workspace_store=store, allowed_hosts=list(allowed_hosts)
        )
        return TestClient(app, base_url=base_url)

    return build


@pytest.mark.parametrize("path", BODYLESS_POSTS)
def test_foreign_origin_cannot_trigger_bodyless_posts(make_client, path):
    client = make_client("http://127.0.0.1:8000")
    response = client.post(path, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]


@pytest.mark.parametrize("path", BODYLESS_POSTS)
def test_non_loopback_host_is_refused_for_every_bodyless_post(make_client, path):
    client = make_client("http://192.168.1.5:8000")
    assert client.post(path).status_code == 403


def test_non_loopback_host_cannot_read_stored_runs(make_client):
    # DNS rebinding: a page on another name resolving to 127.0.0.1 must not read history.
    client = make_client("http://evil.example:8000")
    assert client.get("/api/runs").status_code == 403
    assert client.get("/health").status_code == 403


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost"],
)
def test_console_requests_from_loopback_pass(make_client, base_url):
    client = make_client(base_url)
    assert client.get("/health").status_code == 200
    same_origin = client.post("/api/providers/demo-a/test", headers={"Origin": base_url})
    assert same_origin.status_code == 200
    no_origin = client.post("/api/providers/demo-a/test")
    assert no_origin.status_code == 200


def test_ipv6_loopback_host_passes(make_client):
    # The test client cannot build an IPv6 base_url, so send the headers directly.
    client = make_client("http://127.0.0.1:8000")
    headers = {"Host": "[::1]:8000", "Origin": "http://[::1]:8000"}
    assert client.post("/api/providers/demo-a/test", headers=headers).status_code == 200
    assert client.get("/health", headers={"Host": "[::2]:8000"}).status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_state_changing_method_is_checked(make_client, method):
    client = make_client("http://127.0.0.1:8000")
    path = "/api/workspaces/none"
    foreign = client.request(method, path, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    # Without a foreign Origin the request reaches the app (404 or 405/422), not the guard.
    assert client.request(method, path).status_code != 403


def test_malformed_origin_is_refused_not_a_server_error(make_client):
    client = make_client("http://127.0.0.1:8000")
    for origin in ["http://[::1", "http://[", "::::", "http://exa mple.com", "\x7f"]:
        try:
            response = client.post("/api/providers/demo-a/test", headers={"Origin": origin})
        except Exception:  # the HTTP client itself may refuse to send some values
            continue
        assert response.status_code == 403, origin


def test_head_and_get_do_not_need_an_origin_but_do_need_a_loopback_host(make_client):
    client = make_client("http://127.0.0.1:8000")
    assert client.head("/").status_code != 403  # the app itself answers HEAD / with 405
    assert client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 200
    assert client.head("/", headers={"Host": "evil.example"}).status_code == 403


def test_empty_or_malformed_host_is_refused(make_client):
    client = make_client("http://127.0.0.1:8000")
    for host in ["", "[::1", "127.0.0.1.evil.example", "evil.example:80@127.0.0.1"]:
        response = client.get("/health", headers={"Host": host})
        assert response.status_code == 403, repr(host)


def test_origin_must_match_host_exactly(make_client):
    client = make_client("http://127.0.0.1:8000")
    for origin in ["null", "http://127.0.0.1:9999", "http://localhost:8000", "https://127.0.0.1:8000.evil.example"]:
        response = client.post("/api/providers/demo-a/test", headers={"Origin": origin})
        assert response.status_code == 403, origin


def test_listed_host_is_allowed_and_unlisted_is_not(make_client):
    allowed = make_client("http://conclave.lan:8000", allowed_hosts=["conclave.lan"])
    assert allowed.get("/health").status_code == 200
    assert allowed.post(
        "/api/providers/demo-a/test", headers={"Origin": "http://conclave.lan:8000"}
    ).status_code == 200
    assert allowed.post(
        "/api/providers/demo-a/test", headers={"Origin": "https://evil.example"}
    ).status_code == 403
    other = make_client("http://other.lan:8000", allowed_hosts=["conclave.lan"])
    assert other.get("/health").status_code == 403


def test_allowed_hosts_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCLAVE_ALLOWED_HOSTS", " box.local , other.local:8000 ")
    store = WorkspaceStore(tmp_path / "t.db")
    app = create_app(config=ConclaveConfig(), workspace_store=store)
    assert TestClient(app, base_url="http://box.local:8000").get("/health").status_code == 200
    assert TestClient(app, base_url="http://other.local:8000").get("/health").status_code == 200
    assert TestClient(app, base_url="http://elsewhere:8000").get("/health").status_code == 403


def test_blocked_request_never_reaches_a_provider(tmp_path):
    from conclave.providers.fake import FakeProvider

    calls = []

    class Counting(FakeProvider):
        async def ask(self, prompt):
            calls.append(prompt)
            return await super().ask(prompt)

    import conclave.api as api_module

    original = api_module.FakeProvider
    api_module.FakeProvider = lambda response="ok", **kw: Counting(response, **kw)
    try:
        store = WorkspaceStore(tmp_path / "t.db")
        app = create_app(config=ConclaveConfig(), workspace_store=store, allowed_hosts=[])
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        path = "/api/providers/demo-a/test"
        blocked = client.post(path, headers={"Origin": "https://evil.example"})
        assert blocked.status_code == 403
        assert calls == []
        assert client.post(path).status_code == 200
        assert calls
    finally:
        api_module.FakeProvider = original


def test_same_origin_helper_handles_unparseable_values():
    from conclave.security import _same_origin

    assert _same_origin("http://127.0.0.1:8000", "127.0.0.1:8000")
    assert not _same_origin("http://[::1", "127.0.0.1:8000")  # urlsplit raises ValueError
    assert not _same_origin("", "127.0.0.1:8000")
