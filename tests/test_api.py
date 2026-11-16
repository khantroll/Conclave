from fastapi.testclient import TestClient

from conclave.api import create_app
from conclave.config import ConclaveConfig
from conclave.store import WorkspaceStore


def make_app(store: WorkspaceStore):
    return create_app(config=ConclaveConfig(), workspace_store=store)


def test_web_console_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Conclave" in response.text
    assert "/static/app.js" in response.text


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider_count"] >= 4
    assert body["demo_provider_count"] >= 4
    assert body["configured_provider_count"] == 0
    assert body["demo_only"] is True


def test_request_analysis_recommends_panel_for_complex_question(client):
    response = client.post(
        "/api/analyze",
        json={
            "question": (
                "Compare two architecture strategies, identify implementation risks, "
                "failure modes, tradeoffs, and recommend a roadmap with evidence."
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommended_delegate_count"] >= 3
    assert body["complexity"] in {"complex", "deep"}


def test_provider_connection_test(client):
    response = client.post("/api/providers/demo-a/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["model"] == "fake-model"


def test_all_configured_providers_endpoint(client):
    response = client.post("/api/providers/test-all")
    assert response.status_code == 200
    assert response.json() == []


def test_unknown_provider_connection_test_is_404(client):
    response = client.post("/api/providers/not-real/test")
    assert response.status_code == 404


def test_provider_names(client):
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "demo-a" in providers
    assert "demo-b" in providers
    assert "demo-critic" in providers
    assert "demo-arbiter" in providers
    descriptors = {item["name"]: item for item in response.json()["descriptors"]}
    assert "reasoning" in descriptors["demo-a"]["capabilities"]
    assert "critical" in descriptors["demo-b"]["capabilities"]


def test_demo_deliberation_runs_panel_critic_and_arbiter(client):
    response = client.post(
        "/api/deliberate",
        json={
            "question": "Should Conclave survive partial failures?",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "roles": {
                "demo-a": "Focus on reliability.",
                "demo-b": "Challenge the architecture.",
            },
            "workspace_context": "Conclave is a deterministic multi-model orchestrator.",
            "minimum_successes": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["panel"]["successful_count"] == 2
    assert body["critic"]["status"] == "succeeded"
    assert body["critic"]["raw_response"] == "Critic demo response"
    assert body["arbiter"]["status"] == "succeeded"
    assert body["arbiter"]["raw_response"] == "Synthesized demo response"
    assert response.headers["X-Conclave-Run-ID"]


def test_deliberation_skips_critic_and_arbiter_without_quorum(tmp_path, monkeypatch):
    import conclave.api as api_module
    from conclave.providers.fake import FakeProvider

    def make(response="ok", **kwargs):
        error = RuntimeError("provider down") if response == "Delegate B response" else None
        return FakeProvider(response, error=error, **kwargs)

    monkeypatch.setattr(api_module, "FakeProvider", make)
    client = TestClient(make_app(WorkspaceStore(tmp_path / "t.db")))
    response = client.post(
        "/api/deliberate",
        json={
            "question": "test",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "minimum_successes": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["panel"]["synthesizeable"] is False
    assert body["critic"] is None
    assert body["arbiter"] is None


def test_workspace_persists_defaults_run_and_history(tmp_path):
    store = WorkspaceStore(tmp_path / "test.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "HomeLedger",
            "description": "Personal finance project",
            "context": "Local-first; preserve privacy.",
            "delegates": ["demo-a", "demo-b"],
            "roles": {"demo-b": "Act as the skeptical reviewer."},
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "minimum_successes": 1,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    result = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "Should we add forecasting?"},
    )
    assert result.status_code == 200
    assert result.headers["X-Conclave-Run-ID"]
    body = result.json()
    assert body["panel"]["successful_count"] == 2
    assert body["critic"]["status"] == "succeeded"
    assert body["arbiter"]["status"] == "succeeded"

    history = workspace_client.get(f"/api/workspaces/{workspace['id']}/runs")
    assert history.status_code == 200
    runs = history.json()
    assert len(runs) == 1
    assert runs[0]["id"] == result.headers["X-Conclave-Run-ID"]
    assert runs[0]["question"] == "Should we add forecasting?"

    fetched = workspace_client.get(f"/api/runs/{runs[0]['id']}")
    assert fetched.status_code == 200
    saved = fetched.json()
    assert saved["result"]["arbiter"]["status"] == "succeeded"
    assert saved["request"]["delegates"] == ["demo-a", "demo-b"]

    # demo-a succeeded, so re-running it needs an explicit force.
    refused = workspace_client.post(f"/api/runs/{runs[0]['id']}/delegates/demo-a/retry")
    assert refused.status_code == 409 and "force" in refused.json()["detail"]
    retried = workspace_client.post(
        f"/api/runs/{runs[0]['id']}/delegates/demo-a/retry?force=true"
    )
    assert retried.status_code == 200
    retry_run = retried.json()
    assert retry_run["id"] != runs[0]["id"]
    assert retry_run["result"]["panel"]["successful_count"] == 2
    assert retry_run["result"]["arbiter"]["status"] == "succeeded"

    history_after_retry = workspace_client.get(
        f"/api/workspaces/{workspace['id']}/runs"
    )
    # History lists the newest attempt of each chain; every attempt is still stored.
    assert [r["id"] for r in history_after_retry.json()] == [retry_run["id"]]
    every = workspace_client.get(
        f"/api/workspaces/{workspace['id']}/runs?all_attempts=true"
    ).json()
    assert len(every) == 2
    assert retry_run["parent_run_id"] == runs[0]["id"]
    assert retry_run["chain_root_id"] == runs[0]["id"]


def test_auto_select_workspace_uses_smaller_panel_for_simple_question(tmp_path):
    store = WorkspaceStore(tmp_path / "auto-select.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Auto",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "minimum_successes": 1,
            "auto_select_delegates": True,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    preview = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/select",
        json={"question": "What is RAID 10?"},
    )
    assert preview.status_code == 200
    selection = preview.json()
    assert selection["analysis"]["recommended_delegate_count"] == 1
    assert selection["selected"] == ["demo-a"]

    result = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "What is RAID 10?"},
    )
    assert result.status_code == 200
    run_id = result.headers["X-Conclave-Run-ID"]

    saved = workspace_client.get(f"/api/runs/{run_id}").json()
    assert saved["request"]["delegates"] == ["demo-a"]


def test_workspace_rejects_unknown_providers_and_supports_replace_delete(tmp_path):
    store = WorkspaceStore(tmp_path / "crud.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    bad = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Bad",
            "delegates": ["not-configured"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
        },
    )
    assert bad.status_code == 422
    assert "not-configured" in bad.json()["detail"]

    created = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Editable",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "minimum_successes": 1,
        },
    )
    assert created.status_code == 201
    workspace = created.json()

    replaced = workspace_client.put(
        f"/api/workspaces/{workspace['id']}",
        json={
            "name": "Edited",
            "description": "Changed",
            "delegates": ["demo-a"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
            "minimum_successes": 1,
            "auto_select_delegates": True,
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "Edited"
    assert replaced.json()["delegates"] == ["demo-a"]
    assert replaced.json()["auto_select_delegates"] is True

    deleted = workspace_client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 204
    assert workspace_client.get(f"/api/workspaces/{workspace['id']}").status_code == 404


def test_downstream_retry_endpoints_save_new_runs(tmp_path):
    store = WorkspaceStore(tmp_path / "downstream-retry.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    workspace = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Retry",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
        },
    ).json()

    first = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "retry downstream"},
    )
    run_id = first.headers["X-Conclave-Run-ID"]

    critic_retry = workspace_client.post(f"/api/runs/{run_id}/critic/retry")
    assert critic_retry.status_code == 200
    critic_run = critic_retry.json()
    assert critic_run["id"] != run_id
    assert critic_run["result"]["critic"]["status"] == "succeeded"
    assert critic_run["result"]["arbiter"]["status"] == "succeeded"

    arbiter_retry = workspace_client.post(
        f"/api/runs/{critic_run['id']}/arbiter/retry"
    )
    assert arbiter_retry.status_code == 200
    arbiter_run = arbiter_retry.json()
    assert arbiter_run["id"] != critic_run["id"]
    assert arbiter_run["result"]["arbiter"]["status"] == "succeeded"


def test_deleted_workspace_run_remains_in_global_history(tmp_path):
    store = WorkspaceStore(tmp_path / "detached-history.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    workspace = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Disposable",
            "delegates": ["demo-a"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
        },
    ).json()

    first = workspace_client.post(
        f"/api/workspaces/{workspace['id']}/deliberate",
        json={"question": "preserve me"},
    )
    run_id = first.headers["X-Conclave-Run-ID"]

    deleted = workspace_client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 204

    all_runs = workspace_client.get("/api/runs")
    assert all_runs.status_code == 200
    match = next(run for run in all_runs.json() if run["id"] == run_id)
    assert match["workspace_id"] is None
    assert match["question"] == "preserve me"


def test_workspace_validation_rejects_duplicate_delegates_and_unknown_roles(tmp_path):
    store = WorkspaceStore(tmp_path / "validation.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    duplicate = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Duplicate",
            "delegates": ["demo-a", "demo-a"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
        },
    )
    assert duplicate.status_code == 422
    assert "unique" in duplicate.json()["detail"]

    bad_role = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Bad role",
            "delegates": ["demo-a"],
            "roles": {"demo-b": "Not actually selected"},
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
        },
    )
    assert bad_role.status_code == 422
    assert "non-delegate" in bad_role.json()["detail"]


def test_workspace_rejects_invalid_stage_fallbacks(tmp_path):
    store = WorkspaceStore(tmp_path / "fallback-validation.db")
    workspace_app = make_app(store)
    workspace_client = TestClient(workspace_app)

    duplicate_primary = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Bad fallback",
            "delegates": ["demo-a"],
            "critic": "demo-critic",
            "critic_fallbacks": ["demo-critic"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
        },
    )
    assert duplicate_primary.status_code == 422
    assert "must not repeat" in duplicate_primary.json()["detail"]

    unknown = workspace_client.post(
        "/api/workspaces",
        json={
            "name": "Unknown fallback",
            "delegates": ["demo-a"],
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "critic": None,
            "arbiter_fallbacks": ["not-real"],
        },
    )
    assert unknown.status_code == 422
    assert "not-real" in unknown.json()["detail"]


