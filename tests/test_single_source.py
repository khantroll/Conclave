"""P1-1: say what is missing, never present one source as a panel, label it consistently."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import conclave.api as api_module
from conclave.api import create_app
from conclave.config import ConclaveConfig, ProviderConfig
from conclave.models import (
    DeliberationRequest,
    DelegateResult,
    DelegateStatus,
    SourceGroup,
    WorkspaceCreate,
)
from conclave.orchestrator import Orchestrator
from conclave.prompts import build_arbiter_prompt, build_critic_prompt, coverage_note
from conclave.providers.fake import FakeProvider
from conclave.sources import ProviderIdentity
from conclave.store import WorkspaceStore

SIMPLE = "What is the capital of France?"  # the analyzer recommends one delegate
WEB = Path(__file__).resolve().parents[1] / "web"


class Counting(FakeProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    async def ask(self, prompt):
        self.calls += 1
        return await super().ask(prompt)


def ok(name, text="answer", model="m"):
    return DelegateResult(name=name, status=DelegateStatus.SUCCEEDED, raw_response=text, model=model)


def groups(*sets):
    return [SourceGroup(delegates=list(names)) for names in sets]


# ---------- what is missing is stated, with no names or error bodies ----------


def three_with_one_missing(kind):
    missing = {
        "timeout": DelegateResult(name="secret-delegate", status=DelegateStatus.TIMED_OUT, error="SECRET-ERROR-BODY"),
        "empty": DelegateResult(
            name="secret-delegate", status=DelegateStatus.FAILED, error_kind="empty_response", error="SECRET-ERROR-BODY"
        ),
        "failed": DelegateResult(name="secret-delegate", status=DelegateStatus.FAILED, error="SECRET-ERROR-BODY"),
    }[kind]
    return [ok("a"), ok("b"), missing]


@pytest.mark.parametrize(
    ("kind", "word"), [("timeout", "timed out"), ("empty", "empty"), ("failed", "failed")]
)
def test_both_judge_prompts_say_k_of_n_and_the_failure_kind_only(kind, word):
    results = three_with_one_missing(kind)
    sources = groups(["a"], ["b"])
    critic = build_critic_prompt(question="Q?", delegate_results=results, source_groups=sources)
    arbiter = build_arbiter_prompt(question="Q?", delegate_results=results, source_groups=sources)
    for prompt in (critic, arbiter):
        assert "2 of 3 delegates answered; 2 independent sources." in prompt
        assert f"Slot 3 did not answer: {word}." in prompt
        assert "secret-delegate" not in prompt
        assert "SECRET-ERROR-BODY" not in prompt


def test_coverage_note_without_source_groups_does_not_invent_a_source_count():
    note = coverage_note([ok("a"), ok("b"), three_with_one_missing("failed")[2]], None)
    assert note.startswith("2 of 3 delegates answered.")
    assert "independent source" not in note


def test_coverage_note_singular_wording():
    assert coverage_note([ok("a")], groups(["a"])) == "1 of 1 delegates answered; 1 independent source."


def test_all_delegates_answering_adds_no_missing_slots():
    note = coverage_note([ok("a"), ok("b")], groups(["a"], ["b"]))
    assert note == "2 of 2 delegates answered; 2 independent sources."


# ---------- orchestration: one source skips the Critic and follows the mode ----------


def build(modes_calls=None, identities=None, n=1, same=False):
    providers = {
        "critic": Counting("critique"),
        "arbiter": Counting("assessment"),
    }
    delegates = []
    for i in range(n):
        name = f"d{i}"
        providers[name] = Counting(f"answer {i}", model="m1" if same else f"m{i}")
        delegates.append(name)
    idents = None
    if same:
        idents = {name: ProviderIdentity(base_url="https://x.example/v1", model="m1") for name in delegates}
    return Orchestrator(providers, idents), providers, delegates


def request_for(delegates, mode, **extra):
    return DeliberationRequest(
        question="q", delegates=delegates, critic="critic", arbiter="arbiter", single_source_mode=mode, **extra
    )


async def test_one_delegate_return_answer_costs_exactly_one_call():
    orchestrator, providers, delegates = build(n=1)
    result = await orchestrator.deliberate(request_for(delegates, "return_answer"))
    assert [providers[k].calls for k in ("d0", "critic", "arbiter")] == [1, 0, 0]
    assert result.single_source is True
    assert result.critic is None and result.arbiter is None
    assert result.single_source_answer.delegate == "d0"
    assert result.single_source_answer.text == "answer 0"
    assert "Single source" in result.single_source_label


async def test_one_delegate_arbiter_single_source_costs_two_calls_and_never_the_critic():
    orchestrator, providers, delegates = build(n=1)
    result = await orchestrator.deliberate(request_for(delegates, "arbiter_single_source"))
    assert [providers[k].calls for k in ("d0", "critic", "arbiter")] == [1, 0, 1]
    assert result.critic is None and result.single_source_answer is None
    prompt = result.arbiter.prompt
    assert result.single_source_label in prompt
    assert "Assess the single response" in prompt
    assert "Produce the final answer for the user" not in prompt  # no synthesis framing


async def test_two_delegates_of_one_source_are_a_single_source_run():
    orchestrator, providers, delegates = build(n=2, same=True)
    result = await orchestrator.deliberate(request_for(delegates, "return_answer"))
    assert result.panel.independent_source_count == 1
    assert result.single_source is True
    assert providers["critic"].calls == 0 and providers["arbiter"].calls == 0


async def test_independent_sources_still_get_the_critic_and_arbiter():
    orchestrator, providers, delegates = build(n=2)
    result = await orchestrator.deliberate(request_for(delegates, "return_answer"))
    assert result.single_source is False and result.single_source_label is None
    assert result.critic is not None and result.arbiter is not None
    assert result.single_source_answer is None
    assert "2 of 2 delegates answered" in result.critic.prompt
    assert "2 of 2 delegates answered" in result.arbiter.prompt


async def test_one_of_three_failing_is_disclosed_to_both_judges():
    orchestrator, providers, delegates = build(n=3)
    providers["d2"].error = RuntimeError("SECRET-ERROR-BODY d2 down")
    result = await orchestrator.deliberate(request_for(delegates, "return_answer"))
    for stage in (result.critic, result.arbiter):
        assert "2 of 3 delegates answered; 2 independent sources." in stage.prompt
        assert "Slot 3 did not answer: failed." in stage.prompt
        assert "d2" not in stage.prompt  # the failed delegate is not named
        assert "SECRET-ERROR-BODY" not in stage.prompt


async def test_stage_callbacks_for_a_single_source_run_end_with_the_answer():
    orchestrator, providers, delegates = build(n=1)
    seen = []

    async def on_stage(result):
        seen.append((result.arbiter is not None, result.single_source_answer is not None))

    await orchestrator.deliberate(request_for(delegates, "return_answer"), on_stage=on_stage)
    assert seen == [(False, False), (False, True)]


async def test_retries_follow_the_single_source_rules():
    orchestrator, providers, delegates = build(n=1)
    returned = await orchestrator.deliberate(request_for(delegates, "return_answer"))
    with pytest.raises(ValueError, match="does not use the Critic"):
        await orchestrator.retry_critic(
            request=request_for(delegates, "return_answer"), prior_result=returned
        )
    with pytest.raises(ValueError, match="no Arbiter to retry"):
        await orchestrator.retry_arbiter(
            request=request_for(delegates, "return_answer"), prior_result=returned
        )
    # With the Arbiter mode, an Arbiter retry works and keeps the same label.
    assessed = await orchestrator.deliberate(request_for(delegates, "arbiter_single_source"))
    again = await orchestrator.retry_arbiter(
        request=request_for(delegates, "arbiter_single_source"), prior_result=assessed
    )
    assert again.single_source_label == assessed.single_source_label
    assert again.single_source_label in again.arbiter.prompt


async def test_retrying_a_delegate_into_a_single_source_run_follows_the_mode():
    orchestrator, providers, delegates = build(n=2)
    request = request_for(delegates, "return_answer", minimum_successes=1)
    providers["d1"].error = RuntimeError("down")
    first = await orchestrator.deliberate(request)
    assert first.single_source is True and first.single_source_answer.delegate == "d0"
    providers["d1"].error = None
    retried = await orchestrator.retry_delegate(request=request, prior_result=first, delegate_name="d1")
    assert retried.single_source is False  # two independent sources now
    assert retried.critic is not None and retried.arbiter is not None


# ---------- the permission and the mode are separate, and the label is consistent ----------


def provider(name, model="m", url="https://api.example.com/v1", priority=100):
    return ProviderConfig(name=name, base_url=url, model=model, priority=priority)


@pytest.fixture
def make(tmp_path, monkeypatch):
    def build_app(configs):
        fakes = {}

        def fake_providers(provider_configs):
            out = {}
            for config in provider_configs:
                fakes[config.name] = Counting(f"answer from {config.name}", model=config.model)
                out[config.name] = fakes[config.name]
            return out

        monkeypatch.setattr(api_module, "build_providers", fake_providers)
        store = WorkspaceStore(tmp_path / "t.db")
        app = create_app(config=ConclaveConfig(providers=configs), workspace_store=store)
        return TestClient(app), store, fakes

    return build_app


def ws(delegates, quorum, mode="return_answer", **extra):
    return {
        "name": "w",
        "delegates": delegates,
        "arbiter": "demo-arbiter",
        "critic": "demo-critic",
        "minimum_successes": quorum,
        "single_source_mode": mode,
        **extra,
    }


def deliberate(client, body, question=SIMPLE):
    created = client.post("/api/workspaces", json=body).json()
    return client.post(f"/api/workspaces/{created['id']}/deliberate", json={"question": question})


@pytest.mark.parametrize("mode", ["return_answer", "arbiter_single_source"])
def test_the_mode_can_never_permit_a_below_quorum_run(make, mode):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m1")])  # one source
    response = deliberate(client, ws(["p1", "p2"], 2, mode))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "quorum_unmet"
    assert all(f.calls == 0 for f in fakes.values())
    assert store.list_runs() == []
    direct = client.post(
        "/api/deliberate",
        json={
            "question": "q", "delegates": ["p1", "p2"], "arbiter": "demo-arbiter",
            "minimum_successes": 2, "single_source_mode": mode,
        },
    )
    assert direct.status_code == 422


def test_defaults_deny_single_source_runs():
    assert WorkspaceCreate(name="w", delegates=["a"], arbiter="x").allow_single_source is False
    request = DeliberationRequest(question="q", delegates=["a"], arbiter="x")
    assert request.allow_single_source is False
    assert request.single_source_mode == "return_answer"


@pytest.mark.parametrize("mode", ["return_answer", "arbiter_single_source"])
def test_explicit_permission_is_identified_the_same_way_everywhere(make, mode):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m1")])
    response = deliberate(client, ws(["p1", "p2"], 2, mode, allow_single_source=True))
    assert response.status_code == 200
    body = response.json()
    label = body["single_source_label"]
    assert body["single_source"] is True
    assert "explicitly permitted" in label and "allow_single_source" in label
    assert "quorum of 2 independent sources was NOT met" in label
    assert body["panel"]["quorum"]["status"] == "single_source_override"
    assert "Quorum met" not in body["panel"]["quorum"]["summary"]

    saved = store.get_run(response.headers["X-Conclave-Run-ID"])
    assert saved.result.single_source_label == label  # the saved result
    if mode == "arbiter_single_source":
        assert label in saved.result.arbiter.prompt  # the Arbiter
    else:
        assert saved.result.single_source_answer is not None
    # the console shows the server's sentence verbatim rather than composing its own
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "result.single_source_label" in js and "single_source_answer" in js


def test_a_met_quorum_of_one_is_a_single_source_run_but_not_an_override(make):
    client, store, fakes = make([provider("p1", "m1")])
    body = deliberate(client, ws(["p1"], 1)).json()
    assert body["single_source"] is True
    assert body["panel"]["quorum"]["status"] == "met"
    assert body["single_source_label"].startswith("Single source: only 1 independent source")
    assert "explicitly permitted" not in body["single_source_label"]


def test_auto_select_on_a_simple_question_costs_at_most_two_calls(make):
    for mode, expected in (("return_answer", 1), ("arbiter_single_source", 2)):
        client, store, fakes = make([provider("p1", "m1"), provider("p2", "m2")])
        response = deliberate(client, ws(["p1", "p2"], 1, mode, auto_select_delegates=True))
        assert response.status_code == 200
        provider_calls = sum(f.calls for f in fakes.values())
        # demo-arbiter is a built-in fake, so count the Arbiter through the result.
        arbiter_calls = 1 if response.json()["arbiter"] else 0
        assert provider_calls + arbiter_calls == expected, mode


# ---------- the choice is explicit, stored, and old databases read as return_answer ----------


def test_saving_a_workspace_requires_an_explicit_single_source_mode(tmp_path):
    client = TestClient(create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(tmp_path / "t.db")))
    body = {"name": "w", "delegates": ["demo-a"], "arbiter": "demo-arbiter", "critic": None}
    refused = client.post("/api/workspaces", json=body)
    assert refused.status_code == 422
    assert "single_source_mode is required" in refused.json()["detail"]
    assert "does not allow single-source runs" in refused.json()["detail"]
    bad = client.post("/api/workspaces", json={**body, "single_source_mode": "whatever"})
    assert bad.status_code == 422
    created = client.post("/api/workspaces", json={**body, "single_source_mode": "arbiter_single_source"})
    assert created.status_code == 201
    assert created.json()["single_source_mode"] == "arbiter_single_source"
    assert created.json()["allow_single_source"] is False  # choosing a mode permits nothing
    replaced = client.put(f"/api/workspaces/{created.json()['id']}", json=body)
    assert replaced.status_code == 422  # a full replace must choose again


def test_single_source_mode_is_stored_and_legacy_rows_default_to_return_answer(tmp_path):
    path = tmp_path / "w.db"
    store = WorkspaceStore(path)
    saved = store.create(
        WorkspaceCreate(name="w", delegates=["a"], arbiter="x", single_source_mode="arbiter_single_source")
    )
    assert store.get(saved.id).single_source_mode == "arbiter_single_source"
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE workspaces DROP COLUMN single_source_mode")  # a pre-P1-1 database
    conn.execute("DELETE FROM schema_version")  # unversioned, as such a database was
    conn.commit()
    conn.close()
    assert WorkspaceStore(path).get(saved.id).single_source_mode == "return_answer"


def test_console_form_makes_the_choice_mandatory_and_separate_from_the_permission():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="workspaceSingleSourceMode" required' in html
    assert 'id="workspaceAllowSingleSource"' in html
    assert "does not allow one" in html


# ---------- runs saved before source counting are recounted on retry ----------


def legacy_panel(question="q", names=("a", "b"), models=("m1", "m2")):
    from conclave.models import DeliberationResult, PanelResult

    delegates = [ok(n, text=f"answer {n}", model=m) for n, m in zip(names, models, strict=True)]
    panel = PanelResult(
        question=question,
        delegates=delegates,
        successful_count=len(delegates),
        failed_count=0,
        synthesizeable=True,
    )
    assert panel.independent_source_count is None and panel.quorum is None and panel.sources == []
    return DeliberationResult(panel=panel)


async def test_legacy_run_retry_is_recounted_and_prompted_with_the_source_count():
    providers = {"critic": FakeProvider("crit"), "arbiter": FakeProvider("final")}
    orchestrator = Orchestrator(providers, {})
    request = request_for(["a", "b"], "return_answer")
    again = await orchestrator.retry_arbiter(request=request, prior_result=legacy_panel())
    assert again.panel.independent_source_count == 2 and again.panel.quorum.status == "met"
    assert "2 of 2 delegates answered; 2 independent sources." in again.arbiter.prompt
    retried = await orchestrator.retry_critic(request=request, prior_result=legacy_panel())
    assert "2 of 2 delegates answered; 2 independent sources." in retried.critic.prompt
    assert "2 of 2 delegates answered; 2 independent sources." in retried.arbiter.prompt


async def test_legacy_run_that_counted_one_source_twice_is_judged_by_todays_rules():
    # Saved when two entries for one model counted as two corroborating answers.
    same = {n: ProviderIdentity(base_url="https://x.example/v1", model="m1") for n in "ab"}
    orchestrator = Orchestrator({"critic": FakeProvider("c"), "arbiter": FakeProvider("z")}, same)
    quorum_two = request_for(["a", "b"], "arbiter_single_source", minimum_successes=2)
    with pytest.raises(ValueError, match="does not satisfy quorum"):
        await orchestrator.retry_arbiter(request=quorum_two, prior_result=legacy_panel(models=("m1", "m1")))
    # With a quorum of 1 it is a single-source run, so the retry follows the single-source rules.
    quorum_one = request_for(["a", "b"], "return_answer")
    with pytest.raises(ValueError, match="does not use the Critic"):
        await orchestrator.retry_critic(request=quorum_one, prior_result=legacy_panel(models=("m1", "m1")))
    assessed = await orchestrator.retry_arbiter(
        request=request_for(["a", "b"], "arbiter_single_source"),
        prior_result=legacy_panel(models=("m1", "m1")),
    )
    assert assessed.single_source and assessed.single_source_label in assessed.arbiter.prompt


def run_describe_refresh(cases):
    """Run the console's real describeRefresh (web/render.js) in Node on result-shaped objects."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "const render = require(process.argv[1]);"
        "const cases = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(cases.map(c => render.describeRefresh(c.result, c.stage))));"
    )
    done = subprocess.run(
        [node, "-e", script, str(WEB / "render.js"), json.dumps(cases)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_console_describes_every_retry_from_the_returned_result():
    def result(**extra):
        return {"single_source": False, "panel": {"synthesizeable": True}, "critic": {}, **extra}

    cases = [
        {"stage": "delegate", "result": result(single_source=True, single_source_answer={"text": "x"}, critic=None)},
        {"stage": "delegate", "result": result(single_source=True, critic=None)},
        {"stage": "delegate", "result": result(panel={"synthesizeable": False}, critic=None)},
        {"stage": "delegate", "result": result()},
        {"stage": "critic", "result": result()},
        {"stage": "arbiter", "result": result()},
        {"stage": "arbiter", "result": result(single_source=True, critic=None)},
        {"stage": "delegate", "result": result(critic=None)},
    ]
    said = run_describe_refresh(cases)
    assert said[0] == "single-source answer returned; no Critic or Arbiter ran"
    assert said[1] == "the Arbiter assessed the single source; no Critic ran"
    assert said[2] == "quorum is still not met, so no Critic or Arbiter ran"
    assert said[3] == "Critic and Arbiter refreshed"
    assert said[4] == "Critic and Arbiter refreshed"
    assert said[5] == "Arbiter refreshed; the panel and Critic were kept"
    assert said[6] == "the Arbiter assessed the single source; no Critic ran"
    assert said[7] == "Arbiter refreshed"


def test_every_retry_handler_uses_describe_refresh_and_none_asserts_success_blindly():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert js.count("describeRefresh(run.result") == 2
    assert "Critic retried and Arbiter refreshed." not in js
    assert "; Critic and Arbiter refreshed.${cost" not in js
