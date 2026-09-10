"""The config store reaches a subprocess by one route, and it is an allowlist.

`POST /config` used to do two writes: the encrypted store, and `os.environ[key]`.
The startup hook copied the whole store into `os.environ` as well, and both
subprocess launches — `docker compose run pipeline-runner` and `run_operator.py` —
were built with `os.environ.copy()`. So every stored key was a variable in every
child process this server spawns, set by an endpoint with no authentication in
front of it.

`PYTHONPATH` was one of those keys. One request prepended an import path to the
pipeline container, whose `data/inputs`, `data/outputs` and `data/logs` are bind
mounts a caller can write to — a chain, not a curiosity. `EXECUTION_STRATEGY_OVERRIDE`
on the same route decided where the phases ran.

Three properties are tested here, and they only mean anything together:

* nothing writes `os.environ` any more;
* a launch environment is this process's environment plus exactly
  `SUBPROCESS_ENV_KEYS`, so a stored value a child does not read cannot reach it;
* the store is read *at the launch*, so a key saved in Settings still works on the
  next job without a restart — which is the one useful thing the `os.environ` write
  was doing.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server import app as app_module
from server import config_store as config_store_module
from server.app import app, subprocess_env
from server.config_store import CONFIG_KEYS, RETIRED_CONFIG_KEYS, SUBPROCESS_ENV_KEYS

client = TestClient(app)
REPO_ROOT = Path(__file__).parent.parent
OUTPUTS = REPO_ROOT / "data" / "outputs"

#: A stored key that is deliberately *not* forwarded, used to prove the allowlist is
#: a filter rather than a formality. Nothing anywhere reads `$LOG_LEVEL` from a
#: process this server launches.
NOT_FORWARDED = "LOG_LEVEL"


@pytest.fixture(scope="module", autouse=True)
def _config_table():
    """The suite's schema is fresh; the store needs its table before anything writes.

    Normally the startup hook creates it, and these tests use a module-level
    `TestClient` that never enters its context manager.
    """
    app_module.config_store.init_schema()


@pytest.fixture
def stored():
    """Write config values for one test and take them out again afterwards.

    The suite shares one schema, so a key left behind would be read by whatever runs
    next — `OCTOPRINT_API_KEY` in particular is what `resolve_printer_target` answers
    with.
    """
    written = []

    def write(key: str, value: str) -> None:
        app_module.config_store.set(key, value)
        written.append(key)

    yield write

    for key in written:
        app_module.config_store.delete(key)


# ── The endpoints leave the process environment alone ────────────────────────

def test_saving_a_config_value_does_not_write_os_environ():
    """The store, and only the store. This was the first half of the chain."""
    assert os.environ.get("HF_TOKEN") != "hf-from-the-endpoint"

    resp = client.post("/config", json={"key": "HF_TOKEN", "value": "hf-from-the-endpoint"})
    assert resp.status_code == 200, resp.text

    try:
        assert os.environ.get("HF_TOKEN") != "hf-from-the-endpoint", (
            "POST /config must not put a stored value in this process's environment"
        )
        assert app_module.config_store.get("HF_TOKEN") == "hf-from-the-endpoint"
    finally:
        app_module.config_store.delete("HF_TOKEN")


def test_clearing_a_config_value_does_not_unset_a_dotenv_variable(monkeypatch):
    """DELETE /config drops the row, not the variable `.env` set.

    It used to `del os.environ[key]`, which is the same conflation from the other
    side: the environment holds values this endpoint never wrote, and clearing a
    stored override is not a reason to unset the deployment's own.
    """
    monkeypatch.setenv("HF_TOKEN", "from-dotenv")

    resp = client.delete("/config/HF_TOKEN")
    assert resp.status_code == 200, resp.text
    assert os.environ.get("HF_TOKEN") == "from-dotenv"


# ── PYTHONPATH is gone, and cannot come back through the store ───────────────

def test_pythonpath_is_not_a_config_key():
    """Nothing legitimate sets an import path over an unauthenticated HTTP request.

    The pipeline's import path is the container's, set in the image.
    """
    assert "PYTHONPATH" not in CONFIG_KEYS
    assert "PYTHONPATH" in RETIRED_CONFIG_KEYS

    resp = client.post("/config", json={"key": "PYTHONPATH", "value": "/tmp/evil"})
    assert resp.status_code == 400

    with pytest.raises(ValueError):
        app_module.config_store.set("PYTHONPATH", "/tmp/evil")


def test_a_pythonpath_row_saved_before_the_removal_is_purged(isolated_db_url, tmp_path, monkeypatch):
    """Dropping the key is not the same as dropping the value.

    A deployment that ever set the override has a row nothing can read, edit or
    delete once `PYTHONPATH` leaves `CONFIG_KEYS` — so startup removes it.
    """
    store = config_store_module.ConfigStore(
        dsn=isolated_db_url, key_path=str(tmp_path / ".config_key")
    )
    store.init_schema()

    # Stored while the key was still accepted.
    monkeypatch.setitem(config_store_module.CONFIG_KEYS, "PYTHONPATH", {"label": "old"})
    store.set("PYTHONPATH", "/tmp/evil")
    monkeypatch.delitem(config_store_module.CONFIG_KEYS, "PYTHONPATH")

    assert store.get("PYTHONPATH") == "/tmp/evil"
    assert store.purge_retired_keys() == ["PYTHONPATH"]
    assert store.get("PYTHONPATH") is None
    # Idempotent: nothing to remove on the next start, and nothing reported.
    assert store.purge_retired_keys() == []


# ── The allowlist itself ─────────────────────────────────────────────────────

def test_every_allowlisted_key_is_a_real_config_key():
    """A forwarded key nobody can set is dead code; an unknown one is a typo."""
    assert set(SUBPROCESS_ENV_KEYS) <= set(CONFIG_KEYS)
    assert "PYTHONPATH" not in SUBPROCESS_ENV_KEYS


def test_every_allowlisted_key_names_the_consumer_that_reads_it():
    """Adding a key here is a decision, so each one has to carry its reason."""
    for key, why in SUBPROCESS_ENV_KEYS.items():
        assert why and len(why) > 20, f"{key} has no consumer named"


# ── subprocess_env(): the base environment plus the allowlist, nothing else ──

def _store_returning(values: dict):
    """Patch the module's config store so `get` answers from `values`."""
    return patch.object(
        app_module.config_store, "get", side_effect=lambda key: values.get(key)
    )


