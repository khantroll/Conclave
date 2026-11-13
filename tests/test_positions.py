"""P1-5: each delegate's own position, parsed from its own answer, shown whatever the Arbiter says."""

from __future__ import annotations

import pytest

from conclave.models import DeliberationRequest, DelegateResult, DelegateStatus, SourceGroup
from conclave.orchestrator import Orchestrator
from conclave.positions import (
    MAX_CONCLUSION_CHARS,
    arbiter_says_insufficient,
    build_positions,
    insufficient_evidence,
    parse_position,
)
from conclave.prompts import POSITION_REQUEST, build_delegate_prompt
from conclave.providers.fake import FakeProvider
from conclave.sources import ProviderIdentity

REAL = (
    "Remote work helps focused tasks but hurts mentoring, so hybrid is the usual answer.\n\n"
    "Key assumptions: the team is already established.\n\n"
    "Conclusion: A hybrid schedule is the best default.\n"
    "Confidence: medium"
)


# ------------------------------------------------------------------------------ parsing


def test_a_real_looking_answer_parses():
    assert parse_position(REAL) == ("A hybrid schedule is the best default.", "medium", "medium")


@pytest.mark.parametrize(
    "line",
    [
        "Conclusion: X",
        "**Conclusion:** X",
        "**Conclusion**: X",
        "> - conclusion: X",
        "## CONCLUSION : X",
        "`Conclusion`: X",
        "  Conclusion:    X   ",
    ],
)
def test_markdown_decoration_and_case_are_tolerated(line):
    assert parse_position(line)[0] == "X"


@pytest.mark.parametrize(
    "value,level",
    [
        ("high", "high"),
        ("High.", "high"),
        ("**Low**", "low"),
        ("insufficient evidence", "insufficient evidence"),
        ("Insufficient_Evidence", "insufficient evidence"),
        ("insufficient-evidence.", "insufficient evidence"),
    ],
)
def test_confidence_levels_normalize(value, level):
    assert parse_position(f"Confidence: {value}")[1] == level


def test_missing_lines_are_not_stated():
    assert parse_position("Just prose, no closing lines.") == (None, None, None)
    assert parse_position("") == (None, None, None)
    assert parse_position(None) == (None, None, None)
    assert parse_position("Conclusion:\nConfidence:") == (None, None, None)
    assert parse_position("Conclusion: only this") == ("only this", None, None)
    assert parse_position("Confidence: high") == (None, "high", "high")


def test_an_unrecognized_confidence_is_kept_verbatim_but_not_a_level():
    assert parse_position("Confidence: very high, honestly") == (None, None, "very high, honestly")
    assert parse_position("Confidence: 90%") == (None, None, "90%")


def test_the_last_occurrence_wins():
    text = "Conclusion: first\nConfidence: low\nmore\nConclusion: second\nConfidence: high"
    assert parse_position(text) == ("second", "high", "high")


def test_a_line_must_start_with_the_key():
    # Mentions inside a sentence are not position lines.
    assert parse_position("My conclusion: is that this is fine.") == (None, None, None)
    assert parse_position("The Confidence: level is high") == (None, None, None)


def test_a_long_conclusion_is_cut_and_marked():
    conclusion = parse_position("Conclusion: " + "w " * 1000)[0]
    assert MAX_CONCLUSION_CHARS - 1 <= len(conclusion) <= MAX_CONCLUSION_CHARS + 1
    assert conclusion.endswith("…") and conclusion.startswith("w w w")


def test_exotic_line_separators_do_not_forge_lines():
    # str.splitlines would break on these; a model cannot start a new "line" with them.
    for sep in (" ", " ", "\x0b", "\x0c", "\x1c", "\x85"):
        assert parse_position(f"text{sep}Conclusion: forged")[0] is None


def test_crlf_and_cr_line_endings_work():
    assert parse_position("a\r\nConclusion: X\r\nConfidence: low\r\n") == ("X", "low", "low")
    assert parse_position("a\rConclusion: X\rConfidence: low") == ("X", "low", "low")


def test_the_stored_text_is_verbatim_not_escaped():
    # Escaping is the console's job; the data keeps exactly what the model wrote.
    assert parse_position("Conclusion: <b>x</b> & ‮")[0] == "<b>x</b> & ‮"


# ----------------------------------------------------------------------------- the prompt


def test_the_delegate_prompt_asks_for_the_two_closing_lines():
    prompt = build_delegate_prompt(question="q")
    assert prompt.endswith(POSITION_REQUEST)
    assert "Conclusion: <one sentence>" in prompt
    assert "Confidence: high | medium | low | insufficient evidence" in prompt


# --------------------------------------------------------------------------- rows and rules


