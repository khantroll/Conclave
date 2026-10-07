from __future__ import annotations

import asyncio

from .base import Provider


class FakeProvider(Provider):
    """Test/demo provider used before real provider adapters are wired."""

    def __init__(
        self,
        response: str = "ok",
        *,
        delay_seconds: float = 0,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.delay_seconds = delay_seconds
        self.error = error

    async def ask(self, prompt: str) -> str:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self.response