def test_subprocess_env_carries_the_allowlisted_values():
    with _store_returning({key: f"stored-{key}" for key in SUBPROCESS_ENV_KEYS}):
        env = subprocess_env(base={"PATH": "/usr/bin"})

    for key in SUBPROCESS_ENV_KEYS:
        assert env[key] == f"stored-{key}"
    assert env["PATH"] == "/usr/bin"


def test_subprocess_env_forwards_nothing_else_from_the_store():
    """Exactly the allowlist. A store that answers every key must add only these.

    This is the property the whole change turns on: with `os.environ.copy()` and a
    store hydrated into it, "which stored keys reach the child" was "all of them".
    """
    everything = {key: f"stored-{key}" for key in CONFIG_KEYS}
    everything["PYTHONPATH"] = "/tmp/evil"

    base = {"PATH": "/usr/bin"}
    with _store_returning(everything):
        env = subprocess_env(base=base)

    added = set(env) - set(base)
    assert added == set(SUBPROCESS_ENV_KEYS)
    assert "PYTHONPATH" not in env
    assert NOT_FORWARDED not in env


def test_subprocess_env_reads_the_store_at_launch_not_at_import():
    """A key saved in Settings must reach the *next* job, without a restart.

    That is the one thing the `os.environ` write provided, and it is provided here
    by reading the store inside the call rather than caching it anywhere.
    """
    with _store_returning({"HF_TOKEN": "before"}):
        first = subprocess_env(base={})
    with _store_returning({"HF_TOKEN": "after"}):
        second = subprocess_env(base={})

    assert first["HF_TOKEN"] == "before"
    assert second["HF_TOKEN"] == "after"


def test_a_stored_value_wins_over_the_same_name_in_the_environment():
    """Settings is the live authority for the keys it owns."""
    with _store_returning({"HF_TOKEN": "from-settings"}):
        env = subprocess_env(base={"HF_TOKEN": "from-dotenv"})
    assert env["HF_TOKEN"] == "from-settings"


