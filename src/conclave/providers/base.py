from __future__ import annotations

from abc import ABC, abstractmethod


class Provider(ABC):
    """Provider-neutral delegate interface.

    Concrete adapters may call hosted APIs, LiteLLM, or local OpenAI-compatible
    endpoints. The orchestrator intentionally depends only on this interface.
    """

    @abstractmethod
    async def ask(self, prompt: str) -> str:
        raise NotImplementedError
