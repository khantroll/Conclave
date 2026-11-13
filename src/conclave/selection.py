from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import DelegateSelection, ProviderDescriptor, RequestAnalysis


def rank_candidates(
    *,
    analysis: RequestAnalysis,
    candidates: Iterable[str],
    descriptors: Mapping[str, ProviderDescriptor],
) -> list[str]:
    """Candidates in preference order: capability match, then priority, then pool order."""
    available = list(dict.fromkeys(candidates))
    indexed = {name: index for index, name in enumerate(available)}

    def score(name: str) -> tuple[int, int, int]:
        descriptor = descriptors.get(name)
        if descriptor is None:
            return (0, -100, -indexed[name])

        capabilities = set(descriptor.capabilities)
        matches = sum(1 for item in analysis.desired_capabilities if item in capabilities)
        general_bonus = 1 if "general" in capabilities else 0
        # Higher match score wins. Lower numeric priority wins. Original workspace
        # order is the final stable tie breaker.
        return (matches * 10 + general_bonus, -descriptor.priority, -indexed[name])

    return sorted(available, key=score, reverse=True)


def select_delegates(
    *,
    analysis: RequestAnalysis,
    candidates: Iterable[str],
    descriptors: Mapping[str, ProviderDescriptor],
) -> DelegateSelection:
    available = list(dict.fromkeys(candidates))
    target = min(analysis.recommended_delegate_count, len(available))
    selected = rank_candidates(
        analysis=analysis, candidates=available, descriptors=descriptors
    )[:target]
    return DelegateSelection(
        analysis=analysis,
        selected=selected,
        available=available,
    )
