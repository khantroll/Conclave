from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderResponse:
    text: str
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    attempts: int = 1


class Provider(ABC):
    """Provider-neutral delegate interface.

    Concrete adapters may call hosted APIs, LiteLLM/OpenRouter gateways, or
    local OpenAI-compatible endpoints. The orchestrator intentionally depends
    only on this interface.
    """

    @abstractmethod
    async def ask(self, prompt: str) -> ProviderResponse:
        raise NotImplementedError


class ProviderError(RuntimeError):
    """A failed provider call with request-local attempt telemetry."""

    def __init__(self, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.attempts = attempts

