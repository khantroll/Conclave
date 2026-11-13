from __future__ import annotations

import hashlib
import http.server
import os
import re
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

TESTS_DIR = Path(__file__).resolve().parent
INNER = "CONCLAVE_CANARY_INNER"


def test_no_test_module_imports_the_module_level_app():
    pattern = re.compile(r"from\s+conclave\.api\s+import[^\n]*\bapp\b")
    for path in TESTS_DIR.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_importing_the_api_module_has_no_side_effects(tmp_path):
    code = (
        "import conclave.api, os, sys; "
        "sys.exit(1 if os.listdir('.') else 0)"
    )
    work = tmp_path / "cwd"
    work.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=work, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_real_network_is_blocked():
    with pytest.raises(RuntimeError, match="Network access is blocked"):
        httpx.get("http://127.0.0.1:9/")


def test_default_app_uses_only_isolated_paths(tmp_path):
    from fastapi.testclient import TestClient

    from conclave.api import create_app

    for name in ("CONCLAVE_CONFIG_PATH", "CONCLAVE_DB_PATH", "CONCLAVE_RUN_LOG_DIR"):
        assert Path(os.environ[name]).is_relative_to(tmp_path), name
    assert Path.cwd() == tmp_path
    assert not [k for k in os.environ if k.endswith("_API_KEY")]

    # Default construction reads the environment, as `uvicorn conclave.api:app`
    # does. If isolation failed under the canary, this would load the
    # synthetic configured providers and call them.
    client = TestClient(create_app())
    assert client.get("/health").json()["configured_provider_count"] == 0
    assert client.post("/api/providers/test-all").status_code == 200


def test_configured_provider_cannot_reach_the_network(tmp_path):
    from fastapi.testclient import TestClient

    from conclave.api import create_app
    from conclave.config import ConclaveConfig, ProviderConfig
    from conclave.store import WorkspaceStore

    config = ConclaveConfig(
        providers=[
            ProviderConfig(
                name="real", base_url="http://127.0.0.1:9/v1", model="m", transient_max_retries=0
            )
        ]
    )
    store = WorkspaceStore(tmp_path / "t.db", run_log_dir=tmp_path / "logs")
    client = TestClient(create_app(config=config, workspace_store=store))
    body = client.post("/api/providers/real/test").text
    assert "Network access is blocked" in body


def test_uvicorn_import_string_still_resolves_without_touching_cwd(tmp_path):
    code = (
        "from uvicorn.importer import import_from_string; "
        "a = import_from_string('conclave.api:app'); "
        "print(type(a).__name__)"
    )
    work = tmp_path / "cwd"
    work.mkdir()
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "CONCLAVE_DB_PATH": str(work / "x.db"),
        "CONCLAVE_RUN_LOG_DIR": str(work / "logs"),
        "CONCLAVE_CONFIG_PATH": str(work / "none.json"),
    }
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=work, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FastAPI"


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.skipif(os.environ.get(INNER) == "1", reason="inner canary run")
def test_canary_suite_leaves_a_configured_directory_untouched(tmp_path):
    requests: list[str] = []

    class Recorder(http.server.BaseHTTPRequestHandler):
        def _record(self):
            requests.append(self.path)
            self.send_response(500)
            self.end_headers()

        do_GET = do_POST = _record

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    work = tmp_path / "configured"
    work.mkdir()
    (work / "conclave.json").write_text(
        '{"providers": ['
        + ",".join(
            f'{{"name": "real-{i}", "base_url": "http://127.0.0.1:{port}/v1", '
            f'"model": "m{i}", "api_key_env": "CANARY_API_KEY"}}'
            for i in (1, 2)
        )
        + "]}",
        encoding="utf-8",
    )
    (work / ".env").write_text("CANARY_API_KEY=fake-key\n", encoding="utf-8")
    (work / "run_logs").mkdir()
    db = work / "conclave.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sentinel (id INTEGER)")
    conn.executemany("INSERT INTO sentinel VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    conn.close()
    before = _snapshot(work)

    env = {
        **os.environ,
        INNER: "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CANARY_API_KEY": "fake-key",
        "CONCLAVE_CONFIG_PATH": str(work / "conclave.json"),
        "CONCLAVE_DB_PATH": str(db),
        "CONCLAVE_RUN_LOG_DIR": str(work / "run_logs"),
    }
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(TESTS_DIR),
                # The adversarial suite is large and runs under the same isolation fixtures in
                # the outer run; repeating it here would only double the time.
                "--ignore", str(TESTS_DIR / "adversarial"),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stdout + result.stderr
    assert requests == []
    assert _snapshot(work) == before
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM sentinel").fetchone()[0] == 3
    conn.close()
