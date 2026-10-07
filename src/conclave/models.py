from __future__ import annotations

from enum import StrEnum
from typing import Any

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
    raw_response: str | None = None
    model: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


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
    roles: dict[str, str] = Field(default_factory=dict)
    workspace_context: str | None = None
    minimum_successes: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    arbiter_timeout_seconds: float = Field(default=90.0, gt=0)


class DeliberationResult(BaseModel):
    panel: PanelResult
    arbiter: DelegateResult | None = None
