"""P1-3: judges see answers by label only, in a seeded order, and the mapping is kept for the user."""

from __future__ import annotations

import re

import pytest

from conclave.models import DeliberationRequest, DelegateStatus
from conclave.orchestrator import Orchestrator
from conclave.prompts import label_map
from conclave.providers.fake import FakeProvider
from conclave.sources import ProviderIdentity

# Strings that identify a provider or model. None may appear in a judge prompt.
NAMES = ["alpha-prov", "beta-prov", "gamma-prov"]
MODELS = ["acme-large-7", "bolt-mini-3", "cog-xl-2"]
REPORTED = ["reported-acme-7b", "reported-bolt-3b", "reported-cog-2b"]
SECRETS = [*NAMES, *MODELS, *REPORTED, "critic-prov", "arbiter-prov", "judge-model-x", "judge-reported-y"]


def _identity(model, base_url="https://api.example.com/v1"):
    return ProviderIdentity(base_url=base_url, model=model)


def _build(seed="s1", *, judge_model="judge-model-x", judge_base="https://judge.example.com/v1"):
    providers = {
        name: FakeProvider(f"answer from {i}", model=REPORTED[i], usage={"total_tokens": 137 + i})
        for i, name in enumerate(NAMES)
    }
    providers["critic-prov"] = FakeProvider("critique", model="judge-reported-y")
    providers["arbiter-prov"] = FakeProvider("final", model="judge-reported-y")
    identities = {name: _identity(MODELS[i], f"https://h{i}.example.com/v1") for i, name in enumerate(NAMES)}
    identities["critic-prov"] = _identity(judge_model, judge_base)
    identities["arbiter-prov"] = _identity(judge_model, judge_base)
    request = DeliberationRequest(
        question="q",
        delegates=list(NAMES),
        critic="critic-prov",
        arbiter="arbiter-prov",
        minimum_successes=2,
        seed=seed,
    )
    return Orchestrator(providers, identities), request


async def test_no_provider_or_model_identity_reaches_either_judge_prompt():
    orchestrator, request = _build()
    result = await orchestrator.deliberate(request)
    assert result.critic.prompt and result.arbiter.prompt
    for prompt in (result.critic.prompt, result.arbiter.prompt):
        for secret in SECRETS:
            assert secret not in prompt, secret
        # No timing, token, cost or attempt figures either.
        assert not re.search(r"\b137\b|latency|tokens?:|cost|attempt", prompt, re.IGNORECASE), prompt
        assert "Response A" in prompt


async def test_failed_delegates_leak_no_names_or_error_text():
    orchestrator, request = _build()
    orchestrator._providers["gamma-prov"] = FakeProvider(error=RuntimeError("secret-boom gamma-prov"))
    result = await orchestrator.deliberate(request)
    for prompt in (result.critic.prompt, result.arbiter.prompt):
        assert "secret-boom" not in prompt and "gamma-prov" not in prompt
        assert "Slot 3 did not answer: failed." in prompt


async def test_the_label_mapping_is_stored_and_matches_the_prompt_blocks():
    orchestrator, request = _build()
    result = await orchestrator.deliberate(request)
    assert sorted(result.label_map) == ["A", "B", "C"]
    assert sorted(result.label_map.values()) == sorted(NAMES)
    by_name = {d.name: d.raw_response for d in result.panel.delegates}
    for label, name in result.label_map.items():
        block = re.search(rf"<<<RESPONSE {label} [0-9a-f]+>>>\n(.*?)\n<<<END {label} ", result.arbiter.prompt, re.S)
        assert block and block.group(1) == by_name[name]


async def test_the_order_is_not_the_workspace_order_and_differs_between_seeds():
    orders = set()
    for seed in (f"seed-{i}" for i in range(40)):
        orchestrator, request = _build(seed)
        result = await orchestrator.deliberate(request)
        orders.add(tuple(result.label_map[k] for k in "ABC"))
    assert len(orders) > 1
    assert tuple(NAMES) in orders and len(orders) >= 4  # all six are possible; most appear in 40 draws


async def test_the_same_seed_gives_the_same_order():
    first = label_map(_delegates(), "fixed")
    assert first == label_map(list(reversed(_delegates())), "fixed")  # not workspace order
    assert first == label_map(_delegates(), "fixed")


def _delegates(names=NAMES):
    from conclave.models import DelegateResult

    return [DelegateResult(name=n, status=DelegateStatus.SUCCEEDED, raw_response=n) for n in names]


async def test_a_delegate_keeps_its_label_whoever_else_answers():
    from conclave.models import DelegateResult

    def results(failed):
        return [
            DelegateResult(
                name=n,
                status=DelegateStatus.FAILED if n in failed else DelegateStatus.SUCCEEDED,
                raw_response=None if n in failed else n,
            )
            for n in NAMES
        ]

    for seed in (f"k{i}" for i in range(30)):
        everyone = label_map(results(set()), seed)
        for drop in NAMES:
            partial = label_map(results({drop}), seed)
            assert partial == {k: v for k, v in everyone.items() if v != drop}, (seed, drop)