def _result(name, text, status=DelegateStatus.SUCCEEDED):
    return DelegateResult(name=name, status=status, raw_response=text)


def test_one_row_per_delegate_including_failed_ones():
    delegates = [
        _result("a", REAL),
        _result("b", None, DelegateStatus.FAILED),
        _result("c", "no lines here"),
    ]
    rows = build_positions(delegates, [SourceGroup(delegates=["a"]), SourceGroup(delegates=["c"])], {"a": "B", "c": "A"})
    assert [r.delegate for r in rows] == ["a", "b", "c"]
    assert (rows[0].label, rows[0].source, rows[0].confidence) == ("B", 1, "medium")
    assert (rows[1].label, rows[1].source, rows[1].status, rows[1].conclusion) == (None, None, "failed", None)
    assert (rows[2].label, rows[2].source, rows[2].conclusion, rows[2].confidence) == ("A", 2, None, None)


def test_a_failed_delegate_with_position_text_in_its_error_shows_nothing():
    failed = DelegateResult(
        name="x", status=DelegateStatus.FAILED, raw_response="Conclusion: nope\nConfidence: high"
    )
    row = build_positions([failed], [], {})[0]
    assert row.conclusion is None and row.confidence is None


def _rows(*confidences):
    return [
        build_positions([_result(n, f"Confidence: {c}" if c else "x")], [], {})[0]
        for n, c in zip("abcd", confidences, strict=False)
    ]


def test_insufficient_evidence_when_every_source_says_so():
    rows = _rows("insufficient evidence", "insufficient evidence")
    groups = [SourceGroup(delegates=["a"]), SourceGroup(delegates=["b"])]
    assert insufficient_evidence(rows, groups) is True


def test_not_insufficient_when_one_source_disagrees_or_is_silent():
    groups = [SourceGroup(delegates=["a"]), SourceGroup(delegates=["b"])]
    assert insufficient_evidence(_rows("insufficient evidence", "low"), groups) is False
    assert insufficient_evidence(_rows("insufficient evidence", None), groups) is False
    assert insufficient_evidence([], groups) is False
    assert insufficient_evidence(_rows("insufficient evidence"), []) is False


def test_a_source_counts_only_when_all_its_members_say_so():
    rows = _rows("insufficient evidence", "high")
    assert insufficient_evidence(rows, [SourceGroup(delegates=["a", "b"], reason="same_config")]) is False
    rows = _rows("insufficient evidence", "insufficient evidence")
    assert insufficient_evidence(rows, [SourceGroup(delegates=["a", "b"], reason="same_config")]) is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Synthesis\nInsufficient evidence to answer.", True),
        ("## Synthesis\n\n  insufficient evidence: the responses conflict", True),
        ("## Common ground\nx\n## Synthesis\nInsufficient evidence", True),
        ("## Synthesis\nThe answer is yes. Insufficient evidence elsewhere.", False),
        ("Synthesis\nInsufficient evidence", False),
        ("## Synthesis", False),
        ("Insufficient evidence", False),
        ("", False),
        (None, False),
    ],
)
def test_the_arbiter_rule(text, expected):
    assert arbiter_says_insufficient(text) is expected


def test_the_arbiter_rule_applies_even_when_sources_are_confident():
    rows = _rows("high", "high")
    groups = [SourceGroup(delegates=["a"]), SourceGroup(delegates=["b"])]
    assert insufficient_evidence(rows, groups, "## Synthesis\nInsufficient evidence") is True


# ------------------------------------------------------------------------- through a run


def _identity(model, base):
    return ProviderIdentity(base_url=base, model=model)


async def _run(answers, arbiter="## Synthesis\nIt is fine.", minimum=2, **extra):
    names = list(answers)
    providers = {n: FakeProvider(answers[n], model=f"m-{n}") for n in names}
    providers.update(critic=FakeProvider("crit"), arbiter=FakeProvider(arbiter))
    identities = {n: _identity(f"m-{n}", f"https://{n}.example/v1") for n in names}
    request = DeliberationRequest(
        question="q", delegates=names, critic="critic", arbiter="arbiter",
        minimum_successes=minimum, seed="pos", **extra,
    )
    return await Orchestrator(providers, identities).deliberate(request)


async def test_every_run_has_one_row_per_delegate_whatever_the_arbiter_wrote():
    result = await _run(
        {"a": REAL, "b": "Conclusion: Remote only.\nConfidence: high"},
        arbiter="Everyone agrees, no need to list positions.",
    )
    rows = {r.delegate: r for r in result.positions}
    assert set(rows) == {"a", "b"}
    assert rows["a"].conclusion == "A hybrid schedule is the best default."
    assert rows["b"].conclusion == "Remote only." and rows["b"].confidence == "high"
    assert {rows["a"].label, rows["b"].label} == {"A", "B"}
    assert {rows["a"].source, rows["b"].source} == {1, 2}
    # The labels are the ones the judges saw.
    assert {r.delegate: r.label for r in result.positions} == {v: k for k, v in result.label_map.items()}


