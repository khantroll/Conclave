"""Adversarial regression suite (P1-2): Conclave gives model text no authority.

Every fixture in corpus.json is run through every route by which model text can reach a later
prompt (see harness.py). The assertions are about what Conclave *does*, never about whether a
real model would be persuaded: this suite shows that model text has no authority, not that a
judge model resists persuasion. That is measured separately (roadmap P1-13).
"""

import json
import re
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from harness import (
    BENIGN,
    CONTEXT,
    CRITIC_OK,
    DELEGATES,
    HONEST,
    FIXTURES,
    SCENARIOS,
    SYNTHESIS,
    TOKEN,
    block_count,
    judge_prompts,
    outside_markers,
    run_scenario,
    trace,
)

import conclave.api as api_module
import conclave.providers.factory as factory_module
from conclave.api import create_app
from conclave.config import ConclaveConfig, ProviderConfig
from conclave.prompts import _UNSAFE_CHARS, prepare_untrusted_text
from conclave.providers.fake import FakeProvider
from conclave.store import WorkspaceStore

FIXTURE_IDS = [item["id"] for item in FIXTURES]
SCENARIO_IDS = [s.name for s in SCENARIOS]
GRID = [(s.name, item["id"]) for s in SCENARIOS for item in FIXTURES]
GRID_IDS = [f"{scenario}-{fixture}" for scenario, fixture in GRID]


def test_the_corpus_has_enough_fixtures_in_every_class():
    classes = {}
    for item in FIXTURES:
        classes.setdefault(item["class"], []).append(item["id"])
    assert len(FIXTURES) >= 40
    assert sorted(classes) == list(range(1, 12))
    assert all(len(ids) >= 3 for ids in classes.values())
    assert len(set(FIXTURE_IDS)) == len(FIXTURE_IDS)


# ------------------------------------------------------ control-flow invariance


@pytest.mark.parametrize(("scenario", "fixture"), GRID, ids=GRID_IDS)
def test_hostile_text_changes_nothing_the_orchestrator_does(scenario, fixture):
    hostile = trace(run_scenario(scenario, fixture))
    control = trace(run_scenario(scenario, None))
    assert hostile == control


# ----------------------------------------------------------------- containment


@pytest.mark.parametrize(("scenario", "fixture"), GRID, ids=GRID_IDS)
def test_every_byte_of_model_text_stays_inside_its_own_markers(scenario, fixture):
    spec = next(s for s in SCENARIOS if s.name == scenario)
    item = next(f for f in FIXTURES if f["id"] == fixture)
    hostile_run = run_scenario(scenario, fixture)
    control_run = run_scenario(scenario, None)

    hostile_prompts = judge_prompts(hostile_run)
    control_prompts = judge_prompts(control_run)
    if not spec.judges:
        # The quorum cannot be met, so no model text may buy a Critic or Arbiter call.
        assert hostile_prompts == [] and control_prompts == []
        return
    assert hostile_prompts, "the scenario produced no judge prompt to check"
    assert [name for name, _ in hostile_prompts] == [name for name, _ in control_prompts]

    for (name, prompt), (_, control) in zip(hostile_prompts, control_prompts, strict=True):
        # Nothing outside the markers depends on what any model said. This is the
        # containment property itself: model text cannot have leaked into the template.
        assert outside_markers(prompt) == outside_markers(control), name
        assert block_count(prompt) == block_count(control), name
        # The only ``<<<`` and ``>>>`` sequences are the framing markers Conclave wrote.
        assert prompt.count("<<<") == 2 * block_count(prompt), name
        assert prompt.count(">>>") == 2 * block_count(prompt), name
        assert "<<<" not in outside_markers(prompt) and ">>>" not in outside_markers(prompt)
        # No control, bidirectional or zero-width character survives into a judge prompt.
        assert not _UNSAFE_CHARS.search(prompt), name

        # The text is still shown to the judge, escaped and capped, in the right place.
        shown = prepare_untrusted_text(item["text"])
        in_delegate_slot = spec.delegate_hostile
        in_critic_slot = spec.critic_hostile and name.startswith("arbiter")
        if in_delegate_slot or in_critic_slot:
            assert shown in prompt, name

    # A flood is capped per response, so it cannot crowd out the honest answer.
    for name, prompt in hostile_prompts:
        assert "Honest answer." in prompt, name
        assert len(prompt) < 80_000, name


