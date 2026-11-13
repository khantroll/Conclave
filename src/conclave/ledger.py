"""The call ledger: one row per provider request, with estimated and reported cost kept apart.

Cost used to be recomputed from the stage results that survived a run, so retries, fallbacks,
HTTP-level retries, failed calls, timeouts and connectivity tests all vanished from it, and one
number mixed estimate with fact. The ledger records every request instead:

* **estimated**: tokens x the price configured at the time (stored on the row). Unknown when
  usage or price is missing, never zero.
* **provider-reported**: an amount the provider or gateway stated for that call, read only from
  a response field or header named in that provider's configuration. Conclave never guesses where
  it is.
* **billed**: what appears on the provider's invoice. Conclave never shows or claims it.

Rows are written as calls happen, so a cancelled or crashed run keeps what it already spent.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import CallRow, CostSummary

MAX_USAGE_JSON_CHARS = 4000

Sink = Callable[[CallRow], None]


@dataclass(frozen=True, slots=True)
class CallContext:
    """Which run (and retry chain) the calls of an operation belong to."""

    run_id: str | None = None
    chain_root_id: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize(rows: list[CallRow]) -> CostSummary:
    """Totals over ledger rows. Unknown is never turned into zero."""
    priced = [row for row in rows if row.estimated_cost_usd is not None]
    unpriced = [row for row in rows if row.estimated_cost_usd is None]
    reported = [row for row in rows if row.reported_cost_usd is not None]
    return CostSummary(
        total_calls=len(rows),
        estimated_total_usd=round(sum(r.estimated_cost_usd for r in priced), 8) if priced else None,
        priced_calls=len(priced),
        unpriced_calls=len(unpriced),
        possibly_billed_unpriced_calls=sum(1 for row in unpriced if row.possibly_billed),
        reported_total_usd=round(sum(r.reported_cost_usd for r in reported), 8) if reported else None,
        reported_calls=len(reported),
    )


class RunLedger:
    """The rows of one run (or one connectivity test), kept in memory and forwarded to a sink."""

    def __init__(
        self,
        *,
        run_id: str | None = None,
        chain_root_id: str | None = None,
        sink: Sink | None = None,
    ) -> None:
        self.run_id = run_id
        self.chain_root_id = chain_root_id if chain_root_id is not None else run_id
        self.sink = sink
        self.rows: list[CallRow] = []

    def add(self, row: CallRow) -> CallRow:
        self.rows.append(row)
        if self.sink is not None:
            self.sink(row)
        return row

    def totals(self) -> CostSummary:
        return summarize(self.rows)


class CallScope:
    """One provider call (all its HTTP attempts) inside a stage, as the ledger sees it."""

    def __init__(self, *, ledger: RunLedger, stage: str, provider: str, model: str | None) -> None:
        self.ledger = ledger
        self.stage = stage
        self.provider = provider
        self.configured_model = model
        self.rows_written = 0
        self._open: list[Attempt] = []

    def begin(self, attempt_no: int, *, price_in: float | None, price_out: float | None) -> Attempt:
        attempt = Attempt(
            self,
            attempt_no,
            price_in=price_in,
            price_out=price_out,
        )
        self._open.append(attempt)
        return attempt

    def close_open(self, outcome: str) -> None:
        """Give every request still in flight a row (a timeout or cancellation abandoned it).

        Usage is unknown and the provider may well have started, so such a row is possibly
        billed.
        """
        for attempt in list(self._open):
            attempt.finish(outcome=outcome, possibly_billed=True)

    def write(self, row: CallRow) -> None:
        self.rows_written += 1
        self.ledger.add(row)


class Attempt:
    """One HTTP request. It becomes exactly one row, however it ends."""

    def __init__(
        self, scope: CallScope, attempt_no: int, *, price_in: float | None, price_out: float | None
    ) -> None:
        self.scope = scope
        self.attempt_no = attempt_no
        self.price_in = price_in
        self.price_out = price_out
        self.started_at = now_iso()
        self._started = _clock()
        self.done = False

    def finish(
        self,
        *,
        outcome: str,
        http_status: int | None = None,
        usage: dict[str, Any] | None = None,
        reported_model: str | None = None,
        reported_cost_usd: float | None = None,
        reported_cost_source: str | None = None,
        possibly_billed: bool | None = None,
    ) -> None:
        if self.done:
            return
        self.done = True
        if self in self.scope._open:
            self.scope._open.remove(self)
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = _count(usage.get("prompt_tokens"))
        completion_tokens = _count(usage.get("completion_tokens"))
        estimated = estimate_cost(prompt_tokens, completion_tokens, self.price_in, self.price_out)
        if possibly_billed is None:
            possibly_billed = default_possibly_billed(outcome, http_status)
        self.scope.write(
            CallRow(
                id=uuid.uuid4().hex,
                run_id=self.scope.ledger.run_id,
                chain_root_id=self.scope.ledger.chain_root_id,
                stage=self.scope.stage,
                provider=self.scope.provider,
                configured_model=self.scope.configured_model,
                reported_model=reported_model,
                attempt_no=self.attempt_no,
                outcome=outcome,
                http_status=http_status,
                started_at=self.started_at,
                latency_ms=round((_clock() - self._started) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usage_json=_usage_json(usage),
                price_in_per_million=self.price_in,
                price_out_per_million=self.price_out,
                estimated_cost_usd=estimated,
                reported_cost_usd=reported_cost_usd,
                reported_cost_source=reported_cost_source if reported_cost_usd is not None else None,
                possibly_billed=possibly_billed,
            )
        )


def default_possibly_billed(outcome: str, http_status: int | None) -> bool:
    """Could this request have been charged? Unknown counts as yes."""
    if outcome == "ok":
        return True
    if outcome == "http_error":
        # A 4xx refused the request before any generation; a 5xx may have run it.
        return http_status is None or http_status >= 500
    # A transport error may have happened after the request was accepted, and a timeout or
    # cancellation abandons a request that may be running. (A refused connection overrides this.)
    return True


def estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    price_in: float | None,
    price_out: float | None,
) -> float | None:
    """Tokens x the configured price. None unless every part of the usage has a price.

    A cost with a missing piece would understate the call, and an understated figure reads as a
    fact, so a prompt count without an input price (or a completion count without an output
    price) makes the whole estimate unknown. (Zero tokens cost nothing, priced or not.)
    """
    if prompt_tokens is None and completion_tokens is None:
        return None
    if prompt_tokens and price_in is None:
        return None
    if completion_tokens and price_out is None:
        return None
    cost = 0.0
    if prompt_tokens is not None and price_in is not None:
        cost += prompt_tokens / 1_000_000 * price_in
    if completion_tokens is not None and price_out is not None:
        cost += completion_tokens / 1_000_000 * price_out
    return round(cost, 8)


def read_reported_cost(
    data: Any, headers: Any, *, field: str | None, header: str | None
) -> tuple[float | None, str | None]:
    """The provider-reported cost of one call, from where this provider's config says it is."""
    if field:
        value: Any = data
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        number = _non_negative_number(value)
        if number is not None:
            return number, f"field:{field}"
    if header and headers is not None:
        raw = headers.get(header)
        number = _non_negative_number(raw)
        if number is not None:
            return number, f"header:{header}"
    return None, None


