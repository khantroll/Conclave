"""P1-6: the Arbiter structure across failures, retries and hostile or huge input."""

from __future__ import annotations

import time

from conclave.models import DeliberationRequest
from conclave.orchestrator import Orchestrator
from conclave.providers.fake import FakeProvider
from conclave.sources import ProviderIdentity
from conclave.synthesis import citations_in, parse_sections

FOUR = "## Common ground\n{c}\n\n## Disagreements\nNone.\n\n## Uncertainty\n{u}\n\n## Synthesis\n{s}"


def _answer(common="- shared [A]", uncertain="- unknown [B]", synthesis="Go with it."):
    return FOUR.format(c=common, u=uncertain, s=synthesis)


# ----------------------------------------------------------------- a fifth heading


def test_an_extra_heading_is_a_different_shape():
    for extra in ("## Extra", "# Title", "##  Spaced", "## Recommendation"):
        parsed = parse_sections(_answer() + "\n" + extra + "\nmore")
        assert parsed.format_ok is False, extra
        assert "a heading other than the four required" in parsed.problems


def test_an_extra_heading_between_sections_also_fails():
    text = _answer().replace("## Uncertainty", "## Extra\nx\n\n## Uncertainty")
    assert parse_sections(text).format_ok is False


def test_deeper_headings_and_lookalikes_are_just_text():
    text = _answer(synthesis="### Details\nGo with it.\n#hashtag and ##nospace stay text")
    parsed = parse_sections(text)
    assert parsed.format_ok is True
    assert parsed.sections["synthesis"].startswith("### Details")


# -------------------------------------------------------------------- huge and odd input


def test_a_huge_well_formed_answer_parses_quickly():
    labels = [chr(65 + a) + chr(65 + b) + chr(65 + c) for a in range(26) for b in range(26) for c in range(8)]
    body = "\n".join(f"- point {i} [{label}]" for i, label in enumerate(labels))
    text = _answer(common=body, uncertain=body, synthesis="x " * 50_000)
    start = time.perf_counter()
    parsed = parse_sections(text, {"A"})
    assert time.perf_counter() - start < 2.0
    assert parsed.format_ok is True
    assert len(parsed.unknown_citations) == len(set(labels))
    assert parsed.unknown_citations == sorted(set(labels))


def test_repeated_citations_are_deduplicated_in_order():
    assert citations_in("[B] " * 100_000 + "[A]") == ["B", "A"]


def test_pathological_citation_and_bullet_text_does_not_backtrack():
    start = time.perf_counter()
    assert citations_in("[" + "A," * 50_000) == []
    assert citations_in("[" + "A " * 50_000 + "]") == []
    parse_sections("-" * 200_000)
    parse_sections(_answer(common="- " * 100_000))
    assert time.perf_counter() - start < 3.0


def test_odd_unicode_does_not_raise():
    for text in ("\x00‮퟿\U0010ffff", " ## Common ground ", "## Common ground\x00"):
        assert parse_sections(text).format_ok is False


# ------------------------------------------------- labels, failures and retries in a run


def _providers(arbiter_text, *, fail=()):
    answers = {"a": "answer one " + "w" * 30, "b": "answer two " + "v" * 30, "c": "answer three " + "u" * 30}
    providers = {n: FakeProvider(error=RuntimeError("down")) if n in fail else FakeProvider(t, model=f"m-{n}")
                 for n, t in answers.items()}
    providers.update(critic=FakeProvider("crit"), arbiter=FakeProvider(arbiter_text))
    identities = {n: ProviderIdentity(base_url=f"https://{n}.example/v1", model=f"m-{n}") for n in answers}
    return providers, identities


def _request(**extra):
    return DeliberationRequest(
        question="q", delegates=["a", "b", "c"], critic="critic", arbiter="arbiter",
        minimum_successes=2, seed="runs", **extra,
    )


async def test_citing_the_letter_of_a_delegate_that_failed_is_unknown():
    providers, identities = _providers("", fail=("c",))
    orchestrator = Orchestrator(providers, identities)
    first = await orchestrator.deliberate(_request())
    assert len(first.label_map) == 2
    # The permutation covers all three delegates, so one letter of A..C is unused.
    unused = ({"A", "B", "C"} - set(first.label_map)).pop()
    shown = sorted(first.label_map)
    text = _answer(common=f"- x [{shown[0]}]", uncertain=f"- y [{unused}]")
    orchestrator._providers["arbiter"] = FakeProvider(text)
    again = await orchestrator.retry_arbiter(request=_request(), prior_result=first)
    assert again.arbiter_structure.format_ok is True
    assert again.arbiter_structure.unknown_citations == [unused]


async def test_retries_keep_the_structure_and_use_the_labels_the_judge_saw():
    providers, identities = _providers("")
    orchestrator = Orchestrator(providers, identities)
    request = _request()
    first = await orchestrator.deliberate(request)
    label_b = {v: k for k, v in first.label_map.items()}["b"]
    orchestrator._providers["arbiter"] = FakeProvider(_answer(common=f"- x [{label_b}]", uncertain="- y [Z]"))

    for retried in (
        await orchestrator.retry_critic(request=request, prior_result=first),
        await orchestrator.retry_arbiter(request=request, prior_result=first),
    ):
        assert retried.label_map == first.label_map
        assert retried.arbiter_structure.format_ok is True
        assert retried.arbiter_structure.unknown_citations == ["Z"]
        assert retried.arbiter_structure.points["common_ground"][0].citations == [label_b]


async def test_a_delegate_retry_after_a_failure_keeps_earlier_labels_valid():
    providers, identities = _providers("", fail=("b",))
    orchestrator = Orchestrator(providers, identities)
    request = _request()
    first = await orchestrator.deliberate(request)
    assert "b" not in first.label_map.values()
    orchestrator._providers["b"] = FakeProvider("answer two " + "v" * 30, model="m-b")
    label_of = {v: k for k, v in first.label_map.items()}
    orchestrator._providers["arbiter"] = FakeProvider(_answer(common=f"- x [{label_of['a']}]"))
    retried = await orchestrator.retry_delegate(request=request, prior_result=first, delegate_name="b")
    assert len(retried.label_map) == 3
    assert all(retried.label_map[k] == v for k, v in first.label_map.items())
    assert retried.arbiter_structure.format_ok is True
    assert retried.arbiter_structure.unknown_citations == []
