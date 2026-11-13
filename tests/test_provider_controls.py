"""P1-8: optional output length, temperature and prompt-size controls."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from conclave.config import ProviderConfig
from conclave.models import DeliberationRequest, DelegateStatus
from conclave.orchestrator import Orchestrator
from conclave.providers.base import ProviderError
from conclave.providers.factory import build_providers
from conclave.providers.fake import FakeProvider
from conclave.providers.openai_compatible import OpenAICompatibleProvider

GOOD = {"choices": [{"message": {"content": "an answer"}}], "model": "m"}


class Recorder:
    def __init__(self):
        self.payloads = []

    async def __call__(self, request):
        self.payloads.append(json.loads(request.content))
        return httpx.Response(200, json=GOOD)


def _provider(recorder, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return OpenAICompatibleProvider(base_url="https://p.example/v1", model="m", client=client, **kwargs)


# ------------------------------------------------------------------------------ the payload


async def test_nothing_extra_is_sent_when_nothing_is_configured():
    recorder = Recorder()
    await _provider(recorder).ask("hi")
    assert set(recorder.payloads[0]) == {"model", "messages"}


async def test_max_tokens_is_sent_only_when_configured():
    recorder = Recorder()
    await _provider(recorder, max_output_tokens=300).ask("hi")
    payload = recorder.payloads[0]
    assert payload["max_tokens"] == 300 and "temperature" not in payload


async def test_temperature_is_sent_only_when_configured():
    recorder = Recorder()
    await _provider(recorder, temperature=0.2).ask("hi")
    payload = recorder.payloads[0]
    assert payload["temperature"] == 0.2 and "max_tokens" not in payload


async def test_a_temperature_of_zero_is_still_sent():
    recorder = Recorder()
    await _provider(recorder, temperature=0).ask("hi")
    assert recorder.payloads[0]["temperature"] == 0


async def test_both_controls_together_and_the_rest_of_the_payload_is_unchanged():
    recorder = Recorder()
    await _provider(recorder, max_output_tokens=50, temperature=1.0, system_prompt="sys").ask("hi")
    payload = recorder.payloads[0]
    assert payload == {
        "model": "m",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        "max_tokens": 50,
        "temperature": 1.0,
    }


# -------------------------------------------------------------------------------- prompt size


async def test_a_prompt_over_the_limit_sends_no_request():
    recorder = Recorder()
    provider = _provider(recorder, max_prompt_chars=10)
    with pytest.raises(ProviderError) as info:
        await provider.ask("x" * 11)
    assert recorder.payloads == []
    assert info.value.kind == "prompt_too_large" and info.value.attempts == 1
    assert "11 characters" in str(info.value) and "max_prompt_chars of 10" in str(info.value)


async def test_a_prompt_at_the_limit_is_sent():
    recorder = Recorder()
    await _provider(recorder, max_prompt_chars=10).ask("x" * 10)
    assert len(recorder.payloads) == 1


async def test_the_system_prompt_counts_toward_the_limit():
    recorder = Recorder()
    provider = _provider(recorder, max_prompt_chars=10, system_prompt="s" * 6)
    with pytest.raises(ProviderError):
        await provider.ask("x" * 5)
    assert recorder.payloads == []
    await provider.ask("x" * 4)
    assert len(recorder.payloads) == 1


async def test_the_limit_is_not_retried():
    recorder = Recorder()
    provider = _provider(recorder, max_prompt_chars=1, transient_max_retries=5)
    with pytest.raises(ProviderError):
        await provider.ask("long")
    assert recorder.payloads == []


def _orchestrator(primary, fallback=None):
    providers = {
        "a": FakeProvider("answer one " + "w" * 30, model="m-a"),
        "b": FakeProvider("answer two " + "v" * 30, model="m-b"),
        "critic": FakeProvider("crit"),
        "arbiter": primary,
        "arbiter-fb": fallback or FakeProvider("final from the fallback"),
    }
    return Orchestrator(providers)


async def test_an_oversized_judge_prompt_sends_nothing_and_tries_the_fallback():
    recorder = Recorder()
    primary = _provider(recorder, max_prompt_chars=50)
    request = DeliberationRequest(
        question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter",
        arbiter_fallbacks=["arbiter-fb"], minimum_successes=2,
    )
    result = await _orchestrator(primary).deliberate(request)
    assert recorder.payloads == []  # the primary never received the prompt
    assert result.arbiter.name == "arbiter-fb" and result.arbiter.status == DelegateStatus.SUCCEEDED
    [prior] = result.arbiter.prior_attempts
    assert (prior.name, prior.error_kind) == ("arbiter", "prompt_too_large")


async def test_when_every_judge_is_too_small_the_stage_fails_clearly():
    recorder = Recorder()
    request = DeliberationRequest(
        question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter",
        arbiter_fallbacks=["arbiter-fb"], minimum_successes=2,
    )
    orchestrator = _orchestrator(_provider(recorder, max_prompt_chars=50), _provider(recorder, max_prompt_chars=60))
    result = await orchestrator.deliberate(request)
    assert recorder.payloads == []
    assert result.arbiter.status == DelegateStatus.FAILED
    assert result.arbiter.error_kind == "prompt_too_large"
    assert "not sent" in result.arbiter.error


async def test_a_provider_with_a_limit_never_receives_a_longer_prompt():
    recorder = Recorder()
    limit = 400
    provider = _provider(recorder, max_prompt_chars=limit)
    for size in (1, 399, 400, 401, 5000):
        try:
            await provider.ask("x" * size)
        except ProviderError:
            pass
    sent = [sum(len(m["content"]) for m in payload["messages"]) for payload in recorder.payloads]
    assert sent == [1, 399, 400] and max(sent) <= limit


# ------------------------------------------------------------------------------------ config


def test_the_controls_are_optional_and_default_to_unset():
    config = ProviderConfig(name="p", base_url="https://x/v1", model="m")
    assert (config.max_output_tokens, config.temperature, config.max_prompt_chars) == (None, None, None)


@pytest.mark.parametrize(
    "field,value",
    [("max_output_tokens", 0), ("max_output_tokens", -5), ("temperature", -0.1), ("temperature", 2.1), ("max_prompt_chars", 0)],
)
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ProviderConfig(name="p", base_url="https://x/v1", model="m", **{field: value})


def test_the_factory_passes_the_controls_to_the_adapter(monkeypatch):
    monkeypatch.setenv("P_KEY", "k")
    config = ProviderConfig(
        name="p", base_url="https://x/v1", model="m", api_key_env="P_KEY",
        max_output_tokens=123, temperature=0.4, max_prompt_chars=999,
    )
    provider = build_providers([config])["p"]
    assert (provider.max_output_tokens, provider.temperature, provider.max_prompt_chars) == (123, 0.4, 999)
    plain = build_providers([ProviderConfig(name="q", base_url="https://x/v1", model="m", api_key_env="P_KEY")])["q"]
    assert (plain.max_output_tokens, plain.temperature, plain.max_prompt_chars) == (None, None, None)


@pytest.mark.parametrize(
    "field,value",
    [("max_output_tokens", True), ("temperature", True), ("max_prompt_chars", True), ("max_output_tokens", "300"), ("max_prompt_chars", 10.5)],
)
def test_booleans_strings_and_fractions_are_not_numbers_here(field, value):
    with pytest.raises(ValidationError):
        ProviderConfig(name="p", base_url="https://x/v1", model="m", **{field: value})


def test_a_whole_number_temperature_from_json_is_accepted():
    assert ProviderConfig.model_validate_json(
        '{"name": "p", "base_url": "https://x/v1", "model": "m", "temperature": 1, "max_output_tokens": 200}'
    ).temperature == 1.0


async def test_an_oversized_connectivity_test_prompt_sends_nothing():
    recorder = Recorder()
    orchestrator = Orchestrator({"tiny": _provider(recorder, max_prompt_chars=5)})
    result = await orchestrator.test_provider("tiny")
    assert recorder.payloads == []
    assert result.status == DelegateStatus.FAILED and result.error_kind == "prompt_too_large"
