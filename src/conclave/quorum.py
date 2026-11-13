"""Quorum: how many independent sources a run needs, and whether it can get them.

The configured quorum (``minimum_successes``) is never lowered. Two checks enforce it:

* **Before dispatch** (:func:`plan_delegates`): when automatic selection picks too few
  delegates, extra ones are added from the workspace pool until the *independent sources*
  they represent reach the quorum. A candidate that would only duplicate a source already
  present (same configured model) is skipped, so adding delegates cannot inflate the count.
  If the pool cannot reach the quorum, :class:`QuorumUnmet` is raised and nothing is called.
* **After the answers arrive** (:func:`evaluate_quorum`): selecting enough sources does not
  guarantee enough answers. Only non-empty answers that actually came back, grouped into
  independent sources, are counted.

A single-source run is allowed only through an explicit setting (``allow_single_source``).
It proceeds, is labelled ``single_source_override``, and never claims the quorum was met.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .models import DelegateResult, DelegateStatus, QuorumReport, SourceGroup
from .sources import ProviderIdentity, sharing_config

_REASON_TEXT = {
    "same_config": "same configured model",
    "same_reported_model": "same reported model",
    "unresolved_router_alias": "unresolved router alias",
}


def source_key(name: str, identities: Mapping[str, ProviderIdentity]) -> tuple:
    """What a delegate can contribute as a source, known before it answers.

    Configured providers are identified by ``(base_url, model)``. A router alias is counted
    as its own potential source: which model it uses is only known after the call, and the
    final check (which uses what was reported) is authoritative.
    """
    identity = identities.get(name)
    if identity is None:
        return ("name", name)
    if identity.router_alias:
        return ("alias", name)
    return ("config", *identity.config_key)


def count_sources(names: Iterable[str], identities: Mapping[str, ProviderIdentity]) -> int:
    return len({source_key(name, identities) for name in names})


@dataclass(frozen=True, slots=True)
class DelegatePlan:
    delegates: list[str]
    topped_up: list[str]
    expected_sources: int
    single_source: bool = False


class QuorumUnmet(Exception):
    """The quorum cannot be reached, so the run must not start."""

    def __init__(self, detail: dict) -> None:
        super().__init__(detail["message"])
        self.detail = detail


def plan_delegates(
    *,
    selected: list[str],
    pool: list[str],
    ranked_extra: list[str],
    is_eligible: Callable[[str], bool],
    ineligible_reason: Callable[[str], str],
    identities: Mapping[str, ProviderIdentity],
    required: int,
    allow_single_source: bool = False,
    drop_ineligible: bool = False,
) -> DelegatePlan:
    """Return the delegates to run, topping up from ``ranked_extra`` if needed.

    ``selected`` is the initial choice, ``pool`` everything the workspace allows, and
    ``ranked_extra`` the eligible pool in preference order (empty when the panel is fixed).
    With ``drop_ineligible`` (automatic selection) a pick that cannot run is removed, not
    dispatched; a panel the user listed explicitly keeps it, and it fails visibly.
    """
    delegates = [name for name in selected if is_eligible(name)] if drop_ineligible else list(selected)
    keys = {source_key(name, identities) for name in delegates if is_eligible(name)}
    topped_up: list[str] = []
    for name in ranked_extra:
        if len(keys) >= required:
            break
        if name in delegates or not is_eligible(name):
            continue
        key = source_key(name, identities)
        if key in keys:
            continue  # would add a delegate but not an independent source
        delegates.append(name)
        keys.add(key)
        topped_up.append(name)

    if len(keys) >= required:
        return DelegatePlan(delegates, topped_up, len(keys))

    if allow_single_source and len(keys) == 1:
        # One source can only answer once, so run one delegate rather than pay for copies.
        first = next(name for name in delegates if is_eligible(name))
        # A panel the user listed keeps its unavailable members so their failure stays visible.
        unrunnable = [] if drop_ineligible else [n for n in delegates if not is_eligible(n)]
        return DelegatePlan([first, *unrunnable], [], 1, single_source=True)

    raise QuorumUnmet(
        _unmet_detail(
            required=required,
            selected=selected,
            topped_up=topped_up,
            pool=pool,
            is_eligible=is_eligible,
            ineligible_reason=ineligible_reason,
            identities=identities,
            allow_single_source=allow_single_source,
        )
    )


def _unmet_detail(
    *,
    required: int,
    selected: list[str],
    topped_up: list[str],
    pool: list[str],
    is_eligible: Callable[[str], bool],
    ineligible_reason: Callable[[str], str],
    identities: Mapping[str, ProviderIdentity],
    allow_single_source: bool,
) -> dict:
    eligible_pool = [name for name in pool if is_eligible(name)]
    reachable = count_sources(eligible_pool, identities)
    unavailable = {name: ineligible_reason(name) for name in pool if not is_eligible(name)}
    shared = sharing_config(eligible_pool, identities)

    lines = [
        f"Quorum unmet: {required} independent source(s) required, but this run can reach "
        f"at most {reachable}. No provider was called."
    ]
    if unavailable:
        lines.append(
            "Unavailable: " + "; ".join(f"{name} ({why})" for name, why in unavailable.items()) + "."
        )
    for group in shared:
        lines.append(f"{', '.join(group)} use the same configured model, so they count as one source.")
    if reachable == 1 and not allow_single_source:
        lines.append(
            "To run with one source anyway, enable single-source runs for this workspace; the "
            "result will be labelled and will not count as meeting the quorum."
        )
    elif reachable < required:
        lines.append("Add a delegate backed by a different model, fix the unavailable ones, or lower the quorum.")

    return {
        "code": "quorum_unmet",
        "message": " ".join(lines),
        "required_sources": required,
        "available_sources": reachable,
        "selected": selected,
        "topped_up": topped_up,
        "pool": pool,
        "unavailable": unavailable,
        "shared_sources": shared,
        "allow_single_source": allow_single_source,
    }


def evaluate_quorum(
    *,
    required: int,
    delegates: list[DelegateResult],
    sources: list[SourceGroup],
    allow_single_source: bool = False,
) -> QuorumReport:
    """Judge a finished panel by the answers that really arrived, not by who was selected."""
    received = sum(result.status == DelegateStatus.SUCCEEDED for result in delegates)
    qualifying = len(sources)
    shortfalls = _shortfalls(delegates, sources)

    if qualifying >= required:
        status = "met"
        summary = f"Quorum met: {qualifying} independent source(s) answered (required {required})."
    elif allow_single_source and qualifying == 1:
        status = "single_source_override"
        summary = (
            f"Quorum NOT met: {required} independent sources were required and only 1 answered. "
            "This is a single-source run, allowed by this workspace's setting. It is not a "
            "consensus result."
        )
    else:
        status = "unmet"
        summary = (
            f"Quorum unmet: {required} independent source(s) required, {qualifying} received "
            f"({received} of {len(delegates)} delegates produced an answer). "
            "The Critic and Arbiter were not run."
        )
    if status != "met" and shortfalls:
        summary += " " + " ".join(f"{item}." for item in shortfalls)
    return QuorumReport(
        status=status,
        required=required,
        qualifying_sources=qualifying,
        responses_received=received,
        delegates_attempted=len(delegates),
        summary=summary,
        shortfalls=shortfalls,
    )


def _why(result: DelegateResult) -> str:
    if result.status == DelegateStatus.TIMED_OUT:
        return "timed out"
    if result.error_kind == "empty_response":
        return "returned an empty response"
    if result.error:
        return "failed: " + " ".join(result.error.split())[:120]
    return result.status.value


def _shortfalls(delegates: list[DelegateResult], sources: list[SourceGroup]) -> list[str]:
    items = [
        f"{result.name} {_why(result)}"
        for result in delegates
        if result.status != DelegateStatus.SUCCEEDED
    ]
    for group in sources:
        if len(group.delegates) > 1:
            why = _REASON_TEXT.get(group.reason or "", "shared identity")
            items.append(f"{', '.join(group.delegates)} count as one source ({why})")
    return items


def describe_single_source(report: QuorumReport) -> str:
    """The one sentence that identifies a single-source run, wherever it is shown."""
    if report.status == "single_source_override":
        return (
            "SINGLE-SOURCE RUN, explicitly permitted by this workspace (allow_single_source). "
            f"The configured quorum of {report.required} independent sources was NOT met. "
            "This is not a consensus."
        )
    return (
        f"Single source: only 1 independent source answered (the configured quorum is "
        f"{report.required}). This is not a comparison of sources."
    )
