from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .models import PanelRequest, PanelResult
from .orchestrator import Orchestrator
from .providers.fake import FakeProvider

app = FastAPI(
    title="Conclave",
    version="0.1.0",
    description="Deterministic multi-model deliberation and synthesis.",
)

# Deliberately demo-only. Real provider configuration comes next.
_orchestrator = Orchestrator(
    {
        "demo-a": FakeProvider("Delegate A response"),
        "demo-b": FakeProvider("Delegate B response"),
    }
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/panel", response_model=PanelResult)
async def run_panel(request: PanelRequest) -> PanelResult:
    if request.minimum_successes > len(request.delegates):
        raise HTTPException(
            status_code=422,
            detail="minimum_successes cannot exceed the number of delegates",
        )
    return await _orchestrator.run_panel(request)