async def test_a_delegate_retry_relabels_nobody():
    # b fails first and is retried successfully: a and c keep the labels the judges first saw.
    for seed in (f"r{i}" for i in range(12)):
        orchestrator, request = _build(seed)
        good = orchestrator._providers["beta-prov"]
        orchestrator._providers["beta-prov"] = FakeProvider(error=RuntimeError("down"))
        first = await orchestrator.deliberate(request)
        orchestrator._providers["beta-prov"] = good
        retried = await orchestrator.retry_delegate(
            request=request, prior_result=first, delegate_name="beta-prov"
        )
        assert len(retried.label_map) == 3 and len(first.label_map) == 2
        assert all(retried.label_map[k] == v for k, v in first.label_map.items()), seed


async def test_a_failed_judge_records_no_overlap():
    orchestrator, request = _build(judge_model=MODELS[0], judge_base="https://h0.example.com/v1")
    orchestrator._providers["arbiter-prov"] = FakeProvider(error=RuntimeError("down"))
    orchestrator._providers["critic-prov"] = FakeProvider(error=RuntimeError("down"))
    result = await orchestrator.deliberate(request)
    assert result.arbiter.status != DelegateStatus.SUCCEEDED
    assert result.judge_overlaps == []


async def test_retries_keep_the_order_and_the_mapping():
    orchestrator, request = _build("chain")
    first = await orchestrator.deliberate(request)
    critic_retry = await orchestrator.retry_critic(request=request, prior_result=first)
    arbiter_retry = await orchestrator.retry_arbiter(request=request, prior_result=critic_retry)
    assert first.label_map == critic_retry.label_map == arbiter_retry.label_map
    for result in (first, critic_retry, arbiter_retry):
        assert result.arbiter.prompt.split("Delegate responses:")[1] .count("Response ") >= 3
    # The delegate blocks in the Arbiter prompt are byte-identical across the chain.
    def blocks(prompt):
        return re.findall(r"Response [A-Z]\n<<<RESPONSE .*?>>>", prompt, re.S)

    assert blocks(first.arbiter.prompt) == blocks(critic_retry.arbiter.prompt) == blocks(arbiter_retry.arbiter.prompt)


async def test_source_groups_are_given_by_label_only():
    providers = {
        "a": FakeProvider("one", model="m1"),
        "b": FakeProvider("two", model="m2"),
        "c": FakeProvider("three", model="m1"),
        "critic-prov": FakeProvider("crit"),
        "arbiter-prov": FakeProvider("fin"),
    }
    identities = {"a": _identity("m1"), "b": _identity("m2"), "c": _identity("m1")}
    request = DeliberationRequest(
        question="q", delegates=["a", "b", "c"], critic="critic-prov", arbiter="arbiter-prov",
        minimum_successes=2, seed="g",
    )
    result = await Orchestrator(providers, identities).deliberate(request)
    labels = {name: label for label, name in result.label_map.items()}
    first, second = sorted([labels["a"], labels["c"]])
    assert f"Responses {first} and {second} come from the same underlying source" in result.arbiter.prompt


async def test_a_judge_sharing_a_source_with_a_delegate_is_recorded_not_announced():
    # The Critic and Arbiter are configured on the same endpoint and model as the first delegate.
    orchestrator, request = _build(judge_model=MODELS[0], judge_base="https://h0.example.com/v1")
    result = await orchestrator.deliberate(request)
    expected = [{v: k for k, v in result.label_map.items()}[NAMES[0]]]
    assert result.judge_overlaps == expected
    for prompt in (result.critic.prompt, result.arbiter.prompt):
        assert "own" not in prompt.lower().split("original question")[0]  # not told which is its own
        assert "overlap" not in prompt.lower()


async def test_no_overlap_when_the_judge_is_a_different_source():
    orchestrator, request = _build()
    result = await orchestrator.deliberate(request)
    assert result.judge_overlaps == []


async def test_a_judge_that_reports_a_delegates_model_overlaps_by_reported_model():
    orchestrator, request = _build()
    orchestrator._providers["arbiter-prov"] = FakeProvider("final", model=REPORTED[1])
    result = await orchestrator.deliberate(request)
    by_name = {v: k for k, v in result.label_map.items()}
    assert result.judge_overlaps == [by_name[NAMES[1]]]


async def test_a_run_below_quorum_carries_no_label_map():
    orchestrator, request = _build()
    orchestrator._providers["beta-prov"] = FakeProvider(error=RuntimeError("down"))
    orchestrator._providers["gamma-prov"] = FakeProvider(error=RuntimeError("down"))
    result = await orchestrator.deliberate(request)
    assert result.panel.synthesizeable is False
    assert result.label_map == {} and result.judge_overlaps == []


@pytest.mark.parametrize("seed", [None, ""])
async def test_a_missing_seed_is_still_deterministic(seed):
    assert label_map(_delegates(), seed) == label_map(_delegates(), seed)
