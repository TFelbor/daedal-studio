import os
import shutil
import pytest
import tempfile
import uuid
from datetime import datetime, timezone
import json
import websockets
import socketio
from aiohttp import web

from tests.sweep_tally import SweepTally
from tests.testing_postgres import TestPostgres

_ISOLATED_DIR: str | None = None
_TEST_PG: TestPostgres | None = None
_SESSION_SCHEMA: str | None = None


def pytest_configure(config):
    """Point every database read and write at a throwaway PostgreSQL, before anything reads it.

    Dozens of call sites across tests/ construct ``TelemetryDB()`` with no argument,
    which resolves ``DS_DATABASE_URL`` — in a developer's shell, the Supabase project.
    Two of them (``test_server.py`` and ``test_server_telemetry.py``) then run
    ``DELETE FROM print_job``. The SQLite-era suite once destroyed 312 real job rows
    exactly this way; the variable is therefore rewritten here, to a schema this run
    created and will drop, before a single test module is imported.

    This is a ``pytest_configure`` hook rather than an autouse fixture because it has
    to win a race: ``TelemetryDB.__init__`` reads the URL at construction time and some
    test modules construct one at *import* time, which happens during collection —
    before any fixture, autouse or not, has run. ``pytest_configure`` is the last hook
    that fires before collection begins.

    ``ConfigStore`` keeps its Fernet key at ``DS_CONFIG_KEY_PATH``, so that is
    redirected to the same temporary directory — the real key decrypts HF_TOKEN and
    OCTOPRINT_API_KEY, and the suite must not read or rotate it.

    See ``tests/testing_postgres.py`` for where the PostgreSQL comes from.
    """
    global _ISOLATED_DIR, _TEST_PG, _SESSION_SCHEMA
    _ISOLATED_DIR = tempfile.mkdtemp(prefix="ds-test-")
    os.environ["DS_CONFIG_KEY_PATH"] = os.path.join(_ISOLATED_DIR, ".config_key")

    _TEST_PG = TestPostgres()
    try:
        _TEST_PG.start()
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc)) from exc
    _SESSION_SCHEMA, session_url = _TEST_PG.create_schema()
    os.environ["DS_DATABASE_URL"] = session_url

    # Belt and braces for the paid Phase 2 backend. `PIXAZO_API_KEY` in the
    # environment makes `resolve_backend_name("auto")` select the hosted endpoint at
    # EUR 0.32 a call, so a developer with a real key exported would have the suite
    # spending money. The kill switch is honoured by the backend itself, and the API
    # server forwards it into the pipeline container, so it survives the process
    # boundary that a monkeypatch cannot cross.
    os.environ["DS_DISABLE_PAID_BACKENDS"] = "1"
    os.environ.pop("PIXAZO_API_KEY", None)

    # Give the throwaway schema the shape a deployed one has. `print_job` and friends
    # come from TelemetryDB; `app_config` comes from ConfigStore, whose init_schema()
    # the server only calls from its startup event — and `TestClient(app)` outside a
    # `with` block never fires startup, so /health would otherwise die with
    # `relation "app_config" does not exist`.
    from pythonsrc.telemetry.db import TelemetryDB as _TelemetryDB
    from server.config_store import ConfigStore as _ConfigStore

    _TelemetryDB().init_schema()
    _ConfigStore().init_schema()

    # Cut the shared SimulatorManager off from the real Docker daemon, for the same
    # reason the database is redirected: the suite must not reach outside itself.
    # `server.app`'s shutdown hook calls `stop_octoprint()`, and every test that
    # enters a `TestClient` context manager fires it — so running `pytest tests/`
    # stopped the developer's OctoPrint simulator, mid-session, with nothing in the
    # output saying so. Raising the manager's own typed error is what the code
    # already treats as "cannot tell": `_client_or_none()` returns None and
    # `stop_octoprint` becomes a no-op. Tests that need simulator behaviour build
    # their own `SimulatorManager(client_factory=...)` with a fake, and the two that
    # need the singleton monkeypatch the method they care about — so nothing here
    # depends on this ever succeeding. (The test PostgreSQL container is started with
    # the Docker *CLI*, deliberately outside this manager.)
    from server.simulator_manager import SimulatorAvailabilityError, simulator_manager as _sim

    def _no_docker_in_tests():
        raise SimulatorAvailabilityError("Docker is not reachable from the test suite.")

    _sim._client = None
    _sim._client_factory = _no_docker_in_tests

    _stash_shared_blueprint()


#: Where a real `data/inputs/blueprint.png` was moved to for the session, if there was
#: one. A list so `pytest_unconfigure` can put back exactly what it took and nothing else.
_STASHED_BLUEPRINT: list = []