@pytest.mark.parametrize(("scenario", "fixture"), GRID, ids=GRID_IDS)
def test_raw_model_text_is_stored_exactly_as_received(scenario, fixture):
    spec = next(s for s in SCENARIOS if s.name == scenario)
    item = next(f for f in FIXTURES if f["id"] == fixture)
    result = run_scenario(scenario, fixture).result
    if spec.delegate_hostile:
        attacker = next(d for d in result.panel.delegates if d.name == "attacker")
        assert attacker.raw_response == item["text"]
    if spec.critic_hostile and result.critic is not None and scenario != "fallback_arbiter":
        assert result.critic.raw_response == item["text"]


@pytest.mark.parametrize(("scenario", "fixture"), GRID, ids=GRID_IDS)
def test_no_delegate_prompt_in_any_scenario_contains_any_models_output(scenario, fixture):
    """Independence: a delegate sees the question and context, never another model's words."""
    item = next(f for f in FIXTURES if f["id"] == fixture)
    run = run_scenario(scenario, fixture)
    outputs = [HONEST, CRITIC_OK, SYNTHESIS, BENIGN, item["text"][:200]]
    delegate_prompts = [(name, prompt) for name, prompt in run.calls if name in DELEGATES]
    for name, prompt in delegate_prompts:
        assert CONTEXT in prompt  # the user's workspace context is there, as designed
        for output in outputs:
            assert output not in prompt, (name, output[:40])


# ------------------------------------------------------------ parser isolation


def test_only_arbiter_output_is_parsed_for_sections():
    positions = pytest.importorskip(
        "conclave.positions",
        reason=(
            "needs P1-5/P1-6 (positions and structured Arbiter output), which are not built yet. "
            "Nothing in Conclave parses model output today, which the control-flow tests above "
            "already show: no fixture changes any decision."
        ),
    )
    for item in FIXTURES:
        parsed = positions.parse_sections(item["text"])
        if item["class"] in {4, 5}:
            assert parsed.format_ok is False, item["id"]


# ----------------------------------------------------- API level: saved rows, logs


def _projection(response_json):
    panel = response_json["panel"]
    return {
        "delegates": [(d["name"], d["status"]) for d in panel["delegates"]],
        "critic": (response_json["critic"] or {}).get("status"),
        "arbiter": (response_json["arbiter"] or {}).get("status"),
        "sources": panel["independent_source_count"],
        "quorum": panel["quorum"]["status"],
        "single_source": response_json["single_source"],
    }


def _deliberate_through_the_api(tmp_path, monkeypatch, text, subdir):
    def make(response="ok", **kwargs):
        return FakeProvider(text if response == "Delegate A response" else response, **kwargs)

    monkeypatch.setattr(api_module, "FakeProvider", make)
    (tmp_path / subdir).mkdir()
    store = WorkspaceStore(tmp_path / subdir / "t.db", run_log_dir=tmp_path / subdir / "logs")
    app = create_app(config=ConclaveConfig(), workspace_store=store)
    client = TestClient(app)
    response = client.post(
        "/api/deliberate",
        json={
            "question": "What should we do?",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "minimum_successes": 2,
            "single_source_mode": "return_answer",
        },
    )
    logs = list((tmp_path / subdir / "logs").glob("*.json"))
    return response, store, logs


@pytest.mark.parametrize("fixture", FIXTURE_IDS)
def test_saved_rows_and_run_logs_match_the_benign_control(tmp_path, monkeypatch, fixture):
    item = next(f for f in FIXTURES if f["id"] == fixture)
    hostile, store, logs = _deliberate_through_the_api(tmp_path, monkeypatch, item["text"], "hostile")
    control, control_store, control_logs = _deliberate_through_the_api(tmp_path, monkeypatch, BENIGN, "control")
    assert hostile.status_code == control.status_code == 200
    assert _projection(hostile.json()) == _projection(control.json())
    assert len(store.list_runs()) == len(control_store.list_runs()) == 1
    assert len(logs) == len(control_logs) == 1
    saved = store.list_runs()[0]
    assert saved.status == "complete"
    assert saved.request.minimum_successes == 2  # no text changed the configured quorum
    assert saved.request.allow_single_source is False  # ... or granted a permission
    attacker = next(d for d in saved.result.panel.delegates if d.name == "demo-a")
    assert attacker.raw_response == item["text"]  # stored exactly as received


