from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..ledger import Attempt, begin_attempt, estimate_cost, read_reported_cost
from .base import (
    QUOTA_RETRY_AFTER_SECONDS,
    RETRYABLE_KINDS,
    Provider,
    ProviderError,
    ProviderResponse,
)


_TRANSIENT_429 = ("temporarily rate-limited", "retry shortly", "temporarily unavailable")
_SENSITIVE_HEADER = re.compile(r"auth|key|token|secret|cookie|password|credential", re.IGNORECASE)


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
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        max_prompt_chars: int | None = None,
        reported_cost_field: str | None = None,
        reported_cost_header: str | None = None,
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
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.max_prompt_chars = max_prompt_chars
        self.reported_cost_field = reported_cost_field
        self.reported_cost_header = reported_cost_header
        self._client = client

    # Each HTTP attempt writes its own call-ledger row (see ``conclave.ledger``).
    records_calls = True

    async def ask(self, prompt: str) -> ProviderResponse:
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Everything that would be sent counts, the system prompt included. A prompt over the
        # limit is never sent: it would only be refused, or silently truncated, by the provider.
        sent_chars = sum(len(message["content"]) for message in messages)
        if self.max_prompt_chars is not None and sent_chars > self.max_prompt_chars:
            raise ProviderError(
                f"Prompt is {sent_chars} characters, over this provider's max_prompt_chars of "
                f"{self.max_prompt_chars}; it was not sent",
                attempts=1,
                kind="prompt_too_large",
            )

        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
        }
        # Sent only when configured, so a provider's own defaults are untouched otherwise.
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        max_attempts = self.transient_max_retries + 1
        response: httpx.Response | None = None

        for attempt in range(1, max_attempts + 1):
            record = begin_attempt(
                attempt,
                price_in=self.input_cost_per_million,
                price_out=self.output_cost_per_million,
            )
            try:
                response = await self._post(headers=headers, payload=payload)
            except httpx.ConnectError as exc:
                # The connection never reached the provider, so this request cannot be billed.
                if record is not None:
                    record.finish(outcome="transport_error", possibly_billed=False)
                # A refused or unreachable connection never reached the provider, so it is
                # safe to try again: nothing can have been accepted or billed.
                if attempt < max_attempts:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise ProviderError(
                    self._redact(str(exc).strip())
                    or f"{type(exc).__name__}: provider request failed",
                    attempts=attempt,
                    kind="transport",
                ) from exc
            except httpx.RequestError as exc:
                # Any other transport failure may occur after a request was accepted.
                # Preserve attempts without automatically replaying that request.
                if record is not None:
                    record.finish(outcome="transport_error")
                raise ProviderError(
                    self._redact(str(exc).strip())
                    or f"{type(exc).__name__}: provider request failed",
                    attempts=attempt,
                    kind="transport",
                ) from exc

            if not response.is_error:
                break

            if record is not None:
                record.finish(outcome="http_error", http_status=response.status_code)
            kind = self._classify(response)
            if kind not in RETRYABLE_KINDS or attempt >= max_attempts:
                body = self._redact(response.text.strip().replace("\n", " "))
                if len(body) > 500:
                    body = f"{body[:500]}..."
                suffix = f" after {attempt} attempt(s)" if attempt > 1 else ""
                # Redact the finished message as well: the reason phrase and the URL are
                # provider-controlled or configured text that ends up in a stored error.
                raise ProviderError(
                    self._redact(
                        f"HTTP {response.status_code} from {self.base_url}{suffix}: "
                        f"{body or response.reason_phrase}"
                    ),
                    attempts=attempt,
                    kind=kind,
                    status_code=response.status_code,
                )

            await asyncio.sleep(self._retry_delay(response, attempt))

        assert response is not None
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            self._finish_ok(record, response, None)
            raise ProviderError(
                "Provider returned invalid JSON", attempts=attempt, kind="malformed"
            ) from exc
        self._finish_ok(record, response, data)
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "Provider returned no chat-completion content", attempts=attempt, kind="malformed"
            ) from exc

        if isinstance(text, list):
            # Some gateways return content as a list of parts; the text parts are the answer.
            parts = [
                part.get("text") if isinstance(part, dict) else part
                for part in text
                if isinstance(part, str) or (isinstance(part, dict) and part.get("type") in (None, "text"))
            ]
            if parts and all(isinstance(part, str) for part in parts):
                text = "".join(parts)
        if not isinstance(text, str):
            finish = choice.get("finish_reason") if isinstance(choice, dict) else None
            hint = (
                " (finish_reason 'length': the model may have used its output budget thinking; "
                "raise max_output_tokens)"
                if finish == "length"
                else ""
            )
            raise ProviderError(
                f"Provider returned no text answer{hint}", attempts=attempt, kind="malformed"
            )

        usage = data.get("usage")
        normalized_usage = usage if isinstance(usage, dict) else {}
        return ProviderResponse(
            text=text,
            model=data.get("model") or self.model,
            usage=normalized_usage,
            estimated_cost_usd=self._estimate_cost(normalized_usage),
            attempts=attempt,
        )

    def _finish_ok(
        self, record: Attempt | None, response: httpx.Response, data: Any
    ) -> None:
        """Write the ledger row of a request that got an HTTP success reply."""
        if record is None:
            return
        body = data if isinstance(data, dict) else {}
        usage = body.get("usage")
        reported, source = read_reported_cost(
            body,
            response.headers,
            field=self.reported_cost_field,
            header=self.reported_cost_header,
        )
        model = body.get("model")
        record.finish(
            outcome="ok",
            http_status=response.status_code,
            usage=usage if isinstance(usage, dict) else {},
            reported_model=model if isinstance(model, str) else None,
            reported_cost_usd=reported,
            reported_cost_source=source,
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

    def _redact(self, text: str) -> str:
        """Remove this provider's secrets from text that will be stored or shown.

        Error bodies from some providers echo the credential they rejected. The API key is
        always redacted, whatever its length. An ``extra_headers`` value is redacted when its
        header name looks like a credential (key, token, secret, auth, cookie, password) or
        when the value is at least 8 characters; shorter values of other headers are left
        alone, because they are almost always plain flags that redaction would mangle.
        """
        secrets = [self.api_key] if self.api_key else []
        for name, value in self.extra_headers.items():
            if value and (len(value) >= 8 or _SENSITIVE_HEADER.search(name)):
                secrets.append(value)
        for secret in sorted(set(secrets), key=len, reverse=True):
            text = text.replace(secret, "[redacted]")
        return text

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        """The Retry-After header in seconds, or None when absent or unreadable."""
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return None
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        return delay if math.isfinite(delay) else None

    @staticmethod
    def _classify(response: httpx.Response) -> str:
        """The error kind of a failed HTTP response (see ``providers.base``)."""
        status = response.status_code
        if status in {401, 403}:
            return "auth"
        if status == 429:
            body = response.text.lower()
            wait = OpenAICompatibleProvider._retry_after_seconds(response)
            if wait is not None and wait > QUOTA_RETRY_AFTER_SECONDS:
                return "quota"
            # A gateway sometimes reports a shared upstream pool being busy with an error code
            # that says "insufficient_quota" while its message says to retry shortly. That is a
            # rate limit, not an empty account, so it is retried.
            if any(phrase in body for phrase in _TRANSIENT_429):
                return "rate_limit"
            if any(word in body for word in ("insufficient_quota", "quota", "billing")):
                return "quota"
            return "rate_limit"
        if status in {502, 503, 504}:
            return "capacity"
        if 400 <= status < 500:
            return "bad_request"
        return "server_error"

    def _backoff(self, attempt: int) -> float:
        return min(self.retry_backoff_seconds * (2 ** (attempt - 1)), 10.0)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        delay = self._retry_after_seconds(response)
        if delay is not None:
            return min(max(delay, 0.0), 10.0)
        return self._backoff(attempt)

    def _estimate_cost(self, usage: dict[str, Any]) -> float | None:
        return estimate_cost(
            _token_count(usage.get("prompt_tokens")),
            _token_count(usage.get("completion_tokens")),
            self.input_cost_per_million,
            self.output_cost_per_million,
        )


def _token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if math.isfinite(value) and value >= 0 else None
