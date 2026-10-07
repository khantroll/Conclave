from __future__ import annotations

import asyncio
from collections.abc import Mapping
from time import perf_counter

from .models import DelegateRequest, DelegateResult, DelegateStatus, PanelRequest, PanelResult
from .providers.base import Provider


class Orchestrator:
    """Run independent delegates concurrently and preserve partial success."""

    def __init__(self, providers: Mapping[str, Provider]) -> None:
        self._providers = dict(providers)

    async def run_panel(self, request: PanelRequest) -> PanelResult:
        tasks = [self._run_delegate(delegate) for delegate in request.delegates]
        results = await asyncio.gather(*tasks)

        successful_count = sum(r.status == DelegateStatus.SUCCEEDED for r in results)
        failed_count = len(results) - successful_count

        return PanelResult(
            question=request.question,
            delegates=results,
            successful_count=successful_count,
            failed_count=failed_count,
            synthesizeable=successful_count >= request.minimum_successes,
        )

    async def _run_delegate(self, delegate: DelegateRequest) -> DelegateResult:
        provider = self._providers.get(delegate.name)
        if provider is None:
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                error=f"No provider configured for delegate: {delegate.name}",
            )

        started = perf_counter()
        try:
            response = await asyncio.wait_for(
                provider.ask(delegate.prompt),
                timeout=delegate.timeout_seconds,
            )
        except TimeoutError:
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.TIMED_OUT,
                error=f"Timed out after {delegate.timeout_seconds:g}s",
                latency_ms=_elapsed_ms(started),
            )
        except Exception as exc:  # provider errors become data, not panel failures
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                error=str(exc),
                latency_ms=_elapsed_ms(started),
            )

        return DelegateResult(
            name=delegate.name,
            status=DelegateStatus.SUCCEEDED,
            raw_response=response,
            latency_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
