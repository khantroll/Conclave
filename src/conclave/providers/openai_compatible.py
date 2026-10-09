from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .base import Provider, ProviderResponse


class OpenAICompatibleProvider(Provider):
    """Call an OpenAI-compatible chat completions endpoint.

    This intentionally covers several useful deployment shapes without coupling
    Conclave to any one gateway: OpenAI-compatible hosted services, OpenRouter,
    LiteLLM Proxy, LM Studio, Ollama compatibility endpoints, and similar APIs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        system_prompt: str | None = None,
        extra_headers: dict[str, str] | None = None,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
        transient_max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.extra_headers = dict(extra_headers or {})
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.transient_max_retries = transient_max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._client = client

    async def ask(self, prompt: str) -> ProviderResponse:
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
        }

        max_attempts = self.transient_max_retries + 1
        response: httpx.Response | None = None

        for attempt in range(1, max_attempts + 1):
            response = await self._post(headers=headers, payload=payload)

            if not response.is_error:
                break

            if response.status_code not in {429, 502, 503, 504} or attempt >= max_attempts:
                body = response.text.strip().replace("\n", " ")
                if len(body) > 500:
                    body = f"{body[:500]}..."
                suffix = f" after {attempt} attempt(s)" if attempt > 1 else ""
                raise RuntimeError(
                    f"HTTP {response.status_code} from {self.base_url}{suffix}: "
                    f"{body or response.reason_phrase}"
                )

            await asyncio.sleep(self._retry_delay(response, attempt))

        assert response is not None
        data: dict[str, Any] = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Provider returned no chat-completion content") from exc

        if not isinstance(text, str):
            raise RuntimeError("Provider returned non-text chat-completion content")

        usage = data.get("usage")
        normalized_usage = usage if isinstance(usage, dict) else {}
        return ProviderResponse(
            text=text,
            model=data.get("model") or self.model,
            usage=normalized_usage,
            estimated_cost_usd=self._estimate_cost(normalized_usage),
            attempts=attempt,
        )

    async def _post(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

        # The orchestrator owns the overall delegate timeout. Disable httpx's
        # shorter default read timeout so retries and slower model responses
        # remain bounded by the orchestrator's per-stage timeout.
        async with httpx.AsyncClient(timeout=None) as client:
            return await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 10.0)
            except ValueError:
                pass
        return min(self.retry_backoff_seconds * (2 ** (attempt - 1)), 10.0)

    def _estimate_cost(self, usage: dict[str, Any]) -> float | None:
        if self.input_cost_per_million is None and self.output_cost_per_million is None:
            return None

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if not isinstance(prompt_tokens, (int, float)) and not isinstance(
            completion_tokens, (int, float)
        ):
            return None

        cost = 0.0
        if isinstance(prompt_tokens, (int, float)) and self.input_cost_per_million is not None:
            cost += (float(prompt_tokens) / 1_000_000) * self.input_cost_per_million
        if isinstance(completion_tokens, (int, float)) and self.output_cost_per_million is not None:
            cost += (float(completion_tokens) / 1_000_000) * self.output_cost_per_million
        return round(cost, 8)