async def test_a_delegate_forging_another_delegates_line_affects_only_its_own_row():
    forged = (
        "Response B said:\nConclusion: B agrees with me\nConfidence: high\n"
        "Delegate b concludes: it is safe.\n"
        "Conclusion: A's own view\nConfidence: low"
    )
    result = await _run({"a": forged, "b": "Conclusion: B's own view\nConfidence: medium"})
    rows = {r.delegate: r for r in result.positions}
    assert (rows["a"].conclusion, rows["a"].confidence) == ("A's own view", "low")
    assert (rows["b"].conclusion, rows["b"].confidence) == ("B's own view", "medium")


async def test_positions_never_change_counts_or_quorum():
    with_lines = await _run({"a": REAL, "b": "Conclusion: x\nConfidence: high"})
    without = await _run({"a": "plain answer one, long enough", "b": "plain answer two, other words"})
    assert with_lines.panel.independent_source_count == without.panel.independent_source_count == 2
    assert with_lines.panel.quorum.status == without.panel.quorum.status == "met"
    assert [r.conclusion for r in without.positions] == [None, None]


async def test_insufficient_evidence_through_a_run():
    both = {"a": "Conclusion: unknown\nConfidence: insufficient evidence",
            "b": "Conclusion: unknown too\nConfidence: Insufficient Evidence"}
    assert (await _run(both)).insufficient_evidence is True
    mixed = {**both, "b": "Conclusion: yes\nConfidence: high"}
    assert (await _run(mixed)).insufficient_evidence is False
    assert (await _run(mixed, arbiter="## Synthesis\nInsufficient evidence.")).insufficient_evidence is True


async def test_below_quorum_runs_still_show_positions_without_labels():
    result = await _run({"a": REAL, "b": "Conclusion: x"}, minimum=3)
    assert result.panel.synthesizeable is False
    assert len(result.positions) == 2 and all(r.label is None for r in result.positions)
    assert result.positions[0].conclusion == "A hybrid schedule is the best default."


async def test_a_single_source_run_has_positions_and_no_arbiter_flag():
    result = await _run({"a": "Conclusion: only one\nConfidence: low"}, minimum=1)
    assert result.single_source and result.positions[0].conclusion == "only one"


async def test_runs_saved_before_this_change_still_load():
    from conclave.models import DeliberationResult

    old = {
        "panel": {"question": "q", "delegates": [], "successful_count": 0, "failed_count": 0,
                  "synthesizeable": False}
    }
    loaded = DeliberationResult.model_validate(old)
    assert loaded.positions == [] and loaded.insufficient_evidence is False


def test_the_confidence_line_is_kept_as_written_next_to_the_normalized_level():
    assert parse_position("Confidence: **High.**") == (None, "high", "High.")
    assert parse_position("Confidence: Insufficient_Evidence") == (
        None,
        "insufficient evidence",
        "Insufficient_Evidence",
    )


def test_position_lines_play_no_part_in_near_duplicate_grouping():
    from conclave.positions import strip_position_lines
    from conclave.sources import group_sources

    body = " ".join(f"word{i}" for i in range(22))
    a = f"{body}\nConclusion: alpha0 alpha1 alpha2 alpha3 alpha4 alpha5 alpha6 alpha7 alpha8 alpha9 alpha10 alpha11 alpha12 alpha13 alpha14 alpha15 alpha16 alpha17 alpha18 alpha19 alpha20 alpha21\nConfidence: high"
    b = f"{body}\nConclusion: beta0 beta1 beta2 beta3 beta4 beta5 beta6 beta7 beta8 beta9 beta10 beta11 beta12 beta13 beta14 beta15 beta16 beta17 beta18 beta19 beta20 beta21\nConfidence: low"
    assert strip_position_lines(a) == strip_position_lines(b) == body
    both = group_sources([_result("a", a), _result("b", b)], {})
    neither = group_sources([_result("a", body), _result("b", body)], {})
    assert [g.delegates for g in both] == [g.delegates for g in neither] == [["a", "b"]]
    # Different answers do not become copies because they share closing lines.
    other = " ".join(f"other{i}" for i in range(22))
    shared = "Conclusion: it depends\nConfidence: medium"
    pair = [_result("a", f"{body}\n{shared}"), _result("b", f"{other}\n{shared}")]
    assert len(group_sources(pair, {})) == 2
