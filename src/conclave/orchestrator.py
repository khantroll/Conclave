from __future__ import annotations

import asyncio
import math
import uuid
from contextlib import contextmanager
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

from .budget import (
    unboundable,
    CEILING_ERROR_KIND,
    CostGuard,
    current_guard,
    reset_guard,
    use_guard,
    worst_case_cost,
)
from .models import (
    DeliberationRequest,
    DeliberationResult,
    DelegateRequest,
    DelegateResult,
    CallRow,
    DelegateStatus,
    RESULT_SCHEMA_VERSION,
    PanelRequest,
    PanelResult,
    PriorAttempt,
    SingleSourceAnswer,
)
from .prompts import (
    build_arbiter_prompt,
    build_critic_prompt,
    build_delegate_prompt,
    label_map,
)
from .positions import build_positions, insufficient_evidence
from .synthesis import parse_sections
from .quorum import describe_single_source, evaluate_quorum
from .ledger import (
    CallContext,
    CallScope,
    RunLedger,
    Sink,
    current_ledger,
    now_iso,
    reset_ledger,
    reset_scope,
    use_ledger,
    use_scope,
)
from .providers.base import Provider, ProviderError
from .sources import ProviderIdentity, group_sources, identity_of, judge_overlap, provenance_of


StageCallback = Callable[[DeliberationResult], Awaitable[None]]


