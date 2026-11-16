from conclave.models import DelegateRequest, DelegateStatus, PanelRequest
from conclave.orchestrator import Orchestrator
from conclave.providers.fake import FakeProvider


async def test_panel_preserves_partial_success():
    orchestrator = Orchestrator(
        {
            "good": FakeProvider(
                "useful answer",
                model="good-model",
                usage={"total_tokens": 12},
            ),
            "bad": FakeProvider(error=RuntimeError("provider exploded")),
        }
    )

    result = await orchestrator.run_panel(
        PanelRequest(
            question="Should one failed delegate kill the run?",
            delegates=[
                DelegateRequest(name="good", prompt="answer"),
                DelegateRequest(name="bad", prompt="answer"),
            ],
            minimum_successes=1,
        )
    )

    assert result.successful_count == 1
    assert result.failed_count == 1
    assert result.synthesizeable is True
    assert result.delegates[0].status == DelegateStatus.SUCCEEDED
    assert result.delegates[0].raw_response == "useful answer"
    assert result.delegates[0].model == "good-model"
    assert result.delegates[0].usage["total_tokens"] == 12
    assert result.delegates[1].status == DelegateStatus.FAILED


async def test_delegate_timeout_does_not_cancel_other_delegate():
    orchestrator = Orchestrator(
        {
            "slow": FakeProvider("late", delay_seconds=0.05),
            "fast": FakeProvider("fast"),
        }
    )

    result = await orchestrator.run_panel(
        PanelRequest(
            question="timeout test",
            delegates=[
                DelegateRequest(name="slow", prompt="answer", timeout_seconds=0.001),
                DelegateRequest(name="fast", prompt="answer", timeout_seconds=1),
            ],
            minimum_successes=1,
        )
    )

    statuses = {item.name: item.status for item in result.delegates}
    assert statuses["slow"] == DelegateStatus.TIMED_OUT
    assert statuses["fast"] == DelegateStatus.SUCCEEDED
    assert result.synthesizeable is True


async def test_panel_can_require_more_successes():
    orchestrator = Orchestrator(
        {
            "good": FakeProvider("answer"),
            "bad": FakeProvider(error=RuntimeError("nope")),
        }
    )

    result = await orchestrator.run_panel(
        PanelRequest(
            question="strict quorum",
            delegates=[
                DelegateRequest(name="good", prompt="answer"),
                DelegateRequest(name="bad", prompt="answer"),
            ],
            minimum_successes=2,
        )
    )

    assert result.synthesizeable is False


def test_provider_names_are_sorted():
    orchestrator = Orchestrator(
        {
            "zeta": FakeProvider(),
            "alpha": FakeProvider(),
        }
    )
    assert orchestrator.provider_names == ["alpha", "zeta"]


async def test_failed_critic_does_not_block_arbiter():
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "delegate": FakeProvider("delegate answer"),
            "second": FakeProvider("second answer"),
            "critic": FakeProvider(error=RuntimeError("critic unavailable")),
            "arbiter": FakeProvider("final synthesis"),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="test",
            delegates=["delegate", "second"],
            critic="critic",
            arbiter="arbiter",
        )
    )

    assert result.panel.synthesizeable is True
    assert result.critic is not None
    assert result.critic.status == DelegateStatus.FAILED
    assert result.arbiter is not None
    assert result.arbiter.status == DelegateStatus.SUCCEEDED
    assert result.arbiter.raw_response == "final synthesis"


async def test_retry_delegate_preserves_other_panel_results():
    from conclave.models import DeliberationRequest, DeliberationResult, DelegateResult, PanelResult
    from conclave.providers.base import Provider, ProviderResponse

    class CountingProvider(Provider):
        def __init__(self, responses: list[str]):
            self.responses = list(responses)
            self.calls = 0

        async def ask(self, prompt: str) -> ProviderResponse:
            self.calls += 1
            return ProviderResponse(text=self.responses.pop(0), model="counting")

    target = CountingProvider(["retried answer"])
    untouched = CountingProvider(["should never be called"])
    critic = CountingProvider(["critic rerun"])
    arbiter = CountingProvider(["arbiter rerun"])
    orchestrator = Orchestrator(
        {
            "target": target,
            "untouched": untouched,
            "critic": critic,
            "arbiter": arbiter,
        }
    )

    request = DeliberationRequest(
        question="Retry test",
        delegates=["target", "untouched"],
        critic="critic",
        arbiter="arbiter",
        minimum_successes=1,
    )
    prior = DeliberationResult(
        panel=PanelResult(
            question="Retry test",
            delegates=[
                DelegateResult(
                    name="target",
                    status=DelegateStatus.FAILED,
                    error="temporary failure",
                ),
                DelegateResult(
                    name="untouched",
                    status=DelegateStatus.SUCCEEDED,
                    raw_response="keep this response",
                    model="original",
                ),
            ],
            successful_count=1,
            failed_count=1,
            synthesizeable=True,
        )
    )

    result = await orchestrator.retry_delegate(
        request=request,
        prior_result=prior,
        delegate_name="target",
    )

    by_name = {item.name: item for item in result.panel.delegates}
    assert by_name["target"].raw_response == "retried answer"
    assert by_name["untouched"].raw_response == "keep this response"
    assert target.calls == 1
    assert untouched.calls == 0
    assert critic.calls == 1
    assert arbiter.calls == 1


