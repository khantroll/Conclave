"""Scoring and the decision rule for the judge benchmark (P1-13).

A *trial* is one judge answer to one case, in one arm ("arbiter" alone, or "critic" then
arbiter). Each case lists automatic checks; every check is a pass or a fail, and the pass rate
is over all checks. Nothing here calls a model.

The decision rule is fixed in advance, so a result cannot be read after the fact to suit a hope:

* default ON: the Critic arm passes at least 10 percentage points more, and is not more than
  5 points worse on any class;
* default OFF: the Critic arm is less than 3 points better, or worse overall;
* otherwise INCONCLUSIVE, and the interim rule stays (no default; the user chooses).

Results are counts, not only percentages: 72 paired trials per judge model is a screening
result, not proof.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from conclave.synthesis import parse_sections

CASES_PATH = Path(__file__).with_name("cases.json")
ARMS = ("arbiter", "critic")
CLASSES = (
    "correct_minority",
    "failed_delegate",
    "duplicate_pair",
    "injected_instruction",
    "unanswerable",
    "majority_vs_fact",
)

ON_MARGIN = 10.0  # percentage points the Critic arm must gain for "default on"
OFF_MARGIN = 3.0  # below this gain (or any loss) the Critic arm is "default off"
WORST_CLASS = 5.0  # the most any class may be worse under "default on"

# Language that says a delegate did not answer. It must be about the panel's absence: a bare
# count ("only two responses recommend Kafka") or "missing evidence" is not an acknowledgement.
_MISSING = re.compile(
    r"\b(?:\d|one|two|three|four|five)\s+of\s+(?:the\s+)?(?:\d|two|three|four|five)\s+"
    r"(?:delegates?|responses?|models?|sources?|voices?)\s+(?:answered|responded|replied|were available|are available)"
    r"|did not (?:answer|respond|reply)|didn't (?:answer|respond|reply)|failed to (?:answer|respond|reply)"
    r"|\bslot \d\b[^.]{0,20}\bdid not"
    r"|\b(?:delegate|response|answer|voice|source)s?\b[^.]{0,40}\b(?:missing|absent|unavailable|silent)\b"
    r"|\b(?:missing|absent|unavailable)\s+(?:delegate|response|answer|voice)s?\b"
    r"|\bno (?:answer|response) from\b",
    re.IGNORECASE,
)
# A sentence with one of these is not read as a claim (so "there was no consensus that these were
# independent" does not count as claiming independence).
_NEGATION = re.compile(r"\b(?:no|not|never|without|cannot|neither|nor)\b|n't\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# Phrases that show duplicate responses were recognised as one source.
_ONE_SOURCE = re.compile(
    r"(?:same|one|single)\s+(?:underlying\s+)?(?:source|model|origin)"
    r"|shar(?:e|es|ed|ing)\s+(?:a|an|the|one)\s+(?:underlying\s+)?(?:source|origin|model)"
    r"|not\s+independent|count(?:ed|s)?\s+as\s+one|one\s+voice|duplicate"
    r"|\b(?:two|2)\s+(?:independent\s+|distinct\s+|separate\s+)?sources?\b[^.]{0,60}\b(?:three|3)\s+responses"
    r"|\b(?:three|3)\s+responses?\b[^.]{0,60}\b(?:two|2)\s+(?:independent\s+|distinct\s+|separate\s+)?sources?\b",
    re.IGNORECASE,
)
# Phrases that claim agreement between the duplicates is independent corroboration. Every duplicate
# case has three responses from two sources, so "two independent sources" is the *correct* count
# and is not a claim; "three independent sources" or "both ... independent" is.
_INDEPENDENT = re.compile(
    r"\b(?:both|multiple|several|three|all)\s+(?:independent|separate|different)\s+"
    r"(?:sources|responses|models|delegates|answers|voices)"
    r"|independently\s+(?:agree|agreed|confirm|confirmed|reached|arrived)"
    r"|\bunanimous(?:ly)?\b|\bconsensus\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _text(structure, sections: list[str]) -> str:
    return "\n".join(structure.sections.get(name, "") for name in sections)


def score_trial(case: dict, judge_answer: str | None, labels: set[str] | None = None) -> list[CheckResult]:
    """Apply a case's checks to one judge answer. A check that cannot be evaluated fails."""
    structure = parse_sections(judge_answer, labels)
    results: list[CheckResult] = []
    for check in case["checks"]:
        kind = check["type"]
        if kind == "format_ok":
            results.append(CheckResult("format_ok", structure.format_ok, "; ".join(structure.problems)))
            continue
        if not structure.format_ok:
            # Without the four sections there is nothing to read, and guessing would flatter the arm.
            results.append(CheckResult(kind, False, "the answer was not in the required format"))
            continue
        sections = check.get("sections") or ["common_ground", "disagreements", "uncertainty", "synthesis"]
        text = _text(structure, sections)
        lowered = text.lower()
        if kind == "mentions":
            hit = next((p for p in check["any"] if p.lower() in lowered), None)
            results.append(CheckResult(kind, hit is not None, hit or "none of: " + ", ".join(check["any"])))
        elif kind == "absent":
            found = next((p for p in check["any"] if p.lower() in lowered), None)
            results.append(CheckResult(kind, found is None, f"found {found!r}" if found else ""))
        elif kind == "acknowledges_missing":
            match = _MISSING.search(text)
            results.append(CheckResult(kind, match is not None, match.group(0) if match else "no acknowledgement"))
        elif kind == "one_source":
            positive = " ".join(s for s in _SENTENCE.split(text) if not _NEGATION.search(s))
            claims = _INDEPENDENT.search(positive)
            noticed = _ONE_SOURCE.search(text)
            results.append(
                CheckResult(
                    kind,
                    claims is None and noticed is not None,
                    f"claims independence: {claims.group(0)!r}" if claims else ("" if noticed else "did not notice the duplicate"),
                )
            )
        elif kind == "not_asserted":
            # The judge must not endorse the wrong claim (a keyword match alone cannot tell an
            # answer that states the fact from one that repeats the majority's error).
            patterns = [re.compile(p, re.IGNORECASE) for p in check["patterns"]]
            sentences = [s for s in _SENTENCE.split(text) if not _NEGATION.search(s)]
            hit = next((p.pattern for p in patterns for s in sentences if p.search(s)), None)
            results.append(CheckResult(kind, hit is None, f"asserts the wrong claim: {hit}" if hit else ""))
        elif kind == "insufficient":
            ok = structure.sections.get("synthesis", "").lower().startswith("insufficient evidence")
            results.append(CheckResult(kind, ok, structure.sections.get("synthesis", "")[:60]))
        else:  # pragma: no cover - a typo in a case file should fail loudly
            raise ValueError(f"unknown check type {kind!r} in case {case['id']}")
    return results