# ------------------------------------------------------------- secret hygiene

KEY = "sk-adversarial-FAKE-0123456789abcdef"
ORG_SECRET = "org-secret-header-value-98765"
HOSTILE_SLOT = {"text": BENIGN}


class _SecretWorld:
    """A real OpenAI-compatible adapter talking to a stub server that tries to leak secrets."""

    def __init__(self):
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        model = body["model"]
        if model == "leaky-model":
            # Some providers echo the credential they rejected.
            return httpx.Response(
                401,
                json={"error": f"Incorrect API key provided: {KEY}. org={ORG_SECRET}"},
            )
        text = HOSTILE_SLOT["text"] if model == "atk-model" else "Honest answer."
        return httpx.Response(
            200, json={"model": model, "choices": [{"message": {"content": text}}], "usage": {}}
        )


@pytest.fixture
def secret_world(tmp_path, monkeypatch):
    world = _SecretWorld()
    client = httpx.AsyncClient(transport=httpx.MockTransport(world.handler))
    original = factory_module.OpenAICompatibleProvider
    monkeypatch.setattr(
        factory_module, "OpenAICompatibleProvider", lambda **kw: original(**kw, client=client)
    )
    monkeypatch.setenv("ADVERSARIAL_FAKE_API_KEY", KEY)

    def provider(name, model, **extra):
        return ProviderConfig(
            name=name,
            base_url=f"https://{name}.example/v1",
            model=model,
            api_key_env="ADVERSARIAL_FAKE_API_KEY",
            transient_max_retries=0,
            **extra,
        )

    config = ConclaveConfig(
        providers=[
            provider("atk", "atk-model"),
            provider("honest", "honest-model"),
            provider("leaky", "leaky-model", extra_headers={"X-Org-Secret": ORG_SECRET}),
        ]
    )
    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    app = create_app(config=config, workspace_store=store)
    return world, TestClient(app), store, tmp_path


def _everything_stored_or_returned(world, client, store, tmp_path, responses):
    """All text the key could have reached: requests' bodies, responses, the database, logs."""
    parts = [request.content.decode("utf-8", "replace") for request in world.requests]
    parts += [r.text for r in responses]
    parts += [client.get("/api/runs").text, client.get("/api/providers").text, client.get("/health").text]
    connection = sqlite3.connect(tmp_path / "t.db")
    for (table,) in connection.execute("select name from sqlite_master where type='table'"):
        for row in connection.execute(f'select * from "{table}"'):
            parts.append(" ".join(str(value) for value in row))
    connection.close()
    parts += [path.read_text(encoding="utf-8") for path in (tmp_path / "logs").glob("*.json")]
    return "\n".join(parts)


@pytest.mark.parametrize("fixture", FIXTURE_IDS)
def test_a_fake_api_key_appears_in_no_prompt_stored_run_log_or_response(secret_world, fixture):
    world, client, store, tmp_path = secret_world
    item = next(f for f in FIXTURES if f["id"] == fixture)
    HOSTILE_SLOT["text"] = item["text"]
    try:
        response = client.post(
            "/api/deliberate",
            json={
                "question": "What should we do?",
                "delegates": ["atk", "honest", "leaky"],
                "critic": "demo-critic",
                "arbiter": "demo-arbiter",
                "minimum_successes": 2,
                "single_source_mode": "return_answer",
            },
        )
    finally:
        HOSTILE_SLOT["text"] = BENIGN
    assert response.status_code == 200
    body = response.json()
    leaky = next(d for d in body["panel"]["delegates"] if d["name"] == "leaky")
    assert leaky["status"] == "failed" and "HTTP 401" in leaky["error"]

    # The key really was used (so the test is meaningful) ...
    assert any(r.headers.get("authorization") == f"Bearer {KEY}" for r in world.requests)
    # ... and then it is nowhere that a prompt, a saved run, a run log or a response could show it.
    haystack = _everything_stored_or_returned(world, client, store, tmp_path, [response])
    prompts = " ".join(
        (stage or {}).get("prompt") or "" for stage in [body["critic"], body["arbiter"]]
    )
    assert KEY not in prompts
    assert KEY not in haystack and ORG_SECRET not in haystack
    assert "[redacted]" in leaky["error"]


