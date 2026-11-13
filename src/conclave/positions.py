"""Each delegate's own stated position, read from that delegate's own answer only.

A delegate is asked to end with two lines::

    Conclusion: <one sentence>
    Confidence: high | medium | low | insufficient evidence

Dissent should not depend on whether the Arbiter chooses to report it, so these lines are
shown to the user verbatim next to the synthesis. Nothing here affects counts, quorum or
any decision: positions are display data, parsed from a delegate's own raw answer and never
from another's, and never fed back into a prompt.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from .models import DelegateResult, DelegateStatus, PositionRow, SourceGroup

CONFIDENCE_LEVELS = ("high", "medium", "low", "insufficient evidence")
INSUFFICIENT = "insufficient evidence"
MAX_CONCLUSION_CHARS = 600
MAX_CONFIDENCE_CHARS = 120

# A line that starts with the key, allowing markdown decoration around it:
# "Conclusion: x", "**Conclusion:** x", "> - conclusion: x".
_LINE = re.compile(
    r"^[\s>*_#`\-]*(conclusion|confidence)[\s*_`]*:[\s*_`]*(.*?)[\s*_`]*$",
    re.IGNORECASE,
)


def _split_lines(text: str | None) -> list[str]:
    """Split on newlines only: str.splitlines also breaks on exotic separators."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _cap(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _normalize_confidence(value: str) -> str | None:
    flat = re.sub(r"[\s_\-]+", " ", value.strip().rstrip(".").strip().lower())
    return flat if flat in CONFIDENCE_LEVELS else None


def parse_position(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """``(conclusion, confidence, confidence_text)`` from one delegate's own raw answer.

    The last occurrence of each line is used. ``confidence`` is one of the four levels, or
    None when the line is missing or says anything else; ``confidence_text`` always holds what
    it did say. A missing or empty line gives None, which the console shows as "not stated".
    """
    found: dict[str, str] = {}
    # Split on newlines only: str.splitlines also breaks on exotic separators.
    for line in _split_lines(raw):
        match = _LINE.match(line)
        if match:
            found[match.group(1).lower()] = match.group(2).strip()
    conclusion = found.get("conclusion") or None
    said = found.get("confidence") or None
    level = _normalize_confidence(said) if said else None
    return (
        _cap(conclusion, MAX_CONCLUSION_CHARS) if conclusion else None,
        level,
        _cap(said, MAX_CONFIDENCE_CHARS) if said else None,
    )


def strip_position_lines(raw: str | None) -> str:
    """The answer without its Conclusion and Confidence lines.

    The closing lines are a reporting format, not part of what a delegate argued, so they play
    no part when answers are compared for near-duplication: positions never affect counts.
    """
    lines = _split_lines(raw)
    return "\n".join(line for line in lines if not _LINE.match(line))


def build_positions(
    delegates: Sequence[DelegateResult],
    sources: Iterable[SourceGroup] | None,
    labels: dict[str, str],
) -> list[PositionRow]:
    """One row per delegate, in workspace order. ``labels`` maps delegate name to its label."""
    group_of = {
        name: index for index, group in enumerate(sources or [], start=1) for name in group.delegates
    }
    rows = []
    for result in delegates:
        answered = result.status == DelegateStatus.SUCCEEDED
        conclusion, confidence, said = parse_position(result.raw_response) if answered else (None,) * 3
        rows.append(
            PositionRow(
                delegate=result.name,
                label=labels.get(result.name) if answered else None,
                source=group_of.get(result.name),
                status=result.status.value,
                conclusion=conclusion,
                confidence=confidence,
                confidence_text=said,
            )
        )
    return rows


def arbiter_says_insufficient(text: str | None) -> bool:
    """True when the Arbiter's Synthesis section begins "Insufficient evidence"."""
    lines = _split_lines(text)
    for index, line in enumerate(lines):
        if line.strip() == "## Synthesis":
            for following in lines[index + 1 :]:
                if following.strip():
                    return following.strip().lower().startswith("insufficient evidence")
            return False
    return False


def insufficient_evidence(
    rows: Sequence[PositionRow],
    sources: Iterable[SourceGroup] | None,
    arbiter_text: str | None = None,
) -> bool:
    """Every independent source says "insufficient evidence", or the Arbiter's synthesis does."""
    if arbiter_says_insufficient(arbiter_text):
        return True
    by_name = {row.delegate: row for row in rows}
    groups = [g for g in (sources or []) if g.delegates]
    if not groups:
        return False
    return all(
        all(
            name in by_name and by_name[name].confidence == INSUFFICIENT for name in group.delegates
        )
        for group in groups
    )
