from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field


class DelegateStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class DelegateRequest(BaseModel):
    name: str
    prompt: str
    timeout_seconds: float = Field(default=60.0, gt=0)


class DelegateResult(BaseModel):
    name: str
    status: DelegateStatus
    prompt: str | None = None
    raw_response: str | None = None
    model: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float | None = None
    attempts: int = Field(default=1, ge=1)


class PanelRequest(BaseModel):
    question: str = Field(min_length=1)
    delegates: list[DelegateRequest] = Field(min_length=1)
    minimum_successes: int = Field(default=1, ge=1)


class PanelResult(BaseModel):
    question: str
    delegates: list[DelegateResult]
    successful_count: int
    failed_count: int
    synthesizeable: bool


class DeliberationRequest(BaseModel):
    question: str = Field(min_length=1)
    delegates: list[str] = Field(min_length=1)
    arbiter: str = Field(min_length=1)
    arbiter_fallbacks: list[str] = Field(default_factory=list)
    critic: str | None = None
    critic_fallbacks: list[str] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)
    workspace_context: str | None = None
    minimum_successes: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    critic_timeout_seconds: float = Field(default=60.0, gt=0)
    arbiter_timeout_seconds: float = Field(default=90.0, gt=0)


class DeliberationResult(BaseModel):
    panel: PanelResult
    critic: DelegateResult | None = None
    arbiter: DelegateResult | None = None
    estimated_cost_usd: float | None = None


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    context: str | None = None
    delegates: list[str] = Field(min_length=1)
    roles: dict[str, str] = Field(default_factory=dict)
    critic: str | None = None
    critic_fallbacks: list[str] = Field(default_factory=list)
    arbiter: str = Field(min_length=1)
    arbiter_fallbacks: list[str] = Field(default_factory=list)
    minimum_successes: int = Field(default=1, ge=1)
    auto_select_delegates: bool = False


class Workspace(WorkspaceCreate):
    id: str
    created_at: str
    updated_at: str


class WorkspaceReplace(WorkspaceCreate):
    pass


class WorkspaceDeliberationRequest(BaseModel):
    question: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    critic_timeout_seconds: float = Field(default=60.0, gt=0)
    arbiter_timeout_seconds: float = Field(default=90.0, gt=0)


class DeliberationRun(BaseModel):
    id: str
    workspace_id: str | None = None
    question: str
    request: DeliberationRequest | None = None
    result: DeliberationResult
    created_at: str
    status: Literal["running", "complete", "interrupted"] = "complete"
    updated_at: str | None = None
    status: Literal["running", "complete", "interrupted"] = "complete"
    updated_at: str | None = None


class RequestComplexity(StrEnum):
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"
    DEEP = "deep"


class RequestAnalysis(BaseModel):
    complexity: RequestComplexity
    recommended_delegate_count: int = Field(ge=1, le=4)
    desired_capabilities: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    rationale: str


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1)


class ProviderDescriptor(BaseModel):
    name: str
    model: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    priority: int = 100
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    source: str = "configured"


class ProviderTestResult(BaseModel):
    name: str
    status: DelegateStatus
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    attempts: int = Field(default=1, ge=1)


class DelegateSelection(BaseModel):
    analysis: RequestAnalysis
    selected: list[str]
    available: list[str]
