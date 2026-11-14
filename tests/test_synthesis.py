"""P1-6: the Arbiter's answer is read as four sections, strictly, and what it cites is checked."""

from __future__ import annotations

import pytest

from conclave.models import ArbiterStructure, DeliberationRequest
from conclave.orchestrator import Orchestrator
from conclave.prompts import ARBITER_FORMAT_REQUEST, build_arbiter_prompt
from conclave.providers.fake import FakeProvider
from conclave.synthesis import citations_in, parse_sections, split_points, synthesis_is_insufficient

GOOD = """## Common ground
- Remote work helps focused tasks. [A, B]
- Mentoring is harder at a distance. [B]

## Disagreements
- A thinks hybrid is best, B prefers fully remote. [A] [B]

## Uncertainty
- Long-term effects on careers are unknown. [C]
- A claim with no citation at all.

## Synthesis
A hybrid schedule is the safest default."""


# ------------------------------------------------------------------------------- parsing


def test_a_well_formed_answer_parses():
    parsed = parse_sections(GOOD, {"A", "B", "C"})
    assert parsed.format_ok and parsed.problems == []
    assert list(parsed.sections) == ["common_ground", "disagreements", "uncertainty", "synthesis"]
    assert parsed.sections["synthesis"] == "A hybrid schedule is the safest default."
    common = parsed.points["common_ground"]
    assert [p.citations for p in common] == [["A", "B"], ["B"]]
    assert common[0].text == "Remote work helps focused tasks. [A, B]"
    assert parsed.points["disagreements"][0].citations == ["A", "B"]
    assert parsed.unknown_citations == []
    assert parsed.uncited_points == 1  # the uncited Uncertainty point


def test_none_is_allowed_under_disagreements_without_a_citation():
    text = GOOD.replace("- A thinks hybrid is best, B prefers fully remote. [A] [B]", "None.")
    parsed = parse_sections(text, {"A", "B", "C"})
    assert parsed.format_ok and parsed.points["disagreements"][0].text == "None."
    assert parsed.uncited_points == 1  # still only the Uncertainty point


@pytest.mark.parametrize(
    "mutate,problem",
    [
        (lambda t: t.replace("## Uncertainty\n", ""), "missing heading ## Uncertainty"),
        (lambda t: t.replace("## Common ground\n", ""), "missing heading ## Common ground"),
        (lambda t: t.replace("## Synthesis", "## Synthesis\nx\n## Synthesis"), "repeated heading ## Synthesis"),
        (lambda t: t + "\n## Disagreements\nagain", "repeated heading ## Disagreements"),
        (lambda t: t.replace("## Disagreements", "## Zzz").replace("## Uncertainty", "## Disagreements").replace("## Zzz", "## Uncertainty"), "headings out of order"),
        (lambda t: "Here is my answer.\n\n" + t, "text before the first heading"),
        (lambda t: t.replace("## Synthesis", "## Synthesis:"), "missing heading ## Synthesis"),
        (lambda t: t.replace("## Synthesis", "### Synthesis"), "missing heading ## Synthesis"),
        (lambda t: t.replace("## Synthesis", " ## Synthesis"), "missing heading ## Synthesis"),
        (lambda t: t.replace("## Synthesis", "## synthesis"), "missing heading ## Synthesis"),
        (lambda t: t.replace("## Synthesis", "**## Synthesis**"), "missing heading ## Synthesis"),
        (lambda t: t.replace("## Common ground", "## Common  ground"), "missing heading ## Common ground"),
    ],
)
def test_any_other_shape_is_format_not_ok(mutate, problem):
    parsed = parse_sections(mutate(GOOD))
    assert parsed.format_ok is False
    assert problem in parsed.problems
    assert parsed.sections == {} and parsed.points == {}


def test_a_heading_inside_a_line_of_text_does_not_count():
    text = GOOD.replace("A hybrid schedule is the safest default.", "See ## Disagreements above.")
    assert parse_sections(text).format_ok is True  # mentions are not headings


