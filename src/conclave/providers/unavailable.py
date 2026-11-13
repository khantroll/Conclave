from __future__ import annotations

from .base import Provider, ProviderResponse


class UnavailableProvider(Provider):
    """Configured provider that cannot run until a local configuration issue is fixed."""

    def __init__(self, error: str) -> None:
        self.error = error

    async def ask(self, prompt: str) -> ProviderResponse:
        raise RuntimeError(self.error)
