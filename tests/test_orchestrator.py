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
            "critic": FakeProvider(error=RuntimeError("critic unavailable")),
            "arbiter": FakeProvider("final synthesis"),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="test",
            delegates=["delegate"],
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
            "critic": FakeProvider("critique", estimated_cost_usd=0.02),
            "arbiter": FakeProvider("final", estimated_cost_usd=0.03),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="cost test",
            delegates=["delegate"],
            critic="critic",
            arbiter="arbiter",
        )
    )

    assert result.estimated_cost_usd == 0.06
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
        delegates=["delegate"],
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
                )
            ],
            successful_count=1,
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
        delegates=["delegate"],
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
                )
            ],
            successful_count=1,
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
            "critic-primary": FakeProvider(error=RuntimeError("critic down")),
            "critic-fallback": FakeProvider("fallback critique"),
            "arbiter-primary": FakeProvider(error=RuntimeError("arbiter down")),
            "arbiter-fallback": FakeProvider("fallback final"),
        }
    )

    result = await orchestrator.deliberate(
        DeliberationRequest(
            question="fallback test",
            delegates=["delegate"],
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
