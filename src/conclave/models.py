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
    error_kind: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float | None = None
    attempts: int = Field(default=1, ge=1)


class QuorumReport(BaseModel):
    """Whether a finished panel met the configured quorum, judged by answers received."""

    status: Literal["met", "unmet", "single_source_override"]
    required: int
    qualifying_sources: int
    responses_received: int
    delegates_attempted: int
    summary: str
    shortfalls: list[str] = Field(default_factory=list)


class SelectionTrace(BaseModel):
    """How the delegates of a run were chosen, kept with the saved request."""

    auto_selected: list[str] = Field(default_factory=list)
    topped_up: list[str] = Field(default_factory=list)
    # Picked by the ranking but not run, because the provider is not configured or lacks
    # credentials.
    skipped_unavailable: list[str] = Field(default_factory=list)
    required_sources: int
    expected_sources: int
    single_source: bool = False


# What happens when exactly one independent source answered. This never decides whether such
# a run may start: only ``allow_single_source`` (or a quorum of 1) does that.
SingleSourceMode = Literal["return_answer", "arbiter_single_source"]


class SingleSourceAnswer(BaseModel):
    """The lone delegate answer returned as the result of a single-source run."""

    delegate: str
    text: str
    model: str | None = None


class PositionRow(BaseModel):
    """One delegate's own stated conclusion and confidence, read from its own answer only."""

    delegate: str
    # The label the judges saw (None when the delegate did not answer or no judge could run).
    label: str | None = None
    # 1-based number of the independent source the delegate belongs to.
    source: int | None = None
    status: str
    conclusion: str | None = None
    # high | medium | low | insufficient evidence; None when missing or unrecognized.
    confidence: str | None = None
    # What the Confidence line said when it was not one of the four levels.
    confidence_text: str | None = None


class StructuredPoint(BaseModel):
    """One point in an Arbiter section, with the response labels it cites."""

    text: str
    citations: list[str] = Field(default_factory=list)


class ArbiterStructure(BaseModel):
    """The Arbiter's answer read as four sections. Stored beside the untouched raw answer."""

    format_ok: bool
    # Why the answer was not accepted (fixed wording, never model text). Empty when format_ok.
    problems: list[str] = Field(default_factory=list)
    # common_ground, disagreements, uncertainty, synthesis (only when format_ok).
    sections: dict[str, str] = Field(default_factory=dict)
    points: dict[str, list[StructuredPoint]] = Field(default_factory=dict)
    # Cited labels that do not exist in this run.
    unknown_citations: list[str] = Field(default_factory=list)
    # Points under the first three sections that cite no response (and are not "None.").
    uncited_points: int = 0


class PanelRequest(BaseModel):
    question: str = Field(min_length=1)
    delegates: list[DelegateRequest] = Field(min_length=1)
    minimum_successes: int = Field(default=1, ge=1)
    allow_single_source: bool = False


class SourceGroup(BaseModel):
    """Successful delegates that count as one independent source."""

    delegates: list[str]
    # same_config, same_reported_model, unresolved_router_alias or near_duplicate_text;
    # None for a lone delegate.
    reason: str | None = None
    # Highest text similarity (0 to 1) that merged members by near_duplicate_text.
    similarity: float | None = None


class PanelResult(BaseModel):
    question: str
    delegates: list[DelegateResult]
    successful_count: int
    failed_count: int
    synthesizeable: bool
    # Quorum is measured against independent sources, not raw successes. None on runs
    # saved before source counting existed.
    independent_source_count: int | None = None
    sources: list[SourceGroup] = Field(default_factory=list)
    # None on runs saved before quorum reporting existed.
    quorum: QuorumReport | None = None
    # Model family per answered delegate, where the provider's config names one.
    families: dict[str, str] = Field(default_factory=dict)
    # Distinct known families among the answered delegates. None when none is known.
    distinct_families: int | None = None


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
    # Random per-run seed. Marker tokens in judge prompts derive from it, and every retry
    # in a chain reuses it, so stored runs rebuild their prompts byte for byte.
    seed: str | None = None
    judge_response_char_limit: int = Field(default=24_000, ge=1)
    # Explicit permission to run when only one independent source is available or answers,
    # although the quorum asks for more. Such a run is labelled and never reported as met.
    allow_single_source: bool = False
    # Applies only once a single-source run is happening; it cannot permit one.
    single_source_mode: SingleSourceMode = "return_answer"
    selection: SelectionTrace | None = None


class DeliberationResult(BaseModel):
    panel: PanelResult
    critic: DelegateResult | None = None
    arbiter: DelegateResult | None = None
    estimated_cost_usd: float | None = None
    # True when exactly one independent source answered. The label is the one sentence used
    # for this run everywhere: the console, the saved result and the Arbiter prompt.
    single_source: bool = False
    single_source_label: str | None = None
    # Set when the run returned the delegate's answer instead of running an Arbiter.
    single_source_answer: SingleSourceAnswer | None = None
    # Blind judging: label -> delegate name, for the console only. Judges see labels alone.
    label_map: dict[str, str] = Field(default_factory=dict)
    # Labels of responses that come from the same source as the Critic or the Arbiter that
    # judged them. Judges are not told, since that would undo the blinding.
    judge_overlaps: list[str] = Field(default_factory=list)
    # One row per delegate, shown whatever the Arbiter wrote. Empty on runs saved before this.
    positions: list[PositionRow] = Field(default_factory=list)
    # Every independent source says "insufficient evidence", or the Arbiter's synthesis begins so.
    insufficient_evidence: bool = False
    # None for runs without a (multi-source) Arbiter answer, and for runs saved before this.
    arbiter_structure: ArbiterStructure | None = None


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
    allow_single_source: bool = False
    # Required when a workspace is saved (the API refuses a missing choice). Existing
    # workspaces read as return_answer.
    single_source_mode: SingleSourceMode | None = None


class Workspace(WorkspaceCreate):
    id: str
    created_at: str
    updated_at: str
    # Not stored: advice produced when the workspace is saved.
    warnings: list[str] = Field(default_factory=list)


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
