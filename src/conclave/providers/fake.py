from __future__ import annotations

import asyncio

from .base import Provider, ProviderResponse


class FakeProvider(Provider):
    """Test/demo provider used before or alongside real provider adapters."""

    def __init__(
        self,
        response: str = "ok",
        *,
        delay_seconds: float = 0,
        error: Exception | None = None,
        model: str = "fake-model",
        usage: dict | None = None,
    ) -> None:
        self.response = response
        self.delay_seconds = delay_seconds
        self.error = error
        self.model = model
        self.usage = usage or {}

    async def ask(self, prompt: str) -> ProviderResponse:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return ProviderResponse(text=self.response, model=self.model, usage=self.usage)
