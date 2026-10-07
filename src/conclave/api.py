from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException

from .config import load_config
from .models import (
    DeliberationRequest,
    DeliberationResult,
    PanelRequest,
    PanelResult,
    Workspace,
    WorkspaceCreate,
    WorkspaceDeliberationRequest,
)
from .orchestrator import Orchestrator
from .providers.fake import FakeProvider
from .providers.factory import build_providers
from .store import WorkspaceStore


def create_app(*, workspace_store: WorkspaceStore | None = None) -> FastAPI:
    app = FastAPI(
        title="Conclave",
        version="0.1.0",
        description="Deterministic multi-model deliberation and synthesis.",
    )

    config = load_config()
    configured = build_providers(config.providers)

    providers = {
        "demo-a": FakeProvider("Delegate A response"),
        "demo-b": FakeProvider("Delegate B response"),
        "demo-critic": FakeProvider("Critic demo response"),
        "demo-arbiter": FakeProvider("Synthesized demo response"),
        **configured,
    }
    orchestrator = Orchestrator(providers)
    store = workspace_store or WorkspaceStore(
        os.getenv("CONCLAVE_DB_PATH", "conclave.db")
    )

    @app.get("/health")
    async def health() -> dict[str, str | int]:
        return {
            "status": "ok",
            "provider_count": len(orchestrator.provider_names),
        }

    @app.get("/api/providers")
    async def provider_names() -> dict[str, list[str]]:
        return {"providers": orchestrator.provider_names}

    @app.post("/api/panel", response_model=PanelResult)
    async def run_panel(request: PanelRequest) -> PanelResult:
        _validate_quorum(request.minimum_successes, len(request.delegates))
        return await orchestrator.run_panel(request)

    @app.post("/api/deliberate", response_model=DeliberationResult)
    async def deliberate(request: DeliberationRequest) -> DeliberationResult:
        _validate_quorum(request.minimum_successes, len(request.delegates))
        return await orchestrator.deliberate(request)

    @app.post("/api/workspaces", response_model=Workspace, status_code=201)
    async def create_workspace(request: WorkspaceCreate) -> Workspace:
        _validate_quorum(request.minimum_successes, len(request.delegates))
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

    @app.post(
        "/api/workspaces/{workspace_id}/deliberate",
        response_model=DeliberationResult,
    )
    async def deliberate_in_workspace(
        workspace_id: str,
        request: WorkspaceDeliberationRequest,
    ) -> DeliberationResult:
        workspace = store.get(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        deliberation = DeliberationRequest(
            question=request.question,
            delegates=workspace.delegates,
            arbiter=workspace.arbiter,
            critic=workspace.critic,
            roles=workspace.roles,
            workspace_context=workspace.context,
            minimum_successes=workspace.minimum_successes,
            timeout_seconds=request.timeout_seconds,
            critic_timeout_seconds=request.critic_timeout_seconds,
            arbiter_timeout_seconds=request.arbiter_timeout_seconds,
        )
        return await orchestrator.deliberate(deliberation)

    return app


def _validate_quorum(minimum_successes: int, delegate_count: int) -> None:
    if minimum_successes > delegate_count:
        raise HTTPException(
            status_code=422,
            detail="minimum_successes cannot exceed the number of delegates",
        )


app = create_app()
