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
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.extra_headers = dict(extra_headers or {})
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
            async with httpx.AsyncClient() as client:
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
        return ProviderResponse(
            text=text,
            model=data.get("model") or self.model,
            usage=usage if isinstance(usage, dict) else {},
        )
