import httpx
import pytest

from conclave.providers.openai_compatible import OpenAICompatibleProvider


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