def _non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if math.isfinite(value) and value >= 0 else None


def _numbers_only(value: Any, depth: int = 0) -> Any:
    """Keep numbers, and dicts and lists of numbers; drop every string, null and flag.

    Usage is a provider's own object. Token counts (and breakdowns of them) are all the ledger
    needs, so nothing free-form is stored.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if depth >= 3:
        return None
    if isinstance(value, dict):
        kept = {str(k)[:60]: _numbers_only(v, depth + 1) for k, v in value.items()}
        kept = {k: v for k, v in kept.items() if v not in (None, {}, [])}
        return kept or None
    if isinstance(value, list):
        kept_list = [_numbers_only(v, depth + 1) for v in value[:50]]
        kept_list = [v for v in kept_list if v is not None]
        return kept_list or None
    return None


def _usage_json(usage: dict[str, Any]) -> str | None:
    cleaned = _numbers_only(usage)
    if not cleaned:
        return None
    text = json.dumps(cleaned, sort_keys=True)
    return text if len(text) <= MAX_USAGE_JSON_CHARS else None


def _clock() -> float:
    from time import perf_counter

    return perf_counter()


# The ledger and the call in progress, for code that cannot be handed them (the adapter).
_ledger: ContextVar[RunLedger | None] = ContextVar("conclave_ledger", default=None)
_scope: ContextVar[CallScope | None] = ContextVar("conclave_call_scope", default=None)


def current_ledger() -> RunLedger | None:
    return _ledger.get()


def current_scope() -> CallScope | None:
    return _scope.get()


def use_ledger(ledger: RunLedger | None):
    """Make ``ledger`` the active one; returns a token for :func:`reset_ledger`."""
    return _ledger.set(ledger)


def reset_ledger(token) -> None:
    _ledger.reset(token)


def use_scope(scope: CallScope | None):
    return _scope.set(scope)


def reset_scope(token) -> None:
    _scope.reset(token)


def begin_attempt(
    attempt_no: int, *, price_in: float | None, price_out: float | None
) -> Attempt | None:
    """Called by an adapter before each HTTP request. None when nothing is recording."""
    scope = _scope.get()
    if scope is None:
        return None
    return scope.begin(attempt_no, price_in=price_in, price_out=price_out)
