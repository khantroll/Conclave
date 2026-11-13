"""Which delegates are really one source.

Agreement between answers only means something when the answers come from different
underlying models. Two delegates are the same source when either of these holds:

* their normalized configured identity is equal (same ``base_url`` host and path, same
  configured ``model``), or
* their normalized *reported* model is equal, after the call.

A provider marked ``router_alias`` (a gateway name such as ``openrouter/free`` that picks
a model per call) is identified only by the model it reports. When it reports nothing
usable, it is an unresolved alias, and unresolved aliases on one host count as one source.
Demo and unknown providers are never merged.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from .models import DelegateResult, DelegateStatus, SourceGroup
from .positions import strip_position_lines

SAME_CONFIG = "same_config"
SAME_REPORTED_MODEL = "same_reported_model"
UNRESOLVED_ROUTER_ALIAS = "unresolved_router_alias"
NEAR_DUPLICATE_TEXT = "near_duplicate_text"

# Strongest statement first: this decides the reason a merged group reports.
_REASON_ORDER = (SAME_CONFIG, SAME_REPORTED_MODEL, UNRESOLVED_ROUTER_ALIAS, NEAR_DUPLICATE_TEXT)

# Near-duplicate rules. Fixed constants, checked against tests/fixtures/near_duplicates.json.
NGRAM_SIZE = 5
JACCARD_THRESHOLD = 0.50
CONTAINMENT_THRESHOLD = 0.90
# Short answers legitimately coincide ("Yes.", "No, that is not safe."), so an answer with
# fewer normalized words than this is never compared.
MIN_COMPARED_WORDS = 20
MAX_COMPARED_CHARS = 60_000

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)
# Han and kana are written without spaces, so each character counts as one word. Otherwise a
# whole Chinese or Japanese answer would be a single "word" and never compared.
_UNSPACED = re.compile("([぀-ヿ㐀-䶿一-鿿豈-﫿])")

_DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """What a configured provider is, as far as source counting is concerned."""

    base_url: str
    model: str
    router_alias: bool = False
    family: str | None = None

    @property
    def config_key(self) -> tuple[str, str]:
        return (normalize_base_url(self.base_url), self.model)

    @property
    def host(self) -> str:
        return urlsplit(normalize_base_url(self.base_url)).netloc


def normalize_base_url(base_url: str) -> str:
    """Lowercase scheme and host, drop trailing slashes. The path keeps its case."""
    parts = urlsplit(base_url.strip())
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def normalize_reported_model(model: str | None) -> str | None:
    """Lowercase, drop a leading ``vendor/`` segment and a trailing date suffix."""
    if not model or not model.strip():
        return None
    value = model.strip().lower()
    if "/" in value:
        value = value.split("/", 1)[1]
    value = _DATE_SUFFIX.sub("", value)
    return value or None


def group_sources(
    results: Iterable[DelegateResult],
    identities: Mapping[str, ProviderIdentity],
    *,
    compare_text: bool = True,
) -> list[SourceGroup]:
    """Group the successful delegates into independent sources, in first-seen order.

    Besides shared identity, answers that are copies or near-copies of each other merge
    (``near_duplicate_text``), unless ``compare_text`` is off.
    """
    succeeded = [r for r in results if r.status == DelegateStatus.SUCCEEDED]
    parent = list(range(len(succeeded)))
    reason: dict[int, str] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    similarity: dict[int, float] = {}

    def union(i: int, j: int, why: str, score: float | None = None) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        keep, drop = (ri, rj) if ri < rj else (rj, ri)
        parent[drop] = keep
        # The strongest statement wins: configuration, then reported model, then text.
        reasons = {reason.get(keep), reason.get(drop), why}
        reason[keep] = next(r for r in _REASON_ORDER if r in reasons)
        best = max(similarity.get(keep, 0.0), similarity.get(drop, 0.0), score or 0.0)
        if best:
            similarity[keep] = best

    keyed: list[tuple[tuple, str] | None] = []
    for result in succeeded:
        identity = identities.get(result.name)
        keyed.append(_keys(result, identity))

    for i in range(len(succeeded)):
        for j in range(i + 1, len(succeeded)):
            a, b = keyed[i], keyed[j]
            if a is None or b is None:
                continue
            for key_a, why_a in a:
                for key_b, why_b in b:
                    if key_a == key_b and why_a == why_b:
                        union(i, j, why_a)

    if compare_text:
        prepared = [_prepare(r.raw_response) for r in succeeded]
        for i in range(len(succeeded)):
            for j in range(i + 1, len(succeeded)):
                found = near_duplicate(prepared[i], prepared[j])
                if found is not None:
                    union(i, j, NEAR_DUPLICATE_TEXT, found[1])

    groups: dict[int, list[int]] = {}
    for i in range(len(succeeded)):
        groups.setdefault(find(i), []).append(i)
    out: list[SourceGroup] = []
    for root in sorted(groups):
        members = groups[root]
        out.append(
            SourceGroup(
                delegates=[succeeded[i].name for i in members],
                reason=reason.get(root) if len(members) > 1 else None,
                similarity=(
                    round(similarity[root], 4)
                    if len(members) > 1 and root in similarity
                    else None
                ),
            )
        )
    return out


def _keys(
    result: DelegateResult, identity: ProviderIdentity | None
) -> list[tuple[tuple, str]] | None:
    """Merge keys for one delegate, or None when it must never be merged."""
    if identity is None:
        return None
    reported = normalize_reported_model(result.model)
    if identity.router_alias:
        configured = normalize_reported_model(identity.model)
        if reported is None or reported == configured:
            # The gateway told us nothing about which model answered.
            return [(("alias", identity.host), UNRESOLVED_ROUTER_ALIAS)]
        return [(("model", reported), SAME_REPORTED_MODEL)]
    keys: list[tuple[tuple, str]] = [(("config", *identity.config_key), SAME_CONFIG)]
    if reported is not None:
        keys.append((("model", reported), SAME_REPORTED_MODEL))
    return keys


def sharing_config(
    names: Iterable[str], identities: Mapping[str, ProviderIdentity]
) -> list[list[str]]:
    """Groups of two or more delegate names that share a configured identity."""
    by_key: dict[tuple[str, str], list[str]] = {}
    for name in names:
        identity = identities.get(name)
        if identity is None or identity.router_alias:
            continue
        by_key.setdefault(identity.config_key, []).append(name)
    return [members for members in by_key.values() if len(members) > 1]


def judge_overlap(
    judge: DelegateResult,
    delegates: Iterable[DelegateResult],
    identities: Mapping[str, ProviderIdentity],
) -> list[str]:
    """Names of the successful delegates that are the same source as this judge."""
    marker = "\x00judge"
    answered = [r for r in delegates if r.status == DelegateStatus.SUCCEEDED]
    identity = identities.get(judge.name)
    # A judge that never answered judged nothing, so it cannot have judged its own source.
    if judge.status != DelegateStatus.SUCCEEDED or identity is None or not answered:
        return []
    stand_in = judge.model_copy(update={"name": marker, "status": DelegateStatus.SUCCEEDED})
    # Compare identity only: the judge's critique is never a "copy" of an answer.
    groups = group_sources(
        [*answered, stand_in], {**identities, marker: identity}, compare_text=False
    )
    for group in groups:
        if marker in group.delegates:
            return [name for name in group.delegates if name != marker]
    return []


def normalize_text(text: str | None) -> str:
    """NFKC, lowercase, drop zero-width characters and punctuation (including markdown)."""
    value = unicodedata.normalize("NFKC", (text or "")[:MAX_COMPARED_CHARS])
    value = value.translate(_ZERO_WIDTH).lower()
    return " ".join(_UNSPACED.sub(lambda m: f" {m.group(0)} ", _NON_WORD.sub(" ", value)).split())


def _ngrams(words: list[str]) -> frozenset[tuple[str, ...]]:
    return frozenset(
        tuple(words[i : i + NGRAM_SIZE]) for i in range(len(words) - NGRAM_SIZE + 1)
    )


def _prepare(text: str | None) -> tuple[str, frozenset[tuple[str, ...]]]:
    normalized = normalize_text(strip_position_lines(text))
    return normalized, _ngrams(normalized.split())


def near_duplicate(
    a: tuple[str, frozenset[tuple[str, ...]]], b: tuple[str, frozenset[tuple[str, ...]]]
) -> tuple[str, float] | None:
    """``(rule, score)`` when two prepared answers are copies or near-copies, else None."""
    (text_a, grams_a), (text_b, grams_b) = a, b
    if len(text_a.split()) < MIN_COMPARED_WORDS or len(text_b.split()) < MIN_COMPARED_WORDS:
        return None  # too short to compare: a short answer may match by chance
    if text_a == text_b:
        return ("equal", 1.0)
    shared = len(grams_a & grams_b)
    jaccard = shared / len(grams_a | grams_b)
    containment = shared / min(len(grams_a), len(grams_b))
    fired = []
    if jaccard >= JACCARD_THRESHOLD:
        fired.append(("jaccard", jaccard))
    if containment >= CONTAINMENT_THRESHOLD:
        fired.append(("containment", containment))
    # Report the strongest evidence; on a tie the first rule listed wins.
    return max(fired, key=lambda item: item[1]) if fired else None


def text_similarity(a: str | None, b: str | None) -> tuple[str, float] | None:
    """Convenience wrapper over :func:`near_duplicate` for raw answer text."""
    return near_duplicate(_prepare(a), _prepare(b))
