"""Test isolation: no real configuration, database, run log or network.

The session-level block below runs when pytest imports this file, which is
before any test module imports ``conclave``. The per-test fixture then gives
every test its own empty working directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="conclave-tests-"))


def _isolate_env(base: Path, setenv, delenv) -> None:
    setenv("CONCLAVE_CONFIG_PATH", str(base / "conclave.json"))
    setenv("CONCLAVE_DB_PATH", str(base / "conclave.db"))
    setenv("CONCLAVE_RUN_LOG_DIR", str(base / "run_logs"))
    for name in list(os.environ):
        if name.endswith("_API_KEY") or name.endswith("_KEY"):
            delenv(name)


def _setenv(name: str, value: str) -> None:
    os.environ[name] = value


def _delenv(name: str) -> None:
    os.environ.pop(name, None)


_isolate_env(_SESSION_DIR, _setenv, _delenv)
os.chdir(_SESSION_DIR)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_env(tmp_path, monkeypatch.setenv, monkeypatch.delenv)

    def blocked(*args, **kwargs):
        raise RuntimeError(
            "Network access is blocked in tests. Inject an httpx client "
            "with a MockTransport."
        )

    # MockTransport is unaffected; only real transports are blocked.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


@pytest.fixture
def client(tmp_path):
    from conclave.api import create_app
    from conclave.config import ConclaveConfig
    from conclave.store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    return TestClient(create_app(config=ConclaveConfig(), workspace_store=store))
