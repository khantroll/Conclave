from conclave.models import WorkspaceCreate
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


def test_workspace_store_returns_none_for_missing_id(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    assert store.get("missing") is None