def test_the_leaky_error_body_is_redacted_but_otherwise_kept(secret_world):
    world, client, store, tmp_path = secret_world
    body = client.post(
        "/api/panel",
        json={
            "question": "q",
            "delegates": [{"name": "leaky", "prompt": "p"}],
            "minimum_successes": 1,
        },
    ).json()
    error = body["delegates"][0]["error"]
    assert error.startswith("HTTP 401 from https://leaky.example/v1")
    assert "Incorrect API key provided: [redacted]. org=[redacted]" in error


def test_the_corpus_marker_token_placeholder_is_the_real_token():
    leaked = next(f for f in FIXTURES if f["id"] == "marker-real-token-forged-blocks")
    assert TOKEN in leaked["text"] and "{{TOKEN}}" not in leaked["text"]
    assert re.fullmatch(r"[0-9a-f]{12}", TOKEN)


# ----------------------------------------- the console builds HTML only through render.js


def test_model_derived_html_is_built_only_by_the_tested_render_helpers():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "web" / "app.js").read_text(encoding="utf-8")
    statements = re.findall(r"[\w$\"()]+\.innerHTML\s*=.*?;\n", js, flags=re.S)
    assert statements, "no innerHTML assignments found; the check needs updating"

    helper_sites = [s for s in statements if "delegateCardsHtml(" in s or "historyHtml(" in s]
    assert len(helper_sites) == 2, "delegate cards and history must come from render.js"
    for statement in statements:
        if statement in helper_sites:
            continue
        # Everything else is built from configuration (provider and workspace fields), never
        # from a run result. A run or result identifier here means model text reached innerHTML.
        # Only the ${...} interpolations matter, and quoted literals inside them are not data.
        bare = re.sub(r"\"[^\"\n]*\"|'[^'\n]*'", '""', statement)
        for expression in re.findall(r"\$\{([^{}]*)\}", bare):
            assert not re.search(r"\b(result|run|runs|lone|panel|raw_response)\b", expression), statement
    assert "insertAdjacentHTML" not in js and "outerHTML" not in js and "document.write" not in js
    assert "eval(" not in js and "new Function(" not in js
    # render.js is loaded before app.js
    html = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")
    assert html.index("/static/render.js") < html.index("/static/app.js")


# ------------------------------------ provider-reported metadata is untrusted too


@pytest.mark.parametrize("fixture", FIXTURE_IDS)
def test_a_hostile_reported_model_name_never_reaches_a_judge_prompt(fixture):
    """Judges are blind: the provider-reported model name, whatever it says, is not in a prompt."""
    hostile = run_scenario("hostile_model_metadata", fixture)
    control = run_scenario("hostile_model_metadata", None)
    assert trace(hostile) == trace(control)  # it changes nothing the orchestrator does
    prompts = judge_prompts(hostile)
    assert prompts
    # The reported model is the only thing that differs between the two runs, and a blind
    # prompt cannot depend on it: the prompts are byte-identical.
    for (name, prompt), (_, control_prompt) in zip(prompts, judge_prompts(control), strict=True):
        assert prompt == control_prompt, name

# ------------------------------------------------------------ redaction boundaries


def _provider_that_fails_with(body, api_key, extra_headers=None, exception=None):
    from conclave.providers.openai_compatible import OpenAICompatibleProvider

    def handler(request):
        if exception is not None:
            raise exception
        return httpx.Response(401, text=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        base_url="https://p.example/v1",
        model="m",
        api_key=api_key,
        extra_headers=extra_headers,
        transient_max_retries=0,
        client=client,
    )


def _error_of(provider):
    import asyncio

    from conclave.providers.base import ProviderError

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.ask("hi"))
    return str(caught.value)


