"""Phase 5 does not start without a person.

The pipeline used to be launched with ``--print --start-print``, so the first time
anyone saw which machine a part was going to was in the past tense. These tests hold the
three properties that make the confirmation step real rather than decorative: an
unconfirmed request is refused, the state a job is in is derived rather than guessed,
and a target that moved between the display and the press is refused as well.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server import app as app_module
from server.app import app

client = TestClient(app)
OUTPUTS = Path(__file__).parent.parent / "data" / "outputs"


def _make_job(outcome: str = "success", slice_status: str | None = "success") -> str:
    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    db.insert_job(
        PrintJob(
            job_id=job_id,
            prompt="a low poly planter",
            printer_id="default",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="pythonsrc/profiles/ender3.json",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome=outcome,
        )
    )
    if slice_status:
        db.update_job_slice(job_id, status=slice_status)
    db.close()
    return job_id


@pytest.fixture
def gcode():
    """Write a job's G-code artifact, and take it away afterwards."""
    created: list[Path] = []

    def _write(job_id: str) -> Path:
        directory = OUTPUTS / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "engineered_mesh.gcode"
        path.write_text(";TIME:600\nG1 X1 Y1 E0.1\n")
        created.append(directory)
        return path

    yield _write

    for directory in created:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()


def test_dispatch_is_refused_without_a_confirmation(gcode):
    """The flag *is* the gate: nothing else in the system stops a print."""
    job_id = _make_job()
    gcode(job_id)

    resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": False})
    assert resp.status_code == 400
    assert "confirmation" in resp.json()["detail"].lower()

    # An empty body is not a confirmation either.
    assert client.post(f"/jobs/{job_id}/print-dispatch").status_code == 400


def test_job_awaits_confirmation_once_sliced(gcode):
    job_id = _make_job()
    gcode(job_id)

    body = client.get(f"/jobs/{job_id}").json()
    assert body["dispatch_state"] == "awaiting_confirmation"
    # The target is resolved on read, so the person confirming sees the current printer.
    assert body["dispatch_target"]["firmware"]


def test_job_without_gcode_is_not_ready():
    """A button that would 400 must not be offered."""
    job_id = _make_job()
    assert client.get(f"/jobs/{job_id}").json()["dispatch_state"] == "not_ready"


def test_running_job_is_not_ready(gcode):
    """A pipeline still going may have been launched with --print and dispatch itself."""
    job_id = _make_job(outcome="unknown")
    gcode(job_id)
    assert client.get(f"/jobs/{job_id}").json()["dispatch_state"] == "not_ready"


def test_confirmed_job_reads_as_dispatched(gcode):
    job_id = _make_job()
    gcode(job_id)

    db = TelemetryDB()
    db.record_job_event(job_id, "dispatch_confirmed", {"profile": "x"})
    db.close()

    body = client.get(f"/jobs/{job_id}").json()
    assert body["dispatch_state"] == "dispatched"
    assert client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True}).status_code == 409


def test_target_drift_is_refused(gcode):
    """Confirming a printer you are no longer looking at is not confirming."""
    job_id = _make_job()
    gcode(job_id)

    resp = client.post(
        f"/jobs/{job_id}/print-dispatch",
        json={"confirmed": True, "profile": "pythonsrc/profiles/somebody-elses.json"},
    )
    assert resp.status_code == 409
    assert "changed" in resp.json()["detail"].lower()


def test_awaiting_dispatch_survives_a_reload(gcode):
    """The list filter the UI re-attaches with. Without it the decision disappears."""
    job_id = _make_job()
    gcode(job_id)

    ids = [j["job_id"] for j in client.get("/jobs?status=awaiting_dispatch&limit=50").json()["jobs"]]
    assert job_id in ids

    db = TelemetryDB()
    db.record_job_event(job_id, "dispatch_confirmed", {"profile": "x"})
    db.close()

    ids = [j["job_id"] for j in client.get("/jobs?status=awaiting_dispatch&limit=50").json()["jobs"]]
    assert job_id not in ids


def test_dead_printer_is_refused_before_the_operator_runs(gcode, monkeypatch):
    """Reached and refused, not launched and hoped: a probe here costs one click."""
    job_id = _make_job()
    gcode(job_id)

    async def _offline():
        return {"configured": True, "running": False, "detail": "Connection refused."}

    monkeypatch.setattr(app_module, "printer_status", _offline)
    resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})
    assert resp.status_code == 409
    assert "did not answer" in resp.json()["detail"]

    # Nothing was recorded: a refused dispatch is not a dispatch.
    db = TelemetryDB()
    assert db.get_job_events(job_id, kind="dispatch_confirmed") == []
    assert db.get_job(job_id).outcome == "success"
    db.close()


def test_phase_status_append_is_readable(tmp_path, monkeypatch):
    """Phase 5 now runs from the server, and the rail reads the last line of this file."""
    job_id = str(uuid.uuid4())
    app_module._append_phase_status(job_id, 5, "running")
    status_file = Path(__file__).parent.parent / "data" / "logs" / f"{job_id}.status"
    try:
        record = json.loads(status_file.read_text().strip().splitlines()[-1])
        assert record["phase"] == 5
        assert record["status"] == "running"
        assert record["name"] == "operator"
    finally:
        status_file.unlink(missing_ok=True)


def test_unknown_status_filter_is_refused():
    """An unrecognised filter must not answer with every job.

    `GET /jobs?status=` fell through to no WHERE clause at all when it did not know
    the value, so it answered "every job, newest first" — indistinguishable, to a
    client that only checks whether a row came back, from "here is the job you asked
    about". `NewJob` re-attaches on mount to whatever `status=awaiting_dispatch`
    returns, so a browser one deploy ahead of the server was handed a finished job
    and dropped straight into the running view, with the landing composer
    unreachable for the rest of that tab's life.
    """
    _make_job(outcome="cancelled", slice_status=None)

    resp = client.get("/jobs?status=not_a_status&limit=50")
    assert resp.status_code == 400
    assert "not_a_status" in resp.json()["detail"]

    # The filters it does know still answer.
    for known in ("all", "running", "completed", "failed", "awaiting_verdict", "awaiting_dispatch"):
        assert client.get(f"/jobs?status={known}&limit=1").status_code == 200