async def test_deliberation_sums_available_cost_estimates():
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "delegate": FakeProvider("answer", estimated_cost_usd=0.01),
            "second": FakeProvider("answer two", estimated_cost_usd=0.01),
            "critic": FakeProvider("critique", estimated_cost_usd=0.02),
            "arbiter": FakeProvider("final", estimated_cost_usd=0.03),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="cost test",
            delegates=["delegate", "second"],
            critic="critic",
            arbiter="arbiter",
        )
    )

    assert result.estimated_cost_usd == 0.07
    assert result.panel.delegates[0].estimated_cost_usd == 0.01


async def test_delegate_result_preserves_exact_prompt():
    orchestrator = Orchestrator({"one": FakeProvider("answer")})
    prompt = "EXACT PROMPT FOR INSPECTION"

    result = await orchestrator.run_panel(
        PanelRequest(
            question="prompt visibility",
            delegates=[DelegateRequest(name="one", prompt=prompt)],
            minimum_successes=1,
        )
    )

    assert result.delegates[0].prompt == prompt


async def test_retry_critic_preserves_panel_and_refreshes_arbiter():
    from conclave.models import DeliberationRequest, DeliberationResult, DelegateResult, PanelResult

    orchestrator = Orchestrator(
        {
            "critic": FakeProvider("new critique"),
            "arbiter": FakeProvider("new final"),
        }
    )
    request = DeliberationRequest(
        question="retry critic",
        delegates=["delegate", "second"],
        critic="critic",
        arbiter="arbiter",
    )
    prior = DeliberationResult(
        panel=PanelResult(
            question="retry critic",
            delegates=[
                DelegateResult(
                    name="delegate",
                    status=DelegateStatus.SUCCEEDED,
                    prompt="delegate prompt",
                    raw_response="delegate answer",
                ),
                DelegateResult(
                    name="second",
                    status=DelegateStatus.SUCCEEDED,
                    prompt="delegate prompt",
                    raw_response="second answer",
                ),
            ],
            successful_count=2,
            failed_count=0,
            synthesizeable=True,
        ),
        critic=DelegateResult(
            name="critic",
            status=DelegateStatus.FAILED,
            prompt="old critic prompt",
            error="temporary failure",
        ),
    )

    result = await orchestrator.retry_critic(
        request=request,
        prior_result=prior,
    )

    assert result.panel.delegates[0].raw_response == "delegate answer"
    assert result.critic is not None
    assert result.critic.status == DelegateStatus.SUCCEEDED
    assert result.critic.raw_response == "new critique"
    assert result.arbiter is not None
    assert result.arbiter.raw_response == "new final"


async def test_retry_arbiter_preserves_panel_and_critic():
    from conclave.models import DeliberationRequest, DeliberationResult, DelegateResult, PanelResult

    orchestrator = Orchestrator({"arbiter": FakeProvider("new final")})
    request = DeliberationRequest(
        question="retry arbiter",
        delegates=["delegate", "second"],
        critic="critic",
        arbiter="arbiter",
    )
    critic = DelegateResult(
        name="critic",
        status=DelegateStatus.SUCCEEDED,
        raw_response="keep critique",
    )
    prior = DeliberationResult(
        panel=PanelResult(
            question="retry arbiter",
            delegates=[
                DelegateResult(
                    name="delegate",
                    status=DelegateStatus.SUCCEEDED,
                    raw_response="keep delegate",
                ),
                DelegateResult(
                    name="second",
                    status=DelegateStatus.SUCCEEDED,
                    raw_response="keep second",
                ),
            ],
            successful_count=2,
            failed_count=0,
            synthesizeable=True,
        ),
        critic=critic,
        arbiter=DelegateResult(
            name="arbiter",
            status=DelegateStatus.FAILED,
            error="temporary failure",
        ),
    )

    result = await orchestrator.retry_arbiter(
        request=request,
        prior_result=prior,
    )

    assert result.panel.delegates[0].raw_response == "keep delegate"
    assert result.critic is critic
    assert result.arbiter is not None
    assert result.arbiter.raw_response == "new final"


