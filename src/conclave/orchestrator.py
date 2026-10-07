from __future__ import annotations

import asyncio
from collections.abc import Mapping
from time import perf_counter

from .models import (
    DeliberationRequest,
    DeliberationResult,
    DelegateRequest,
    DelegateResult,
    DelegateStatus,
    PanelRequest,
    PanelResult,
)
from .prompts import build_arbiter_prompt, build_critic_prompt, build_delegate_prompt
from .providers.base import Provider


class Orchestrator:
    """Run independent delegates concurrently and preserve partial success."""

    def __init__(self, providers: Mapping[str, Provider]) -> None:
        self._providers = dict(providers)

    @property
    def provider_names(self) -> list[str]:
        return sorted(self._providers)

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

    async def deliberate(self, request: DeliberationRequest) -> DeliberationResult:
        panel_request = PanelRequest(
            question=request.question,
            delegates=[
                DelegateRequest(
                    name=name,
                    prompt=build_delegate_prompt(
                        question=request.question,
                        role=request.roles.get(name),
                        workspace_context=request.workspace_context,
                    ),
                    timeout_seconds=request.timeout_seconds,
                )
                for name in request.delegates
            ],
            minimum_successes=request.minimum_successes,
        )
        panel = await self.run_panel(panel_request)

        if not panel.synthesizeable:
            return DeliberationResult(panel=panel)

        critic: DelegateResult | None = None
        if request.critic:
            critic = await self._run_delegate(
                DelegateRequest(
                    name=request.critic,
                    prompt=build_critic_prompt(
                        question=request.question,
                        delegate_results=panel.delegates,
                        workspace_context=request.workspace_context,
                    ),
                    timeout_seconds=request.critic_timeout_seconds,
                )
            )

        arbiter_prompt = build_arbiter_prompt(
            question=request.question,
            delegate_results=panel.delegates,
            workspace_context=request.workspace_context,
            critic_result=critic,
        )
        arbiter = await self._run_delegate(
            DelegateRequest(
                name=request.arbiter,
                prompt=arbiter_prompt,
                timeout_seconds=request.arbiter_timeout_seconds,
            )
        )
        return DeliberationResult(panel=panel, critic=critic, arbiter=arbiter)

    async def retry_delegate(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        delegate_name: str,
    ) -> DeliberationResult:
        if delegate_name not in request.delegates:
            raise ValueError(f"Delegate '{delegate_name}' was not part of the original request")

        retry = await self._run_delegate(
            DelegateRequest(
                name=delegate_name,
                prompt=build_delegate_prompt(
                    question=request.question,
                    role=request.roles.get(delegate_name),
                    workspace_context=request.workspace_context,
                ),
                timeout_seconds=request.timeout_seconds,
            )
        )

        delegates = [
            retry if result.name == delegate_name else result
            for result in prior_result.panel.delegates
        ]
        successful_count = sum(
            result.status == DelegateStatus.SUCCEEDED for result in delegates
        )
        panel = PanelResult(
            question=request.question,
            delegates=delegates,
            successful_count=successful_count,
            failed_count=len(delegates) - successful_count,
            synthesizeable=successful_count >= request.minimum_successes,
        )

        if not panel.synthesizeable:
            return DeliberationResult(panel=panel)

        critic: DelegateResult | None = None
        if request.critic:
            critic = await self._run_delegate(
                DelegateRequest(
                    name=request.critic,
                    prompt=build_critic_prompt(
                        question=request.question,
                        delegate_results=panel.delegates,
                        workspace_context=request.workspace_context,
                    ),
                    timeout_seconds=request.critic_timeout_seconds,
                )
            )

        arbiter = await self._run_delegate(
            DelegateRequest(
                name=request.arbiter,
                prompt=build_arbiter_prompt(
                    question=request.question,
                    delegate_results=panel.delegates,
                    workspace_context=request.workspace_context,
                    critic_result=critic,
                ),
                timeout_seconds=request.arbiter_timeout_seconds,
            )
        )
        return DeliberationResult(panel=panel, critic=critic, arbiter=arbiter)

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
            raw_response=response.text,
            model=response.model,
            usage=response.usage,
            latency_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
