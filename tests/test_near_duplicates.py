"""P1-4: copies and near-copies are one source; paraphrases and unrelated answers are not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conclave.config import ProviderConfig
from conclave.models import DeliberationRequest, DelegateResult, DelegateStatus
from conclave.orchestrator import Orchestrator
from conclave.prompts import AGREEMENT_SENTENCE
from conclave.providers.factory import build_identities
from conclave.providers.fake import FakeProvider
from conclave.sources import (
    CONTAINMENT_THRESHOLD,
    JACCARD_THRESHOLD,
    MIN_COMPARED_WORDS,
    NEAR_DUPLICATE_TEXT,
    ProviderIdentity,
    group_sources,
    normalize_text,
    text_similarity,
)

PAIRS = json.loads(
    (Path(__file__).parent / "fixtures" / "near_duplicates.json").read_text(encoding="utf-8")
)["pairs"]


P = {p["id"]: p for p in PAIRS}


def _result(name, text):
    return DelegateResult(name=name, status=DelegateStatus.SUCCEEDED, raw_response=text)


def test_the_fixture_set_is_large_and_covers_every_kind():
    assert len(PAIRS) >= 20
    kinds = " ".join(p["kind"] for p in PAIRS)
    for needle in ("verbatim", "light edit", "padded", "paraphrase", "unrelated"):
        assert needle in kinds
    assert any(p["merge"] for p in PAIRS) and any(not p["merge"] for p in PAIRS)


@pytest.mark.parametrize("pair", PAIRS, ids=[p["id"] for p in PAIRS])
def test_every_fixture_pair_classifies_as_specified(pair):
    found = text_similarity(pair["a"], pair["b"])
    assert (found is not None) == pair["merge"], (pair["kind"], found)
    # Symmetric.
    assert (text_similarity(pair["b"], pair["a"]) is not None) == pair["merge"]


def test_the_thresholds_sit_in_a_gap_between_the_two_classes():
    """A guard against tuning to one lucky pair: scores must be clearly separated."""
    from conclave.sources import _prepare

    def jaccard(pair):
        a, b = _prepare(pair["a"])[1], _prepare(pair["b"])[1]
        return len(a & b) / len(a | b) if a and b else 0.0

    longish = [p for p in PAIRS if len(normalize_text(p["a"]).split()) >= MIN_COMPARED_WORDS]
    merges = [jaccard(p) for p in longish if p["merge"] and "padded" not in p["kind"]]
    keeps = [jaccard(p) for p in longish if not p["merge"]]
    assert min(merges) > JACCARD_THRESHOLD > max(keeps)
    assert JACCARD_THRESHOLD - max(keeps) >= 0.15 and min(merges) - JACCARD_THRESHOLD >= 0.03
    assert 0.8 <= CONTAINMENT_THRESHOLD <= 0.95


def test_the_rule_that_fires_is_the_expected_one():
    by_id = {p["id"]: p for p in PAIRS}
    assert text_similarity(by_id["verbatim-1"]["a"], by_id["verbatim-1"]["b"])[0] == "equal"
    # A copy buried in three times as much new text is caught by containment, not Jaccard.
    buried = by_id["verbatim-1"]["a"] + " " + " ".join(f"extra{i}" for i in range(120))
    assert text_similarity(by_id["verbatim-1"]["a"], buried)[0] == "containment"
    assert text_similarity(by_id["padded-1"]["a"], by_id["padded-1"]["b"]) is not None
    assert text_similarity(by_id["word-swap-1"]["a"], by_id["word-swap-1"]["b"])[0] == "jaccard"


def test_normalization_removes_case_markdown_zero_width_and_compatibility_forms():
    assert normalize_text("**Hello**,  W​orld!\n\nＴｅｓｔ_x") == "hello world test x"
    assert normalize_text(None) == "" and normalize_text("...") == ""


def test_short_answers_are_never_compared():
    text = "No, that is not safe to do in production."
    assert text_similarity(text, text) is None
    twenty = " ".join(f"w{i}" for i in range(MIN_COMPARED_WORDS))
    assert text_similarity(twenty, twenty) == ("equal", 1.0)
    assert text_similarity(" ".join(twenty.split()[:-1]), " ".join(twenty.split()[:-1])) is None


# ---------------------------------------------------------------- grouping integration


def _identity(model, base="https://api.example.com/v1", family=None):
    return ProviderIdentity(base_url=base, model=model, family=family)


def test_copies_from_different_models_merge_with_reason_and_score():
    groups = group_sources(
        [_result("x", P["case-punct-1"]["a"]), _result("y", P["case-punct-1"]["b"]),
         _result("z", P["paraphrase-1"]["b"])],
        {"x": _identity("m1"), "y": _identity("m2"), "z": _identity("m3")},
    )
    assert [g.delegates for g in groups] == [["x", "y"], ["z"]]
    assert groups[0].reason == NEAR_DUPLICATE_TEXT and groups[0].similarity == 1.0
    assert groups[1].reason is None and groups[1].similarity is None


def test_paraphrases_from_different_models_do_not_merge():
    groups = group_sources(
        [_result("x", P["paraphrase-1"]["a"]), _result("y", P["paraphrase-1"]["b"])],
        {"x": _identity("m1"), "y": _identity("m2")},
    )
    assert len(groups) == 2 and all(g.similarity is None for g in groups)


def test_a_stronger_reason_wins_over_text():
    text = P["verbatim-1"]["a"]
    groups = group_sources(
        [_result("x", text), _result("y", text)], {"x": _identity("m1"), "y": _identity("m1")}
    )
    assert len(groups) == 1 and groups[0].reason == "same_config"


def test_text_merging_applies_to_providers_with_no_identity():
    groups = group_sources([_result("x", P["verbatim-1"]["a"]), _result("y", P["verbatim-1"]["a"])], {})
    assert len(groups) == 1 and groups[0].reason == NEAR_DUPLICATE_TEXT


def test_merging_is_transitive_and_keeps_the_best_score():
    base = P["verbatim-1"]["a"]
    padded = P["padded-1"]["b"]  # a copy of base plus a sentence
    edited = P["padded-1"]["b"] + " Yet another sentence that is only in this one answer."
    groups = group_sources(
        [_result("a", base), _result("b", padded), _result("c", edited), _result("d", P["unrelated-2"]["a"])], {}
    )
    assert [g.delegates for g in groups] == [["a", "b", "c"], ["d"]]
    assert groups[0].similarity >= 0.9


def test_comparison_can_be_switched_off():
    groups = group_sources(
        [_result("x", P["verbatim-1"]["a"]), _result("y", P["verbatim-1"]["a"])], {}, compare_text=False
    )
    assert len(groups) == 2


# ------------------------------------------------------- effect on a run: quorum and prompts


async def test_copied_answers_do_not_meet_a_quorum_of_two():
    text = P["verbatim-1"]["a"]
    orchestrator = Orchestrator(
        {
            "x": FakeProvider(text, model="m1"),
            "y": FakeProvider(text, model="m2"),
            "critic": FakeProvider("c"),
            "arbiter": FakeProvider("a"),
        },
        {"x": _identity("m1", "https://one.example/v1"), "y": _identity("m2", "https://two.example/v1")},
    )
    request = DeliberationRequest(
        question="q", delegates=["x", "y"], critic="critic", arbiter="arbiter", minimum_successes=2
    )
    result = await orchestrator.deliberate(request)
    assert result.panel.independent_source_count == 1
    assert result.panel.synthesizeable is False and result.panel.quorum.status == "unmet"
    assert result.critic is None and result.arbiter is None
    assert any("near-duplicate answers" in s for s in result.panel.quorum.shortfalls)


# ------------------------------------------------------------------------- model family


def test_family_is_optional_and_flows_into_the_identity():
    config = ProviderConfig(name="p", base_url="https://x/v1", model="m", family="openai")
    assert build_identities([config])["p"].family == "openai"
    assert ProviderConfig(name="p", base_url="https://x/v1", model="m").family is None


def _family_run(families, answers=None):
    names = ["a", "b", "c"]
    answers = answers or [P["paraphrase-1"]["a"], P["paraphrase-1"]["b"], P["unrelated-2"]["b"]]
    providers = {n: FakeProvider(answers[i], model=f"model-{i}") for i, n in enumerate(names)}
    providers.update(critic=FakeProvider("c"), arbiter=FakeProvider("a"))
    identities = {
        n: _identity(f"model-{i}", f"https://h{i}.example/v1", families.get(n))
        for i, n in enumerate(names)
    }
    request = DeliberationRequest(
        question="q", delegates=names, critic="critic", arbiter="arbiter",
        minimum_successes=2, seed="fam",
    )
    return Orchestrator(providers, identities), request


async def test_distinct_families_counts_known_families_and_the_judge_gets_labels_only():
    orchestrator, request = _family_run({"a": "openai", "b": "openai", "c": "meta"})
    result = await orchestrator.deliberate(request)
    assert result.panel.independent_source_count == 3
    assert result.panel.distinct_families == 2
    assert result.panel.families == {"a": "openai", "b": "openai", "c": "meta"}
    labels = {name: label for label, name in result.label_map.items()}
    first, second = sorted([labels["a"], labels["b"]])
    for prompt in (result.critic.prompt, result.arbiter.prompt):
        assert f"Responses {first} and {second} come from the same model family" in prompt
        assert "openai" not in prompt and "meta" not in prompt  # the family name stays hidden
        assert AGREEMENT_SENTENCE in prompt


async def test_no_family_note_when_families_differ_or_are_unknown():
    for families in ({}, {"a": "openai", "b": "meta", "c": "mistral"}):
        orchestrator, request = _family_run(families)
        result = await orchestrator.deliberate(request)
        assert "model family" not in result.arbiter.prompt
        assert AGREEMENT_SENTENCE in result.arbiter.prompt and AGREEMENT_SENTENCE in result.critic.prompt
    assert result.panel.distinct_families == 3
    orchestrator, request = _family_run({})
    assert (await orchestrator.deliberate(request)).panel.distinct_families is None


async def test_a_family_inside_one_source_gets_no_separate_family_line():
    text = P["verbatim-1"]["a"]
    orchestrator, request = _family_run(
        {"a": "openai", "b": "openai", "c": "meta"}, answers=[text, text, P["unrelated-2"]["b"]]
    )
    result = await orchestrator.deliberate(request)
    assert result.panel.independent_source_count == 2
    assert "same model family" not in result.arbiter.prompt
    assert "nearly identical text" in result.arbiter.prompt


async def test_a_failed_delegate_has_no_family_entry():
    orchestrator, request = _family_run({"a": "openai", "b": "openai", "c": "meta"})
    orchestrator._providers["b"] = FakeProvider(error=RuntimeError("down"))
    result = await orchestrator.deliberate(request)
    assert set(result.panel.families) == {"a", "c"} and result.panel.distinct_families == 2


async def test_runs_saved_before_this_change_still_load():
    from conclave.models import PanelResult

    old = {"question": "q", "delegates": [], "successful_count": 0, "failed_count": 0,
           "synthesizeable": False}
    panel = PanelResult.model_validate(old)
    assert panel.families == {} and panel.distinct_families is None


async def test_a_judge_that_repeats_an_answer_is_not_an_overlap_by_text():
    # The Critic echoing a delegate's answer word for word is not the same *source*.
    text = P["verbatim-1"]["a"]
    providers = {
        "x": FakeProvider(text, model="m1"),
        "y": FakeProvider(P["unrelated-2"]["b"], model="m2"),
        "critic": FakeProvider(text, model="judge-model"),
        "arbiter": FakeProvider(text, model="judge-model"),
    }
    identities = {
        "x": _identity("m1", "https://x.example/v1"),
        "y": _identity("m2", "https://y.example/v1"),
        "critic": _identity("judge-model", "https://j.example/v1"),
        "arbiter": _identity("judge-model", "https://j.example/v1"),
    }
    request = DeliberationRequest(
        question="q", delegates=["x", "y"], critic="critic", arbiter="arbiter", minimum_successes=2
    )
    result = await Orchestrator(providers, identities).deliberate(request)
    assert result.critic.status == DelegateStatus.SUCCEEDED
    assert result.judge_overlaps == []
