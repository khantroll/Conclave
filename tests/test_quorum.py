"""Quorum is never lowered: top up from the pool, stop clearly, or run labelled."""

import pytest
from fastapi.testclient import TestClient

import conclave.api as api_module
from conclave.api import create_app
from conclave.config import ConclaveConfig, ProviderConfig
from conclave.models import DelegateResult, DelegateStatus, SourceGroup
from conclave.providers.fake import FakeProvider
from conclave.quorum import QuorumUnmet, evaluate_quorum, plan_delegates
from conclave.sources import ProviderIdentity
from conclave.store import WorkspaceStore

SIMPLE = "What is the capital of France?"  # the analyzer recommends a single delegate


class Counting(FakeProvider):
    calls = 0

    async def ask(self, prompt):
        type(self).calls += 1
        self.calls_here = getattr(self, "calls_here", 0) + 1
        return await super().ask(prompt)


def provider(name, model="m", url="https://api.example.com/v1", priority=100, key_env=None):
    return ProviderConfig(
        name=name, base_url=url, model=model, priority=priority, api_key_env=key_env
    )


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Build an app whose configured providers are fakes. Returns (client, store, fakes)."""

    def build(configs, behaviours=None):
        behaviours = behaviours or {}
        fakes = {}

        def fake_providers(provider_configs):
            from conclave.providers.unavailable import UnavailableProvider

            out = {}
            for config in provider_configs:
                if config.api_key_env:  # no such variable in the test environment
                    out[config.name] = UnavailableProvider(
                        f"requires environment variable {config.api_key_env}"
                    )
                    continue
                behaviour = behaviours.get(config.name, {})
                fakes[config.name] = Counting(
                    behaviour.get("text", f"answer from {config.name}"),
                    model=behaviour.get("reported", config.model),
                    error=behaviour.get("error"),
                )
                out[config.name] = fakes[config.name]
            return out

        monkeypatch.setattr(api_module, "build_providers", fake_providers)
        store = WorkspaceStore(tmp_path / "t.db")
        app = create_app(config=ConclaveConfig(providers=configs), workspace_store=store)
        return TestClient(app), store, fakes

    return build


def workspace_body(delegates, quorum, **extra):
    return {
        "name": "w",
        "delegates": delegates,
        "arbiter": "demo-arbiter",
        "critic": "demo-critic",
        "minimum_successes": quorum,
        **extra,
    }


def run(client, body, question=SIMPLE):
    ws = client.post("/api/workspaces", json=body).json()
    return client.post(f"/api/workspaces/{ws['id']}/deliberate", json={"question": question})


# ---------- pure planning ----------


def ident(model, url="https://api.example.com/v1", alias=False):
    return ProviderIdentity(base_url=url, model=model, router_alias=alias)


def plan(selected, pool, extra, required, identities, allow=False, unavailable=(), drop=False):
    return plan_delegates(
        selected=selected,
        pool=pool,
        ranked_extra=extra,
        is_eligible=lambda n: n not in unavailable,
        ineligible_reason=lambda n: "missing credentials",
        identities=identities,
        required=required,
        allow_single_source=allow,
        drop_ineligible=drop,
    )


def test_top_up_adds_only_what_is_needed_in_rank_order():
    identities = {n: ident(n) for n in "abcd"}
    result = plan(["a"], list("abcd"), ["a", "b", "c", "d"], 3, identities)
    assert result.delegates == ["a", "b", "c"]
    assert result.topped_up == ["b", "c"]
    assert result.expected_sources == 3


def test_top_up_skips_candidates_that_only_duplicate_a_source():
    identities = {"a": ident("m1"), "b": ident("m1"), "c": ident("m2")}
    result = plan(["a"], ["a", "b", "c"], ["a", "b", "c"], 2, identities)
    assert result.delegates == ["a", "c"]
    assert result.topped_up == ["c"]


def test_top_up_never_uses_unavailable_providers():
    identities = {n: ident(n) for n in "abc"}
    result = plan(["a"], list("abc"), ["a", "b", "c"], 2, identities, unavailable={"b"})
    assert result.delegates == ["a", "c"]


def test_an_ineligible_initial_pick_does_not_count_toward_quorum():
    identities = {n: ident(n) for n in "abc"}
    result = plan(["b"], list("abc"), ["a", "b", "c"], 1, identities, unavailable={"b"})
    assert "a" in result.delegates and result.expected_sources == 1


def test_automatic_selection_drops_an_ineligible_pick_instead_of_dispatching_it():
    identities = {n: ident(n) for n in "abc"}
    dropped = plan(["b"], list("abc"), ["a", "c"], 1, identities, unavailable={"b"}, drop=True)
    assert dropped.delegates == ["a"]
    # A panel the user listed explicitly keeps it, so its failure stays visible.
    kept = plan(["b"], list("abc"), ["a", "c"], 1, identities, unavailable={"b"}, drop=False)
    assert kept.delegates == ["b", "a"]


def test_exhausted_pool_raises_with_required_available_and_why():
    identities = {"a": ident("m1"), "b": ident("m1"), "c": ident("m2"), "d": ident("m3")}
    with pytest.raises(QuorumUnmet) as caught:
        plan(["a"], list("abcd"), list("abcd"), 4, identities, unavailable={"d"})
    detail = caught.value.detail
    assert detail["code"] == "quorum_unmet"
    assert detail["required_sources"] == 4 and detail["available_sources"] == 2
    assert detail["unavailable"] == {"d": "missing credentials"}
    assert detail["shared_sources"] == [["a", "b"]]
    assert "No provider was called" in detail["message"]
    assert "a, b use the same configured model" in detail["message"]
    assert "d (missing credentials)" in detail["message"]


def test_single_source_override_only_when_exactly_one_source_is_reachable():
    one = {"a": ident("m1"), "b": ident("m1")}
    result = plan(["a", "b"], ["a", "b"], ["a", "b"], 2, one, allow=True)
    assert result.single_source and result.delegates == ["a"]
    two = {"a": ident("m1"), "b": ident("m2")}
    with pytest.raises(QuorumUnmet):
        plan(["a"], ["a", "b"], ["a", "b"], 3, two, allow=True)
    with pytest.raises(QuorumUnmet):
        plan([], ["a"], [], 2, {"a": ident("m1")}, allow=True, unavailable={"a"})


def test_single_source_override_keeps_an_explicitly_listed_unavailable_delegate_visible():
    identities = {"good": ident("m1"), "bad": ident("m2")}
    kept = plan(["good", "bad"], ["good", "bad"], [], 2, identities, allow=True, unavailable={"bad"})
    assert kept.single_source and kept.delegates == ["good", "bad"]
    # An automatic selection never dispatches it.
    dropped = plan(
        ["good", "bad"], ["good", "bad"], [], 2, identities, allow=True, unavailable={"bad"}, drop=True
    )
    assert dropped.delegates == ["good"]


def test_the_single_source_hint_is_only_offered_when_it_would_help():
    one = {"a": ident("m1"), "b": ident("m1")}
    with pytest.raises(QuorumUnmet) as caught:
        plan(["a"], ["a", "b"], ["a", "b"], 2, one)
    assert "enable single-source runs" in caught.value.detail["message"]
    assert "will not count as meeting the quorum" in caught.value.detail["message"]


# ---------- judging by answers actually received ----------


def ok(name):
    return DelegateResult(name=name, status=DelegateStatus.SUCCEEDED, raw_response="x", model="m")


def test_evaluate_quorum_met_unmet_and_override_wording():
    a, b = ok("a"), ok("b")
    both = [SourceGroup(delegates=["a"]), SourceGroup(delegates=["b"])]
    met = evaluate_quorum(required=2, delegates=[a, b], sources=both)
    assert met.status == "met" and met.qualifying_sources == 2

    failed = DelegateResult(name="b", status=DelegateStatus.TIMED_OUT, error="Timed out")
    one = [SourceGroup(delegates=["a"])]
    unmet = evaluate_quorum(required=2, delegates=[a, failed], sources=one)
    assert unmet.status == "unmet"
    assert "Quorum unmet: 2 independent source(s) required, 1 received" in unmet.summary
    assert "1 of 2 delegates produced an answer" in unmet.summary
    assert "b timed out" in unmet.summary and "were not run" in unmet.summary

    override = evaluate_quorum(required=2, delegates=[a, failed], sources=one, allow_single_source=True)
    assert override.status == "single_source_override"
    assert "Quorum NOT met" in override.summary and "not a consensus" in override.summary
    assert "Quorum met" not in override.summary


def test_empty_response_and_shared_source_are_explained():
    empty = DelegateResult(
        name="c", status=DelegateStatus.FAILED, error_kind="empty_response", error="empty"
    )
    shared = SourceGroup(delegates=["a", "b"], reason="same_reported_model")
    report = evaluate_quorum(
        required=3, delegates=[ok("a"), ok("b"), empty], sources=[shared]
    )
    assert "c returned an empty response" in report.summary
    assert "a, b count as one source (same reported model)" in report.summary


# ---------- end to end through the API ----------


def test_auto_select_tops_up_from_the_pool_and_keeps_the_configured_quorum(make):
    client, store, fakes = make(
        [provider("p1", "m1", priority=10), provider("p2", "m2", priority=20), provider("p3", "m3", priority=30)]
    )
    response = run(client, workspace_body(["p1", "p2", "p3"], 2, auto_select_delegates=True))
    assert response.status_code == 200
    saved = store.get_run(response.headers["X-Conclave-Run-ID"])
    # The simple question selects one delegate; quorum 2 forces exactly one top-up.
    assert saved.request.delegates == ["p1", "p2"]
    assert saved.request.minimum_successes == 2
    assert saved.request.selection.auto_selected == ["p1"]
    assert saved.request.selection.topped_up == ["p2"]
    assert saved.result.panel.quorum.status == "met"
    assert saved.result.panel.independent_source_count == 2
    assert getattr(fakes["p3"], "calls_here", 0) == 0  # no more than needed


def test_top_up_does_not_inflate_sources_with_a_same_model_delegate(make):
    client, store, fakes = make(
        [provider("p1", "m1", priority=10), provider("p2", "m1", priority=20), provider("p3", "m3", priority=30)]
    )
    response = run(client, workspace_body(["p1", "p2", "p3"], 2, auto_select_delegates=True))
    assert response.status_code == 200
    saved = store.get_run(response.headers["X-Conclave-Run-ID"])
    assert saved.request.delegates == ["p1", "p3"]  # p2 would only repeat p1's source
    assert saved.result.panel.quorum.status == "met"


def test_exhausted_pool_stops_before_any_call_and_explains(make):
    # Three delegates, but p3 repeats p2's model: only two independent sources exist.
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m2"), provider("p3", "m2")])
    Counting.calls = 0
    response = run(client, workspace_body(["p1", "p2", "p3"], 3, auto_select_delegates=True))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "quorum_unmet"
    assert detail["required_sources"] == 3 and detail["available_sources"] == 2
    assert detail["shared_sources"] == [["p2", "p3"]]
    assert "Quorum unmet" in detail["message"] and "No provider was called" in detail["message"]
    assert Counting.calls == 0
    assert store.list_runs() == []


def test_duplicate_sources_in_the_pool_do_not_satisfy_the_quorum(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m1", "HTTPS://API.EXAMPLE.COM/v1/")])
    Counting.calls = 0
    for auto in (True, False):
        response = run(client, workspace_body(["p1", "p2"], 2, auto_select_delegates=auto))
        assert response.status_code == 422, auto
        detail = response.json()["detail"]
        assert detail["available_sources"] == 1
        assert detail["shared_sources"] == [["p1", "p2"]]
    assert Counting.calls == 0


def test_unavailable_providers_are_not_eligible_and_are_reported(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m2", key_env="NO_SUCH_KEY")])
    response = run(client, workspace_body(["p1", "p2"], 2))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["available_sources"] == 1
    assert "NO_SUCH_KEY" in detail["unavailable"]["p2"]
    assert "p2 (" in detail["message"]


def test_a_delegate_failing_after_selection_leaves_the_quorum_unmet(make):
    client, store, fakes = make(
        [provider("p1", "m1"), provider("p2", "m2")],
        {"p2": {"error": RuntimeError("upstream exploded")}},
    )
    response = run(client, workspace_body(["p1", "p2"], 2))
    assert response.status_code == 200  # selection was fine; the answers were not
    body = response.json()
    assert body["panel"]["synthesizeable"] is False
    quorum = body["panel"]["quorum"]
    assert quorum["status"] == "unmet" and quorum["qualifying_sources"] == 1
    assert quorum["responses_received"] == 1 and quorum["delegates_attempted"] == 2
    assert "p2 failed: upstream exploded" in quorum["summary"]
    assert body["critic"] is None and body["arbiter"] is None
    assert fakes["p1"].calls_here == 1


def test_an_empty_answer_after_selection_does_not_count(make):
    client, store, fakes = make(
        [provider("p1", "m1"), provider("p2", "m2")], {"p2": {"text": "   "}}
    )
    body = run(client, workspace_body(["p1", "p2"], 2)).json()
    assert body["panel"]["quorum"]["status"] == "unmet"
    assert "p2 returned an empty response" in body["panel"]["quorum"]["summary"]


def test_selected_sources_that_report_the_same_model_collapse_at_the_final_check(make):
    # Two different configurations look independent beforehand, but both report one model.
    client, store, fakes = make(
        [provider("p1", "alias-1", "https://one.example/v1"), provider("p2", "alias-2", "https://two.example/v1")],
        {"p1": {"reported": "openai/gpt-x"}, "p2": {"reported": "gpt-x-2026-08-06"}},
    )
    body = run(client, workspace_body(["p1", "p2"], 2)).json()
    quorum = body["panel"]["quorum"]
    assert quorum["status"] == "unmet" and quorum["qualifying_sources"] == 1
    assert "p1, p2 count as one source (same reported model)" in quorum["summary"]


def test_single_source_run_needs_the_explicit_setting_and_is_labelled(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m1")])
    refused = run(client, workspace_body(["p1", "p2"], 2))
    assert refused.status_code == 422

    Counting.calls = 0
    allowed = run(client, workspace_body(["p1", "p2"], 2, allow_single_source=True))
    assert allowed.status_code == 200
    body = allowed.json()
    quorum = body["panel"]["quorum"]
    assert quorum["status"] == "single_source_override"
    assert quorum["required"] == 2 and quorum["qualifying_sources"] == 1
    assert "Quorum NOT met" in quorum["summary"] and "Quorum met" not in quorum["summary"]
    assert len(body["panel"]["delegates"]) == 1  # one source, so one call, not two
    saved = store.get_run(allowed.headers["X-Conclave-Run-ID"])
    assert saved.request.minimum_successes == 2  # the configured quorum is untouched
    assert saved.request.allow_single_source and saved.request.selection.single_source


def test_override_does_not_cover_two_sources_when_three_are_required(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m2"), provider("p3", "m2")])
    response = run(client, workspace_body(["p1", "p2", "p3"], 3, allow_single_source=True))
    assert response.status_code == 422
    assert response.json()["detail"]["available_sources"] == 2


def test_override_also_applies_when_only_one_source_answers(make):
    client, store, fakes = make(
        [provider("p1", "m1"), provider("p2", "m2")],
        {"p2": {"error": RuntimeError("down")}},
    )
    body = run(client, workspace_body(["p1", "p2"], 2, allow_single_source=True)).json()
    assert body["panel"]["quorum"]["status"] == "single_source_override"
    assert body["panel"]["synthesizeable"] is True
    assert body["arbiter"] is not None


def test_direct_endpoint_applies_the_same_check_and_override(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m1")])
    body = {"question": "q", "delegates": ["p1", "p2"], "arbiter": "demo-arbiter", "minimum_successes": 2}
    refused = client.post("/api/deliberate", json=body)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "quorum_unmet"
    assert store.list_runs() == []
    allowed = client.post("/api/deliberate", json={**body, "allow_single_source": True})
    assert allowed.status_code == 200
    assert allowed.json()["panel"]["quorum"]["status"] == "single_source_override"


def test_retrying_a_failed_delegate_re_evaluates_the_quorum(make):
    client, store, fakes = make(
        [provider("p1", "m1"), provider("p2", "m2")],
        {"p2": {"error": RuntimeError("flaky")}},
    )
    first = run(client, workspace_body(["p1", "p2"], 2))
    run_id = first.headers["X-Conclave-Run-ID"]
    assert first.json()["panel"]["quorum"]["status"] == "unmet"
    fakes["p2"].error = None  # the provider recovers
    retried = client.post(f"/api/runs/{run_id}/delegates/p2/retry").json()
    assert retried["result"]["panel"]["quorum"]["status"] == "met"
    assert retried["result"]["arbiter"] is not None


def test_allow_single_source_is_stored_with_the_workspace_and_migrates(tmp_path):
    import sqlite3

    from conclave.models import WorkspaceCreate

    path = tmp_path / "w.db"
    store = WorkspaceStore(path)
    created = store.create(
        WorkspaceCreate(name="w", delegates=["demo-a"], arbiter="demo-arbiter", allow_single_source=True)
    )
    assert store.get(created.id).allow_single_source is True
    plain = store.create(WorkspaceCreate(name="p", delegates=["demo-a"], arbiter="demo-arbiter"))
    assert store.get(plain.id).allow_single_source is False

    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE workspaces DROP COLUMN allow_single_source")  # a pre-change database
    conn.commit()
    conn.close()
    reopened = WorkspaceStore(path)
    assert reopened.get(created.id).allow_single_source is False  # default: not allowed
    assert reopened.get(plain.id).allow_single_source is False


def test_auto_select_does_not_dispatch_an_unavailable_top_pick(make):
    client, store, fakes = make(
        [provider("p1", "m1", priority=10, key_env="NO_SUCH_KEY"), provider("p2", "m2", priority=20)]
    )
    response = run(client, workspace_body(["p1", "p2"], 1, auto_select_delegates=True))
    assert response.status_code == 200
    saved = store.get_run(response.headers["X-Conclave-Run-ID"])
    assert saved.request.delegates == ["p2"]
    assert saved.request.selection.auto_selected == ["p1"]
    assert saved.request.selection.skipped_unavailable == ["p1"]
    assert saved.request.selection.topped_up == ["p2"]
    assert saved.result.panel.quorum.status == "met"


def test_direct_endpoint_reports_quorum_unmet_even_when_the_quorum_exceeds_the_list(make):
    client, store, fakes = make([provider("p1", "m1")])
    body = {"question": "q", "delegates": ["p1"], "arbiter": "demo-arbiter", "minimum_successes": 2}
    refused = client.post("/api/deliberate", json=body)
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "quorum_unmet" and detail["required_sources"] == 2
    assert detail["available_sources"] == 1
    allowed = client.post("/api/deliberate", json={**body, "allow_single_source": True})
    assert allowed.status_code == 200
    assert allowed.json()["panel"]["quorum"]["status"] == "single_source_override"


def test_single_source_run_of_a_fixed_panel_still_reports_the_unavailable_delegate(make):
    client, store, fakes = make([provider("p1", "m1"), provider("p2", "m2", key_env="NO_SUCH_KEY")])
    body = run(client, workspace_body(["p1", "p2"], 2, allow_single_source=True)).json()
    quorum = body["panel"]["quorum"]
    assert quorum["status"] == "single_source_override"
    assert [d["name"] for d in body["panel"]["delegates"]] == ["p1", "p2"]
    assert "p2 failed" in quorum["summary"] and "NO_SUCH_KEY" in quorum["summary"]