class Orchestrator:
    """Run independent delegates concurrently and preserve partial success."""

    def __init__(
        self,
        providers: Mapping[str, Provider],
        identities: Mapping[str, ProviderIdentity] | None = None,
        ledger_sink: Sink | None = None,
    ) -> None:
        # Every provider request becomes a call-ledger row, handed to this sink as it happens.
        self.ledger_sink = ledger_sink
        self._providers = dict(providers)
        # Providers without an identity (demo and test providers) are never merged
        # into one source.
        self._identities = dict(identities or {})

    def _panel_result(
        self,
        *,
        question: str,
        delegates: list[DelegateResult],
        minimum_successes: int,
        allow_single_source: bool = False,
    ) -> PanelResult:
        """Count real answers, and independent sources, for a set of delegate results.

        The quorum is judged on the answers that actually arrived. It proceeds only when
        it is met, or when one source answered and the caller explicitly allowed that.
        """
        successful_count = sum(r.status == DelegateStatus.SUCCEEDED for r in delegates)
        sources = group_sources(delegates, self._identities)
        families = {}
        for r in delegates:
            if r.status != DelegateStatus.SUCCEEDED:
                continue
            identity = identity_of(r, self._identities)
            if identity is not None and identity.family:
                families[r.name] = identity.family
        quorum = evaluate_quorum(
            required=minimum_successes,
            delegates=delegates,
            sources=sources,
            allow_single_source=allow_single_source,
        )
        return PanelResult(
            question=question,
            delegates=delegates,
            successful_count=successful_count,
            failed_count=len(delegates) - successful_count,
            synthesizeable=quorum.status != "unmet",
            independent_source_count=len(sources),
            sources=sources,
            quorum=quorum,
            families=families,
            distinct_families=len(set(families.values())) if families else None,
        )

    def unboundable(self, names: list[str]) -> list[str]:
        """Participants whose cost cannot be bounded, so a cost ceiling cannot cover them."""
        return unboundable(self._providers, names)

    @property
    def provider_names(self) -> list[str]:
        return sorted(self._providers)

    async def run_panel(
        self,
        request: PanelRequest,
        *,
        on_interrupt: Callable[[list[DelegateResult]], Awaitable[None]] | None = None,
    ) -> PanelResult:
        """Run the delegates concurrently.

        If the run is cancelled (or fails) part-way, every delegate that had already answered
        keeps its result: ``on_interrupt`` is awaited with one result per delegate, in order,
        where a delegate that had not finished is recorded as cancelled. What was paid for is
        never lost.
        """
        tasks = [
            asyncio.ensure_future(self._run_delegate(delegate)) for delegate in request.delegates
        ]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            # Let the cancelled calls write their ledger rows before anything else happens.
            await asyncio.gather(*tasks, return_exceptions=True)
            if on_interrupt is not None:
                kept = [
                    task.result()
                    if task.done() and not task.cancelled() and task.exception() is None
                    else DelegateResult(
                        name=delegate.name,
                        status=DelegateStatus.FAILED,
                        prompt=delegate.prompt,
                        error="Cancelled before this delegate answered",
                        error_kind="cancelled",
                    )
                    for delegate, task in zip(request.delegates, tasks, strict=True)
                ]
                await on_interrupt(kept)
            raise
        return self._panel_result(
            question=request.question,
            delegates=list(results),
            minimum_successes=request.minimum_successes,
            allow_single_source=request.allow_single_source,
        )

    async def test_provider(self, name: str, *, timeout_seconds: float = 20.0) -> DelegateResult:
        return await self._run_delegate(
            DelegateRequest(
                name=name,
                prompt=(
                    "Respond with exactly: CONCLAVE_OK\n"
                    "This is a provider connectivity test. Do not add anything else."
                ),
                timeout_seconds=timeout_seconds,
            ),
            stage="connectivity_test",
        )

    def _result(
        self,
        panel: PanelResult,
        *,
        critic: DelegateResult | None = None,
        arbiter: DelegateResult | None = None,
        answer: SingleSourceAnswer | None = None,
        seed: str | None = None,
    ) -> DeliberationResult:
        """Assemble a result. A single-source run carries one label, used everywhere."""
        single = panel.synthesizeable and panel.independent_source_count == 1
        labels = label_map(panel.delegates, seed) if panel.synthesizeable else {}
        name_label = {name: label for label, name in labels.items()}
        positions = build_positions(panel.delegates, panel.sources, name_label)
        # Only a multi-source Arbiter answer is read as four sections: a single-source
        # assessment is written under a different instruction.
        structure = (
            parse_sections(arbiter.raw_response, labels)
            if arbiter is not None and arbiter.status == DelegateStatus.SUCCEEDED and not single
            else None
        )
        overlapping = {
            name_label[name]
            for judge in (critic, arbiter)
            if judge is not None
            for name in judge_overlap(judge, panel.delegates, self._identities)
            if name in name_label
        }
        ledger = current_ledger()
        cost = ledger.totals() if ledger is not None else None
        refused = any(
            r is not None and r.error_kind == CEILING_ERROR_KIND
            for r in [*panel.delegates, critic, arbiter]
        )
        return DeliberationResult(
            schema_version=RESULT_SCHEMA_VERSION,
            stopped_reason="cost_ceiling" if refused else None,
            panel=panel,
            critic=critic,
            arbiter=arbiter,
            # The calls this run made, from the call ledger (every attempt, failure, fallback and
            # timeout). Without a ledger (a bare orchestrator call) the stage results are summed.
            estimated_cost_usd=(
                cost.estimated_total_usd
                if cost is not None
                else _total_cost([*panel.delegates, critic, arbiter])
            ),
            cost=cost,
            single_source=single,
            single_source_label=(
                describe_single_source(panel.quorum) if single and panel.quorum else None
            ),
            single_source_answer=answer,
            label_map=labels,
            judge_overlaps=sorted(overlapping),
            positions=positions,
            arbiter_structure=structure,
            insufficient_evidence=insufficient_evidence(
                positions,
                panel.sources,
                arbiter.raw_response
                if arbiter is not None and arbiter.status == DelegateStatus.SUCCEEDED
                else None,
            ),
        )

    @contextmanager
    def _ledger_for(self, call_context: CallContext | None, ceiling_usd: float | None = None):
        """Make a ledger active for one operation, so every call it makes is recorded."""
        context = call_context or CallContext()
        ledger = RunLedger(
            run_id=context.run_id, chain_root_id=context.chain_root_id, sink=self.ledger_sink
        )
        token = use_ledger(ledger)
        guard_token = use_guard(CostGuard(ceiling_usd) if ceiling_usd is not None else None)
        try:
            yield ledger
        finally:
            reset_guard(guard_token)
            reset_ledger(token)

    async def deliberate(
        self,
        request: DeliberationRequest,
        *,
        on_stage: StageCallback | None = None,
        call_context: CallContext | None = None,
    ) -> DeliberationResult:
        with self._ledger_for(call_context, request.max_estimated_cost_usd):
            return await self._deliberate(request, on_stage=on_stage)

    async def retry_delegate(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        delegate_name: str,
        call_context: CallContext | None = None,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        with self._ledger_for(call_context, request.max_estimated_cost_usd):
            return await self._retry_delegate(
                request=request,
                prior_result=prior_result,
                delegate_name=delegate_name,
                on_stage=on_stage,
            )

    async def retry_critic(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        call_context: CallContext | None = None,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        with self._ledger_for(call_context, request.max_estimated_cost_usd):
            return await self._retry_critic(
                request=request, prior_result=prior_result, on_stage=on_stage
            )

    async def retry_arbiter(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        call_context: CallContext | None = None,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        with self._ledger_for(call_context, request.max_estimated_cost_usd):
            return await self._retry_arbiter(
                request=request, prior_result=prior_result, on_stage=on_stage
            )

    async def _deliberate(
        self,
        request: DeliberationRequest,
        *,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        """Run the panel, then the Critic and Arbiter where they apply.

        ``on_stage`` is awaited with the result so far after the panel, after
        the Critic and after the Arbiter, so callers can persist each stage.
        """
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
            allow_single_source=request.allow_single_source,
        )
        async def keep_partial_panel(kept: list[DelegateResult]) -> None:
            if on_stage is not None:
                partial = self._panel_result(
                    question=request.question,
                    delegates=kept,
                    minimum_successes=request.minimum_successes,
                    allow_single_source=request.allow_single_source,
                )
                await on_stage(self._result(partial, seed=request.seed))

        panel = await self.run_panel(panel_request, on_interrupt=keep_partial_panel)
        if request.reserve_delegates and panel.quorum is not None and panel.quorum.status != "met":
            panel = await self._reserve_wave(request, panel, on_stage=on_stage)

        after_panel = self._result(panel, seed=request.seed)
        if on_stage is not None:
            await on_stage(after_panel)
        if not panel.synthesizeable:
            return after_panel
        return await self._downstream(
            request=request, panel=panel, critic=None, rerun_critic=True, on_stage=on_stage
        )

    async def _reserve_wave(
        self,
        request: DeliberationRequest,
        panel: PanelResult,
        *,
        on_stage: StageCallback | None = None,
    ) -> PanelResult:
        """One bounded replacement wave when the panel fell short of the quorum.

        At most as many reserves as independent sources are missing are called, together, once.
        A reserve that is the same configured model as an answer already in hand could not add
        a source, so it is skipped. Every answer already received is kept and nothing is
        re-run. Whether the quorum is now met is judged exactly as for any panel.
        """
        assert panel.quorum is not None
        missing = max(panel.quorum.required - panel.quorum.qualifying_sources, 0)
        held = {
            ident.config_key
            for r in panel.delegates
            if r.status == DelegateStatus.SUCCEEDED
            and (ident := identity_of(r, self._identities)) is not None
        }
        used = {r.name for r in panel.delegates}
        chosen: list[str] = []
        for name in request.reserve_delegates:
            if len(chosen) >= missing:
                break
            if name in used or name in chosen:
                continue
            ident = self._identities.get(name)
            if ident is not None:
                if ident.config_key in held:
                    continue
                held.add(ident.config_key)
            chosen.append(name)
        if not chosen:
            return panel

        wave_request = PanelRequest(
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
                for name in chosen
            ],
            minimum_successes=request.minimum_successes,
            allow_single_source=request.allow_single_source,
        )

        def combined(wave: list[DelegateResult]) -> PanelResult:
            marked = [r.model_copy(update={"reserve": True}) for r in wave]
            return self._panel_result(
                question=request.question,
                delegates=[*panel.delegates, *marked],
                minimum_successes=request.minimum_successes,
                allow_single_source=request.allow_single_source,
            )

        async def keep_partial_wave(kept: list[DelegateResult]) -> None:
            if on_stage is not None:
                await on_stage(self._result(combined(kept), seed=request.seed))

        wave = await self.run_panel(wave_request, on_interrupt=keep_partial_wave)
        return combined(wave.delegates)

    async def _downstream(
        self,
        *,
        request: DeliberationRequest,
        panel: PanelResult,
        critic: DelegateResult | None,
        rerun_critic: bool,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        """Critic and Arbiter for a panel that may proceed (one code path for every run).

        A single independent source has nothing to be compared with, so the Critic is
        skipped. The workspace's ``single_source_mode`` then decides whether the Arbiter
        runs. That mode only chooses how a single-source run ends: whether such a run may
        start at all was already decided by the quorum check.
        """
        single = panel.independent_source_count == 1
        label = describe_single_source(panel.quorum) if single and panel.quorum else None

        if single:
            critic = None
        elif rerun_critic and request.critic:
            critic = await self._run_with_fallback(
                stage="critic",
                primary=request.critic,
                fallbacks=request.critic_fallbacks,
                prompt=build_critic_prompt(
                    seed=request.seed,
                    response_char_limit=request.judge_response_char_limit,
                    source_groups=panel.sources,
                    families=panel.families,
                    question=request.question,
                    delegate_results=panel.delegates,
                    workspace_context=request.workspace_context,
                ),
                timeout_seconds=request.critic_timeout_seconds,
                shared_deadline=request.shared_stage_deadline,
            )
            if on_stage is not None:
                await on_stage(self._result(panel, critic=critic, seed=request.seed))

        if single and request.single_source_mode == "return_answer":
            only = next(r for r in panel.delegates if r.status == DelegateStatus.SUCCEEDED)
            final = self._result(
                panel,
                answer=SingleSourceAnswer(
                    delegate=only.name, text=only.raw_response or "", model=only.model
                ),
                seed=request.seed,
            )
        else:
            arbiter = await self._run_with_fallback(
                stage="arbiter",
                primary=request.arbiter,
                fallbacks=request.arbiter_fallbacks,
                prompt=build_arbiter_prompt(
                    seed=request.seed,
                    response_char_limit=request.judge_response_char_limit,
                    source_groups=panel.sources,
                    families=panel.families,
                    question=request.question,
                    delegate_results=panel.delegates,
                    workspace_context=request.workspace_context,
                    critic_result=critic,
                    single_source_label=label,
                ),
                timeout_seconds=request.arbiter_timeout_seconds,
                shared_deadline=request.shared_stage_deadline,
            )
            final = self._result(panel, critic=critic, arbiter=arbiter, seed=request.seed)
        if on_stage is not None:
            await on_stage(final)
        return final

    async def _retry_delegate(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        delegate_name: str,
        on_stage: StageCallback | None = None,
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
        panel = self._panel_result(
            question=request.question,
            delegates=delegates,
            minimum_successes=request.minimum_successes,
            allow_single_source=request.allow_single_source,
        )
        after_panel = self._result(panel, seed=request.seed)
        # The retried delegate's answer is saved the moment it exists, before any judge runs.
        if on_stage is not None:
            await on_stage(after_panel)
        if not panel.synthesizeable:
            return after_panel
        return await self._downstream(
            request=request, panel=panel, critic=None, rerun_critic=True, on_stage=on_stage
        )

    def _counted(self, request: DeliberationRequest, panel: PanelResult) -> PanelResult:
        """Give a run saved before source counting its source groups and quorum report.

        Such a panel has no ``independent_source_count``. Recomputing it from the stored
        answers (with the providers' current identities) means a retry is judged, and its
        prompts are written, by the same rules as a new run.
        """
        if panel.independent_source_count is not None:
            return panel
        return self._panel_result(
            question=panel.question,
            delegates=panel.delegates,
            minimum_successes=request.minimum_successes,
            allow_single_source=request.allow_single_source,
        )

    async def _retry_critic(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        if not request.critic:
            raise ValueError("The original request did not configure a Critic")
        panel = self._counted(request, prior_result.panel)
        if not panel.synthesizeable:
            raise ValueError("The Delegate panel does not satisfy quorum")
        if panel.independent_source_count == 1:
            raise ValueError("A single-source run does not use the Critic")
        return await self._downstream(
            request=request, panel=panel, critic=None, rerun_critic=True, on_stage=on_stage
        )

    async def _retry_arbiter(
        self,
        *,
        request: DeliberationRequest,
        prior_result: DeliberationResult,
        on_stage: StageCallback | None = None,
    ) -> DeliberationResult:
        panel = self._counted(request, prior_result.panel)
        if not panel.synthesizeable:
            raise ValueError("The Delegate panel does not satisfy quorum")
        if panel.independent_source_count == 1 and request.single_source_mode == "return_answer":
            raise ValueError(
                "This single-source run returned the delegate's answer, so it has no Arbiter to retry"
            )
        return await self._downstream(
            request=request,
            panel=panel,
            critic=prior_result.critic,
            rerun_critic=False,
            on_stage=on_stage,
        )

    async def _run_with_fallback(
        self,
        *,
        stage: str,
        primary: str,
        fallbacks: list[str],
        prompt: str,
        timeout_seconds: float,
        shared_deadline: bool = False,
    ) -> DelegateResult:
        """Try the primary, then each fallback in order, until one answers.

        By default every attempt gets the full ``timeout_seconds``. With ``shared_deadline`` the
        whole chain shares that one budget: each attempt gets what is left of it, and no further
        fallback starts once it is spent (the last failure is returned, with its prior attempts).
        """
        providers = [primary, *fallbacks]
        last_result: DelegateResult | None = None
        prior: list[PriorAttempt] = []
        loop = asyncio.get_running_loop()
        stage_deadline = loop.time() + timeout_seconds
        for name in providers:
            attempt_timeout = timeout_seconds
            if shared_deadline:
                attempt_timeout = stage_deadline - loop.time()
                if attempt_timeout <= 0 and last_result is not None:
                    break
                attempt_timeout = max(attempt_timeout, 0.001)
            result = await self._run_delegate(
                DelegateRequest(
                    name=name,
                    prompt=prompt,
                    timeout_seconds=attempt_timeout,
                ),
                stage=stage,
            )
            result = result.model_copy(update={"prior_attempts": list(prior)})
            if result.status == DelegateStatus.SUCCEEDED:
                return result
            last_result = result
            prior.append(
                PriorAttempt(
                    name=result.name,
                    status=result.status,
                    error_kind=result.error_kind,
                    latency_ms=result.latency_ms,
                    attempts=result.attempts,
                )
            )
        assert last_result is not None
        return last_result

    async def _run_delegate(
        self, delegate: DelegateRequest, *, stage: str = "delegate"
    ) -> DelegateResult:
        provider = self._providers.get(delegate.name)
        if provider is None:
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                prompt=delegate.prompt,
                error=f"No provider configured for delegate: {delegate.name}",
            )

        guard = current_guard()
        bound: float | None = 0.0
        if guard is not None:
            bound = worst_case_cost(provider, delegate.prompt)
            if not guard.admit(bound):
                return DelegateResult(
                    name=delegate.name,
                    status=DelegateStatus.FAILED,
                    prompt=delegate.prompt,
                    error=(
                        "Not called: its cost could not be bounded under the cost ceiling"
                        if bound is None
                        else "Not called: it could exceed the run's estimated cost ceiling"
                    ),
                    error_kind=CEILING_ERROR_KIND,
                )
        try:
            return await self._run_admitted(delegate, provider, stage)
        finally:
            if guard is not None and bound is not None:
                guard.release(bound)

    async def _run_admitted(
        self, delegate: DelegateRequest, provider: Provider, stage: str
    ) -> DelegateResult:
        ledger = current_ledger() or RunLedger(sink=self.ledger_sink)
        identity = self._identities.get(delegate.name)
        scope = CallScope(
            ledger=ledger,
            stage=stage,
            provider=delegate.name,
            model=identity.model if identity is not None else getattr(provider, "model", None),
        )
        token = use_scope(scope)
        try:
            result = await self._call_provider(delegate, provider)
            # Recorded with the answer: what this provider was when it gave it.
            result = result.model_copy(update={"provenance": provenance_of(identity)})
        except BaseException:
            # Cancelled mid-call: the request in flight may still be billed.
            scope.close_open("cancelled")
            self._record_unrecorded(scope, provider, None, "cancelled")
            raise
        finally:
            reset_scope(token)
        if result.status == DelegateStatus.TIMED_OUT:
            scope.close_open("timeout")
        self._record_unrecorded(scope, provider, result, None)
        return result

    def _record_unrecorded(
        self,
        scope: CallScope,
        provider: Provider,
        result: DelegateResult | None,
        forced_outcome: str | None,
    ) -> None:
        """One ledger row for a provider that does not write its own (fakes, demo providers)."""
        if getattr(provider, "records_calls", False) or scope.rows_written:
            return
        if forced_outcome is not None:
            outcome = forced_outcome
        elif result is not None and result.status == DelegateStatus.TIMED_OUT:
            outcome = "timeout"
        elif result is not None and (
            result.status == DelegateStatus.SUCCEEDED or result.error_kind == "empty_response"
        ):
            outcome = "ok"
        elif result is not None and result.error_kind in _HTTP_KINDS:
            outcome = "http_error"
        else:
            outcome = "transport_error"
        usage = result.usage if result is not None else {}
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        scope.write(
            CallRow(
                id=uuid.uuid4().hex,
                run_id=scope.ledger.run_id,
                chain_root_id=scope.ledger.chain_root_id,
                stage=scope.stage,
                provider=scope.provider,
                configured_model=scope.configured_model,
                reported_model=result.model if result is not None else None,
                attempt_no=result.attempts if result is not None else 1,
                outcome=outcome,
                started_at=now_iso(),
                latency_ms=result.latency_ms if result is not None else None,
                prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                completion_tokens=completion_tokens if isinstance(completion_tokens, int) else None,
                estimated_cost_usd=result.estimated_cost_usd if result is not None else None,
                possibly_billed=outcome in {"ok", "timeout", "cancelled", "transport_error"},
            )
        )

    async def _call_provider(self, delegate: DelegateRequest, provider: Provider) -> DelegateResult:
        started = perf_counter()
        try:
            async with asyncio.timeout(delegate.timeout_seconds) as deadline:
                response = await provider.ask(delegate.prompt)
        except Exception as exc:  # provider errors become data, not panel failures
            if isinstance(exc, TimeoutError) and deadline.expired():
                return DelegateResult(
                    name=delegate.name,
                    status=DelegateStatus.TIMED_OUT,
                    prompt=delegate.prompt,
                    error=f"Timed out after {delegate.timeout_seconds:g}s",
                    error_kind="timeout",
                    latency_ms=_elapsed_ms(started),
                )
            # A TimeoutError the provider raised on its own is a failure, not our deadline.
            message = str(exc).strip()
            if not message:
                message = f"{type(exc).__name__}: provider call failed without an error message"
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                prompt=delegate.prompt,
                error=message,
                error_kind=exc.kind if isinstance(exc, ProviderError) else None,
                attempts=exc.attempts if isinstance(exc, ProviderError) else 1,
                latency_ms=_elapsed_ms(started),
            )

        # Whatever a provider reports is untrusted data. A reply whose text or metadata is not
        # the shape we need becomes a contained failure of this one delegate, never an exception
        # that aborts the panel. (Cancellation is a BaseException and is not caught here.)
        try:
            text, model, usage, cost, attempts = _clean_response(response)
        except Exception:  # noqa: BLE001 - any malformed shape is the provider's failure
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                prompt=delegate.prompt,
                error="Provider returned a malformed reply (unusable text or metadata)",
                error_kind="malformed",
                latency_ms=_elapsed_ms(started),
            )
        if not text.strip():
            return DelegateResult(
                name=delegate.name,
                status=DelegateStatus.FAILED,
                prompt=delegate.prompt,
                raw_response=text,
                model=model,
                usage=usage,
                estimated_cost_usd=cost,
                error="Provider returned an empty response",
                error_kind="empty_response",
                attempts=attempts,
                latency_ms=_elapsed_ms(started),
            )

        return DelegateResult(
            name=delegate.name,
            status=DelegateStatus.SUCCEEDED,
            prompt=delegate.prompt,
            raw_response=text,
            model=model,
            usage=usage,
            estimated_cost_usd=cost,
            attempts=attempts,
            latency_ms=_elapsed_ms(started),
        )


MAX_REPORTED_MODEL_CHARS = 200


def _clean_response(response) -> tuple[str, str | None, dict, float | None, int]:
    """Text, reported model, usage, cost and attempts, each of the type the pipeline relies on.

    The text must be a string (anything else raises, and the caller records a malformed reply).
    Metadata of the wrong type is dropped to unknown rather than trusted: a reported model that
    is not a string, usage that is not a mapping, a cost that is not a finite non-negative number.
    """
    text = response.text
    if not isinstance(text, str):
        raise TypeError("reply text is not a string")
    model = response.model
    model = model[:MAX_REPORTED_MODEL_CHARS] if isinstance(model, str) and model.strip() else None
    usage = response.usage if isinstance(response.usage, dict) else {}
    cost = response.estimated_cost_usd
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        cost = None
    attempts = response.attempts
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        attempts = 1
    return text, model, usage, cost, attempts


_HTTP_KINDS = frozenset(
    {"auth", "quota", "rate_limit", "capacity", "bad_request", "server_error"}
)


def _total_cost(results: list[DelegateResult | None]) -> float | None:
    costs = [
        result.estimated_cost_usd
        for result in results
        if result is not None and result.estimated_cost_usd is not None
    ]
    if not costs:
        return None
    return round(sum(costs), 8)


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)