def test_empty_and_missing_text():
    for text in ("", None, "   \n\n"):
        parsed = parse_sections(text)
        assert parsed.format_ok is False and len(parsed.problems) == 4


def test_trailing_whitespace_and_crlf_are_tolerated():
    text = GOOD.replace("\n", "  \r\n")
    parsed = parse_sections(text)
    assert parsed.format_ok is True


def test_exotic_line_separators_do_not_forge_a_heading():
    text = GOOD.replace("## Uncertainty", "## Uncertainty").replace(
        "- A claim with no citation at all.", "- x ## Disagreements - y"
    )
    parsed = parse_sections(text)
    assert parsed.format_ok is True and len(parsed.sections) == 4


def test_the_text_of_a_section_is_verbatim():
    odd = "<b>bold</b> & ‮ rtl [A]"
    parsed = parse_sections(GOOD.replace("A hybrid schedule is the safest default.", odd))
    assert parsed.sections["synthesis"] == odd


# ----------------------------------------------------------------------------- citations


def test_citations_in_text():
    assert citations_in("x [A] y [C, A] z [B,D]") == ["A", "C", "B", "D"]
    assert citations_in("no citation, [a], [1], [AB1], [ABCD], []") == []
    assert citations_in("[AA] is a valid label when there are many delegates") == ["AA"]


def test_a_citation_to_a_nonexistent_label_is_listed():
    text = GOOD.replace("[C]", "[Z]").replace("[A, B]", "[A, Q]")
    parsed = parse_sections(text, {"A", "B", "C"})
    assert parsed.format_ok and parsed.unknown_citations == ["Q", "Z"]


def test_unknown_citations_are_not_judged_without_the_run_labels():
    assert parse_sections(GOOD.replace("[C]", "[Z]")).unknown_citations == []
    # An empty label set means nothing exists, so every citation is unknown.
    assert parse_sections(GOOD, set()).unknown_citations == ["A", "B", "C"]


def test_a_citation_in_the_synthesis_is_checked_too():
    text = GOOD.replace("A hybrid schedule is the safest default.", "Go hybrid. [Z]")
    assert parse_sections(text, {"A", "B", "C"}).unknown_citations == ["Z"]


# ----------------------------------------------------------------------------------- points


def test_points_are_bullets_with_continuations_or_paragraphs():
    body = "- first point\n  continues here [A]\n- second [B]\n\nA loose paragraph\nover two lines.\n\n1. numbered [C]"
    assert split_points(body) == [
        "first point continues here [A]",
        "second [B]",
        "A loose paragraph over two lines.",
        "numbered [C]",
    ]
    assert split_points("") == []


# ------------------------------------------------------------- the insufficient evidence rule


def test_synthesis_beginning_insufficient_evidence():
    structure = parse_sections(GOOD.replace("A hybrid schedule is the safest default.", "Insufficient evidence to decide."))
    assert synthesis_is_insufficient(structure) is True
    assert synthesis_is_insufficient(parse_sections(GOOD)) is False
    assert synthesis_is_insufficient(ArbiterStructure(format_ok=False)) is False


# --------------------------------------------------------------------------------- prompt


def test_the_arbiter_prompt_asks_for_exactly_the_four_headings():
    for heading in ("## Common ground", "## Disagreements", "## Uncertainty", "## Synthesis"):
        assert heading + "\n" in ARBITER_FORMAT_REQUEST
    assert "[A, C]" in ARBITER_FORMAT_REQUEST and "None." in ARBITER_FORMAT_REQUEST
    assert "Insufficient evidence" in ARBITER_FORMAT_REQUEST
    prompt = build_arbiter_prompt(question="q", delegate_results=[])
    assert prompt.endswith(ARBITER_FORMAT_REQUEST)


def test_the_single_source_instruction_is_not_structured():
    from conclave.models import DelegateResult, DelegateStatus

    only = DelegateResult(name="a", status=DelegateStatus.SUCCEEDED, raw_response="x")
    prompt = build_arbiter_prompt(
        question="q", delegate_results=[only], single_source_label="Single source: one."
    )
    assert "## Common ground" not in prompt and "do not describe common ground" in prompt