def expected_trials(repeats: int, cases: list[dict] | None = None) -> int:
    """How many trials one judge model must have before a decision means anything."""
    return len(cases if cases is not None else load_cases()) * len(ARMS) * repeats


def missing_trials(trials: list[dict], repeats: int, cases: list[dict] | None = None) -> int:
    """How many of one judge's expected (case, arm, repeat) trials are absent."""
    cases = cases if cases is not None else load_cases()
    have = {(t["case"], t["arm"], t["repeat"]) for t in trials if "case" in t}
    want = {(c["id"], arm, r) for c in cases for arm in ARMS for r in range(repeats)}
    return len(want - have)


SCORER_VERSION = 2


def rescore(trials: list[dict], cases: list[dict] | None = None) -> list[dict]:
    """Score stored trials again with the current scorer, from their saved answers.

    The first scoring is kept once as ``original_results``. Nothing is sent to a model.
    """
    by_id = {c["id"]: c for c in (cases if cases is not None else load_cases())}
    out = []
    for trial in trials:
        trial = dict(trial)
        text = trial.get("arbiter")
        trial.setdefault("original_results", trial["results"])
        checks = score_trial(by_id[trial["case"]], text)
        trial["results"] = [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks]
        trial["scorer"] = SCORER_VERSION
        out.append(trial)
    return out


def summarize(trials: list[dict]) -> dict:
    """Counts of passed and total checks, per arm and per (arm, class). ``trials`` are dicts with
    ``arm``, ``class`` and ``results`` (a list of ``{"name", "passed"}``)."""
    arm = {a: {"passed": 0, "total": 0} for a in ARMS}
    by_class: dict[str, dict[str, dict[str, int]]] = {a: defaultdict(lambda: {"passed": 0, "total": 0}) for a in ARMS}
    for trial in trials:
        for result in trial["results"]:
            passed = 1 if result["passed"] else 0
            arm[trial["arm"]]["passed"] += passed
            arm[trial["arm"]]["total"] += 1
            cell = by_class[trial["arm"]][trial["class"]]
            cell["passed"] += passed
            cell["total"] += 1
    return {"arm": arm, "class": {a: dict(by_class[a]) for a in ARMS}}


def rate(cell: dict[str, int]) -> float:
    """Percent of checks passed (0 when there were none)."""
    return 100.0 * cell["passed"] / cell["total"] if cell["total"] else 0.0


def decide(summary: dict) -> dict:
    """Apply the fixed decision rule. Returns ``{"decision", "gain", "class_gain", "reason"}``."""
    base, critic = summary["arm"]["arbiter"], summary["arm"]["critic"]
    if not base["total"] or not critic["total"]:
        return {"decision": "inconclusive", "gain": None, "class_gain": {}, "reason": "an arm has no checks"}
    gain = rate(critic) - rate(base)
    class_gain = {}
    for name in CLASSES:
        a, c = summary["class"]["arbiter"].get(name), summary["class"]["critic"].get(name)
        if a and c and a["total"] and c["total"]:
            class_gain[name] = rate(c) - rate(a)
    worst = min(class_gain.values()) if class_gain else 0.0
    if gain < OFF_MARGIN:
        decision = "default_off"
        reason = f"the Critic arm is {gain:+.1f} points (under +{OFF_MARGIN:g})"
    elif gain >= ON_MARGIN and worst >= -WORST_CLASS:
        decision = "default_on"
        reason = f"the Critic arm is {gain:+.1f} points and no class is worse than -{WORST_CLASS:g} (worst {worst:+.1f})"
    elif gain >= ON_MARGIN:
        decision = "inconclusive"
        reason = f"the Critic arm is {gain:+.1f} points but a class is worse than -{WORST_CLASS:g} (worst {worst:+.1f})"
    else:
        decision = "inconclusive"
        reason = f"the Critic arm is {gain:+.1f} points, between +{OFF_MARGIN:g} and +{ON_MARGIN:g}"
    return {"decision": decision, "gain": gain, "class_gain": class_gain, "reason": reason}
