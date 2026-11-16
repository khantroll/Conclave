"""A per-run cost ceiling that fails closed.

The ceiling is checked against **estimated** cost (tokens x the prices configured for each
provider, as in the call ledger), never against what a provider invoices. Before each provider
call the guard computes a deliberately pessimistic upper bound for that call and refuses the call
unless what the run has already spent, plus what calls still in flight could spend, plus this
bound, stays within the ceiling.

The bound for one call is ``attempts x (prompt_bytes x input price + max_output_tokens x output
price)``, where ``attempts`` is the provider's transient retry limit plus one and a prompt byte is
counted as one token (a token is never shorter than a byte). A provider whose input price, output
price, ``max_output_tokens`` or retry limit is unknown has an unknowable cost: its calls are
refused rather than guessed at. Spend that cannot be priced after the fact (a possibly billed call
with no usable usage) counts as the ceiling being exhausted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from contextvars import ContextVar

from .ledger import current_ledger
from .providers.base import Provider

CEILING_ERROR_KIND = "cost_ceiling"


def worst_case_cost(provider: Provider, prompt: str) -> float | None:
    """Upper bound of one call's estimated cost in USD, or None when it cannot be bounded."""
    price_in = getattr(provider, "input_cost_per_million", None)
    price_out = getattr(provider, "output_cost_per_million", None)
    max_out = getattr(provider, "max_output_tokens", None)
    retries = getattr(provider, "transient_max_retries", None)
    if not (
        isinstance(price_in, (int, float))
        and isinstance(price_out, (int, float))
        and isinstance(max_out, int)
        and isinstance(retries, int)
        and not isinstance(max_out, bool)
        and not isinstance(retries, bool)
    ):
        return None
    system = getattr(provider, "system_prompt", None) or ""
    prompt_tokens = len(prompt.encode("utf-8")) + len(system.encode("utf-8"))
    per_attempt = (prompt_tokens * price_in + max_out * price_out) / 1_000_000
    return (retries + 1) * per_attempt


def unboundable(providers: Mapping[str, Provider], names: list[str]) -> list[str]:
    """Names whose calls could not be bounded (so a ceiling cannot be enforced for them)."""
    return sorted({n for n in names if n in providers and worst_case_cost(providers[n], "") is None})


class CostGuard:
    """Admits or refuses provider calls against one run's ceiling."""

    def __init__(self, ceiling_usd: float) -> None:
        self.ceiling_usd = ceiling_usd
        self._in_flight = 0.0

    def spent(self) -> float:
        """Estimated spend so far on this run; infinite when part of it cannot be priced."""
        ledger = current_ledger()
        if ledger is None:
            return 0.0
        totals = ledger.totals()
        if totals.possibly_billed_unpriced_calls:
            return math.inf
        return totals.estimated_total_usd or 0.0

    def admit(self, bound: float | None) -> bool:
        """Reserve ``bound`` for a call about to start. The caller must ``release`` it later."""
        if bound is None:
            return False
        if self.spent() + self._in_flight + bound > self.ceiling_usd:
            return False
        self._in_flight += bound
        return True

    def release(self, bound: float) -> None:
        self._in_flight = max(self._in_flight - bound, 0.0)


_guard: ContextVar[CostGuard | None] = ContextVar("conclave_cost_guard", default=None)


def use_guard(guard: CostGuard | None):
    return _guard.set(guard)


def reset_guard(token) -> None:
    _guard.reset(token)


def current_guard() -> CostGuard | None:
    return _guard.get()