def test_the_api_key_is_redacted_even_when_it_is_short():
    # Below the 8-character floor that applies to ordinary header values. (A one-character
    # key would also garble the text around it, which is why nobody should use one.)
    for key in ["abcd", "sk-12", "sk-12345", KEY]:
        message = _error_of(_provider_that_fails_with(f"bad token {key}, sorry", key))
        assert "bad token [redacted], sorry" in message
        assert key not in message


def test_header_values_are_redacted_by_name_or_length_but_plain_flags_are_not_mangled():
    body = "token=abc org=zz flag=true beta=v2 longvalue=plain-header-value-12345"
    provider = _provider_that_fails_with(
        body,
        "unused-key-1234",
        {
            "X-Api-Token": "abc",  # a credential name: redacted even though it is short
            "Authorization-Org": "zz",  # likewise
            "X-Feature": "true",  # a short, ordinary value: left alone
            "X-Beta": "v2",
            "X-Trace": "plain-header-value-12345",  # long enough to be redacted
        },
    )
    message = _error_of(provider)
    assert "token=[redacted] org=[redacted] flag=true beta=v2 longvalue=[redacted]" in message


def test_overlapping_secrets_are_redacted_longest_first():
    provider = _provider_that_fails_with(
        "got secret-abcdefghij here",
        "abcdefghij",
        {"X-Secret": "secret-abcdefghij"},
    )
    message = _error_of(provider)
    assert "secret-abcdefghij" not in message and "abcdefghij" not in message
    assert "got [redacted] here" in message


def test_a_transport_error_that_mentions_the_key_is_redacted_too():
    provider = _provider_that_fails_with(
        "", KEY, exception=httpx.ConnectError(f"cannot connect, auth was Bearer {KEY}")
    )
    message = _error_of(provider)
    assert KEY not in message and "[redacted]" in message


# ------------- API level: saved rows and run logs for retries and fallback judges


def _projection_of(result):
    def stage(item):
        return (item["name"], item["status"]) if item else None

    panel = result["panel"]
    return {
        "delegates": [(d["name"], d["status"]) for d in panel["delegates"]],
        "critic": stage(result["critic"]),
        "arbiter": stage(result["arbiter"]),
        "sources": panel["independent_source_count"],
        "quorum": panel["quorum"]["status"],
        "single_source": result["single_source"],
    }


def _api_scenario(tmp_path, monkeypatch, text, subdir, kind):
    made = {}

    class Counted(FakeProvider):
        calls = 0

        async def ask(self, prompt):
            self.calls += 1
            return await super().ask(prompt)

    def make(response="ok", **kwargs):
        provider = Counted(text if response == "Delegate A response" else response, **kwargs)
        made[response] = provider
        return provider

    monkeypatch.setattr(api_module, "FakeProvider", make)
    (tmp_path / subdir).mkdir()
    store = WorkspaceStore(tmp_path / subdir / "t.db", run_log_dir=tmp_path / subdir / "logs")
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
    body = {
        "question": "What should we do?",
        "delegates": ["demo-a", "demo-b"],
        "critic": "demo-critic",
        "arbiter": "demo-arbiter",
        "minimum_successes": 2,
        "single_source_mode": "return_answer",
    }
    seen = []

    if kind == "fallback_judges":
        # The fallbacks are healthy providers that are not the ones taken down: demo-b answers
        # for the Critic and demo-a for the Arbiter.
        body["critic_fallbacks"] = ["demo-b"]
        body["arbiter_fallbacks"] = ["demo-a"]
        made["Critic demo response"].error = RuntimeError("critic down")
        made["Synthesized demo response"].error = RuntimeError("arbiter down")
        first = client.post("/api/deliberate", json=body)
        seen.append(first)
    elif kind == "delegate_retry":
        made["Delegate B response"].error = RuntimeError("down")  # quorum 2 is unmet at first
        first = client.post("/api/deliberate", json=body)
        made["Delegate B response"].error = None
        run_id = first.headers["X-Conclave-Run-ID"]
        seen += [first, client.post(f"/api/runs/{run_id}/delegates/demo-b/retry")]
    else:  # critic_retry or arbiter_retry
        first = client.post("/api/deliberate", json=body)
        run_id = first.headers["X-Conclave-Run-ID"]
        stage = "critic" if kind == "critic_retry" else "arbiter"
        seen += [first, client.post(f"/api/runs/{run_id}/{stage}/retry")]

    results = [(r.json() if "result" not in r.json() else r.json()["result"]) for r in seen]
    runs = store.list_runs()
    logs = list((tmp_path / subdir / "logs").glob("*.json"))
    return seen, results, runs, logs, {k: v.calls for k, v in made.items()}


