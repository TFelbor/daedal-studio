import os
import shutil
import pytest
import tempfile
import asyncio
import uuid
from datetime import datetime, timezone
import json
import websockets
import socketio
from aiohttp import web

_ISOLATED_DB_DIR: str | None = None


def pytest_configure(config):
    """Redirect the telemetry database somewhere disposable, before anything reads it.

    Nineteen call sites across tests/ construct ``TelemetryDB()`` with no path, which
    resolves to ``~/.p2p-mesh/telemetry.db`` — the developer's *real* database. Two of
    them (``test_server.py`` and ``test_server_telemetry.py``) then run
    ``DELETE FROM print_job`` against it. A full ``pytest tests/`` run therefore
    destroyed 312 real job rows and left their ``job_event`` children orphaned.

    This is a ``pytest_configure`` hook rather than an autouse fixture because it has
    to win a race: ``TelemetryDB.__init__`` reads ``TELEMETRY_DB_PATH`` at construction
    time and some test modules construct one at *import* time, which happens during
    collection — before any fixture, autouse or not, has run. ``pytest_configure`` is
    the last hook that fires before collection begins.

    ``ConfigStore`` derives ``.config_key`` from the same directory, so redirecting the
    database also keeps tests away from the real encrypted config store — which holds
    HF_TOKEN and OCTOPRINT_API_KEY.
    """
    global _ISOLATED_DB_DIR
    _ISOLATED_DB_DIR = tempfile.mkdtemp(prefix="p2p-test-db-")
    os.environ["TELEMETRY_DB_PATH"] = os.path.join(_ISOLATED_DB_DIR, "telemetry.db")

    # Belt and braces for the paid Phase 2 backend. `PIXAZO_API_KEY` in the
    # environment makes `resolve_backend_name("auto")` select the hosted endpoint at
    # EUR 0.32 a call, so a developer with a real key exported would have the suite
    # spending money. The kill switch is honoured by the backend itself, and the API
    # server forwards it into the pipeline container, so it survives the process
    # boundary that a monkeypatch cannot cross.
    os.environ["P2P_DISABLE_PAID_BACKENDS"] = "1"
    os.environ.pop("PIXAZO_API_KEY", None)

    # Give the throwaway database the shape a deployed one has. `print_job` and
    # friends come from TelemetryDB; `app_config` comes from ConfigStore, whose
    # init_schema() the server only calls from its startup event — and
    # `TestClient(app)` outside a `with` block never fires startup. Against the real
    # database that went unnoticed because the table was already there from ordinary
    # use; against a fresh one, /health dies with "no such table: app_config".
    from pythonsrc.telemetry.db import TelemetryDB as _TelemetryDB
    from server.config_store import ConfigStore as _ConfigStore

    _db = _TelemetryDB(os.environ["TELEMETRY_DB_PATH"])
    _db.init_schema()
    _db.close()
    _ConfigStore(os.environ["TELEMETRY_DB_PATH"]).init_schema()


def pytest_unconfigure(config):
    """Remove the throwaway database directory once the session ends."""
    if _ISOLATED_DB_DIR:
        shutil.rmtree(_ISOLATED_DB_DIR, ignore_errors=True)


from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample

@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = TelemetryDB(db_path=tmp.name)
        db.init_schema()
        yield db
        db.close()

@pytest.fixture
def sample_job(tmp_db):
    job = PrintJob(
        job_id=str(uuid.uuid4()),
        prompt="test prompt",
        printer_id="test_printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    tmp_db.insert_job(job)
    return job

@pytest.fixture
def sample_samples(tmp_db, sample_job):
    import time
    with open("tests/fixtures/sample_telemetry.json") as f:
        samples_data = json.load(f)
    
    samples = []
    for data in samples_data:
        data["job_id"] = sample_job.job_id
        sample = TelemetrySample.from_dict(data)
        tmp_db.insert_sample(sample)
        samples.append(sample)
    
    # Ensure there are 60 samples as requested by the test requirements
    if len(samples) < 60:
        for i in range(len(samples), 60):
            data = samples_data[i % len(samples_data)].copy()
            data["job_id"] = sample_job.job_id
            data["sampled_at"] = datetime.now(timezone.utc).isoformat()
            data["gcode_line"] = i * 10
            sample = TelemetrySample.from_dict(data)
            tmp_db.insert_sample(sample)
            samples.append(sample)
    return samples

@pytest.fixture
async def fake_moonraker_ws(unused_tcp_port):
    async def handler(websocket):
        try:
            async for message in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass

    async with websockets.serve(handler, "127.0.0.1", unused_tcp_port) as server:
        yield f"ws://127.0.0.1:{unused_tcp_port}/websocket"

@pytest.fixture
async def fake_octoprint_sio(unused_tcp_port):
    sio = socketio.AsyncServer(async_mode='aiohttp')
    app = web.Application()
    sio.attach(app)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', unused_tcp_port)
    await site.start()
    
    yield f"http://127.0.0.1:{unused_tcp_port}"
    
    await runner.cleanup()


@pytest.fixture
def printer_configured():
    """Satisfy POST /jobs' "a printer must be configured" gate.

    `printer_status()` inspects live simulator containers and the encrypted config
    store, so without this patch job-submission tests pass or fail depending on what
    happens to be running on the developer's machine.
    """
    from unittest.mock import AsyncMock, patch

    with patch(
        "server.app.printer_status",
        new=AsyncMock(return_value={"configured": True, "type": "simulator", "running": True}),
    ) as p:
        yield p
