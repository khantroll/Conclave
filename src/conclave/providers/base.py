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
