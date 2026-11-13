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


# What a failed call was, as far as retrying is concerned:
#   auth          401 or 403: the key or access is wrong. Retrying cannot help.
#   quota         a 429 that mentions quota or billing, or asks to wait over a minute.
#   rate_limit    any other 429. Retried.
#   capacity      502, 503 or 504. Retried.
#   server_error  any other 5xx.
#   bad_request   any other 4xx.
#   transport     the request failed on the way (a refused connection is retried, the rest not).
#   malformed     the reply was not a usable chat completion.
#   empty_response  set by the orchestrator when the reply held no text.
RETRYABLE_KINDS = frozenset({"rate_limit", "capacity"})
# A Retry-After longer than this means "come back later", which is a quota, not a rate limit.
QUOTA_RETRY_AFTER_SECONDS = 60.0


class ProviderError(RuntimeError):
    """A failed provider call with request-local attempt telemetry."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 1,
        kind: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.kind = kind
        self.status_code = status_code

