"""Read the Arbiter's answer as four labelled sections, and check what it cites.

Disagreement and uncertainty used to be only a request in the prompt. The Arbiter is now asked
to write exactly four headings, once each, in order::

    ## Common ground
    ## Disagreements
    ## Uncertainty
    ## Synthesis

with each point under the first three citing response labels such as ``[A]`` or ``[A, C]``.

Only the Arbiter's own answer is ever read this way: never a delegate's or the Critic's. The
reading is strict. A heading counts only when a whole line equals it, and any other shape
(a missing, repeated or out-of-order heading, or text before the first heading) gives
``format_ok: False`` and no sections, so the console falls back to the raw answer with a
notice. The raw answer is never altered.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import ArbiterStructure, StructuredPoint

HEADINGS = (
    ("common_ground", "## Common ground"),
    ("disagreements", "## Disagreements"),
    ("uncertainty", "## Uncertainty"),
    ("synthesis", "## Synthesis"),
)
_HEADING_KEYS = {heading: key for key, heading in HEADINGS}
# Sections whose points are expected to cite responses.
CITED_SECTIONS = ("common_ground", "disagreements", "uncertainty")

_CITATION = re.compile(r"\[([A-Z]{1,3}(?:\s*,\s*[A-Z]{1,3})*)\]")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
_NONE_POINT = re.compile(r"^\W*none\.?\W*$", re.IGNORECASE)
# Any other top-level or second-level Markdown heading is a fifth heading. Deeper headings
# (### and below) are ordinary text inside a section.
_OTHER_HEADING = re.compile(r"^#{1,2}\s")


def _lines(text: str | None) -> list[str]:
    # Newlines only: str.splitlines would also break on exotic separators.
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def citations_in(text: str) -> list[str]:
    """Response labels cited in ``text``, in order of appearance, without repeats."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _CITATION.finditer(text):
        for label in re.split(r"\s*,\s*", match.group(1)):
            if label not in seen:
                seen.add(label)
                found.append(label)
    return found


def split_points(body: str) -> list[str]:
    """Points in a section: bullet items (with their continuation lines), else paragraphs."""
    points: list[list[str]] = []
    open_point = False
    for line in body.split("\n"):
        if not line.strip():
            open_point = False
            continue
        if _BULLET.match(line) or not open_point:
            points.append([_BULLET.sub("", line, count=1).strip()])
            open_point = True
        else:
            points[-1].append(line.strip())
    return [" ".join(parts) for parts in points]


def parse_sections(text: str | None, valid_labels: Iterable[str] | None = None) -> ArbiterStructure:
    """Parse an Arbiter answer. ``valid_labels`` are the response labels that exist in the run;
    when given, any other label the answer cites is listed in ``unknown_citations``."""
    problems: list[str] = []
    seen: dict[str, int] = {}
    positions: list[tuple[int, str]] = []
    lines = _lines(text)
    unexpected = False
    for index, line in enumerate(lines):
        key = _HEADING_KEYS.get(line.rstrip())
        if key is None:
            unexpected = unexpected or bool(_OTHER_HEADING.match(line))
            continue
        seen[key] = seen.get(key, 0) + 1
        positions.append((index, key))

    for key, heading in HEADINGS:
        if key not in seen:
            problems.append(f"missing heading {heading}")
        elif seen[key] > 1:
            problems.append(f"repeated heading {heading}")
    order = [key for _, key in positions]
    if not problems and order != [key for key, _ in HEADINGS]:
        problems.append("headings out of order")
    if positions and any(line.strip() for line in lines[: positions[0][0]]):
        problems.append("text before the first heading")
    if unexpected:
        problems.append("a heading other than the four required")
    if problems:
        return ArbiterStructure(format_ok=False, problems=problems)

    bodies: dict[str, str] = {}
    for n, (start, key) in enumerate(positions):
        end = positions[n + 1][0] if n + 1 < len(positions) else len(lines)
        bodies[key] = "\n".join(lines[start + 1 : end]).strip()

    points: dict[str, list[StructuredPoint]] = {}
    cited: list[str] = []
    cited_seen: set[str] = set()
    uncited = 0
    for key, _ in HEADINGS:
        built = []
        for point in split_points(bodies[key]):
            labels = citations_in(point)
            built.append(StructuredPoint(text=point, citations=labels))
            for label in labels:
                if label not in cited_seen:
                    cited_seen.add(label)
                    cited.append(label)
            if key in CITED_SECTIONS and not labels and not _NONE_POINT.match(point):
                uncited += 1
        points[key] = built
    valid = set(valid_labels) if valid_labels is not None else None
    return ArbiterStructure(
        format_ok=True,
        sections=bodies,
        points=points,
        unknown_citations=sorted(label for label in cited if valid is not None and label not in valid),
        uncited_points=uncited,
    )


def synthesis_is_insufficient(structure: ArbiterStructure) -> bool:
    """True for a well-formed answer whose Synthesis begins "Insufficient evidence"."""
    return structure.format_ok and structure.sections.get("synthesis", "").lower().startswith(
        "insufficient evidence"
    )
