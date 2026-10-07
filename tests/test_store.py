from conclave.models import DeliberationResult, PanelResult, WorkspaceCreate
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

    saved = store.save_run(
        workspace_id=workspace.id,
        question="question",
        result=result,
    )

    fetched = store.get_run(saved.id)
    assert fetched is not None
    assert fetched.workspace_id == workspace.id
    assert fetched.question == "question"
    assert store.list_runs(workspace.id)[0].id == saved.id


def test_workspace_store_returns_none_for_missing_id(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    assert store.get("missing") is None
    assert store.get_run("missing") is None
