import httpx
import pytest

from conclave.providers.openai_compatible import OpenAICompatibleProvider


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_exhausted_retries_preserve_attempts_in_panel(status, monkeypatch):
    from conclave.models import DelegateRequest, DelegateStatus, PanelRequest
    from conclave.orchestrator import Orchestrator

    calls = 0

    async def fake_sleep(delay):
        pass

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="temporarily unavailable")

    monkeypatch.setattr("conclave.providers.openai_compatible.asyncio.sleep", fake_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", model="test", client=client
        )
        result = await Orchestrator({"one": provider}).run_panel(
            PanelRequest(question="test", delegates=[DelegateRequest(name="one", prompt="hi")])
        )
    failed = result.delegates[0]
    assert failed.status == DelegateStatus.FAILED
    assert failed.attempts == calls == 3
    assert f"HTTP {status}" in failed.error
    assert result.model_dump(mode="json")["delegates"][0]["attempts"] == 3


@pytest.mark.parametrize("failure", ["transport", "invalid_json", "missing_content"])
async def test_error_after_retry_keeps_attempt_count(failure, monkeypatch):
    from conclave.providers.base import ProviderError

    calls = 0

    async def fake_sleep(delay):
        pass

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        if failure == "transport":
            raise httpx.ReadError("connection lost", request=request)
        if failure == "invalid_json":
            return httpx.Response(200, text="not JSON")
        return httpx.Response(200, json={"choices": []})

    monkeypatch.setattr("conclave.providers.openai_compatible.asyncio.sleep", fake_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", model="test", client=client
        )
        with pytest.raises(ProviderError) as caught:
            await provider.ask("hi")
    assert caught.value.attempts == calls == 2


@pytest.mark.parametrize("header, expected", [
    ("Sat, 24 Oct 2026 12:00:04 GMT", 4.0),
    ("Sat, 24 Oct 2026 13:00:00 GMT", 10.0),
    ("Sat, 24 Oct 2026 11:00:00 GMT", 0.0),
    ("invalid", 2.0), ("nan", 2.0), ("inf", 2.0), ("-1", 0.0),
])
def test_retry_after_dates_and_invalid_values(header, expected, monkeypatch):
    from datetime import datetime, timezone

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 24, 12, tzinfo=timezone.utc)

    monkeypatch.setattr("conclave.providers.openai_compatible.datetime", FixedDatetime)
    provider = OpenAICompatibleProvider(base_url="https://example.test", model="test")
    response = httpx.Response(429, headers={"Retry-After": header})
    assert provider._retry_delay(response, 2) == expected


async def test_stage_timeout_cancels_backoff_without_more_requests():
    import asyncio

    from conclave.models import DelegateRequest, DelegateStatus, PanelRequest
    from conclave.orchestrator import Orchestrator
    from conclave.providers.fake import FakeProvider

    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, headers={"Retry-After": "10"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test", model="test", client=client
        )
        result = await asyncio.wait_for(
            Orchestrator({"slow": provider, "good": FakeProvider("kept")}).run_panel(
                PanelRequest(question="test", delegates=[
                    DelegateRequest(name="slow", prompt="hi", timeout_seconds=0.05),
                    DelegateRequest(name="good", prompt="hi"),
                ])
            ), timeout=1,
        )
    assert calls == 1
    assert result.delegates[0].status == DelegateStatus.TIMED_OUT
    assert result.delegates[1].raw_response == "kept"
    assert result.synthesizeable


async def test_openai_compatible_provider_returns_text_and_usage():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        body = request.read().decode()
        assert '"model":"test-model"' in body
        return httpx.Response(
            200,
            json={
                "model": "test-model-2026",
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            api_key="secret",
            input_cost_per_million=2.0,
            output_cost_per_million=8.0,
            client=client,
        )
        response = await provider.ask("hi")

    assert response.text == "hello"
    assert response.model == "test-model-2026"
    assert response.usage["total_tokens"] == 5
    assert response.estimated_cost_usd == pytest.approx(0.000022)
    assert response.attempts == 1


async def test_openai_compatible_provider_surfaces_http_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            client=client,
        )
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await provider.ask("hi")


async def test_openai_compatible_provider_rejects_missing_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            client=client,
        )
        with pytest.raises(RuntimeError, match="no chat-completion content"):
            await provider.ask("hi")


def test_default_client_disables_internal_httpx_timeout(monkeypatch):
    captured = {}

    class DummyResponse:
        is_error = False

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "model": "model-x",
                "usage": {},
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr("conclave.providers.openai_compatible.httpx.AsyncClient", DummyClient)

    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        model="model-x",
        api_key="secret",
    )

    import asyncio

    result = asyncio.run(provider.ask("hello"))
    assert result.text == "ok"
    assert captured["timeout"] is None


async def test_transient_http_errors_are_retried(monkeypatch):
    attempts = 0
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="high demand")
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "recovered"}}],
                "usage": {},
            },
        )

    monkeypatch.setattr(
        "conclave.providers.openai_compatible.asyncio.sleep",
        fake_sleep,
    )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            transient_max_retries=2,
            retry_backoff_seconds=0.5,
            client=client,
        )
        response = await provider.ask("hi")

    assert response.text == "recovered"
    assert response.attempts == 3
    assert attempts == 3
    assert sleeps == [0.5, 1.0]


async def test_non_transient_http_error_is_not_retried(monkeypatch):
    attempts = 0

    async def fake_sleep(delay):
        raise AssertionError("sleep should not be called")

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="bad key")

    monkeypatch.setattr(
        "conclave.providers.openai_compatible.asyncio.sleep",
        fake_sleep,
    )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            transient_max_retries=2,
            client=client,
        )
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await provider.ask("hi")

    assert attempts == 1


async def test_retry_after_header_is_respected_and_capped(monkeypatch):
    attempts = 0
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text="rate limited", headers={"Retry-After": "30"})
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            },
        )

    monkeypatch.setattr(
        "conclave.providers.openai_compatible.asyncio.sleep",
        fake_sleep,
    )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            model="test-model",
            transient_max_retries=1,
            client=client,
        )
        response = await provider.ask("hi")

    assert response.text == "ok"
    assert response.attempts == 2
    assert attempts == 2
    assert sleeps == [10.0]