def _stash_shared_blueprint():
    """Move a real shared blueprint out of the suite's way, and remember to put it back.

    `data/inputs/blueprint.png` is a live runtime artifact, not scratch space: it is
    the image a skip-Phase-1 run exists to reuse, which is precisely why `POST /jobs`
    was changed to stop deleting it in its stale-artifact sweep. Three tests
    (`test_blueprint_gate.py` twice, `test_ip_screen.py` once) write to that exact path
    to exercise the real resolution order — `_snapshot_blueprint` and `create_job`
    derive it from `server/app.py`'s own location, so there is no path to redirect —
    and then `unlink()` it. A full `pytest tests/` therefore destroyed whatever render
    was sitting there, silently, the same way it once destroyed real job rows.

    It also fails outright when that file was written by a container: the bind mounts
    run as root, so the PNG comes back `root:root 0644` and the developer's own
    interpreter cannot open it for writing. Renaming needs write permission on the
    *directory*, not the file, so moving it aside works where overwriting does not —
    and the tests then create their own from scratch.

    Restored by `pytest_unconfigure`. A crash hard enough to skip that leaves the file
    under `_ISOLATED_DIR`, named as it was, rather than gone.
    """
    import pathlib

    inputs = pathlib.Path(__file__).parent.parent / "data" / "inputs"
    for name in ("blueprint.png", "blueprint.provenance.json"):
        source = inputs / name
        if not source.exists():
            continue
        stashed = pathlib.Path(_ISOLATED_DIR) / f"stashed-{name}"
        try:
            # `shutil.move`, not `os.rename`: the stash is a tempdir, which is
            # routinely on a different filesystem from the repo, and `os.rename` fails
            # EXDEV there. Silently — the except below swallowed it, the file was
            # never stashed, and the tests deleted the real one anyway.
            shutil.move(str(source), str(stashed))
        except OSError:
            # Nothing here is worth failing a test run over; the worst case is the
            # pre-existing behaviour.
            continue
        _STASHED_BLUEPRINT.append((str(stashed), str(source)))


def pytest_unconfigure(config):
    """Put back the shared blueprint, drop the session schema, stop the container."""
    for stashed, original in _STASHED_BLUEPRINT:
        try:
            # The tests leave their own file behind on some paths; the real one wins.
            if os.path.exists(original):
                os.unlink(original)
            shutil.move(stashed, original)
        except OSError:
            pass
    _STASHED_BLUEPRINT.clear()

    try:
        from pythonsrc.telemetry.db import close_pools

        close_pools()
    except Exception:  # noqa: BLE001 — teardown must finish
        pass
    if _TEST_PG is not None:
        try:
            if _SESSION_SCHEMA:
                _TEST_PG.drop_schema(_SESSION_SCHEMA)
        except Exception:  # noqa: BLE001
            pass
        _TEST_PG.stop()

    if _ISOLATED_DIR:
        shutil.rmtree(_ISOLATED_DIR, ignore_errors=True)


from pythonsrc.telemetry.db import TelemetryDB, close_pool
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample


@pytest.fixture
def isolated_db_url():
    """A URL onto a fresh, empty schema that exists only for this test.

    What a temporary SQLite file used to be: a database nothing else can see, thrown
    away afterwards. Pass it to `TelemetryDB(...)`, or set it as `DS_DATABASE_URL` for
    code that resolves the default.
    """
    name, url = _TEST_PG.create_schema()
    yield url
    close_pool(url)
    _TEST_PG.drop_schema(name)


@pytest.fixture
def isolated_db(isolated_db_url):
    """A `TelemetryDB` on its own schema, with the current schema applied."""
    db = TelemetryDB(isolated_db_url)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def isolated_db_env(isolated_db_url, monkeypatch):
    """Make the fresh schema the *default* database for the duration of the test.

    For code that constructs `TelemetryDB()` with no argument — the pipeline recorders,
    the server's handlers — and must be kept off the session schema other tests share.
    """
    monkeypatch.setenv("DS_DATABASE_URL", isolated_db_url)
    TelemetryDB().init_schema()
    return isolated_db_url


@pytest.fixture
def tmp_db(isolated_db):
    return isolated_db

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


# ── The dimensional sweep's summary (issue #85) ────────────────────────────────
#
# `tests/test_organizer_dimensional_accuracy.py` drives every registered archetype over
# the envelope its own module declares, and CI runs it as a named step. These three
# hooks turn that into one line per archetype at the end of the run, so "which
# archetypes were swept, and how far" is legible from the job list without opening a
# log. They live in `conftest.py` because pytest only reads reporting hooks from a
# conftest or a plugin; the counting and the wording are in `tests/sweep_tally.py`,
# where they can be tested directly.

_SWEEP_TALLY = SweepTally()
#: nodeid → archetype, built at collection because `pytest_runtest_logreport` is handed
#: a report rather than an item and cannot reach the parametrized values itself.
_SWEEP_ARCHETYPES: dict[str, str] = {}


def pytest_collection_modifyitems(config, items):
    """Note which collected cases belong to which archetype's envelope."""
    for item in items:
        if item.get_closest_marker("dimensional_sweep") is None:
            continue
        callspec = getattr(item, "callspec", None)
        archetype = callspec.params.get("archetype") if callspec is not None else None
        if isinstance(archetype, str):
            _SWEEP_ARCHETYPES[item.nodeid] = archetype


def pytest_runtest_logreport(report):
    if report.when != "call":
        return
    archetype = _SWEEP_ARCHETYPES.get(report.nodeid)
    if archetype is not None:
        _SWEEP_TALLY.record(archetype, report.outcome)


def pytest_terminal_summary(terminalreporter):
    if not _SWEEP_TALLY:
        return
    terminalreporter.write_sep("-", "dimensional sweep (PRD N1)")
    for line in _SWEEP_TALLY.lines():
        terminalreporter.write_line(line)
