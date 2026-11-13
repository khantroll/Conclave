"""The mock benchmark (P1-12): a fixed, scripted, free measure of whether the pipeline keeps what
Conclave exists to keep: independence, dissent, absence, uncertainty and honest cost.

Every fixture in ``fixtures.json`` scripts a panel with fake providers and is run through the real
orchestrator. Thirteen invariants are then checked, each against every fixture it applies to. The
benchmark is the test: every fixture passes, with no expected failures.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx
import pytest

from conclave.ledger import summarize
from conclave.models import CallRow, DeliberationRequest, DeliberationResult, DelegateStatus
from conclave.orchestrator import Orchestrator
from conclave.prompts import label_map, marker_token
from conclave.providers.base import Provider, ProviderResponse
from conclave.providers.fake import FakeProvider
from conclave.providers.openai_compatible import OpenAICompatibleProvider
from conclave.sources import ProviderIdentity

DATA = json.loads((Path(__file__).with_name("fixtures.json")).read_text(encoding="utf-8"))
FIXTURES = DATA["fixtures"]
HTTP_FIXTURES = DATA["http_fixtures"]
IDS = [f["id"] for f in FIXTURES]
SEED = "benchmark-seed-0001"
TIMEOUT = 0.15

_spent: list[float] = []


# ------------------------------------------------------------------------------- scripting


def answer_text(delegate: dict, by_name: dict[str, dict]) -> str:
    """The scripted answer: thirty words unique to the delegate, then optional marker and lines."""
    if "copy_of" in delegate:
        source = by_name[delegate["copy_of"]]
        body = base_words(source)
    else:
        body = base_words(delegate)
    parts = [body]
    if delegate.get("dissent"):
        parts.append(delegate["dissent"])
    lines = []
    if delegate.get("conclusion"):
        lines.append(f"Conclusion: {delegate['conclusion']}")
    if delegate.get("confidence"):
        lines.append(f"Confidence: {delegate['confidence']}")
    return "\n\n".join(parts) + ("\n" + "\n".join(lines) if lines else "")


def base_words(delegate: dict) -> str:
    stem, count = delegate["say"], delegate.get("words", 30)
    return " ".join(f"{stem}{i}" for i in range(1, count + 1))


class Hanging(Provider):
    """Never answers (until it is cancelled or times out)."""

    def __init__(self, calls, name):
        self.calls, self.name, self.started = calls, name, asyncio.Event()

    async def ask(self, prompt):
        self.calls.append((self.name, prompt))
        self.started.set()
        await asyncio.Event().wait()


class Scripted(Provider):
    """A provider whose reply is computed from the prompt, recording every call."""

    def __init__(self, calls, name, reply, *, model="fake-model", error=None):
        self.calls, self.name, self.reply, self.model, self.error = calls, name, reply, model, error

    async def ask(self, prompt):
        self.calls.append((self.name, prompt))
        if self.error is not None:
            raise self.error
        return ProviderResponse(text=self.reply(prompt), model=self.model)


def labels_in(prompt: str) -> list[str]:
    return re.findall(r"^Response ([A-Z]+)$", prompt, re.M)


def arbiter_reply(mode: str):
    def reply(prompt: str) -> str:
        labels = labels_in(prompt) or ["A"]
        first, rest = labels[0], labels[1:]
        if mode == "malformed":
            return "I believe the answer is clear, and I will not use your format."
        cite = f"[{first}]"
        other = f"[{', '.join(rest)}]" if rest else cite
        synthesis = "Insufficient evidence to decide." if mode == "insufficient" else "Go ahead, carefully."
        uncertainty = f"- Open question. [{'Z' if mode == 'unknown_citation' else first}]"
        return (
            f"## Common ground\n- Both see the risk. {cite}\n\n"
            f"## Disagreements\n- They differ on timing. {other}\n\n"
            f"## Uncertainty\n{uncertainty}\n\n## Synthesis\n{synthesis}"
        )

    return reply


class Built:
    """A fixture turned into a running pipeline."""

    def __init__(self, fixture: dict, *, hang: str | None = None, seed: str = SEED):
        self.fixture = fixture
        self.calls: list[tuple[str, str]] = []
        self.rows: list[CallRow] = []
        delegates = fixture["delegates"]
        self.by_name = {d["name"]: d for d in delegates}
        providers: dict[str, Provider] = {}
        identities: dict[str, ProviderIdentity] = {}
        self.hung: Hanging | None = None
        for d in delegates:
            name = d["name"]
            ident = self.by_name[d["same_as"]] if "same_as" in d else d
            base = ident.get("base", f"https://{ident['name']}.example/v1")
            model = ident.get("model", f"model-{ident['name']}")
            identities[name] = ProviderIdentity(
                base_url=base, model=model, router_alias=bool(ident.get("alias")), family=ident.get("family")
            )
            reported = d.get("reports", model)
            fail = d.get("fail")
            if fail == "timeout" or (hang == "panel" and d is delegates[-1] and not fail):
                providers[name] = self.hung = Hanging(self.calls, name)
            elif fail == "error":
                providers[name] = Scripted(self.calls, name, None, error=RuntimeError("scripted failure"))
            elif fail in ("empty", "blank"):
                providers[name] = Scripted(self.calls, name, lambda p, f=fail: "" if f == "empty" else "  \n\t ", model=reported)
            else:
                text = answer_text(d, self.by_name)
                providers[name] = Scripted(self.calls, name, lambda p, t=text: t, model=reported)

        critic = fixture["critic"]
        arbiter = fixture["arbiter"]
        critic_fallbacks, arbiter_fallbacks = [], []
        providers["critic"] = (
            Hanging(self.calls, "critic") if hang == "critic" else Scripted(self.calls, "critic", lambda p: "Critique text.")
        )
        providers["critic-fb"] = Scripted(self.calls, "critic-fb", lambda p: "Fallback critique.")
        if critic in ("fail", "fallback"):
            providers["critic"] = Scripted(self.calls, "critic", None, error=RuntimeError("critic down"))
        if critic == "fallback":
            critic_fallbacks = ["critic-fb"]
        mode = "structured" if arbiter in ("fallback", "fail") else arbiter
        providers["arbiter"] = (
            Hanging(self.calls, "arbiter") if hang == "arbiter" else Scripted(self.calls, "arbiter", arbiter_reply(mode))
        )
        providers["arbiter-fb"] = Scripted(self.calls, "arbiter-fb", arbiter_reply("structured"))
        if arbiter in ("fallback", "fail"):
            providers["arbiter"] = Scripted(self.calls, "arbiter", None, error=RuntimeError("arbiter down"))
        if arbiter == "fallback":
            arbiter_fallbacks = ["arbiter-fb"]
        if hang in ("critic", "arbiter"):
            self.hung = providers[hang]

        self.orchestrator = Orchestrator(providers, identities, ledger_sink=self.rows.append)
        extra = {}
        if "judge_char_limit" in fixture:
            extra["judge_response_char_limit"] = fixture["judge_char_limit"]
        self.request = DeliberationRequest(
            question=fixture["question"],
            delegates=[d["name"] for d in delegates],
            arbiter="arbiter",
            arbiter_fallbacks=arbiter_fallbacks,
            critic=None if critic is False else "critic",
            critic_fallbacks=critic_fallbacks,
            minimum_successes=fixture["min"],
            allow_single_source=fixture.get("allow_single", False),
            single_source_mode=fixture.get("single_mode", "return_answer"),
            timeout_seconds=TIMEOUT,
            critic_timeout_seconds=TIMEOUT,
            arbiter_timeout_seconds=TIMEOUT,
            seed=seed,
            **extra,
        )

    async def run(self, **kwargs) -> DeliberationResult:
        return await self.orchestrator.deliberate(self.request, **kwargs)

    def calls_to(self, *names):
        return [prompt for name, prompt in self.calls if name in names]

    @property
    def delegate_names(self):
        return list(self.by_name)

    def judge_prompts(self, result: DeliberationResult) -> list[str]:
        return [stage.prompt for stage in (result.critic, result.arbiter) if stage is not None and stage.prompt]


@lru_cache(maxsize=None)
def ran(fixture_id: str):
    fixture = next(f for f in FIXTURES if f["id"] == fixture_id)
    built = Built(fixture)
    started = time.perf_counter()
    result = asyncio.run(built.run())
    _spent.append(time.perf_counter() - started)
    return built, result


def fresh(fixture_id: str):
    """A private run, for tests that retry (a retry makes more calls, so it must not touch the
    cached run the other invariants read)."""
    built = Built(fx(fixture_id))
    return built, asyncio.run(built.run())


def fx(fixture_id):
    return next(f for f in FIXTURES if f["id"] == fixture_id)


def unique_tokens(built: Built, name: str) -> list[str]:
    d = built.by_name[name]
    return [f"{d['say']}7", f"{d['say']}23"] if "say" in d else []


# ----------------------------------------------------------------------------- the fixtures


def test_there_are_at_least_25_fixtures_with_unique_ids():
    assert len(FIXTURES) + len(HTTP_FIXTURES) >= 25 and len(set(IDS)) == len(IDS)


@pytest.mark.parametrize("fid", IDS)
def test_what_each_fixture_expects_is_what_happens(fid):
    """Sources, successes, quorum, single-source status, merges and call counts."""
    built, result = ran(fid)
    expect = built.fixture["expect"]
    panel = result.panel
    assert panel.independent_source_count == expect["sources"], panel.sources
    assert panel.successful_count == expect["successes"]
    assert panel.quorum.status == expect["quorum"]
    assert (result.critic is not None or result.arbiter is not None or result.single_source_answer is not None) == expect["judges"]
    assert result.single_source is expect.get("single", False)
    assert len(built.calls_to(*(n for n in built.delegate_names))) == len(built.delegate_names)  # 7: each delegate once
    assert len(built.calls_to("critic", "critic-fb")) == expect["critic_calls"]
    assert len(built.calls_to("arbiter", "arbiter-fb")) == expect["arbiter_calls"]
    merged = sorted(sorted(g.delegates) for g in panel.sources if len(g.delegates) > 1)
    assert merged == sorted(sorted(g) for g in expect.get("merged", []))
    for key, reason in expect.get("reasons", {}).items():
        group = next(g for g in panel.sources if sorted(g.delegates) == key.split("+"))
        assert group.reason == reason
    if "families" in expect:
        assert panel.distinct_families == expect["families"]
    assert result.insufficient_evidence is expect.get("insufficient", False)


# 1. Dissent reaches the Arbiter.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if any(d.get("dissent") for d in f["delegates"])])
def test_1_dissent_reaches_the_arbiter_inside_its_own_response_block(fid):
    built, result = ran(fid)
    assert result.arbiter is not None and result.critic is not None
    token = marker_token(SEED)
    for delegate in built.fixture["delegates"]:
        if not delegate.get("dissent"):
            continue
        marker = re.search(r"DISSENT-MARKER-\w+", delegate["dissent"]).group(0)
        label = {v: k for k, v in result.label_map.items()}[delegate["name"]]
        for prompt in built.judge_prompts(result):
            blocks = dict(re.findall(rf"<<<RESPONSE ([A-Z]+) {token}>>>\n(.*?)\n<<<END \1 {token}>>>", prompt, re.S))
            assert marker in blocks[label], "the minority's marker is in its own block"
            assert sum(marker in text for text in blocks.values()) == 1  # and in no other block
            outside = re.sub(rf"<<<RESPONSE [A-Z]+ {token}>>>.*?<<<END [A-Z]+ {token}>>>", "", prompt, flags=re.S)
            assert marker not in outside


# 2. Failure is disclosed.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single")])
def test_2_failure_is_disclosed_k_of_n_in_both_judge_prompts(fid):
    built, result = ran(fid)
    n, k = len(built.fixture["delegates"]), result.panel.successful_count
    prompts = built.judge_prompts(result)
    assert len(prompts) == (2 if built.fixture["critic"] is not False else 1)
    for prompt in prompts:
        assert f"{k} of {n} delegates answered" in prompt
        if "disclosed" in built.fixture["expect"]:
            assert built.fixture["expect"]["disclosed"] in prompt
        for slot, d in enumerate(built.fixture["delegates"], start=1):
            note = f"Slot {slot} did not answer"
            assert (note in prompt) == bool(d.get("fail"))
        assert "scripted failure" not in prompt  # the reason is a word, never the error text


# 3. A single source is labelled, and the Critic is skipped.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"].get("single")])
def test_3_a_single_source_is_labelled_and_the_critic_skipped(fid):
    built, result = ran(fid)
    assert result.single_source and result.single_source_label
    assert result.critic is None and built.calls_to("critic", "critic-fb") == []
    assert "not a consensus" in result.single_source_label.lower() or "single source" in result.single_source_label.lower()
    if result.arbiter is not None:
        assert result.single_source_label in result.arbiter.prompt
        assert "do not describe common ground" in result.arbiter.prompt
    else:
        assert result.single_source_answer is not None and built.calls_to("arbiter", "arbiter-fb") == []


@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if not f["expect"].get("single") and f["expect"]["judges"]])
def test_3b_a_multi_source_run_is_not_labelled_single_source(fid):
    built, result = ran(fid)
    assert result.single_source is False and result.single_source_label is None


# 4. An empty answer is not a success.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if any(d.get("fail") in ("empty", "blank") for d in f["delegates"])])
def test_4_an_empty_answer_is_not_a_success_and_counts_for_nothing(fid):
    built, result = ran(fid)
    for delegate in result.panel.delegates:
        spec = built.by_name[delegate.name]
        if spec.get("fail") in ("empty", "blank"):
            assert delegate.status == DelegateStatus.FAILED and delegate.error_kind == "empty_response"
            assert delegate.name not in result.label_map.values()
            assert all(delegate.name not in g.delegates for g in result.panel.sources)
    for name, kind in built.fixture["expect"].get("failure_kinds", {}).items():
        assert next(d for d in result.panel.delegates if d.name == name).error_kind == kind


# 5. Duplicate sources collapse; different models stay separate. (Counts and reasons are
#    asserted for every fixture in test_what_each_fixture_expects_is_what_happens.)
def test_5_the_fixtures_cover_each_way_two_answers_can_be_one_source():
    reasons = {r for f in FIXTURES for r in f["expect"].get("reasons", {}).values()}
    assert reasons == {"same_config", "same_reported_model", "unresolved_router_alias", "near_duplicate_text"}
    separate = [f["id"] for f in FIXTURES if f["expect"].get("merged") == [] and len(f["delegates"]) > 1]
    assert len(separate) >= 2  # models that answer alike, or an alias that resolves, are not merged


# 6. Judging is blind.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"]])
def test_6_no_identity_string_reaches_a_judge_prompt(fid):
    built, result = ran(fid)
    secrets = set()
    for d in built.fixture["delegates"]:
        ident = built.by_name[d["same_as"]] if "same_as" in d else d
        secrets |= {d["name"] if len(d["name"]) > 3 else f"{d['name']}.example", f"{ident['name']}.example",
                    ident.get("model", f"model-{ident['name']}"), d.get("reports", ""), ident.get("family", "")}
    secrets |= {"critic-fb", "arbiter-fb", "fake-model"}
    secrets.discard("")
    for prompt in built.judge_prompts(result):
        for secret in secrets:
            assert secret not in prompt, secret
        assert not re.search(r"\b\d+ ?ms\b|latency|token|cost|attempt", prompt, re.I)
        assert all(re.fullmatch(r"Response [A-Z]+", line) for line in prompt.splitlines() if line.startswith("Response "))


@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["successes"] >= 2 and f["expect"]["judges"]])
def test_6b_the_order_varies_by_seed(fid):
    built, result = ran(fid)
    orders = {tuple(label_map(result.panel.delegates, f"seed-{i}").values()) for i in range(16)}
    assert len(orders) > 1
    assert tuple(label_map(result.panel.delegates, SEED).values()) == tuple(result.label_map.values())


@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single") and f["critic"] is True])
def test_6c_the_order_is_stable_across_retries(fid):
    built, result = fresh(fid)
    stored = DeliberationResult.model_validate_json(result.model_dump_json())
    again = asyncio.run(built.orchestrator.retry_critic(request=built.request, prior_result=stored))
    final = asyncio.run(built.orchestrator.retry_arbiter(request=built.request, prior_result=again))
    assert result.label_map == again.label_map == final.label_map


# 7. Call count and prompt size.
@pytest.mark.parametrize("fid", IDS)
def test_7_provider_calls_and_prompt_sizes_match_the_fixture(fid):
    built, result = ran(fid)
    delegate_prompts = built.calls_to(*built.delegate_names)
    assert len(delegate_prompts) == len(built.delegate_names) and len(set(delegate_prompts)) == 1
    assert len(delegate_prompts[0]) < 1500  # a delegate prompt is the question and a few fixed lines
    if built.fixture["expect"].get("max_arbiter_chars"):
        assert result.arbiter is not None
        assert len(result.arbiter.prompt) < built.fixture["expect"]["max_arbiter_chars"]
        assert "characters omitted" in result.arbiter.prompt or "truncated" in result.arbiter.prompt.lower() or "cut" in result.arbiter.prompt.lower()
        stored = {d.name: d.raw_response for d in result.panel.delegates}
        assert all(len(text) > 10_000 for text in stored.values())  # the stored answers are whole
    total_calls = len(built.calls)
    assert total_calls == len(built.delegate_names) + built.fixture["expect"]["critic_calls"] + built.fixture["expect"]["arbiter_calls"]


# 8. Nothing paid for is lost when the run is cancelled at each stage.
async def cancelled_run(fixture: dict, stage: str):
    built = Built(fixture, hang=stage)
    saved: list[DeliberationResult] = []

    built.rows_at_each_save = []

    async def on_stage(partial):
        saved.append(partial)
        built.rows_at_each_save.append((len(built.rows), len(built.calls)))

    task = asyncio.ensure_future(built.run(on_stage=on_stage))
    await asyncio.wait_for(built.hung.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    built.rows_when_cancelled = len(built.rows)  # no further loop turn has run yet
    return built, saved


def cancel_cases():
    cases = []
    for f in FIXTURES:
        e = f["expect"]
        if f["id"] == "only-empty-answers-fail-quorum" or any(d.get("fail") == "timeout" for d in f["delegates"]):
            continue
        ok_delegates = [d for d in f["delegates"] if not d.get("fail")]
        if len(ok_delegates) >= 2:
            cases.append((f["id"], "panel"))
        if e["judges"] and not e.get("single") and f["critic"] is True:
            cases.append((f["id"], "critic"))
        if e["judges"] and e["arbiter_calls"] and f["arbiter"] != "fallback":
            cases.append((f["id"], "arbiter"))
    return cases


@pytest.mark.parametrize("fid,stage", cancel_cases(), ids=[f"{a}:{b}" for a, b in cancel_cases()])
def test_8_nothing_paid_for_is_lost_when_cancelled_at_each_stage(fid, stage):
    built, saved = asyncio.run(cancelled_run(fx(fid), stage))
    # Every call that began has exactly one ledger row, including the one that was cut off.
    assert built.rows_when_cancelled == len(built.calls) == len(built.rows)
    # By the time the partial result is saved, every call that began already has its row.
    assert all(rows == calls for rows, calls in built.rows_at_each_save[-1:])
    assert [r.outcome for r in built.rows].count("cancelled") == 1
    assert sum(1 for r in built.rows if r.possibly_billed) == len(built.rows)
    last = saved[-1]
    done = {d.name for d in last.panel.delegates if d.status == DelegateStatus.SUCCEEDED}
    finished = {d["name"] for d in built.fixture["delegates"] if not d.get("fail")} - {built.hung.name}
    if stage == "panel":
        assert finished and finished == done  # every delegate that answered keeps its answer, no more
        hung = next(d for d in last.panel.delegates if d.name == built.hung.name)
        assert (hung.status, hung.error_kind) == (DelegateStatus.FAILED, "cancelled")
        assert last.critic is None and last.arbiter is None
        assert all(d.raw_response for d in last.panel.delegates if d.name in finished)
    else:
        assert len(done) == built.fixture["expect"]["successes"]  # the whole panel was saved
        assert last.arbiter is None
        has_critic = built.fixture["critic"] in (True, "fallback") and not built.fixture["expect"].get("single")
        assert (last.critic is not None) is (stage == "arbiter" and has_critic)


# 9. The ledger is honest.
@pytest.mark.parametrize("fid", IDS)
def test_9_ledger_totals_equal_the_sum_of_the_rows_and_unknown_is_never_zero(fid):
    built, result = ran(fid)
    assert len(built.rows) == len(built.calls)  # one row per provider call
    assert result.cost == summarize(built.rows) and result.cost.total_calls == len(built.rows)
    assert result.cost.priced_calls + result.cost.unpriced_calls == result.cost.total_calls
    # These fakes state no price, so nothing may be shown as a cost, least of all $0.
    assert result.cost.estimated_total_usd is None and result.estimated_cost_usd is None
    assert result.cost.unpriced_calls == len(built.rows)


def http_scripts(fixture):
    def response(item):
        if item == "ok":
            return httpx.Response(200, json={"choices": [{"message": {"content": "answer " * 12}}], "model": "reported",
                                             "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
        if item == "quota":
            return httpx.Response(429, text="insufficient_quota")
        if item == "auth":
            return httpx.Response(401, text="bad key")
        if item == "connect":
            return httpx.ConnectError("refused")
        return httpx.Response(item, text="busy")

    return response


class Transport:
    def __init__(self, script, response):
        self.script, self.response, self.requests = list(script), response, 0

    async def __call__(self, request):
        item = self.script[min(self.requests, len(self.script) - 1)]
        self.requests += 1
        out = self.response(item)
        if isinstance(out, Exception):
            raise out
        return out


def http_provider(transport, fixture):
    prices = {"input_cost_per_million": 2.0, "output_cost_per_million": 10.0} if fixture["priced"] else {}
    return OpenAICompatibleProvider(
        base_url="https://p.example/v1", model="cfg", transient_max_retries=fixture["retries"],
        retry_backoff_seconds=0.0, client=httpx.AsyncClient(transport=httpx.MockTransport(transport)), **prices,
    )


@pytest.mark.parametrize("fixture", HTTP_FIXTURES, ids=[f["id"] for f in HTTP_FIXTURES])
def test_9b_every_http_request_has_exactly_one_row_and_totals_hold(fixture):
    response = http_scripts(fixture)
    primary = Transport(fixture["script"], response)
    rows: list[CallRow] = []
    providers = {
        "a": FakeProvider("answer one " + "w" * 30, model="m-a"), "b": FakeProvider("answer two " + "v" * 30, model="m-b"),
        "critic": FakeProvider("crit"), "arbiter": http_provider(primary, fixture),
    }
    fallbacks = []
    fallback = None
    if "fallback" in fixture:
        fallback = Transport(fixture["fallback"], response)
        providers["arbiter-fb"] = http_provider(fallback, fixture)
        fallbacks = ["arbiter-fb"]
    request = DeliberationRequest(question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter",
                                  arbiter_fallbacks=fallbacks, minimum_successes=2, seed=SEED)
    result = asyncio.run(Orchestrator(providers, ledger_sink=rows.append).deliberate(request))

    http_rows = [r for r in rows if r.provider in ("arbiter", "arbiter-fb")]
    requests = primary.requests + (fallback.requests if fallback else 0)
    expect = fixture["expect"]
    assert requests == expect["requests"] == len(http_rows)  # one row per request the transport saw
    assert sum(r.estimated_cost_usd is not None for r in http_rows) == expect["priced"]
    assert sum(r.estimated_cost_usd is None for r in http_rows) == expect["unpriced"]
    totals = summarize(http_rows)
    if expect["priced"]:
        assert totals.estimated_total_usd == pytest.approx(0.007 * expect["priced"])
    else:
        assert totals.estimated_total_usd is None  # unpriced is never shown as $0
    assert result.cost == summarize(rows)  # the run's totals are the sum over every row, fakes included


# 10. Positions are present for every delegate, whatever the Arbiter wrote.
@pytest.mark.parametrize("fid", IDS)
def test_10_a_position_row_for_every_delegate_whatever_the_arbiter_wrote(fid):
    built, result = ran(fid)
    assert [r.delegate for r in result.positions] == built.delegate_names
    for row, spec in zip(result.positions, built.fixture["delegates"], strict=True):
        if spec.get("fail"):
            assert row.status != "succeeded" and row.conclusion is None
            continue
        assert row.conclusion == spec.get("conclusion")
        if spec.get("confidence"):
            assert row.confidence_text == spec["confidence"]


# 11. Structured output parses, or says it did not.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single")])
def test_11_the_arbiters_structure_parses_or_is_marked_not_ok(fid):
    built, result = ran(fid)
    structure = result.arbiter_structure
    assert structure is not None
    assert structure.format_ok is built.fixture["expect"]["format_ok"]
    if structure.format_ok:
        assert list(structure.sections) == ["common_ground", "disagreements", "uncertainty", "synthesis"]
        assert structure.unknown_citations == built.fixture["expect"].get("unknown_citations", [])
    else:
        assert structure.sections == {} and structure.problems
    assert result.arbiter.raw_response  # the raw answer is kept either way


# 12. Prompts rebuilt from stored runs are byte-identical.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single") and f["critic"] is True and f["arbiter"] != "fallback"])
def test_12_prompts_rebuilt_from_a_stored_run_are_byte_identical(fid):
    built, result = fresh(fid)
    stored = DeliberationResult.model_validate_json(result.model_dump_json())  # as the database holds it
    stored_request = DeliberationRequest.model_validate_json(built.request.model_dump_json())
    again = asyncio.run(built.orchestrator.retry_critic(request=stored_request, prior_result=stored))
    assert again.critic.prompt == result.critic.prompt
    assert again.arbiter.prompt == result.arbiter.prompt
    only_arbiter = asyncio.run(built.orchestrator.retry_arbiter(request=stored_request, prior_result=again))
    assert only_arbiter.arbiter.prompt == result.arbiter.prompt


# 13. No delegate prompt contains any other model's output.
@pytest.mark.parametrize("fid", IDS)
def test_13_no_delegate_prompt_contains_any_other_models_output(fid):
    built, result = ran(fid)
    # Whole answers, and a long run from the start of each, for every other model: the delegates
    # that answered, the Critic and the Arbiter (a failed delegate said nothing to leak).
    outputs = ["Critique text.", "Fallback critique.", "Go ahead, carefully.", "I believe the answer is clear"]
    for d in built.fixture["delegates"]:
        if not d.get("fail"):
            outputs.append(answer_text(d, built.by_name))
    for stage in (result.critic, result.arbiter):
        if stage is not None and stage.raw_response:
            outputs.append(stage.raw_response)
    outputs += [text[:60] for text in list(outputs)]
    for prompt in built.calls_to(*built.delegate_names):
        for text in outputs:
            assert text not in prompt, text[:40]
        assert "<<<" not in prompt and "Response A" not in prompt
        assert built.fixture["question"] in prompt


# 8b. Races: a delegate finishing as the cancel arrives, a cancel during the save, a cancel
#     while a fallback is being chosen. Never a duplicate or missing row, never a lost answer.
def run_in_a_watched_loop(coro_factory):
    """Run in a fresh loop and return (result, loop exceptions nobody retrieved)."""
    import gc

    problems = []
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(lambda loop, context: problems.append(context))
    try:
        result = loop.run_until_complete(coro_factory())
        gc.collect()
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()
    return result, problems


def test_8b_a_delegate_finishing_as_the_cancel_arrives_is_kept_exactly_once():
    built = Built(fx("three-independent-agree"), hang="panel")
    saved = []

    async def scenario():
        release = asyncio.Event()
        first = built.by_name["a"]

        class Late(Scripted):
            async def ask(self, prompt):
                self.calls.append((self.name, prompt))
                await release.wait()
                return ProviderResponse(text=answer_text(first, built.by_name), model="model-a")

        built.orchestrator._providers["a"] = Late(built.calls, "a", None)

        async def on_stage(partial):
            saved.append(partial)

        task = asyncio.ensure_future(built.run(on_stage=on_stage))
        await asyncio.wait_for(built.hung.started.wait(), 5)
        task.cancel()
        release.set()  # a's answer arrives in the same breath as the cancellation
        with pytest.raises(asyncio.CancelledError):
            await task
        built.rows_when_cancelled = len(built.rows)

    _, problems = run_in_a_watched_loop(scenario)
    assert problems == []
    assert built.rows_when_cancelled == len(built.rows) == len(built.calls) == 3  # one row per call, none doubled, none missing
    assert len(saved) == 1  # saved exactly once
    names = [d.name for d in saved[0].panel.delegates]
    assert names == ["a", "b", "c"]  # one result per delegate, in order, no duplicates
    by = {d.name: d for d in saved[0].panel.delegates}
    assert by["b"].status == DelegateStatus.SUCCEEDED and by["b"].raw_response
    assert by["c"].error_kind == "cancelled"
    assert (by["a"].status == DelegateStatus.SUCCEEDED) == (by["a"].error_kind is None)  # never half-recorded


def test_8b_a_second_cancel_during_the_save_leaks_nothing_and_loses_no_row():
    built = Built(fx("three-independent-agree"), hang="panel")
    entered = []

    async def scenario():
        async def slow_save(partial):
            entered.append(partial)
            await asyncio.sleep(5)  # the save itself is interrupted by a second cancel

        task = asyncio.ensure_future(built.run(on_stage=slow_save))
        await asyncio.wait_for(built.hung.started.wait(), 5)
        task.cancel()
        while not entered:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _, problems = run_in_a_watched_loop(scenario)
    assert problems == []
    assert len(built.rows) == len(built.calls) and [r.outcome for r in built.rows].count("cancelled") == 1


def test_8b_cancelling_while_a_fallback_is_chosen_keeps_the_failed_primary_and_cancels_the_fallback():
    built = Built(fx("critic-fails-and-its-fallback-answers"))
    saved = []

    async def scenario():
        began = asyncio.Event()

        class HangingFallback(Hanging):
            async def ask(self, prompt):
                began.set()
                return await super().ask(prompt)

        built.orchestrator._providers["critic-fb"] = HangingFallback(built.calls, "critic-fb")

        async def on_stage(partial):
            saved.append(partial)

        task = asyncio.ensure_future(built.run(on_stage=on_stage))
        await asyncio.wait_for(began.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _, problems = run_in_a_watched_loop(scenario)
    assert problems == []
    assert len(built.rows) == len(built.calls)
    critic_rows = [(r.provider, r.outcome) for r in built.rows if r.stage == "critic"]
    assert critic_rows == [("critic", "transport_error"), ("critic-fb", "cancelled")]
    assert len(saved) == 1 and len(saved[0].panel.delegates) == 2 and saved[0].critic is None  # the panel is kept


# 9c. The ledger across stage retries.
@pytest.mark.parametrize(
    "fid",
    [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single") and f["critic"] is True and f["arbiter"] != "fallback"],
)
def test_9c_ledger_totals_hold_across_stage_retries(fid):
    from conclave.ledger import CallContext

    built, first = fresh(fid)
    before = len(built.rows)
    stored = DeliberationResult.model_validate_json(first.model_dump_json())
    again = asyncio.run(
        built.orchestrator.retry_critic(request=built.request, prior_result=stored, call_context=CallContext("r2", "root"))
    )
    final = asyncio.run(
        built.orchestrator.retry_arbiter(request=built.request, prior_result=again, call_context=CallContext("r3", "root"))
    )

    def mine(run_id):
        return [r for r in built.rows if r.run_id == run_id]

    assert len(built.rows) == len(built.calls)  # every call, across the chain, has one row
    assert len(mine("r2")) == 2 and len(mine("r3")) == 1  # a Critic retry runs Critic+Arbiter; an Arbiter retry one call
    assert again.cost == summarize(mine("r2")) and final.cost == summarize(mine("r3"))
    chain = summarize([r for r in built.rows if r.chain_root_id == "root"])
    assert chain.total_calls == 3 and chain.unpriced_calls == 3 and chain.estimated_total_usd is None
    assert len(built.rows) == before + 3


# 7b. Prompt sizes follow from the answers, whatever the fixture.
@pytest.mark.parametrize("fid", [f["id"] for f in FIXTURES if f["expect"]["judges"] and not f["expect"].get("single")])
def test_7b_judge_prompt_sizes_follow_from_the_answers_and_the_cap(fid):
    built, result = ran(fid)
    limit = built.fixture.get("judge_char_limit", 24_000)
    kept = sum(min(len(d.raw_response), limit) for d in result.panel.delegates if d.status == DelegateStatus.SUCCEEDED)
    answered = result.panel.successful_count
    for prompt in built.judge_prompts(result):
        assert len(prompt) >= kept  # nothing that was kept is missing
        assert len(prompt) <= kept + 3500 + 400 * answered  # and only fixed framing and markers are added
    if result.critic is not None and result.arbiter is not None:
        # The Arbiter also sees the Critic's text, so its prompt is the larger of the two.
        assert len(result.arbiter.prompt) > len(result.critic.prompt)


def test_the_benchmark_is_fast():
    for fid in IDS:
        ran(fid)
    assert sum(_spent) < 10


# 6d. A delegate retry relabels nobody (part of "order is stable across retries").
@pytest.mark.parametrize(
    "fid",
    [
        f["id"]
        for f in FIXTURES
        if f["expect"]["judges"]
        and not f["expect"].get("single")
        and [d.get("fail") for d in f["delegates"]].count("error") == 1
    ],
)
def test_6d_a_delegate_retry_relabels_nobody(fid):
    built, result = fresh(fid)
    failed = next(d for d in built.fixture["delegates"] if d.get("fail") == "error")
    text = " ".join(f"retried{i}" for i in range(1, 31))
    built.orchestrator._providers[failed["name"]] = Scripted(built.calls, failed["name"], lambda p: text)
    stored = DeliberationResult.model_validate_json(result.model_dump_json())
    retried = asyncio.run(
        built.orchestrator.retry_delegate(request=built.request, prior_result=stored, delegate_name=failed["name"])
    )
    assert failed["name"] in retried.label_map.values()
    assert all(retried.label_map[label] == name for label, name in result.label_map.items())


# 8c. The same, for a real HTTP request that is cut off mid-flight.
def test_8c_an_http_request_cut_off_by_a_cancel_gets_a_possibly_billed_row():
    rows: list[CallRow] = []
    started = {}

    async def scenario():
        started["event"] = asyncio.Event()

        async def hang(request):
            started["event"].set()
            await asyncio.Event().wait()

        provider = OpenAICompatibleProvider(
            base_url="https://p.example/v1", model="cfg", input_cost_per_million=2.0,
            output_cost_per_million=10.0, client=httpx.AsyncClient(transport=httpx.MockTransport(hang)),
        )
        providers = {
            "a": FakeProvider("answer one " + "w" * 30, model="m-a"), "b": FakeProvider("answer two " + "v" * 30, model="m-b"),
            "critic": FakeProvider("crit"), "arbiter": provider,
        }
        request = DeliberationRequest(question="q", delegates=["a", "b"], critic="critic", arbiter="arbiter",
                                      minimum_successes=2, seed=SEED, arbiter_timeout_seconds=30)
        task = asyncio.ensure_future(Orchestrator(providers, ledger_sink=rows.append).deliberate(request))
        await asyncio.wait_for(started["event"].wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        started["rows"] = list(rows)  # before any further loop turn

    _, problems = run_in_a_watched_loop(scenario)
    assert problems == []
    cut = [r for r in started["rows"] if r.provider == "arbiter"]
    assert [(r.outcome, r.possibly_billed, r.estimated_cost_usd) for r in cut] == [("cancelled", True, None)]
    assert len(started["rows"]) == 4  # two delegates, the Critic, and the request that was cut off
