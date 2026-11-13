"""P1-7: provider errors are classified, only some are retried, and a fallback keeps the trail."""

from __future__ import annotations

import httpx
import pytest

from conclave.models import DeliberationRequest, DelegateRequest, DelegateStatus, PanelRequest
from conclave.orchestrator import Orchestrator
from conclave.providers.base import RETRYABLE_KINDS, ProviderError
from conclave.providers.fake import FakeProvider
from conclave.providers.openai_compatible import OpenAICompatibleProvider

GOOD = {"choices": [{"message": {"content": "an answer"}}], "model": "m"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fake_sleep(delay):
        pass

    monkeypatch.setattr("conclave.providers.openai_compatible.asyncio.sleep", fake_sleep)


def _provider(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        base_url="https://p.example/v1", model="m", client=client, **kwargs
    )


async def _fail(handler, **kwargs) -> ProviderError:
    provider = _provider(handler, **kwargs)
    with pytest.raises(ProviderError) as info:
        await provider.ask("hi")
    return info.value


class Counter:
    """A handler that replies with each response in turn and counts the requests it received."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = 0

    async def __call__(self, request):
        self.requests += 1
        item = self.responses[min(self.requests, len(self.responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize(
    "response,kind",
    [
        (httpx.Response(401, text="bad key"), "auth"),
        (httpx.Response(403, text="forbidden"), "auth"),
        (httpx.Response(429, text='{"error":{"code":"insufficient_quota"}}'), "quota"),
        (httpx.Response(429, text="You exceeded your current quota"), "quota"),
        (httpx.Response(429, text="Billing hard limit reached"), "quota"),
        (httpx.Response(429, text="slow down", headers={"Retry-After": "61"}), "quota"),
        (httpx.Response(429, text="slow down", headers={"Retry-After": "60"}), "rate_limit"),
        (httpx.Response(429, text="slow down", headers={"Retry-After": "2"}), "rate_limit"),
        (httpx.Response(429, text="slow down"), "rate_limit"),
        (httpx.Response(502), "capacity"),
        (httpx.Response(503), "capacity"),
        (httpx.Response(504), "capacity"),
        (httpx.Response(400, text="bad"), "bad_request"),
        (httpx.Response(404, text="no such model"), "bad_request"),
        (httpx.Response(422, text="bad"), "bad_request"),
        (httpx.Response(500, text="oops"), "server_error"),
        (httpx.Response(501), "server_error"),
    ],
)
async def test_http_errors_are_classified(response, kind):
    handler = Counter(response)
    error = await _fail(handler, transient_max_retries=0)
    assert error.kind == kind and error.status_code == response.status_code


async def test_a_retry_after_date_far_in_the_future_is_a_quota():
    from email.utils import format_datetime
    from datetime import datetime, timedelta, timezone

    when = format_datetime(datetime.now(timezone.utc) + timedelta(hours=2), usegmt=True)
    error = await _fail(Counter(httpx.Response(429, headers={"Retry-After": when})), transient_max_retries=0)
    assert error.kind == "quota"


@pytest.mark.parametrize("failure", ["invalid_json", "missing_content", "non_text"])
async def test_unusable_replies_are_malformed(failure):
    reply = {
        "invalid_json": httpx.Response(200, text="not json"),
        "missing_content": httpx.Response(200, json={"choices": []}),
        "non_text": httpx.Response(200, json={"choices": [{"message": {"content": 5}}]}),
    }[failure]
    assert (await _fail(Counter(reply))).kind == "malformed"


async def test_a_transport_failure_is_transport():
    error = await _fail(Counter(httpx.ReadError("connection reset")))
    assert error.kind == "transport" and error.attempts == 1


# ------------------------------------------------------------------------------- retries


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="bad key"),
        httpx.Response(403, text="no"),
        httpx.Response(429, text="insufficient_quota"),
        httpx.Response(429, text="x", headers={"Retry-After": "120"}),
        httpx.Response(400, text="bad"),
        httpx.Response(404, text="x"),
        httpx.Response(500, text="x"),
    ],
)
async def test_errors_that_cannot_succeed_on_a_repeat_make_one_request(response):
    handler = Counter(response)
    error = await _fail(handler, transient_max_retries=5)
    assert handler.requests == 1 and error.attempts == 1


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_rate_limit_and_capacity_are_retried_to_the_limit(status):
    handler = Counter(httpx.Response(status, text="busy"))
    error = await _fail(handler, transient_max_retries=2)
    assert handler.requests == 3 and error.attempts == 3


async def test_a_rate_limit_then_success_makes_two_requests():
    handler = Counter(httpx.Response(429, text="busy"), httpx.Response(200, json=GOOD))
    response = await _provider(handler).ask("hi")
    assert handler.requests == 2 and response.attempts == 2 and response.text == "an answer"


async def test_a_refused_connection_is_retried_then_succeeds():
    handler = Counter(httpx.ConnectError("refused"), httpx.Response(200, json=GOOD))
    response = await _provider(handler).ask("hi")
    assert handler.requests == 2 and response.attempts == 2


async def test_a_refused_connection_gives_up_after_the_retries():
    handler = Counter(httpx.ConnectError("refused"))
    error = await _fail(handler, transient_max_retries=2)
    assert handler.requests == 3 and error.attempts == 3 and error.kind == "transport"
    assert "refused" in str(error)


async def test_a_refused_connection_with_no_retries_allowed_makes_one_request():
    handler = Counter(httpx.ConnectError("refused"))
    error = await _fail(handler, transient_max_retries=0)
    assert handler.requests == 1 and error.attempts == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadError("reset"), httpx.WriteError("x"), httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.RemoteProtocolError("p")],
)
async def test_other_transport_failures_are_never_replayed(failure):
    handler = Counter(failure)
    error = await _fail(handler, transient_max_retries=5)
    assert handler.requests == 1 and error.kind == "transport"


async def test_only_these_kinds_are_retried():
    assert RETRYABLE_KINDS == {"rate_limit", "capacity"}


async def test_backoff_applies_to_connection_retries(monkeypatch):
    sleeps = []

    async def record(delay):
        sleeps.append(delay)

    monkeypatch.setattr("conclave.providers.openai_compatible.asyncio.sleep", record)
    await _fail(Counter(httpx.ConnectError("refused")), transient_max_retries=2, retry_backoff_seconds=0.5)
    assert sleeps == [0.5, 1.0]


# ---------------------------------------------------------------- the kind reaches the result


async def _panel(provider):
    result = await Orchestrator({"one": provider}).run_panel(
        PanelRequest(question="q", delegates=[DelegateRequest(name="one", prompt="hi")])
    )
    return result.delegates[0]


async def test_the_error_kind_is_stored_on_the_delegate_result():
    for response, kind in ((httpx.Response(401, text="no"), "auth"), (httpx.Response(429, text="quota"), "quota")):
        delegate = await _panel(_provider(Counter(response)))
        assert delegate.status == DelegateStatus.FAILED and delegate.error_kind == kind
        assert delegate.attempts == 1


async def test_a_timeout_and_an_unclassified_error_have_kinds_too():
    slow = Hanging()
    result = await Orchestrator({"one": slow}).run_panel(
        PanelRequest(question="q", delegates=[DelegateRequest(name="one", prompt="hi", timeout_seconds=0.01)])
    )
    assert result.delegates[0].status == DelegateStatus.TIMED_OUT and result.delegates[0].error_kind == "timeout"
    plain = await _panel(FakeProvider(error=RuntimeError("boom")))
    assert plain.error_kind is None  # not a provider error, so no provider kind is invented


async def test_an_empty_reply_keeps_its_own_kind():
    delegate = await _panel(FakeProvider("   "))
    assert delegate.error_kind == "empty_response"


# ------------------------------------------------------------------------- the fallback trail


def _request():
    return DeliberationRequest(
        question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter",
        arbiter_fallbacks=["arbiter-fb"], critic_fallbacks=["critic-fb"], minimum_successes=1,
    )


def _orchestrator(**overrides):
    providers = {
        "a": FakeProvider("answer one " + "w" * 30, model="m-a"),
        "b": FakeProvider("answer two " + "v" * 30, model="m-b"),
        "critic": FakeProvider("crit"),
        "critic-fb": FakeProvider("crit fallback"),
        "arbiter": FakeProvider("final"),
        "arbiter-fb": FakeProvider("final fallback"),
    }
    providers.update(overrides)
    from conclave.sources import ProviderIdentity

    identities = {n: ProviderIdentity(base_url=f"https://{n}.example/v1", model=f"m-{n}") for n in "ab"}
    return Orchestrator(providers, identities)


class Hanging:
    """Never answers. (FakeProvider's delay uses asyncio.sleep, which these tests silence.)"""

    async def ask(self, prompt):
        import asyncio

        await asyncio.Event().wait()


class Failing:
    def __init__(self, error):
        self.error = error

    async def ask(self, prompt):
        raise self.error


async def test_a_fallback_keeps_the_primarys_failure_as_a_prior_attempt():
    primary = _provider(Counter(httpx.Response(401, text="bad key")), transient_max_retries=0)
    result = await _orchestrator(arbiter=primary).deliberate(_request())
    assert result.arbiter.name == "arbiter-fb" and result.arbiter.status == DelegateStatus.SUCCEEDED
    [prior] = result.arbiter.prior_attempts
    assert (prior.name, prior.status, prior.error_kind, prior.attempts) == ("arbiter", DelegateStatus.FAILED, "auth", 1)
    assert prior.latency_ms is not None
    # The Critic did not fail, so it has no trail.
    assert result.critic.prior_attempts == []


async def test_the_trail_lists_every_earlier_failure_in_order():
    first = _provider(Counter(httpx.Response(503, text="busy")), transient_max_retries=1)
    second = Failing(ProviderError("quota out", kind="quota", attempts=1))
    result = await _orchestrator(critic=first, **{"critic-fb": second}).deliberate(_request())
    assert result.critic.status == DelegateStatus.FAILED  # every provider failed
    assert [(p.name, p.error_kind, p.attempts) for p in result.critic.prior_attempts] == [("critic", "capacity", 2)]
    assert result.critic.name == "critic-fb" and result.critic.error_kind == "quota"


async def test_a_timed_out_primary_is_in_the_trail():
    slow = Hanging()
    request = _request().model_copy(update={"arbiter_timeout_seconds": 0.02})
    result = await _orchestrator(arbiter=slow).deliberate(request)
    [prior] = result.arbiter.prior_attempts
    assert (prior.status, prior.error_kind) == (DelegateStatus.TIMED_OUT, "timeout")


async def test_a_primary_that_succeeds_has_no_trail():
    result = await _orchestrator().deliberate(_request())
    assert result.arbiter.prior_attempts == [] and result.critic.prior_attempts == []
    assert all(d.prior_attempts == [] for d in result.panel.delegates)


async def test_the_trail_survives_storage_and_reload():
    from conclave.models import DeliberationResult

    primary = _provider(Counter(httpx.Response(401, text="bad key")), transient_max_retries=0)
    result = await _orchestrator(arbiter=primary).deliberate(_request())
    again = DeliberationResult.model_validate_json(result.model_dump_json())
    assert again.arbiter.prior_attempts == result.arbiter.prior_attempts


async def test_the_trail_never_reaches_a_judge_prompt():
    primary = _provider(Counter(httpx.Response(401, text="bad key")), transient_max_retries=0)
    result = await _orchestrator(critic=primary).deliberate(_request())
    for text in (result.arbiter.prompt,):
        assert "401" not in text and "bad key" not in text and "critic-fb" not in text


async def test_old_results_without_the_new_fields_still_load():
    from conclave.models import DelegateResult

    loaded = DelegateResult.model_validate({"name": "x", "status": "failed"})
    assert loaded.prior_attempts == [] and loaded.error_kind is None


async def test_a_timeout_the_provider_raised_itself_is_a_failure_not_our_deadline():
    delegate = await _panel(Failing(TimeoutError("upstream gateway timed out")))
    assert delegate.status == DelegateStatus.FAILED
    assert delegate.error_kind is None and "upstream gateway timed out" in delegate.error


async def test_our_own_deadline_still_times_a_stage_out():
    result = await Orchestrator({"one": Hanging()}).run_panel(
        PanelRequest(question="q", delegates=[DelegateRequest(name="one", prompt="hi", timeout_seconds=0.01)])
    )
    assert result.delegates[0].status == DelegateStatus.TIMED_OUT
    assert result.delegates[0].error == "Timed out after 0.01s"


async def test_the_trail_across_the_retry_endpoints():
    bad = _provider(Counter(httpx.Response(401, text="bad key")), transient_max_retries=0)
    orchestrator = _orchestrator(arbiter=bad)
    request = _request()
    first = await orchestrator.deliberate(request)
    assert [p.name for p in first.arbiter.prior_attempts] == ["arbiter"]

    # Retrying the Critic re-runs the Arbiter too, with a fresh trail (the primary fails again).
    orchestrator._providers["arbiter"] = _provider(
        Counter(httpx.Response(401, text="bad key")), transient_max_retries=0
    )
    critic = await orchestrator.retry_critic(request=request, prior_result=first)
    assert [(p.name, p.error_kind) for p in critic.arbiter.prior_attempts] == [("arbiter", "auth")]
    assert critic.critic.prior_attempts == []

    # Once the primary Arbiter works, retrying only the Arbiter leaves no trail on it, and keeps
    # the Critic exactly as it was.
    orchestrator._providers["arbiter"] = FakeProvider("final from the primary")
    again = await orchestrator.retry_arbiter(request=request, prior_result=critic)
    assert again.arbiter.name == "arbiter" and again.arbiter.prior_attempts == []
    assert again.critic == critic.critic


async def test_a_critic_trail_is_kept_when_only_the_arbiter_is_retried():
    bad = _provider(Counter(httpx.Response(503, text="busy")), transient_max_retries=0)
    orchestrator = _orchestrator(critic=bad)
    request = _request()
    first = await orchestrator.deliberate(request)
    assert [p.error_kind for p in first.critic.prior_attempts] == ["capacity"]
    again = await orchestrator.retry_arbiter(request=request, prior_result=first)
    assert again.critic.prior_attempts == first.critic.prior_attempts
    assert again.critic.name == "critic-fb"


async def test_a_delegate_retry_rebuilds_the_judges_trails():
    orchestrator = _orchestrator(a=FakeProvider(error=RuntimeError("down")))
    request = _request().model_copy(update={"minimum_successes": 1})
    first = await orchestrator.deliberate(request)
    assert first.panel.delegates[0].status == DelegateStatus.FAILED
    orchestrator._providers["a"] = FakeProvider("answer one now " + "w" * 30, model="m-a")
    retried = await orchestrator.retry_delegate(request=request, prior_result=first, delegate_name="a")
    assert retried.panel.delegates[0].status == DelegateStatus.SUCCEEDED
    assert retried.arbiter.prior_attempts == []


async def test_content_given_as_a_list_of_text_parts_is_the_answer():
    reply = httpx.Response(200, json={"choices": [{"message": {"content": [{"type": "text", "text": "Hello "}, {"type": "text", "text": "there"}]}}]})
    assert (await _provider(Counter(reply)).ask("hi")).text == "Hello there"


async def test_a_null_answer_that_ran_out_of_budget_says_so():
    reply = httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": None, "reasoning": "thinking..."}}]})
    error = await _fail(Counter(reply))
    assert error.kind == "malformed" and "max_output_tokens" in str(error) and "thinking..." not in str(error)
    plain = await _fail(Counter(httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": None}}]})))
    assert "no text answer" in str(plain) and "max_output_tokens" not in str(plain)
