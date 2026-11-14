"""Repairs to the judge benchmark's evaluator (found by an independent audit of the stored trials)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.judge import runner, scoring  # noqa: E402
from conclave.providers.base import Provider, ProviderResponse  # noqa: E402

CASES = scoring.load_cases()
BY_ID = {c["id"]: c for c in CASES}


def answer(common="- Shared. [A]", disagreements="None.", uncertainty="- Open. [A]", synthesis="Go ahead."):
    return (
        f"## Common ground\n{common}\n\n## Disagreements\n{disagreements}\n\n"
        f"## Uncertainty\n{uncertainty}\n\n## Synthesis\n{synthesis}"
    )


def score(case_id, text):
    return {r.name: r.passed for r in scoring.score_trial(BY_ID[case_id], text)}


# ---------------------------------------------------- duplicates: three responses, two sources


@pytest.mark.parametrize(
    "text",
    [
        "Responses A and B share a source, so there are two independent sources overall. [A, B, C]",
        "A and B share one source; the three responses reduce to two independent sources. [A, B, C]",
        "A and B come from the same source and count as one. [A, B]",
        "There are three responses but only two sources, because A and B are duplicates. [A, B, C]",
    ],
)
def test_the_correct_count_of_two_sources_is_not_an_overclaim(text):
    assert score("duplicate-01-orm", answer(common=f"- {text}"))["one_source"] is True


@pytest.mark.parametrize(
    "text",
    [
        "Three independent sources agree on an ORM. [A, B, C]",
        "All three different responses reached the same conclusion on their own. [A, B, C]",
        "A and B are both independent sources that agree. [A, B]",
        "The responses are unanimous. [A, B, C]",
    ],
)
def test_overclaiming_independence_still_fails(text):
    assert score("duplicate-01-orm", answer(common=f"- {text} They share one source."))["one_source"] is False


# -------------------------------------------------------------- facts: dates and wrong claims


@pytest.mark.parametrize("date", ["30 June 2018", "June 30, 2018", "June 2018"])
def test_either_date_format_counts_as_the_fact(date):
    text = answer(synthesis=f"PCI DSS banned early TLS from {date}, so TLS 1.0 is not allowed.")
    assert score("fact-03-tls-pci", text)["mentions"] is True


def test_a_keyword_without_the_fact_is_caught_by_the_wrong_claim_check():
    keyword_only = answer(synthesis="RFC 8996 exists; TLS 1.0 remains acceptable for PCI compliance.")
    got = score("fact-03-tls-pci", keyword_only)
    assert got["mentions"] is True and got["not_asserted"] is False  # keyword present, endorsement wrong
    right = answer(synthesis="RFC 8996 deprecated TLS 1.0; it is not acceptable under PCI DSS.")
    assert score("fact-03-tls-pci", right)["not_asserted"] is True


@pytest.mark.parametrize(
    "case_id,wrong,right",
    [
        ("fact-01-http-spec", "RFC 2616 is still the current specification.", "RFC 2616 is obsolete; see RFC 9110 and RFC 9112."),
        ("fact-02-leap-year", "1900 was a leap year.", "1900 was not a leap year: it is divisible by 100 but not 400."),
        ("fact-04-python-gil", "The GIL was removed in Python 3.12.", "The GIL is still present in 3.12; PEP 703 arrived in 3.13."),
    ],
)
def test_each_fact_case_rejects_the_majoritys_wrong_claim_and_accepts_the_fact(case_id, wrong, right):
    assert score(case_id, answer(synthesis=wrong))["not_asserted"] is False
    assert score(case_id, answer(synthesis=right))["not_asserted"] is True


def test_a_negation_excuses_only_its_own_sentence():
    mixed = answer(synthesis="RFC 2616 is still the current specification. That is not controversial.")
    assert score("fact-01-http-spec", mixed)["not_asserted"] is False  # the endorsement stands
    same_sentence = answer(synthesis="RFC 2616 is not still the current specification.")
    assert score("fact-01-http-spec", same_sentence)["not_asserted"] is True


# ----------------------------------------------------------------------------------- rescoring


def test_rescoring_uses_the_saved_answer_and_keeps_the_first_scoring_once():
    case = BY_ID["duplicate-01-orm"]
    stored = {
        "case": case["id"], "class": case["class"], "arm": "arbiter", "repeat": 0, "judge": "j",
        "arbiter": answer(common="- A and B share a source, so there are two independent sources overall. [A, B, C]"),
        "results": [
            {"name": "format_ok", "passed": True, "detail": ""},
            {"name": "one_source", "passed": False, "detail": "claims independence: 'two independent sources'"},
        ],
    }
    [fixed] = scoring.rescore([stored])
    assert [r["passed"] for r in fixed["results"]] == [True, True] and fixed["scorer"] == scoring.SCORER_VERSION
    assert fixed["original_results"][1]["passed"] is False  # the old judgement is kept for audit
    [again] = scoring.rescore([fixed])
    assert again["original_results"] == fixed["original_results"]  # never overwritten by a later rescore


def test_rescore_from_the_command_line_calls_no_model(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(runner, "build_providers", lambda configs: called.append(1) or {})
    out = tmp_path / "r.jsonl"
    case = CASES[0]
    row = {"case": case["id"], "class": case["class"], "arm": "arbiter", "repeat": 0, "judge": "j",
           "arbiter": answer(disagreements="- Use HttpOnly cookies. [C]"), "results": []}
    out.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert runner.main(["--rescore", "--out", str(out)]) == 0 and called == []
    [rescored] = runner.load_results(out)
    assert rescored["scorer"] == scoring.SCORER_VERSION and [r["passed"] for r in rescored["results"]] == [True, True]


# ------------------------------------------------------ identity: the model behind a provider name


class Model(Provider):
    def __init__(self, model, text):
        self.model, self.text, self.calls = model, text, 0

    async def ask(self, prompt):
        self.calls += 1
        return ProviderResponse(text=self.text)


def test_a_provider_repointed_at_another_model_does_not_reuse_the_old_models_results(tmp_path):
    out = tmp_path / "r.jsonl"
    first = Model("vendor/model-one", answer())
    asyncio.run(runner.run_all(CASES[:1], {"j": first}, 1, out, log=lambda *_: None))
    assert {t["model"] for t in runner.load_results(out)} == {"vendor/model-one"}
    second = Model("vendor/model-two", answer())  # the same provider name, a different model
    new = asyncio.run(runner.run_all(CASES[:1], {"j": second}, 1, out, log=lambda *_: None))
    assert len(new) == 2 and second.calls > 0  # nothing was reused
    assert {t["model"] for t in runner.load_results(out)} == {"vendor/model-one", "vendor/model-two"}
    same = Model("vendor/model-two", answer())
    assert asyncio.run(runner.run_all(CASES[:1], {"j": same}, 1, out, log=lambda *_: None)) == [] and same.calls == 0


# ------------------------------------------------ accounting: a failed trial's spend is kept


def test_the_cost_of_a_completed_critic_is_recorded_when_its_arbiter_fails(tmp_path):
    class CriticThenFail(Provider):
        model = "m"

        def __init__(self):
            self.n = 0

        async def ask(self, prompt):
            self.n += 1
            if self.n == 1:  # the arbiter-alone trial of the first case answers
                return ProviderResponse(text=answer(), usage={"prompt_tokens": 10, "completion_tokens": 5})
            if self.n == 2:  # the Critic of the Critic arm answers (and is paid for)...
                return ProviderResponse(text="a critique", usage={"prompt_tokens": 1000, "completion_tokens": 500})
            raise RuntimeError("down")  # ...then its Arbiter fails

    out = tmp_path / "r.jsonl"
    asyncio.run(runner.run_all(CASES[:1], {"j": CriticThenFail()}, 1, out, log=lambda *_: None))
    [trial] = runner.load_results(out)  # only the Arbiter-alone trial was scored
    assert trial["arm"] == "arbiter"
    [entry] = runner.load_results(runner.operational_path(out))
    assert entry["arm"] == "critic" and entry["stages"][0][1] == "succeeded"
    assert entry["cost"]["total_calls"] >= 2  # includes the Critic that finished and the Arbiter that failed
    assert entry["cost"]["unpriced_calls"] == entry["cost"]["total_calls"]  # unpriced here, but counted, not lost