async def test_critic_and_arbiter_fallbacks_are_used():
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "delegate": FakeProvider("delegate answer"),
            "second": FakeProvider("second answer"),
            "critic-primary": FakeProvider(error=RuntimeError("critic down")),
            "critic-fallback": FakeProvider("fallback critique"),
            "arbiter-primary": FakeProvider(error=RuntimeError("arbiter down")),
            "arbiter-fallback": FakeProvider("fallback final"),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="fallback test",
            delegates=["delegate", "second"],
            critic="critic-primary",
            critic_fallbacks=["critic-fallback"],
            arbiter="arbiter-primary",
            arbiter_fallbacks=["arbiter-fallback"],
        )
    )

    assert result.critic is not None
    assert result.critic.name == "critic-fallback"
    assert result.critic.status == DelegateStatus.SUCCEEDED
    assert result.critic.raw_response == "fallback critique"
    assert result.arbiter is not None
    assert result.arbiter.name == "arbiter-fallback"
    assert result.arbiter.status == DelegateStatus.SUCCEEDED
    assert result.arbiter.raw_response == "fallback final"


async def test_on_stage_reports_panel_critic_then_arbiter():
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "a": FakeProvider("A"),
            "b": FakeProvider("B"),
            "critic": FakeProvider("C"),
            "arbiter": FakeProvider("Z"),
        }
    )
    seen = []

    async def on_stage(result):
        seen.append((result.critic is not None, result.arbiter is not None))

    request = DeliberationRequest(
        question="q",
        delegates=["a", "b"],
        critic="critic",
        arbiter="arbiter",
        minimum_successes=2,
    )
    final = await orchestrator.deliberate(request, on_stage=on_stage)
    assert seen == [(False, False), (True, False), (True, True)]
    assert final.arbiter is not None


async def test_on_stage_without_critic_and_on_quorum_failure():
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "a": FakeProvider("A"),
            "bad": FakeProvider("", error=RuntimeError("boom")),
            "arbiter": FakeProvider("Z"),
        }
    )
    seen = []

    async def on_stage(result):
        seen.append(result.arbiter is not None)

    no_critic = DeliberationRequest(
        question="q",
        delegates=["a"],
        arbiter="arbiter",
        minimum_successes=1,
        single_source_mode="arbiter_single_source",
    )
    await orchestrator.deliberate(no_critic, on_stage=on_stage)
    assert seen == [False, True]

    seen.clear()
    short = DeliberationRequest(
        question="q", delegates=["a", "bad"], arbiter="arbiter", minimum_successes=2
    )
    result = await orchestrator.deliberate(short, on_stage=on_stage)
    assert seen == [False]
    assert result.arbiter is None


# --- honest counting (P0-6) ---


