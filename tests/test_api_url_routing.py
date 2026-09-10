"""`DS_API_URL` names two different machines, and the pipeline is always a container.

The collectors relay their samples to this server through `$DS_API_URL`
(`internal_telemetry.send_internal_telemetry`), which is what puts live print
telemetry on the job's WebSocket. The value used to be chosen by execution
strategy — `127.0.0.1:8000` for `mps_native`, `host.docker.internal:8000`
otherwise — and one environment served two processes: the *native* Phase 1
subprocess, where the host's loopback is right, and the pipeline, which runs as
`docker compose run --rm pipeline-runner` on **every** strategy including
`mps_native`. So on a Mac the container was handed the address of itself and every
sample POSTed into the void.

Silent in three ways at once, which is why it is worth a test rather than a fix:
the relay falls back to a local broadcaster the container does not have, the
pipeline exits 0 regardless, and it only bites once Phase 5 runs *inside* the
pipeline (`--print`) — which the web app never asks for, since it stops at the
dispatch gate.

The property asserted is therefore about the argument, not the strategy: whatever
`-e DS_API_URL=…` is handed to `docker compose run`, it must never name a loopback
host. And on `mps_native` the two addresses must actually differ, or the fix is
just the old bug written twice.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import pytest

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server import app as app_module
from server.app import NATIVE_API_URL, _container_api_url

REPO_ROOT = Path(__file__).parent.parent

#: Every strategy runs the pipeline in a container; only Phase 1's placement differs.
STRATEGIES = ("mps_native", "nvidia_docker", "cpu_docker")

#: What a container must never be told the API server is. `0.0.0.0` is in here
#: because it is what uvicorn binds *inside* a container and is the kind of value
#: that gets copied into a URL by mistake.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _host_of(url: str) -> str | None:
    return urlparse(url).hostname


# ── _container_api_url ───────────────────────────────────────────────────────

def test_a_loopback_address_is_translated_and_keeps_its_port():
    assert _container_api_url("http://127.0.0.1:8000") == "http://host.docker.internal:8000"
    assert _container_api_url("http://localhost:8000") == "http://host.docker.internal:8000"


def test_a_routable_address_is_left_alone():
    """A real hostname or LAN address means the same thing from either side."""
    assert _container_api_url("http://ds-api.internal:8000") == "http://ds-api.internal:8000"
    assert _container_api_url("http://192.168.1.50:8000") == "http://192.168.1.50:8000"


def test_only_the_host_is_rewritten():
    """The host is parsed, not string-replaced — `_container_database_url`'s reason.

    A path or query that happens to contain the word is not an address.
    """
    assert (
        _container_api_url("http://127.0.0.1:8000/proxy/localhost")
        == "http://host.docker.internal:8000/proxy/localhost"
    )
    assert (
        _container_api_url("https://example.test/x?next=http://localhost:8000")
        == "https://example.test/x?next=http://localhost:8000"
    )


def test_the_native_constant_is_what_gets_translated():
    """The one value set for the native side must survive the boundary as a route."""
    translated = _container_api_url(NATIVE_API_URL)
    assert translated == "http://host.docker.internal:8000"
    assert _host_of(translated) not in LOOPBACK_HOSTS


# ── The argument handed to `docker compose run` ──────────────────────────────

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


def _launches(job_id: str, strategy: str, request: app_module.JobRequest) -> list[tuple]:
    """Drive `_run_pipeline` to its launches and return every (argv, env) pair."""
    (REPO_ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    captured: list[tuple] = []

    fake_process = AsyncMock()
    fake_process.returncode = 0

    async def fake_exec(*cmd, **kwargs):
        captured.append((list(cmd), kwargs.get("env") or {}))
        return fake_process

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()), \
         patch("server.app.get_resolved_strategy", return_value=strategy):
        asyncio.run(app_module._run_pipeline(job_id, request))

    assert captured, "nothing was launched"
    return captured


def _compose_run(launches: list[tuple]) -> tuple:
    """The `docker compose run` launch, which is the pipeline itself."""
    for argv, env in launches:
        if argv[:2] == ["docker", "compose"] and "run" in argv:
            return argv, env
    raise AssertionError(f"no `docker compose run` among {[a[0] for a, _ in launches]}")


def _forwarded(argv: list[str], name: str) -> str | None:
    """The value of a `-e NAME=value` argument, or None if it was not forwarded."""
    for flag, pair in zip(argv, argv[1:]):
        if flag == "-e" and pair.startswith(f"{name}="):
            return pair.split("=", 1)[1]
    return None


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_container_is_never_handed_a_loopback_api_url(strategy):
    request = app_module.JobRequest(
        prompt="a vase", printer_id="default", profile="default", skip_visualizer=True,
    )
    argv, _ = _compose_run(_launches(_job_row(), strategy, request))

    forwarded = _forwarded(argv, "DS_API_URL")
    assert forwarded, "the collectors have nowhere to relay samples without this"
    assert _host_of(forwarded) not in LOOPBACK_HOSTS, (
        f"{strategy} hands the pipeline container {forwarded}, which names the "
        "container itself — the telemetry relay posts into the void"
    )
    assert forwarded == "http://host.docker.internal:8000"


def test_mps_native_keeps_the_two_addresses_apart():
    """Native Phase 1 gets the host's loopback; the container gets the route.

    One environment served both processes, which is how a value that is correct for
    the first one reached the second. `--print` is what makes this run ungated, so
    both launches happen in one call rather than the run parking at the blueprint
    gate after Phase 1.
    """
    job_id = _job_row()
    # Phase 1 is mocked, so its output has to be put where the real one would write
    # it: the run raises if the blueprint is missing before it launches the container.
    blueprint = REPO_ROOT / "data" / "inputs" / job_id / "blueprint.png"
    blueprint.parent.mkdir(parents=True, exist_ok=True)
    blueprint.write_bytes(b"not a real render")

    try:
        request = app_module.JobRequest(
            prompt="a vase", printer_id="default", profile="default", print=True,
        )
        launches = _launches(job_id, "mps_native", request)

        phase1 = next(
            (argv, env) for argv, env in launches
            if "infra/scripts/run_phase1_native.sh" in argv
        )
        assert phase1[1]["DS_API_URL"] == NATIVE_API_URL, (
            "the native process runs on this host, where the server is on loopback"
        )

        argv, _ = _compose_run(launches)
        assert _forwarded(argv, "DS_API_URL") == "http://host.docker.internal:8000"
    finally:
        blueprint.unlink()
        blueprint.parent.rmdir()