# --- stage persistence (P0-3) ---


def _delayed_app(tmp_path, monkeypatch, slow_texts):
    import conclave.api as api_module
    from conclave.providers.fake import FakeProvider

    def make(response="ok", **kwargs):
        delay = 5 if response in slow_texts else 0
        return FakeProvider(response, delay_seconds=delay, **kwargs)

    monkeypatch.setattr(api_module, "FakeProvider", make)
    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    return make_app(store), store


async def _cancelled_deliberate(app, timeout):
    import asyncio

    import httpx

    body = {
        "question": "Should we ship?",
        "delegates": ["demo-a", "demo-b"],
        "critic": "demo-critic",
        "arbiter": "demo-arbiter",
        "single_source_mode": "arbiter_single_source",
        "minimum_successes": 2,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        try:
            await asyncio.wait_for(http.post("/api/deliberate", json=body), timeout)
        except asyncio.TimeoutError:
            return
    raise AssertionError("request was not cancelled")


async def test_cancel_during_arbiter_keeps_panel_and_critic(tmp_path, monkeypatch):
    app, store = _delayed_app(tmp_path, monkeypatch, {"Synthesized demo response"})
    await _cancelled_deliberate(app, 1.0)

    runs = store.list_runs()
    assert len(runs) == 1
    run = store.get_run(runs[0].id)
    assert run.status == "interrupted"
    assert run.result.panel.successful_count == 2
    assert run.result.critic is not None
    assert run.result.arbiter is None
    assert list((tmp_path / "logs").glob("*.json"))


async def test_cancel_during_panel_leaves_interrupted_row(tmp_path, monkeypatch):
    app, store = _delayed_app(tmp_path, monkeypatch, {"Delegate A response"})
    await _cancelled_deliberate(app, 1.0)

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "interrupted"
    # Nothing paid for is lost: the delegate that had answered keeps its answer, and the one that
    # was cut off is recorded as cancelled instead of silently missing.
    by_name = {d.name: d for d in runs[0].result.panel.delegates}
    assert set(by_name) == {"demo-a", "demo-b"}
    assert by_name["demo-b"].status.value == "succeeded" and by_name["demo-b"].raw_response
    assert (by_name["demo-a"].status.value, by_name["demo-a"].error_kind) == ("failed", "cancelled")
    assert runs[0].result.critic is None and runs[0].result.arbiter is None


def test_normal_run_is_one_complete_row(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(make_app(store))
    response = client.post(
        "/api/deliberate",
        json={
            "question": "Q",
            "delegates": ["demo-a", "demo-b"],
            "critic": "demo-critic",
            "arbiter": "demo-arbiter",
            "single_source_mode": "arbiter_single_source",
            "minimum_successes": 2,
        },
    )
    assert response.status_code == 200
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "complete"
    assert runs[0].result.arbiter is not None
    assert response.headers["X-Conclave-Run-ID"] == runs[0].id


def test_startup_marks_leftover_running_rows_interrupted(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    stuck = store.create_run(question="left running")
    assert store.get_run(stuck.id).status == "running"
    make_app(store)
    assert store.get_run(stuck.id).status == "interrupted"


def test_interrupted_run_meeting_quorum_can_be_resumed(tmp_path, monkeypatch):
    import asyncio

    app, store = _delayed_app(tmp_path, monkeypatch, {"Synthesized demo response"})
    asyncio.run(_cancelled_deliberate(app, 1.0))
    run_id = store.list_runs()[0].id

    resumed = TestClient(make_app(store)).post(f"/api/runs/{run_id}/arbiter/retry")
    assert resumed.status_code == 200
    assert resumed.json()["result"]["arbiter"]["status"] == "succeeded"


# --- seed, caps and byte-for-byte prompt rebuild (P0-4) ---

PANEL_BODY = {
    "question": "Q",
    "delegates": ["demo-a", "demo-b"],
    "critic": "demo-critic",
    "arbiter": "demo-arbiter",
    "single_source_mode": "arbiter_single_source",
    "minimum_successes": 2,
}


def test_run_gets_a_seed_and_judge_prompts_rebuild_byte_for_byte(tmp_path):
    from conclave.prompts import build_arbiter_prompt, build_critic_prompt

    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(make_app(store))
    assert client.post("/api/deliberate", json=PANEL_BODY).status_code == 200
    run = store.get_run(store.list_runs()[0].id)
    assert run.request.seed and len(run.request.seed) == 32

    panel = run.result.panel.delegates
    kwargs = {
        "seed": run.request.seed,
        "response_char_limit": run.request.judge_response_char_limit,
        "source_groups": run.result.panel.sources,
    }
    assert run.result.critic.prompt == build_critic_prompt(
        question=run.request.question, delegate_results=panel, **kwargs
    )
    assert run.result.arbiter.prompt == build_arbiter_prompt(
        question=run.request.question,
        delegate_results=panel,
        critic_result=run.result.critic,
        **kwargs,
    )


def test_retry_reuses_the_seed_and_markers_of_the_original_run(tmp_path):
    from conclave.prompts import marker_token

    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(make_app(store))
    client.post("/api/deliberate", json=PANEL_BODY)
    first = store.list_runs()[0]
    retried = client.post(f"/api/runs/{first.id}/arbiter/retry").json()
    assert retried["request"]["seed"] == first.request.seed
    token = marker_token(first.request.seed)
    assert f"<<<RESPONSE A {token}>>>" in retried["result"]["arbiter"]["prompt"]


def test_legacy_run_without_seed_gets_one_on_retry(tmp_path):
    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(make_app(store))
    client.post(
        "/api/deliberate",
        json={"question": "Q", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-arbiter"},
    )
    run = store.list_runs()[0]
    legacy = run.request.model_copy(update={"seed": None})
    saved = store.save_run(question="Q", request=legacy, result=run.result)
    retried = client.post(f"/api/runs/{saved.id}/arbiter/retry").json()
    seed = retried["request"]["seed"]
    assert seed

    # The seed that was stored is the one the prompt was built from.
    from conclave.models import DelegateResult
    from conclave.prompts import build_arbiter_prompt, marker_token

    assert f"<<<RESPONSE A {marker_token(seed)}>>>" in retried["result"]["arbiter"]["prompt"]
    stored = store.get_run(retried["id"])
    assert stored.request.seed == seed
    assert stored.result.arbiter.prompt == build_arbiter_prompt(
        question=stored.request.question,
        delegate_results=[DelegateResult(**d.model_dump()) for d in stored.result.panel.delegates],
        critic_result=stored.result.critic,
        seed=seed,
        response_char_limit=stored.request.judge_response_char_limit,
        source_groups=stored.result.panel.sources,
    )


def test_huge_answer_is_capped_in_judge_prompt_but_stored_whole(tmp_path, monkeypatch):
    import conclave.api as api_module
    from conclave.providers.fake import FakeProvider

    huge = "x" * 1_000_000

    def make(response="ok", **kwargs):
        return FakeProvider(huge if response == "Delegate A response" else response, **kwargs)

    monkeypatch.setattr(api_module, "FakeProvider", make)
    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(make_app(store))
    client.post("/api/deliberate", json=PANEL_BODY)
    run = store.get_run(store.list_runs()[0].id)
    stored = next(d for d in run.result.panel.delegates if d.name == "demo-a")
    assert len(stored.raw_response) == 1_000_000
    assert len(run.result.critic.prompt) < 60_000
    assert "[truncated: 976000 characters omitted]" in run.result.critic.prompt


# --- validation and warnings (P0-6) ---


def _post(client, path, body, expected):
    response = client.post(path, json=body)
    assert response.status_code == expected, (path, body, response.text)
    return response


def test_direct_endpoints_reject_duplicate_and_unknown_names(tmp_path):
    client = TestClient(make_app(WorkspaceStore(tmp_path / "t.db")))
    base = {"question": "q", "arbiter": "demo-arbiter"}

    dup = _post(client, "/api/deliberate", {**base, "delegates": ["demo-a", "demo-a"]}, 422)
    assert "unique" in dup.json()["detail"]
    _post(client, "/api/deliberate", {**base, "delegates": ["demo-a", "nope"]}, 422)
    _post(client, "/api/deliberate", {"question": "q", "delegates": ["demo-a"], "arbiter": "nope"}, 422)
    _post(
        client,
        "/api/deliberate",
        {**base, "delegates": ["demo-a"], "critic": "demo-critic", "critic_fallbacks": ["demo-critic"]},
        422,
    )
    _post(
        client,
        "/api/deliberate",
        {**base, "delegates": ["demo-a"], "roles": {"demo-b": "not a delegate"}},
        422,
    )
    # Nothing was stored for a rejected request.
    assert client.get("/api/runs").json() == []

    panel = {"question": "q", "minimum_successes": 1}
    names = [{"name": "demo-a", "prompt": "p"}, {"name": "demo-a", "prompt": "p"}]
    _post(client, "/api/panel", {**panel, "delegates": names}, 422)
    _post(client, "/api/panel", {**panel, "delegates": [{"name": "nope", "prompt": "p"}]}, 422)
    ok = _post(client, "/api/panel", {**panel, "delegates": [{"name": "demo-a", "prompt": "p"}]}, 200)
    assert ok.json()["independent_source_count"] == 1


def test_panel_response_reports_independent_sources_for_demo_providers(client):
    body = {
        "question": "q",
        "delegates": [{"name": "demo-a", "prompt": "p"}, {"name": "demo-b", "prompt": "p"}],
        "minimum_successes": 2,
    }
    result = client.post("/api/panel", json=body).json()
    assert result["successful_count"] == 2
    assert result["independent_source_count"] == 2
    assert result["synthesizeable"] is True


def test_workspace_with_two_delegates_of_one_config_saves_with_a_warning(tmp_path):
    from conclave.config import ProviderConfig

    def provider(name, model, url="https://api.example.com/v1"):
        return ProviderConfig(name=name, base_url=url, model=model)

    config = ConclaveConfig(
        providers=[
            provider("one", "m1"),
            provider("two", "m1", "HTTPS://API.EXAMPLE.COM/v1/"),
            provider("three", "m2"),
        ]
    )
    store = WorkspaceStore(tmp_path / "t.db")
    client = TestClient(create_app(config=config, workspace_store=store))
    body = {
        "name": "w",
        "delegates": ["one", "two", "three"],
        "arbiter": "demo-arbiter",
        "single_source_mode": "arbiter_single_source",
        "critic": None,
        "minimum_successes": 2,
    }
    created = _post(client, "/api/workspaces", body, 201).json()
    assert len(created["warnings"]) == 1
    assert "one, two" in created["warnings"][0] and "one source" in created["warnings"][0]
    # The warning is advice, not data: reading the workspace back stores none.
    assert client.get(f"/api/workspaces/{created['id']}").json()["warnings"] == []

    replaced = client.put(
        f"/api/workspaces/{created['id']}", json={**body, "delegates": ["one", "three"]}
    ).json()
    assert replaced["warnings"] == []
    clean = _post(client, "/api/workspaces", {**body, "name": "w2", "delegates": ["one", "three"]}, 201)
    assert clean.json()["warnings"] == []


def test_reserve_delegates_are_validated(client):
    base = {"question": "q", "delegates": ["demo-a"], "arbiter": "demo-arbiter"}
    dup = client.post("/api/deliberate", json={**base, "reserve_delegates": ["demo-a"]})
    assert dup.status_code == 422 and "already on the panel" in dup.json()["detail"]
    unknown = client.post("/api/deliberate", json={**base, "reserve_delegates": ["nope"]})
    assert unknown.status_code == 422 and "Unknown provider" in unknown.json()["detail"]
    twice = client.post("/api/deliberate", json={**base, "reserve_delegates": ["demo-b", "demo-b"]})
    assert twice.status_code == 422


def test_reserves_are_recorded_with_the_run_request(client):
    body = {
        "question": "q",
        "delegates": ["demo-a"],
        "arbiter": "demo-arbiter",
        "reserve_delegates": ["demo-b"],
        "shared_stage_deadline": True,
    }
    response = client.post("/api/deliberate", json=body)
    assert response.status_code == 200
    run = client.get(f"/api/runs/{response.headers['X-Conclave-Run-ID']}").json()
    assert run["request"]["reserve_delegates"] == ["demo-b"]
    assert run["request"]["shared_stage_deadline"] is True


def test_a_cost_ceiling_is_refused_up_front_when_a_cost_cannot_be_bounded(client):
    body = {
        "question": "q",
        "delegates": ["demo-a"],
        "arbiter": "demo-arbiter",
        "max_estimated_cost_usd": 1.0,
    }
    response = client.post("/api/deliberate", json=body)
    assert response.status_code == 422
    assert "demo-a" in response.json()["detail"] and "Cannot bound" in response.json()["detail"]
    assert client.get("/api/runs").json() == []  # nothing was started
    assert client.post("/api/deliberate", json={**body, "max_estimated_cost_usd": 0}).status_code == 422


def _slow(monkeypatch, seconds):
    import asyncio

    from conclave.providers.fake import FakeProvider

    original = FakeProvider.ask

    async def slow(self, prompt):
        await asyncio.sleep(seconds)
        return await original(self, prompt)

    monkeypatch.setattr(FakeProvider, "ask", slow)


def _wait_for(client, run_id, status, tries=100):
    import time

    for _ in range(tries):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == status:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run never reached {status}: {run['status']}")


BODY = {"question": "q", "delegates": ["demo-a", "demo-b"], "arbiter": "demo-arbiter"}


def test_background_mode_returns_the_run_id_at_once_and_the_run_completes(tmp_path, monkeypatch):
    _slow(monkeypatch, 0.2)
    with TestClient(make_app(WorkspaceStore(tmp_path / "bg.db"))) as client:
        response = client.post("/api/deliberate?background=true", json=BODY)
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert response.headers["X-Conclave-Run-ID"] == run_id
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
        done = _wait_for(client, run_id, "complete")
        assert done["result"]["arbiter"]["status"] == "succeeded"
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409  # nothing to stop


def test_a_background_run_can_be_cancelled_and_is_marked_interrupted(tmp_path, monkeypatch):
    _slow(monkeypatch, 5)
    with TestClient(make_app(WorkspaceStore(tmp_path / "bg2.db"))) as client:
        run_id = client.post("/api/deliberate?background=true", json=BODY).json()["run_id"]
        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 202
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "interrupted"
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409


def test_the_default_still_waits_for_the_whole_run(client):
    response = client.post("/api/deliberate", json=BODY)
    assert response.status_code == 200 and response.json()["arbiter"]["status"] == "succeeded"


def test_provider_status_reports_unknowns_as_unknown(client):
    rows = {r["name"]: r for r in client.get("/api/providers/status").json()}
    demo = rows["demo-a"]
    assert demo["source"] == "demo" and demo["last_success_at"] is None
    assert demo["quota_remaining"] is None and demo["context_window_tokens"] is None
    assert demo["input_cost_per_million"] is None  # unknown, not 0
    assert "api_key" not in str(rows).lower()


def test_provider_status_learns_last_success_from_the_ledger(client):
    assert client.post("/api/providers/demo-a/test").status_code == 200
    rows = {r["name"]: r for r in client.get("/api/providers/status").json()}
    assert rows["demo-a"]["last_success_at"] is not None
    assert rows["demo-b"]["last_success_at"] is None


def test_dashboard_has_recent_runs_cost_and_background_list(client):
    body = {"question": "q", "delegates": ["demo-a"], "arbiter": "demo-arbiter"}
    assert client.post("/api/deliberate", json=body).status_code == 200
    dash = client.get("/api/dashboard").json()
    assert len(dash["recent_runs"]) == 1 and dash["running_in_background"] == []
    assert dash["cost_last_7_days"]["total_calls"] >= 1


def test_the_version_is_the_same_everywhere():
    import tomllib
    from pathlib import Path

    import conclave
    from conclave.api import create_app
    from conclave.config import ConclaveConfig
    from conclave.store import WorkspaceStore  # noqa: F401

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    app = create_app(config=ConclaveConfig(), workspace_store=WorkspaceStore(Path("v.db")))
    assert conclave.__version__ == pyproject["project"]["version"] == app.version
