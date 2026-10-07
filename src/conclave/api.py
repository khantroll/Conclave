from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .config import load_config
from .models import DeliberationRequest, DeliberationResult, PanelRequest, PanelResult
from .orchestrator import Orchestrator
from .providers.fake import FakeProvider
from .providers.factory import build_providers


def create_app() -> FastAPI:
    app = FastAPI(
        title="Conclave",
        version="0.1.0",
        description="Deterministic multi-model deliberation and synthesis.",
    )

    config = load_config()
    configured = build_providers(config.providers)

    # Keep deterministic demo delegates available until the UI/configuration
    # workflow exists. Configured providers simply add to this registry.
    providers = {
        "demo-a": FakeProvider("Delegate A response"),
        "demo-b": FakeProvider("Delegate B response"),
        "demo-arbiter": FakeProvider("Synthesized demo response"),
        **configured,
    }
    orchestrator = Orchestrator(providers)

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
        if request.minimum_successes > len(request.delegates):
            raise HTTPException(
                status_code=422,
                detail="minimum_successes cannot exceed the number of delegates",
            )
        return await orchestrator.run_panel(request)

    @app.post("/api/deliberate", response_model=DeliberationResult)
    async def deliberate(request: DeliberationRequest) -> DeliberationResult:
        if request.minimum_successes > len(request.delegates):
            raise HTTPException(
                status_code=422,
                detail="minimum_successes cannot exceed the number of delegates",
            )
        return await orchestrator.deliberate(request)

    return app


app = create_app()