def test_an_unset_key_leaves_the_dotenv_value_alone():
    """Nothing stored is not the same as "unset this"."""
    with _store_returning({}):
        env = subprocess_env(base={"HF_TOKEN": "from-dotenv"})
    assert env["HF_TOKEN"] == "from-dotenv"


# ── The pipeline launch ──────────────────────────────────────────────────────

def _job_row() -> str:
    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    db.insert_job(
        PrintJob(
            job_id=job_id,
            prompt="a vase",
            printer_id="default_printer",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="pythonsrc/profiles/ender3.json",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome="unknown",
        )
    )
    db.close()
    return job_id


def _pipeline_launch_env(job_id: str) -> dict:
    """Drive `_run_pipeline` as far as the launch and return the env it built."""
    (REPO_ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    captured = {}

    fake_process = AsyncMock()
    fake_process.returncode = 0

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return fake_process

    request = app_module.JobRequest(
        prompt="a vase", printer_id="default", profile="default", skip_visualizer=True,
    )
    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()), \
         patch("server.app.get_resolved_strategy", return_value="cpu_docker"):
        asyncio.run(app_module._run_pipeline(job_id, request))

    assert "env" in captured, "the pipeline was never launched"
    return captured["env"]


def test_the_pipeline_launch_carries_the_allowlist_and_no_other_stored_key(stored):
    stored("HF_TOKEN", "hf-for-the-pipeline")
    stored(NOT_FORWARDED, "DEBUG")

    env = _pipeline_launch_env(_job_row())

    assert env["HF_TOKEN"] == "hf-for-the-pipeline"
    # The Hub's own variable name is an alias for the same secret, derived at the
    # launch rather than being a second key anyone can store.
    assert env["HUGGINGFACE_HUB_TOKEN"] == "hf-for-the-pipeline"
    assert env.get(NOT_FORWARDED) != "DEBUG", (
        "a stored key with no reader in the child must not be forwarded"
    )
    assert "PYTHONPATH" not in set(env) - set(os.environ), (
        "PYTHONPATH must come from the image, never from the store"
    )


def test_the_pipeline_launch_reads_the_store_after_the_server_started(stored):
    """A token saved in Settings reaches the next job without a restart."""
    stored("HF_TOKEN", "saved-just-now")
    first = _pipeline_launch_env(_job_row())
    assert first["HF_TOKEN"] == "saved-just-now"

    app_module.config_store.set("HF_TOKEN", "changed-since")
    second = _pipeline_launch_env(_job_row())
    assert second["HF_TOKEN"] == "changed-since"


# ── The operator launch ──────────────────────────────────────────────────────

@pytest.fixture
def sliced_job_with_gcode():
    job_id = _job_row()
    db = TelemetryDB()
    db.update_job_outcome_verdict(job_id, "success", source="machine")
    db.update_job_slice(job_id, status="success")
    db.close()
    directory = OUTPUTS / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "engineered_mesh.gcode").write_text(";TIME:600\nG1 X1 Y1 E0.1\n")
    yield job_id
    for f in directory.iterdir():
        f.unlink()
    directory.rmdir()


def test_the_operator_launch_carries_the_allowlist_and_no_other_stored_key(
    sliced_job_with_gcode, printer_configured, stored,
):
    """`run_operator.py` authenticates from `OCTOPRINT_API_KEY`, and nothing else."""
    stored("OCTOPRINT_API_KEY", "key-for-the-operator")
    stored(NOT_FORWARDED, "DEBUG")

    captured = {}
    fake_process = AsyncMock()
    fake_process.returncode = 0

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return fake_process

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(
            f"/jobs/{sliced_job_with_gcode}/print-dispatch", json={"confirmed": True},
        )
    assert resp.status_code == 200, resp.text

    env = captured["env"]
    assert env["OCTOPRINT_API_KEY"] == "key-for-the-operator"
    assert env.get(NOT_FORWARDED) != "DEBUG"
    assert "PYTHONPATH" not in set(env) - set(os.environ)