class CountingProvider(FakeProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    async def ask(self, prompt):
        self.calls += 1
        return await super().ask(prompt)


def _identity(model, base_url="https://api.example.com/v1", alias=False):
    from conclave.sources import ProviderIdentity

    return ProviderIdentity(base_url=base_url, model=model, router_alias=alias)


def _request(delegates, minimum=2):
    from conclave.models import DeliberationRequest

    return DeliberationRequest(
        question="q",
        delegates=delegates,
        critic="critic",
        arbiter="arbiter",
        minimum_successes=minimum,
    )


async def test_empty_and_whitespace_answers_are_failures_and_never_count():
    critic, arbiter = CountingProvider("c"), CountingProvider("z")
    orchestrator = Orchestrator(
        {"a": FakeProvider(""), "b": FakeProvider("  \n\t "), "critic": critic, "arbiter": arbiter}
    )
    result = await orchestrator.deliberate(_request(["a", "b"]))
    assert [d.status for d in result.panel.delegates] == [DelegateStatus.FAILED] * 2
    assert {d.error_kind for d in result.panel.delegates} == {"empty_response"}
    assert result.panel.successful_count == 0
    assert result.panel.synthesizeable is False
    assert result.critic is None and result.arbiter is None
    assert critic.calls == 0 and arbiter.calls == 0


async def test_two_delegates_of_one_source_do_not_meet_quorum_two():
    critic, arbiter = CountingProvider("c"), CountingProvider("z")
    orchestrator = Orchestrator(
        {
            "a": FakeProvider("answer one", model="m1"),
            "b": FakeProvider("answer two", model="m1"),
            "critic": critic,
            "arbiter": arbiter,
        },
        {"a": _identity("m1"), "b": _identity("m1")},
    )
    result = await orchestrator.deliberate(_request(["a", "b"]))
    assert result.panel.successful_count == 2
    assert result.panel.independent_source_count == 1
    assert result.panel.synthesizeable is False
    assert [g.delegates for g in result.panel.sources] == [["a", "b"]]
    assert critic.calls == 0 and arbiter.calls == 0


async def test_different_models_are_two_sources_and_judges_are_told_which_share_one():
    orchestrator = Orchestrator(
        {
            "a": FakeProvider("one", model="m1"),
            "b": FakeProvider("two", model="m2"),
            "c": FakeProvider("three", model="m1"),
            "critic": FakeProvider("crit"),
            "arbiter": FakeProvider("final"),
        },
        {"a": _identity("m1"), "b": _identity("m2"), "c": _identity("m1")},
    )
    result = await orchestrator.deliberate(_request(["a", "b", "c"]))
    assert result.panel.independent_source_count == 2
    assert result.panel.synthesizeable is True
    # Labels are a seeded permutation, so find which two labels a and c were given.
    by_name = {name: label for label, name in result.label_map.items()}
    first, second = sorted([by_name["a"], by_name["c"]])
    for prompt in (result.critic.prompt, result.arbiter.prompt):
        assert f"Responses {first} and {second} come from the same underlying source" in prompt
        assert "not independent corroboration" in prompt


async def test_reported_model_names_that_normalize_equal_are_one_source():
    orchestrator = Orchestrator(
        {
            "a": FakeProvider("one", model="openai/gpt-x"),
            "b": FakeProvider("two", model="gpt-x-2026-08-06"),
        },
        {
            "a": _identity("gpt-x", "https://api.one.com/v1"),
            "b": _identity("gpt-x-latest", "https://api.two.com/v1"),
        },
    )
    panel = await orchestrator.run_panel(
        PanelRequest(
            question="q",
            delegates=[DelegateRequest(name="a", prompt="p"), DelegateRequest(name="b", prompt="p")],
            minimum_successes=2,
        )
    )
    assert panel.independent_source_count == 1
    assert panel.sources[0].reason == "same_reported_model"
    assert panel.synthesizeable is False


async def test_retrying_a_delegate_recounts_sources():
    from conclave.models import DeliberationResult

    orchestrator = Orchestrator(
        {
            "a": FakeProvider("one", model="m1"),
            "b": FakeProvider("two", model="m2"),
            "critic": FakeProvider("crit"),
            "arbiter": FakeProvider("final"),
        },
        {"a": _identity("m1"), "b": _identity("m2")},
    )
    request = _request(["a", "b"])
    first = await orchestrator.deliberate(request)
    assert first.panel.independent_source_count == 2

    # b is replaced by a provider that now serves the same model as a.
    orchestrator._providers["b"] = FakeProvider("two again", model="m1")
    orchestrator._identities["b"] = _identity("m1")
    retried = await orchestrator.retry_delegate(
        request=request, prior_result=DeliberationResult(**first.model_dump()), delegate_name="b"
    )
    assert retried.panel.independent_source_count == 1
    assert retried.panel.synthesizeable is False
    assert retried.arbiter is None


async def _chain(shared: bool):
    from conclave.models import DeliberationRequest

    orchestrator = Orchestrator(
        {
            "d": FakeProvider("answer"),
            "arb1": FakeProvider("slow", delay_seconds=0.3),
            "arb2": FakeProvider("slower", delay_seconds=0.3),
            "arb3": FakeProvider("final"),
        }
    )
    request = DeliberationRequest(
        question="q",
        delegates=["d"],
        arbiter="arb1",
        arbiter_fallbacks=["arb2", "arb3"],
        arbiter_timeout_seconds=0.2,
        single_source_mode="arbiter_single_source",
        shared_stage_deadline=shared,
    )
    return await orchestrator.deliberate(request)


async def test_each_fallback_gets_a_full_timeout_by_default():
    result = await _chain(False)
    assert result.arbiter.name == "arb3"
    assert [a.name for a in result.arbiter.prior_attempts] == ["arb1", "arb2"]


async def test_a_shared_stage_deadline_stops_the_chain_when_the_budget_is_spent():
    result = await _chain(True)
    # arb1 consumes the whole 0.2s budget, so no fallback gets to start.
    assert result.arbiter.name == "arb1"
    assert result.arbiter.status == DelegateStatus.TIMED_OUT
    assert result.arbiter.prior_attempts == []
