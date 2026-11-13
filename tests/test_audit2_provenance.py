"""Second audit, findings 4 and 5: immutable provenance, and malformed metadata contained."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from conclave.models import (
    DelegateRequest,
    DelegateStatus,
    DeliberationRequest,
    DeliberationResult,
    PanelRequest,
)
from conclave.orchestrator import Orchestrator
from conclave.providers.base import Provider, ProviderResponse
from conclave.providers.fake import FakeProvider
from conclave.providers.openai_compatible import OpenAICompatibleProvider
from conclave.sources import ProviderIdentity, safe_endpoint

TEXT = {n: f"{n}-answer " + " ".join(f"{n}{i}" for i in range(30)) for n in "abc"}


def identity(model, base=None, **kw):
    return ProviderIdentity(base_url=base or f"https://{model}.example/v1", model=model, **kw)


class Raw(Provider):
    def __init__(self, response):
        self.response = response

    async def ask(self, prompt):
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def request(**kw):
    return DeliberationRequest(
        question="q", delegates=["a", "b", "c"], arbiter="arb", critic="crit",
        minimum_successes=2, seed="s", **kw,
    )


def providers(fail_c=True):
    base = {n: FakeProvider(TEXT[n], model=f"m-{n}") for n in "abc"}
    if fail_c:
        base["c"] = FakeProvider(error=RuntimeError("down"))
    return {**base, "crit": FakeProvider("crit"), "arb": FakeProvider("final")}


def panel_of(orch, *names, minimum=1):
    delegates = [DelegateRequest(name=n, prompt="p") for n in names]
    return asyncio.run(orch.run_panel(PanelRequest(question="q", delegates=delegates, minimum_successes=minimum)))


# ------------------------------------------------------------------ finding 4: provenance


def test_an_answer_records_the_provider_it_came_from_without_any_secret():
    ids = {"a": identity("m-a", "https://user:hunter2@a.example/v1?key=SECRET#x", family="acme"), "b": identity("m-b")}
    result = asyncio.run(Orchestrator(providers(), ids).deliberate(request()))
    prov = {d.name: d.provenance for d in result.panel.delegates}["a"]
    assert (prov.endpoint, prov.configured_model, prov.family, prov.router_alias) == (
        "https://a.example/v1", "m-a", "acme", False,
    )
    dumped = result.model_dump_json()
    assert "hunter2" not in dumped and "SECRET" not in dumped
    assert safe_endpoint("HTTPS://U:p@Host.example:8080/V1/?k=v") == "https://host.example:8080/V1"


def test_changing_the_configuration_later_does_not_reclassify_an_unchanged_answer():
    ids = {"a": identity("m-a", family="one"), "b": identity("m-b", family="two"), "c": identity("m-c")}
    first = asyncio.run(Orchestrator(providers(), ids).deliberate(request()))
    assert first.panel.independent_source_count == 2 and first.panel.distinct_families == 2
    stored = DeliberationResult.model_validate_json(first.model_dump_json())

    # Today's configuration says a and b are the same model and family, and a a router alias.
    changed = {
        "a": identity("same", "https://x.example/v1", family="one", router_alias=True),
        "b": identity("same", "https://x.example/v1", family="one"),
        "c": identity("m-c"),
    }
    later = Orchestrator(providers(fail_c=False), changed)
    retried = asyncio.run(later.retry_delegate(request=request(), prior_result=stored, delegate_name="c"))
    by = {d.name: d for d in retried.panel.delegates}
    assert retried.panel.independent_source_count == 3  # a and b are still two sources; c is a third
    assert by["a"].provenance == stored.panel.delegates[0].provenance  # history is unchanged
    assert by["a"].provenance.router_alias is False and by["a"].provenance.family == "one"
    assert by["c"].provenance.configured_model == "m-c"  # the new answer records the new configuration


def test_without_provenance_an_old_answer_falls_back_to_the_current_configuration():
    ids = {"a": identity("m-a"), "b": identity("m-b"), "c": identity("m-c")}
    first = asyncio.run(Orchestrator(providers(), ids).deliberate(request()))
    legacy = DeliberationResult.model_validate_json(first.model_dump_json())
    for d in legacy.panel.delegates:
        d.provenance = None  # as saved before provenance existed
    same = {"a": identity("same", "https://x/v1"), "b": identity("same", "https://x/v1"), "c": identity("m-c")}
    retried = asyncio.run(
        Orchestrator(providers(fail_c=False), same).retry_delegate(
            request=request(), prior_result=legacy, delegate_name="c"
        )
    )
    assert retried.panel.independent_source_count == 2  # a and b collapse: no provenance protects them


# --------------------------------------------------------- finding 5: malformed metadata

GOOD = "a fine answer " * 5


@pytest.mark.parametrize(
    "response",
    [
        ProviderResponse(text=GOOD, model=5),
        ProviderResponse(text=GOOD, model=["x"]),
        ProviderResponse(text=GOOD, model="m" * 5000),
        ProviderResponse(text=GOOD, usage="oops"),
        ProviderResponse(text=GOOD, usage=[1, 2]),
        ProviderResponse(text=GOOD, estimated_cost_usd="free"),
        ProviderResponse(text=GOOD, estimated_cost_usd=float("nan")),
        ProviderResponse(text=GOOD, estimated_cost_usd=-1),
        ProviderResponse(text=GOOD, attempts=0),
        ProviderResponse(text=GOOD, attempts="three"),
    ],
)
def test_malformed_metadata_never_aborts_a_healthy_panel(response):
    orch = Orchestrator(
        {"bad": Raw(response), "ok": FakeProvider(TEXT["a"], model="m")},
        {"bad": identity("x"), "ok": identity("y")},
    )
    by = {d.name: d for d in panel_of(orch, "bad", "ok").delegates}
    assert by["ok"].status == DelegateStatus.SUCCEEDED
    assert by["bad"].status == DelegateStatus.SUCCEEDED and by["bad"].raw_response  # the answer is kept
    assert by["bad"].model is None or (isinstance(by["bad"].model, str) and len(by["bad"].model) <= 200)
    assert isinstance(by["bad"].usage, dict) and by["bad"].attempts >= 1
    assert by["bad"].estimated_cost_usd is None or by["bad"].estimated_cost_usd >= 0


@pytest.mark.parametrize("text", [None, 5, ["list"], b"bytes"])
def test_a_reply_whose_text_is_not_a_string_is_that_delegates_contained_failure(text):
    orch = Orchestrator({"bad": Raw(ProviderResponse(text=text)), "ok": FakeProvider(TEXT["a"])})
    panel = panel_of(orch, "bad", "ok")
    by = {d.name: d for d in panel.delegates}
    assert by["bad"].status == DelegateStatus.FAILED and by["bad"].error_kind == "malformed"
    assert by["ok"].status == DelegateStatus.SUCCEEDED and panel.synthesizeable


def test_a_non_string_reported_model_cannot_break_source_counting_or_a_whole_run():
    provs = {n: Raw(ProviderResponse(text=TEXT[n], model=(7 if n == "a" else {"x": 1}))) for n in "ab"}
    provs.update(crit=FakeProvider("crit"), arb=FakeProvider("final"))
    ids = {n: identity(f"m-{n}") for n in "ab"}
    req = DeliberationRequest(question="q", delegates=["a", "b"], arbiter="arb", critic="crit",
                              minimum_successes=2, seed="s")
    result = asyncio.run(Orchestrator(provs, ids).deliberate(req))
    assert result.panel.independent_source_count == 2 and result.arbiter.status == DelegateStatus.SUCCEEDED


def test_cancellation_still_propagates_through_the_containment():
    orch = Orchestrator({"x": Raw(asyncio.CancelledError())})
    with pytest.raises(asyncio.CancelledError):
        panel_of(orch, "x")


def test_an_http_reply_with_odd_metadata_is_an_answer_not_a_crash():
    reply = httpx.Response(200, json={"choices": [{"message": {"content": "an honest answer here"}}],
                                      "model": 12345, "usage": ["not", "a", "mapping"]})

    async def handler(request):
        return reply

    provider = OpenAICompatibleProvider(
        base_url="https://p.example/v1", model="cfg",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    [d] = panel_of(Orchestrator({"p": provider}), "p").delegates
    assert d.status == DelegateStatus.SUCCEEDED and d.raw_response == "an honest answer here"
    assert isinstance(d.model, (str, type(None))) and d.usage == {}
