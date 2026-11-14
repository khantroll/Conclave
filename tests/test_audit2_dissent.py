"""Second audit, finding 3: matching text is not agreement, and similarity is not proof of origin."""

from __future__ import annotations

import asyncio

import pytest

from conclave.models import DelegateResult, DelegateStatus, DeliberationRequest
from conclave.orchestrator import Orchestrator
from conclave.providers.fake import FakeProvider
from conclave.sources import group_sources, opposing

BACKGROUND = (
    "The migration touches the orders table, which holds about two million rows. Row locks are "
    "taken while each batch is copied, the replica lags behind during the copy, and the team has "
    "run this procedure on staging twice already without incident. "
)


def result(name, text):
    return DelegateResult(name=name, status=DelegateStatus.SUCCEEDED, raw_response=text)


def merged(a, b):
    groups = group_sources([result("a", a), result("b", b)], {})
    return len(groups) == 1


@pytest.mark.parametrize(
    "a,b",
    [
        (BACKGROUND + "\nConclusion: Run it during peak hours.", BACKGROUND + "\nConclusion: Do not run it during peak hours."),
        (BACKGROUND + "\nConclusion: Ship it.\nConfidence: high", BACKGROUND + "\nConclusion: Hold the release.\nConfidence: high"),
        (BACKGROUND + "You should run it now.", BACKGROUND + "You should not run it now."),
        (BACKGROUND + "Do it.", BACKGROUND + "Never do it."),
        (BACKGROUND + "Set the batch size to 500 rows.", BACKGROUND + "Set the batch size to 5000 rows."),
        (BACKGROUND + "It will take 2 hours.", BACKGROUND + "It will take 20 hours."),
        (BACKGROUND + "There is no risk.", BACKGROUND + "There is a risk."),
        (BACKGROUND + "This can be done without downtime.", BACKGROUND + "This can be done with downtime."),
    ],
    ids=["opposite-conclusions", "opposite-conclusion-lines", "negation", "never", "changed-number", "changed-hours", "no-vs-a", "without"],
)
def test_matching_background_does_not_merge_answers_that_disagree(a, b):
    assert opposing(a, b) is True
    assert merged(a, b) is False  # two sources: the dissent is not suppressed


@pytest.mark.parametrize(
    "a,b",
    [
        (BACKGROUND + "\nConclusion: Ship it.\nConfidence: high", BACKGROUND + "\nConclusion: Ship it.\nConfidence: low"),
        (BACKGROUND + "Ship it.", "**" + BACKGROUND.upper() + "** Ship it!"),
        (BACKGROUND + "Ship it.", BACKGROUND.replace("twice", "two times") + "Ship it."),
        (BACKGROUND + "Ship it.", BACKGROUND + "Ship it. Let me know if you need more."),
    ],
    ids=["same-conclusion", "case-markdown", "light-edit", "padded"],
)
def test_genuine_copies_still_merge(a, b):
    assert opposing(a, b) is False
    assert merged(a, b) is True  # the anti-inflation safeguard is intact


def test_opposite_numbers_and_negations_must_differ_not_merely_exist():
    # The same number or the same negation on both sides is just shared text.
    a = BACKGROUND + "It is not risky and takes 2 hours."
    assert opposing(a, a.replace("risky", "dangerous")) is False
    assert merged(a, a.replace("risky", "dangerous")) is True


def test_a_copy_that_differs_only_by_its_stated_conclusion_text_is_opposing_even_without_other_changes():
    a, b = BACKGROUND + "\nConclusion: Yes.", BACKGROUND + "\nConclusion: No."
    assert merged(a, b) is False


def test_the_judge_is_not_told_that_lexical_similarity_proves_a_shared_origin():
    text = " ".join(f"word{i}" for i in range(40)) + " Ship it."
    ids = {}
    providers = {"a": FakeProvider(text), "b": FakeProvider(text), "c": FakeProvider("other " + " ".join(f"o{i}" for i in range(30))),
                 "crit": FakeProvider("c"), "arb": FakeProvider("f")}
    req = DeliberationRequest(question="q", delegates=["a", "b", "c"], arbiter="arb", critic="crit", minimum_successes=2, seed="s")
    result_ = asyncio.run(Orchestrator(providers, ids).deliberate(req))
    assert result_.panel.sources[0].reason == "near_duplicate_text"
    for prompt in (result_.critic.prompt, result_.arbiter.prompt):
        assert "nearly identical text" in prompt and "may be copying" in prompt
        assert "same underlying source" not in prompt  # that is said only of known shared identity
        assert "Their origin is not known to be the same" in prompt


def test_known_identity_is_still_described_as_the_same_source():
    from conclave.sources import ProviderIdentity

    ids = {n: ProviderIdentity(base_url="https://x/v1", model="m") for n in ("a", "b")}
    ids["c"] = ProviderIdentity(base_url="https://y/v1", model="n")
    providers = {n: FakeProvider(f"{n} " + " ".join(f"{n}{i}" for i in range(30)), model=f"model-{n}") for n in "abc"}
    providers.update(crit=FakeProvider("c"), arb=FakeProvider("f"))
    req = DeliberationRequest(question="q", delegates=["a", "b", "c"], arbiter="arb", critic="crit", minimum_successes=2, seed="s")
    out = asyncio.run(Orchestrator(providers, ids).deliberate(req))
    assert "come from the same underlying source" in out.arbiter.prompt


def test_two_delegates_with_opposite_conclusions_count_toward_quorum_as_two_sources():
    text_a, text_b = BACKGROUND + "\nConclusion: Ship.", BACKGROUND + "\nConclusion: Do not ship."
    providers = {"a": FakeProvider(text_a), "b": FakeProvider(text_b), "crit": FakeProvider("c"), "arb": FakeProvider("f")}
    req = DeliberationRequest(question="q", delegates=["a", "b"], arbiter="arb", critic="crit", minimum_successes=2, seed="s")
    out = asyncio.run(Orchestrator(providers).deliberate(req))
    assert out.panel.independent_source_count == 2 and out.panel.quorum.status == "met" and out.arbiter is not None


def test_opposing_answers_cannot_merge_through_a_third_that_states_no_conclusion():
    proceed = BACKGROUND + "\nConclusion: Proceed with the release."
    stop = BACKGROUND + "\nConclusion: Stop the release."
    middle = BACKGROUND  # no conclusion line, so it opposes neither
    for order in ([proceed, middle, stop], [middle, proceed, stop], [proceed, stop, middle], [stop, middle, proceed]):
        groups = group_sources([result(f"r{i}", text) for i, text in enumerate(order)], {})
        proceed_at = order.index(proceed)
        stop_at = order.index(stop)
        for g in groups:
            assert not ({f"r{proceed_at}", f"r{stop_at}"} <= set(g.delegates)), order  # never in one source
        assert len(groups) >= 2


def test_a_chain_of_genuine_near_copies_still_merges():
    texts = [BACKGROUND + "Ship it.", BACKGROUND + "Ship it!", BACKGROUND.replace("twice", "two times") + "Ship it."]
    assert len(group_sources([result(f"r{i}", t) for i, t in enumerate(texts)], {})) == 1