API_SCENARIOS = ["critic_retry", "arbiter_retry", "delegate_retry", "fallback_judges"]
API_GRID = [(kind, item["id"]) for kind in API_SCENARIOS for item in FIXTURES]


@pytest.mark.parametrize(("kind", "fixture"), API_GRID, ids=[f"{k}-{f}" for k, f in API_GRID])
def test_retries_and_fallback_judges_save_the_same_rows_and_logs_as_the_control(
    tmp_path, monkeypatch, kind, fixture
):
    item = next(f for f in FIXTURES if f["id"] == fixture)
    seen, results, runs, logs, calls = _api_scenario(tmp_path, monkeypatch, item["text"], "hostile", kind)
    c_seen, c_results, c_runs, c_logs, c_calls = _api_scenario(tmp_path, monkeypatch, BENIGN, "control", kind)
    assert calls == c_calls  # the hostile text bought no extra and no fewer provider calls
    # The targeted stage was really run again, by the endpoint under test.
    critic, arbiter = calls["Critic demo response"], calls["Synthesized demo response"]
    b_calls, a_calls = calls["Delegate B response"], calls["Delegate A response"]
    expected = {
        # (critic, arbiter, demo-b, demo-a)
        "critic_retry": (2, 2, 1, 1),
        "arbiter_retry": (1, 2, 1, 1),
        "delegate_retry": (1, 1, 2, 1),  # demo-b failed once, was retried once
        # each primary failed once; demo-b then answered as Critic and demo-a as Arbiter
        "fallback_judges": (1, 1, 2, 2),
    }[kind]
    assert (critic, arbiter, b_calls, a_calls) == expected, calls
    if kind == "delegate_retry":
        assert results[0]["panel"]["quorum"]["status"] == "unmet" and results[0]["critic"] is None
        assert [d["status"] for d in results[1]["panel"]["delegates"]] == ["succeeded", "succeeded"]

    assert [r.status_code for r in seen] == [r.status_code for r in c_seen]
    assert all(code == 200 for code in (r.status_code for r in seen))
    assert [_projection_of(r) for r in results] == [_projection_of(r) for r in c_results]
    assert len(runs) == len(c_runs) >= 1
    assert len(logs) == len(c_logs) == len(runs)  # one log per saved row
    assert [r.status for r in runs] == [r.status for r in c_runs]
    assert all(r.request.minimum_successes == 2 and r.request.allow_single_source is False for r in runs)
    # the judges really ran (the retry and fallback paths were exercised, not skipped)
    last = results[-1]
    assert last["arbiter"] is not None and last["critic"] is not None
    if kind == "fallback_judges":
        # The fallbacks really answered; the primaries failed and were skipped over.
        assert (last["critic"]["name"], last["critic"]["status"]) == ("demo-b", "succeeded")
        assert (last["arbiter"]["name"], last["arbiter"]["status"]) == ("demo-a", "succeeded")
    else:
        assert last["critic"]["status"] == "succeeded" and last["arbiter"]["status"] == "succeeded"


# ------------------------------------------------- the reason phrase is a secret sink too


def test_a_reason_phrase_that_echoes_the_key_is_redacted():
    from conclave.providers.openai_compatible import OpenAICompatibleProvider

    def handler(request):
        # An empty body makes the adapter fall back to the HTTP reason phrase.
        return httpx.Response(401, text="", extensions={"reason_phrase": f"Bad key {KEY}".encode()})

    provider = OpenAICompatibleProvider(
        base_url="https://p.example/v1",
        model="m",
        api_key=KEY,
        transient_max_retries=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    message = _error_of(provider)
    assert KEY not in message and message.endswith("Bad key [redacted]")
