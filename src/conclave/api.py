from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import analyze_request
from .config import ConclaveConfig, load_config
from .models import (
    AnalyzeRequest,
    DeliberationRequest,
    DeliberationResult,
    DeliberationRun,
    DelegateSelection,
    ProviderDescriptor,
    ProviderTestResult,
    RequestAnalysis,
    PanelRequest,
    PanelResult,
    Workspace,
    WorkspaceCreate,
    WorkspaceDeliberationRequest,
    WorkspaceReplace,
)
from .orchestrator import Orchestrator
from .providers.fake import FakeProvider
from .providers.factory import build_providers
from .selection import select_delegates
from .store import WorkspaceStore


def create_app(
    *,
    config: ConclaveConfig | None = None,
    workspace_store: WorkspaceStore | None = None,
    run_log_dir: str | Path | None = None,
    load_env: bool = True,
) -> FastAPI:
    """Build the application.

    When ``config`` is given, no configuration file or ``.env`` is read. When
    ``workspace_store`` is given, no database or run-log directory is opened.
    """
    app = FastAPI(
        title="Conclave",
        version="0.1.0",
        description="Deterministic multi-model deliberation and synthesis.",
    )

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
    orchestrator = Orchestrator(providers)
    store = workspace_store or WorkspaceStore(
        os.getenv("CONCLAVE_DB_PATH", "conclave.db"),
        run_log_dir=run_log_dir or os.getenv("CONCLAVE_RUN_LOG_DIR", "run_logs"),
    )

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
            attempts=result.attempts,
        )

    @app.post("/api/analyze", response_model=RequestAnalysis)
    async def analyze(request: AnalyzeRequest) -> RequestAnalysis:
        return analyze_request(request.question)

    @app.post("/api/panel", response_model=PanelResult)
    async def run_panel(request: PanelRequest) -> PanelResult:
        _validate_quorum(request.minimum_successes, len(request.delegates))
        return await orchestrator.run_panel(request)

    @app.post("/api/deliberate", response_model=DeliberationResult)
    async def deliberate(
        request: DeliberationRequest,
        response: Response,
    ) -> DeliberationResult:
        _validate_quorum(request.minimum_successes, len(request.delegates))
        result = await orchestrator.deliberate(request)
        run = store.save_run(
            question=request.question,
            request=request,
            result=result,
        )
        response.headers["X-Conclave-Run-ID"] = run.id
        return result

    @app.post("/api/workspaces", response_model=Workspace, status_code=201)
    async def create_workspace(request: WorkspaceCreate) -> Workspace:
        _validate_workspace(request, orchestrator.provider_names)
        return store.create(request)

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
        return workspace

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
        response_model=list[DeliberationRun],
    )
    async def list_workspace_runs(workspace_id: str) -> list[DeliberationRun]:
        if store.get(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return store.list_runs(workspace_id)

    @app.get("/api/runs", response_model=list[DeliberationRun])
    async def list_all_runs() -> list[DeliberationRun]:
        return store.list_runs()

    @app.get("/api/runs/{run_id}", response_model=DeliberationRun)
    async def get_run(run_id: str) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        return run

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

        delegates = workspace.delegates
        if workspace.auto_select_delegates:
            selection = select_delegates(
                analysis=analyze_request(request.question),
                candidates=workspace.delegates,
                descriptors=descriptors,
            )
            delegates = selection.selected

        deliberation = DeliberationRequest(
            question=request.question,
            delegates=delegates,
            arbiter=workspace.arbiter,
            arbiter_fallbacks=workspace.arbiter_fallbacks,
            critic=workspace.critic,
            critic_fallbacks=workspace.critic_fallbacks,
            roles={name: workspace.roles[name] for name in delegates if name in workspace.roles},
            workspace_context=workspace.context,
            minimum_successes=min(workspace.minimum_successes, len(delegates)),
            timeout_seconds=request.timeout_seconds,
            critic_timeout_seconds=request.critic_timeout_seconds,
            arbiter_timeout_seconds=request.arbiter_timeout_seconds,
        )
        result = await orchestrator.deliberate(deliberation)
        run = store.save_run(
            workspace_id=workspace.id,
            question=request.question,
            request=deliberation,
            result=result,
        )
        response.headers["X-Conclave-Run-ID"] = run.id
        return result

    @app.post("/api/runs/{run_id}/delegates/{delegate_name}/retry", response_model=DeliberationRun)
    async def retry_delegate(run_id: str, delegate_name: str) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        if run.request is None:
            raise HTTPException(
                status_code=409,
                detail="This run predates request snapshots and cannot be retried safely",
            )
        try:
            result = await orchestrator.retry_delegate(
                request=run.request,
                prior_result=run.result,
                delegate_name=delegate_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return store.save_run(
            workspace_id=run.workspace_id,
            question=run.question,
            request=run.request,
            result=result,
        )

    @app.post("/api/runs/{run_id}/critic/retry", response_model=DeliberationRun)
    async def retry_critic(run_id: str) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        if run.request is None:
            raise HTTPException(
                status_code=409,
                detail="This run predates request snapshots and cannot be retried safely",
            )
        try:
            result = await orchestrator.retry_critic(
                request=run.request,
                prior_result=run.result,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return store.save_run(
            workspace_id=run.workspace_id,
            question=run.question,
            request=run.request,
            result=result,
        )

    @app.post("/api/runs/{run_id}/arbiter/retry", response_model=DeliberationRun)
    async def retry_arbiter(run_id: str) -> DeliberationRun:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Deliberation run not found")
        if run.request is None:
            raise HTTPException(
                status_code=409,
                detail="This run predates request snapshots and cannot be retried safely",
            )
        try:
            result = await orchestrator.retry_arbiter(
                request=run.request,
                prior_result=run.result,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return store.save_run(
            workspace_id=run.workspace_id,
            question=run.question,
            request=run.request,
            result=result,
        )

    return app


def _validate_workspace(request: WorkspaceCreate, provider_names: list[str]) -> None:
    _validate_quorum(request.minimum_successes, len(request.delegates))
    if len(set(request.delegates)) != len(request.delegates):
        raise HTTPException(status_code=422, detail="Delegates must be unique")
    unknown_roles = sorted(set(request.roles) - set(request.delegates))
    if unknown_roles:
        names = ", ".join(unknown_roles)
        raise HTTPException(
            status_code=422,
            detail=f"Role configured for non-delegate provider(s): {names}",
        )
    known = set(provider_names)
    missing = [name for name in request.delegates if name not in known]
    if request.critic and request.critic not in known:
        missing.append(request.critic)
    missing.extend(name for name in request.critic_fallbacks if name not in known)
    if request.arbiter not in known:
        missing.append(request.arbiter)
    missing.extend(name for name in request.arbiter_fallbacks if name not in known)
    if request.critic and request.critic in request.critic_fallbacks:
        raise HTTPException(status_code=422, detail="Critic fallback list must not repeat the primary Critic")
    if request.arbiter in request.arbiter_fallbacks:
        raise HTTPException(status_code=422, detail="Arbiter fallback list must not repeat the primary Arbiter")
    if len(set(request.critic_fallbacks)) != len(request.critic_fallbacks):
        raise HTTPException(status_code=422, detail="Critic fallback providers must be unique")
    if len(set(request.arbiter_fallbacks)) != len(request.arbiter_fallbacks):
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
