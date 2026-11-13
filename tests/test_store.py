from conclave.models import (
    DeliberationRequest,
    DeliberationResult,
    PanelResult,
    WorkspaceCreate,
    WorkspaceReplace,
)
from conclave.store import WorkspaceStore


def test_workspace_store_round_trip(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    created = store.create(
        WorkspaceCreate(
            name="Conclave",
            description="Meta-orchestrator",
            context="Prefer inspectable pipelines.",
            delegates=["a", "b"],
            roles={"b": "Be skeptical."},
            critic="critic",
            arbiter="arbiter",
            minimum_successes=1,
        )
    )

    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.name == "Conclave"
    assert fetched.context == "Prefer inspectable pipelines."
    assert fetched.roles["b"] == "Be skeptical."
    assert fetched.critic == "critic"

    listed = store.list()
    assert [item.id for item in listed] == [created.id]


def test_workspace_store_persists_run_history(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    workspace = store.create(
        WorkspaceCreate(
            name="Test",
            delegates=["a"],
            arbiter="arbiter",
        )
    )
    result = DeliberationResult(
        panel=PanelResult(
            question="question",
            delegates=[],
            successful_count=0,
            failed_count=0,
            synthesizeable=False,
        )
    )

    request = DeliberationRequest(
        question="question",
        delegates=["a"],
        critic="critic",
        arbiter="arbiter",
    )
    saved = store.save_run(
        workspace_id=workspace.id,
        question="question",
        request=request,
        result=result,
    )

    fetched = store.get_run(saved.id)
    assert fetched is not None
    assert fetched.workspace_id == workspace.id
    assert fetched.question == "question"
    assert fetched.request is not None
    assert fetched.request.delegates == ["a"]
    assert fetched.request.critic == "critic"
    assert store.list_runs(workspace.id)[0].id == saved.id


def test_workspace_store_returns_none_for_missing_id(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    assert store.get("missing") is None
    assert store.get_run("missing") is None


def test_workspace_replace_and_delete_preserve_run_history(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    workspace = store.create(
        WorkspaceCreate(
            name="Original",
            delegates=["a"],
            arbiter="arbiter",
        )
    )
    result = DeliberationResult(
        panel=PanelResult(
            question="q",
            delegates=[],
            successful_count=0,
            failed_count=0,
            synthesizeable=False,
        )
    )
    run = store.save_run(
        workspace_id=workspace.id,
        question="q",
        result=result,
    )

    updated = store.replace(
        workspace.id,
        WorkspaceReplace(
            name="Renamed",
            delegates=["a", "b"],
            critic="critic",
            arbiter="arbiter",
            minimum_successes=1,
            auto_select_delegates=True,
        ),
    )
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.auto_select_delegates is True
    assert updated.updated_at != workspace.updated_at

    assert store.delete(workspace.id) is True
    assert store.get(workspace.id) is None
    preserved = store.get_run(run.id)
    assert preserved is not None
    assert preserved.workspace_id is None


def test_workspace_persists_stage_fallbacks(tmp_path):
    from conclave.models import WorkspaceCreate

    store = WorkspaceStore(tmp_path / "fallbacks.db")
    workspace = store.create(
        WorkspaceCreate(
            name="Fallbacks",
            delegates=["demo-a"],
            critic="demo-critic",
            critic_fallbacks=["demo-b"],
            arbiter="demo-arbiter",
            arbiter_fallbacks=["demo-a"],
        )
    )

    loaded = store.get(workspace.id)
    assert loaded is not None
    assert loaded.critic_fallbacks == ["demo-b"]
    assert loaded.arbiter_fallbacks == ["demo-a"]


def test_saved_run_writes_pretty_json_audit_log(tmp_path):
    import json

    from conclave.models import DelegateResult, DelegateStatus

    log_dir = tmp_path / "run_logs"
    store = WorkspaceStore(
        tmp_path / "workspaces.db",
        run_log_dir=log_dir,
    )
    workspace = store.create(
        WorkspaceCreate(
            name="Human test",
            description="Used to inspect real Conclave runs later.",
            context="Preserve disagreement.",
            delegates=["a"],
            roles={"a": "Independent reviewer"},
            critic="critic",
            arbiter="arbiter",
        )
    )
    request = DeliberationRequest(
        question="Should we ship this?",
        delegates=["a"],
        roles={"a": "Independent reviewer"},
        critic="critic",
        arbiter="arbiter",
        workspace_context="Preserve disagreement.",
    )
    result = DeliberationResult(
        panel=PanelResult(
            question="Should we ship this?",
            delegates=[
                DelegateResult(
                    name="a",
                    status=DelegateStatus.SUCCEEDED,
                    prompt="EXACT DELEGATE PROMPT",
                    raw_response="Delegate answer",
                    model="model-a",
                    latency_ms=123,
                    usage={"total_tokens": 42},
                    attempts=2,
                )
            ],
            successful_count=1,
            failed_count=0,
            synthesizeable=True,
        ),
        critic=DelegateResult(
            name="critic",
            status=DelegateStatus.SUCCEEDED,
            prompt="EXACT CRITIC PROMPT",
            raw_response="Critic answer",
        ),
        arbiter=DelegateResult(
            name="arbiter",
            status=DelegateStatus.SUCCEEDED,
            prompt="EXACT ARBITER PROMPT",
            raw_response="Final synthesis",
        ),
    )

    saved = store.save_run(
        workspace_id=workspace.id,
        question=request.question,
        request=request,
        result=result,
    )

    files = list(log_dir.glob("*.json"))
    assert len(files) == 1
    assert saved.id in files[0].name

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["workspace"]["id"] == workspace.id
    assert payload["workspace"]["name"] == "Human test"
    assert payload["run"]["id"] == saved.id
    assert payload["run"]["request"]["workspace_context"] == "Preserve disagreement."
    assert payload["run"]["result"]["panel"]["delegates"][0]["prompt"] == "EXACT DELEGATE PROMPT"
    assert payload["run"]["result"]["panel"]["delegates"][0]["raw_response"] == "Delegate answer"
    assert payload["run"]["result"]["panel"]["delegates"][0]["attempts"] == 2
    assert payload["run"]["result"]["critic"]["prompt"] == "EXACT CRITIC PROMPT"
    assert payload["run"]["result"]["arbiter"]["raw_response"] == "Final synthesis"