# ------------------------------------------------------------------------------ through a run


async def _run(arbiter_text, *, delegates=("a", "b", "c"), minimum=2, critic=True, **extra):
    providers = {n: FakeProvider(f"answer {n} " + "w" * 40 + n, model=f"m-{n}") for n in delegates}
    providers.update(critic=FakeProvider("crit"), arbiter=FakeProvider(arbiter_text))
    from conclave.sources import ProviderIdentity

    identities = {
        n: ProviderIdentity(base_url=f"https://{n}.example/v1", model=f"m-{n}") for n in delegates
    }
    request = DeliberationRequest(
        question="q", delegates=list(delegates), critic="critic" if critic else None,
        arbiter="arbiter", minimum_successes=minimum, seed="syn", **extra,
    )
    return await Orchestrator(providers, identities).deliberate(request)


async def test_a_run_stores_the_structure_beside_the_untouched_raw_answer():
    result = await _run(GOOD)
    assert result.arbiter.raw_response == GOOD
    assert result.arbiter_structure.format_ok is True
    assert result.arbiter_structure.unknown_citations == []


async def test_labels_the_judges_saw_are_the_valid_citations():
    bad = GOOD.replace("[C]", "[Z]")
    result = await _run(bad)
    assert result.arbiter_structure.unknown_citations == ["Z"]
    # A letter that exists in the permutation but belongs to a delegate that did not answer
    # was never shown to the Arbiter, so citing it is unknown too.
    ok = await _run(GOOD)
    assert set(ok.label_map) == {"A", "B", "C"}


async def test_a_malformed_answer_is_kept_raw_with_format_ok_false():
    result = await _run("I think the answer is hybrid.")
    assert result.arbiter.raw_response == "I think the answer is hybrid."
    assert result.arbiter_structure.format_ok is False and result.arbiter_structure.sections == {}


async def test_a_failed_arbiter_has_no_structure():
    providers_result = await _run(GOOD)
    assert providers_result.arbiter_structure is not None

    providers = {
        "a": FakeProvider("one " + "w" * 40), "b": FakeProvider("two " + "v" * 40),
        "critic": FakeProvider("c"), "arbiter": FakeProvider(error=RuntimeError("down")),
    }
    request = DeliberationRequest(
        question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter", minimum_successes=2,
    )
    result = await Orchestrator(providers).deliberate(request)
    assert result.arbiter.status.value == "failed" and result.arbiter_structure is None


async def test_a_single_source_assessment_is_not_read_as_sections():
    result = await _run(
        "Assessment of the single response.", delegates=("a",), minimum=1,
        allow_single_source=True, single_source_mode="arbiter_single_source",
    )
    assert result.single_source and result.arbiter is not None
    assert result.arbiter_structure is None


async def test_insufficient_evidence_flag_follows_the_structured_synthesis():
    text = GOOD.replace("A hybrid schedule is the safest default.", "Insufficient evidence: the responses conflict.")
    assert (await _run(text)).insufficient_evidence is True
    assert (await _run(GOOD)).insufficient_evidence is False


async def test_runs_saved_before_this_change_still_load():
    from conclave.models import DeliberationResult

    old = {"panel": {"question": "q", "delegates": [], "successful_count": 0, "failed_count": 0,
                     "synthesizeable": False}}
    assert DeliberationResult.model_validate(old).arbiter_structure is None
    assert ArbiterStructure.model_validate({"format_ok": False}).sections == {}


def test_the_arbiter_must_report_coverage_and_shared_sources_under_uncertainty():
    text = ARBITER_FORMAT_REQUEST
    assert "first point under ## Uncertainty" in text and "report coverage" in text
    assert "k of n delegates answered" in text and "count as one source" in text
    assert "say that instead" in text  # the all-answered, nothing-shared case is stated too
    # It asks the judge to use what the prompt already says; it names no provider or model.
    for word in ("provider", "model name", "latency"):
        assert word not in text.lower()
