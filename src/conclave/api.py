from __future__ import annotations

import asyncio
import os
import secrets
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import analyze_request
from .config import ConclaveConfig, load_config
from .ledger import CallContext
from .models import (
    CallRow,
    DelegateStatus,
    RunSummary,
    AnalyzeRequest,
    DeliberationRequest,
    DeliberationResult,
    DeliberationRun,
    DelegateSelection,
    ProviderDescriptor,
    ProviderTestResult,
    RequestAnalysis,
    SelectionTrace,
    PanelRequest,
    PanelResult,
    Workspace,
    WorkspaceCreate,
    WorkspaceDeliberationRequest,
    WorkspaceReplace,
)
from .orchestrator import Orchestrator
from .providers.fake import FakeProvider
from .providers.factory import build_identities, build_providers
from .providers.unavailable import UnavailableProvider
from .quorum import QuorumUnmet, plan_delegates
from .security import LoopbackGuardMiddleware
from .selection import rank_candidates, select_delegates
from .sources import sharing_config
from .store import WorkspaceStore, summarize_run


DEFAULT_PAGE = 50
MAX_PAGE = 200


def create_app(
    *,
    config: ConclaveConfig | None = None,
    workspace_store: WorkspaceStore | None = None,
    run_log_dir: str | Path | None = None,
    load_env: bool = True,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """Build the application.

    When ``config`` is given, no configuration file or ``.env`` is read. When
    ``workspace_store`` is given, no database or run-log directory is opened.
    ``allowed_hosts`` adds to the loopback hosts that may reach the server; when omitted,
    ``CONCLAVE_ALLOWED_HOSTS`` (comma-separated) is used.
    """
    app = FastAPI(
        title="Conclave",
        version="0.1.0",
        description="Deterministic multi-model deliberation and synthesis.",
    )

    app.add_middleware(LoopbackGuardMiddleware, allowed_hosts=allowed_hosts)

    web_dir = Path(__file__).resolve().parents[2] / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def web_console() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    if config is None:
        config = load_config(load_env=load_env)
    configured = build_providers(config.providers)

    providers = {
        "demo-a": FakeProvider("Delegate A response"),
        "demo-b": FakeProvider("Delegate B response"),
        "demo-critic": FakeProvider("Critic demo response"),
        "demo-arbiter": FakeProvider("Synthesized demo response"),
        **configured,
    }
    descriptors: dict[str, ProviderDescriptor] = {
        "demo-a": ProviderDescriptor(
            name="demo-a",
            model="fake-model",
            capabilities=["general", "reasoning"],
            priority=50,
            source="demo",
        ),
        "demo-b": ProviderDescriptor(
            name="demo-b",
            model="fake-model",
            capabilities=["general", "critical"],
            priority=60,
            source="demo",
        ),
        "demo-critic": ProviderDescriptor(
            name="demo-critic",
            model="fake-model",
            capabilities=["critical"],
            priority=50,
            source="demo",
        ),
        "demo-arbiter": ProviderDescriptor(
            name="demo-arbiter",
            model="fake-model",
            capabilities=["reasoning", "general"],
            priority=40,
            source="demo",
        ),
        **{
            item.name: ProviderDescriptor(
                name=item.name,
                model=item.model,
                capabilities=item.capabilities or ["general"],
                priority=item.priority,
                input_cost_per_million=item.input_cost_per_million,
                output_cost_per_million=item.output_cost_per_million,
                source="configured",
            )
            for item in config.providers
        },
    }
    identities = build_identities(config.providers)
    orchestrator = Orchestrator(providers, identities)

    def is_eligible(name: str) -> bool:
        provider = providers.get(name)
        return provider is not None and not isinstance(provider, UnavailableProvider)

    def ineligible_reason(name: str) -> str:
        provider = providers.get(name)
        if provider is None:
            return "not configured"
        if isinstance(provider, UnavailableProvider):
            return provider.error
        return "unavailable"

    def plan_or_422(**kwargs):
        """Plan the delegates, or stop with a structured "quorum unmet" before any call."""
        try:
            return plan_delegates(
                is_eligible=is_eligible,
                ineligible_reason=ineligible_reason,
                identities=identities,
                **kwargs,
            )
        except QuorumUnmet as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc

    def workspace_warnings(delegates: list[str]) -> list[str]:
        return [
            f"{', '.join(group)} use the same base URL and model, so they will count as "
            "one source, not as corroboration."
            for group in sharing_config(delegates, identities)
        ]
    store = workspace_store or WorkspaceStore(
        os.getenv("CONCLAVE_DB_PATH", "conclave.db"),
        run_log_dir=run_log_dir or os.getenv("CONCLAVE_RUN_LOG_DIR", "run_logs"),
    )

    store.mark_interrupted_runs()
    # Chain roots with a retry in progress (one retry at a time per chain).
    retrying: set[str] = set()
    # Every provider request, from any endpoint, is recorded in the call ledger as it happens.
    orchestrator.ledger_sink = store.record_call

    async def _deliberate_and_store(
        *,
        request: DeliberationRequest,
        workspace_id: str | None,
        response: Response,
    ) -> DeliberationResult:
        if request.seed is None:
            request = request.model_copy(update={"seed": secrets.token_hex(16)})
        # The row exists before any provider is called, and is updated after
        # each stage, so a cancel or crash keeps every answer already paid for.
        run = store.create_run(
            question=request.question,
            request=request,
            workspace_id=workspace_id,
        )
        response.headers["X-Conclave-Run-ID"] = run.id

        async def on_stage(partial: DeliberationResult) -> None:
            store.update_run(run.id, partial, "running")

        try:
            result = await orchestrator.deliberate(
                request,
                on_stage=on_stage,
                call_context=CallContext(run_id=run.id, chain_root_id=run.id),
            )
        except BaseException:
            store.mark_interrupted(run.id)
            raise
        store.update_run(run.id, result, "complete")
        return result

    @app.get("/health")
    async def health() -> dict[str, str | int | bool]:
        configured_count = sum(1 for item in descriptors.values() if item.source == "configured")
        demo_count = sum(1 for item in descriptors.values() if item.source == "demo")
        return {
            "status": "ok",
            "provider_count": len(orchestrator.provider_names),
            "configured_provider_count": configured_count,
            "demo_provider_count": demo_count,
            "demo_only": configured_count == 0,
        }

    @app.get("/api/providers")
    async def provider_names() -> dict[str, object]:
        return {
            "providers": orchestrator.provider_names,
            "descriptors": [
                descriptors[name].model_dump()
                for name in orchestrator.provider_names
                if name in descriptors
            ],
        }

    @app.post("/api/providers/test-all", response_model=list[ProviderTestResult])
    async def test_all_configured_providers() -> list[ProviderTestResult]:
        names = [
            name
            for name in orchestrator.provider_names
            if descriptors.get(name) and descriptors[name].source == "configured"
        ]
        results = await asyncio.gather(
            *(orchestrator.test_provider(name) for name in names)
        )
        return [
            ProviderTestResult(
                name=result.name,
                status=result.status,
                model=result.model,
                latency_ms=result.latency_ms,
                error=result.error,
                error_kind=result.error_kind,
                attempts=result.attempts,
            )
            for result in results
        ]

    @app.post("/api/providers/{provider_name}/test", response_model=ProviderTestResult)
    async def test_provider(provider_name: str) -> ProviderTestResult:
        if provider_name not in orchestrator.provider_names:
            raise HTTPException(status_code=404, detail="Provider not found")
        result = await orchestrator.test_provider(provider_name)
        return ProviderTestResult(
            name=result.name,
            status=result.status,
            model=result.model,
            latency_ms=result.latency_ms,
            error=result.error,
            error_kind=result.error_kind,
            attempts=result.attempts,
        )

    @app.post("/api/analyze", response_model=RequestAnalysis)
    async def analyze(request: AnalyzeRequest) -> RequestAnalysis:
        return analyze_request(request.question)

    @app.post("/api/panel", response_model=PanelResult)
    async def run_panel(request: PanelRequest) -> PanelResult:
        _validate_quorum(request.minimum_successes, len(request.delegates))
        _validate_participants(
            delegates=[delegate.name for delegate in request.delegates],
            roles={},
            critic=None,
            critic_fallbacks=[],
            arbiter=None,
            arbiter_fallbacks=[],
            provider_names=orchestrator.provider_names,
        )
        return await orchestrator.run_panel(request)

    @app.post("/api/deliberate", response_model=DeliberationResult)
    async def deliberate(
        request: DeliberationRequest,
        response: Response,
    ) -> DeliberationResult:
        # No bare count check here: plan_delegates() decides whether the quorum is reachable
        # and answers with a structured "quorum unmet" (or a labelled single-source run).
        _validate_participants(
            delegates=request.delegates,
            roles=request.roles,
            critic=request.critic,
            critic_fallbacks=request.critic_fallbacks,
            arbiter=request.arbiter,
            arbiter_fallbacks=request.arbiter_fallbacks,
            provider_names=orchestrator.provider_names,
        )
        plan = plan_or_422(
            selected=request.delegates,
            pool=request.delegates,
            ranked_extra=[],
            required=request.minimum_successes,
            allow_single_source=request.allow_single_source,
        )
        if plan.delegates != request.delegates:
            # Single-source run: one source answers once, so only one delegate is called.
            request = request.model_copy(
                update={
                    "delegates": plan.delegates,
                    "roles": {k: v for k, v in request.roles.items() if k in plan.delegates},
                    "selection": SelectionTrace(
                        required_sources=request.minimum_successes,
                        expected_sources=plan.expected_sources,
                        single_source=True,
                    ),
                }
            )
        return await _deliberate_and_store(
            request=request, workspace_id=None, response=response
        )

    @app.post("/api/workspaces", response_model=Workspace, status_code=201)
    async def create_workspace(request: WorkspaceCreate) -> Workspace:
        _validate_workspace(request, orchestrator.provider_names)
        return store.create(request).model_copy(
            update={"warnings": workspace_warnings(request.delegates)}
        )

    @app.get("/api/workspaces", response_model=list[Workspace])
    async def list_workspaces() -> list[Workspace]:
        return store.list()

    @app.get("/api/workspaces/{workspace_id}", response_model=Workspace)
    async def get_workspace(workspace_id: str) -> Workspace:
        workspace = store.get(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace

    @app.put("/api/workspaces/{workspace_id}", response_model=Workspace)
    async def replace_workspace(
        workspace_id: str,
        request: WorkspaceReplace,
    ) -> Workspace:
        _validate_workspace(request, orchestrator.provider_names)
        workspace = store.replace(workspace_id, request)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace.model_copy(update={"warnings": workspace_warnings(request.delegates)})

    @app.delete("/api/workspaces/{workspace_id}", status_code=204)
    async def delete_workspace(workspace_id: str) -> Response:
        if not store.delete(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        return Response(status_code=204)


    @app.post(
        "/api/workspaces/{workspace_id}/select",
        response_model=DelegateSelection,
    )
    async def preview_workspace_selection(
        workspace_id: str,
        request: AnalyzeRequest,
    ) -> DelegateSelection:
        workspace = store.get(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        analysis = analyze_request(request.question)
        return select_delegates(
            analysis=analysis,
            candidates=workspace.delegates,
            descriptors=descriptors,
        )

    @app.get(
        "/api/workspaces/{workspace_id}/runs",
        response_model=list[RunSummary],
    )
    async def list_workspace_runs(
        workspace_id: str,
        all_attempts: bool = False,
        limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
        before: str | None = None,
    ) -> list[RunSummary]:
        if store.get(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return _page(workspace_id, all_attempts, limit, before)

    @app.get("/api/runs", response_model=list[RunSummary])
    async def list_all_runs(
        all_attempts: bool = False,
        limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
        before: str | None = None,
    ) -> list[RunSummary]:
        """Summaries of the newest run of each retry chain, newest first.

        ``?all_attempts=true`` lists every attempt; ``limit`` (default 50, at most 200) and
        ``before`` (a run id, for the next page) bound the list. Full detail, including every
        prompt and answer, is ``GET /api/runs/{id}``.
        """
        return _page(None, all_attempts, limit, before)

    def _page(
        workspace_id: str | None, all_attempts: bool, limit: int, before: str | None
    ) -> list[RunSummary]:
        try:
            return store.list_run_summaries(
                workspace_id, include_all_attempts=all_attempts, limit=limit, before=before
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="'before' is not a known run id") from exc

    @app.get("/api/runs/{run_id}/chain", response_model=list[RunSummary])
    async def get_run_chain(run_id: str) -> list[RunSummary]:
        """Every attempt in the retry chain a run belongs to, from the root to the newest."""
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        return [summarize_run(run) for run in store.chain_runs(store.chain_root_of(run_id))]

    @app.get("/api/runs/{run_id}", response_model=DeliberationRun)
    async def get_run(run_id: str) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        return run

    @app.get("/api/runs/{run_id}/calls", response_model=list[CallRow])
    async def get_run_calls(run_id: str, chain: bool = False) -> list[CallRow]:
        """The call-ledger rows of a run, or of its whole retry chain with ``?chain=true``."""
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        if chain:
            return store.calls_for_chain(store.chain_root_of(run_id))
        return store.calls_for_run(run_id)

    @app.post(
        "/api/workspaces/{workspace_id}/deliberate",
        response_model=DeliberationResult,
    )
    async def deliberate_in_workspace(
        workspace_id: str,
        request: WorkspaceDeliberationRequest,
        response: Response,
    ) -> DeliberationResult:
        workspace = store.get(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        required = workspace.minimum_successes  # the configured quorum is never lowered
        trace: SelectionTrace | None = None
        if workspace.auto_select_delegates:
            analysis = analyze_request(request.question)
            selection = select_delegates(
                analysis=analysis,
                candidates=workspace.delegates,
                descriptors=descriptors,
            )
            plan = plan_or_422(
                selected=selection.selected,
                pool=workspace.delegates,
                ranked_extra=rank_candidates(
                    analysis=analysis,
                    candidates=[n for n in workspace.delegates if is_eligible(n)],
                    descriptors=descriptors,
                ),
                required=required,
                allow_single_source=workspace.allow_single_source,
                drop_ineligible=True,
            )
            trace = SelectionTrace(
                auto_selected=selection.selected,
                topped_up=plan.topped_up,
                skipped_unavailable=[n for n in selection.selected if not is_eligible(n)],
                required_sources=required,
                expected_sources=plan.expected_sources,
                single_source=plan.single_source,
            )
        else:
            plan = plan_or_422(
                selected=workspace.delegates,
                pool=workspace.delegates,
                ranked_extra=[],
                required=required,
                allow_single_source=workspace.allow_single_source,
            )
            if plan.single_source:
                trace = SelectionTrace(
                    required_sources=required,
                    expected_sources=plan.expected_sources,
                    single_source=True,
                )
        delegates = plan.delegates

        deliberation = DeliberationRequest(
            question=request.question,
            delegates=delegates,
            arbiter=workspace.arbiter,
            arbiter_fallbacks=workspace.arbiter_fallbacks,
            critic=workspace.critic,
            critic_fallbacks=workspace.critic_fallbacks,
            roles={name: workspace.roles[name] for name in delegates if name in workspace.roles},
            workspace_context=workspace.context,
            minimum_successes=required,
            allow_single_source=workspace.allow_single_source,
            single_source_mode=workspace.single_source_mode or "return_answer",
            selection=trace,
            timeout_seconds=request.timeout_seconds,
            critic_timeout_seconds=request.critic_timeout_seconds,
            arbiter_timeout_seconds=request.arbiter_timeout_seconds,
        )
        return await _deliberate_and_store(
            request=deliberation, workspace_id=workspace.id, response=response
        )

    async def _retry(run_id: str, error_status: int, call) -> DeliberationRun:
        """Run one retry as a new run in the same chain.

        The new run's row exists, as ``running``, before any provider is called, so every ledger
        row written for it has a run to belong to even if the retry is cancelled or fails.
        """
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        if run.request is None:
            raise HTTPException(
                status_code=409,
                detail="This run predates request snapshots and cannot be retried safely",
            )
        request = _seeded(run.request)
        new_id, chain_root = str(uuid4()), store.chain_root_of(run_id)
        # One retry at a time per chain: two at once would both spend and write conflicting
        # histories. (A single event loop makes this check-and-add atomic.)
        if chain_root in retrying:
            raise HTTPException(
                status_code=409, detail="A retry is already running for this run's chain"
            )
        retrying.add(chain_root)
        try:
            store.create_run(
                question=run.question,
                request=request,
                workspace_id=run.workspace_id,
                run_id=new_id,
                parent_run_id=run_id,
                chain_root_id=chain_root,
            )
            context = CallContext(run_id=new_id, chain_root_id=chain_root)
            try:
                result = await call(request, run.result, context)
            except ValueError as exc:
                # Refused before any provider was called: there is nothing to keep.
                store.discard_run(new_id)
                raise HTTPException(status_code=error_status, detail=str(exc)) from exc
            except BaseException:
                store.mark_interrupted(new_id)
                raise
            store.update_run(new_id, result, "complete")
            saved = store.get_run(new_id)
            assert saved is not None
            return saved
        finally:
            retrying.discard(chain_root)

    @app.post("/api/runs/{run_id}/delegates/{delegate_name}/retry", response_model=DeliberationRun)
    async def retry_delegate(
        run_id: str, delegate_name: str, force: bool = False
    ) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is not None and not force:
            current = next((d for d in run.result.panel.delegates if d.name == delegate_name), None)
            if current is not None and current.status == DelegateStatus.SUCCEEDED:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Delegate '{delegate_name}' already succeeded in this run; pass "
                        "?force=true to run it again"
                    ),
                )
        return await _retry(
            run_id,
            404,
            lambda request, prior, context: orchestrator.retry_delegate(
                request=request, prior_result=prior, delegate_name=delegate_name, call_context=context
            ),
        )

    @app.post("/api/runs/{run_id}/critic/retry", response_model=DeliberationRun)
    async def retry_critic(run_id: str) -> DeliberationRun:
        return await _retry(
            run_id,
            409,
            lambda request, prior, context: orchestrator.retry_critic(
                request=request, prior_result=prior, call_context=context
            ),
        )

    @app.post("/api/runs/{run_id}/arbiter/retry", response_model=DeliberationRun)
    async def retry_arbiter(run_id: str) -> DeliberationRun:
        return await _retry(
            run_id,
            409,
            lambda request, prior, context: orchestrator.retry_arbiter(
                request=request, prior_result=prior, call_context=context
            ),
        )

    return app


def _seeded(request: DeliberationRequest) -> DeliberationRequest:
    """Keep the stored seed so a retry rebuilds the same markers; legacy runs get one."""
    if request.seed is not None:
        return request
    return request.model_copy(update={"seed": secrets.token_hex(16)})


def _validate_workspace(request: WorkspaceCreate, provider_names: list[str]) -> None:
    if "critic" not in request.model_fields_set:
        # There is no Critic default: whether a Critic helps has not been measured yet, so the
        # choice is the user's, made explicitly (a provider name, or null for no Critic).
        raise HTTPException(
            status_code=422,
            detail=(
                "critic is required: name a Critic provider, or send null for no Critic. There "
                "is no default, because the Critic's value has not been measured yet."
            ),
        )
    if request.single_source_mode is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "single_source_mode is required: choose 'return_answer' (the lone answer is "
                "returned, no Arbiter) or 'arbiter_single_source' (the Arbiter assesses it). "
                "It does not allow single-source runs; that is allow_single_source."
            ),
        )
    _validate_quorum(request.minimum_successes, len(request.delegates))
    _validate_participants(
        delegates=request.delegates,
        roles=request.roles,
        critic=request.critic,
        critic_fallbacks=request.critic_fallbacks,
        arbiter=request.arbiter,
        arbiter_fallbacks=request.arbiter_fallbacks,
        provider_names=provider_names,
    )


def _validate_participants(
    *,
    delegates: list[str],
    roles: dict[str, str],
    critic: str | None,
    critic_fallbacks: list[str],
    arbiter: str | None,
    arbiter_fallbacks: list[str],
    provider_names: list[str],
) -> None:
    """Names must be unique and known, and fallbacks must not repeat their primary."""
    if len(set(delegates)) != len(delegates):
        raise HTTPException(status_code=422, detail="Delegates must be unique")
    unknown_roles = sorted(set(roles) - set(delegates))
    if unknown_roles:
        names = ", ".join(unknown_roles)
        raise HTTPException(
            status_code=422,
            detail=f"Role configured for non-delegate provider(s): {names}",
        )
    known = set(provider_names)
    missing = [name for name in delegates if name not in known]
    if critic and critic not in known:
        missing.append(critic)
    missing.extend(name for name in critic_fallbacks if name not in known)
    if arbiter and arbiter not in known:
        missing.append(arbiter)
    missing.extend(name for name in arbiter_fallbacks if name not in known)
    if critic and critic in critic_fallbacks:
        raise HTTPException(
            status_code=422, detail="Critic fallback list must not repeat the primary Critic"
        )
    if arbiter and arbiter in arbiter_fallbacks:
        raise HTTPException(
            status_code=422, detail="Arbiter fallback list must not repeat the primary Arbiter"
        )
    if len(set(critic_fallbacks)) != len(critic_fallbacks):
        raise HTTPException(status_code=422, detail="Critic fallback providers must be unique")
    if len(set(arbiter_fallbacks)) != len(arbiter_fallbacks):
        raise HTTPException(status_code=422, detail="Arbiter fallback providers must be unique")
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise HTTPException(status_code=422, detail=f"Unknown provider(s): {names}")


def _validate_quorum(minimum_successes: int, delegate_count: int) -> None:
    if minimum_successes > delegate_count:
        raise HTTPException(
            status_code=422,
            detail="minimum_successes cannot exceed the number of delegates",
        )


_default_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    # ``uvicorn conclave.api:app`` still works, but importing this module no
    # longer reads configuration or opens the database. The application is
    # built on first access.
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
