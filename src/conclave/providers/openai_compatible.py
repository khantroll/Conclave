from __future__ import annotations

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
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.extra_headers = dict(extra_headers or {})
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
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

        if self._client is not None:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        else:
            # The orchestrator owns the overall delegate timeout. Disable httpx's
            # much shorter default read timeout here so slower model responses
            # are not aborted after only a few seconds.
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

        if response.is_error:
            body = response.text.strip().replace("\n", " ")
            if len(body) > 500:
                body = f"{body[:500]}..."
            raise RuntimeError(
                f"HTTP {response.status_code} from {self.base_url}: {body or response.reason_phrase}"
            )

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
        )

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
