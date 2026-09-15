"""Stopping a job must read as stopped — and must not be recorded as a crash.

Pressing "Stop job" used to do three things wrong at once, all silently:

1. The cancel endpoint wrote ``outcome="cancelled"``, then ``_run_pipeline`` observed
   the killed process's non-zero exit code, read it as a crash, and overwrote the row
   with ``"failure"``. Both are machine-sourced writes, so the precedence rule in
   ``update_job_outcome_verdict`` does not stop it. The user's stop became a failure,
   and the dataset gained a crash that never happened.
2. A killed pipeline never writes the ``.status`` line that would close its phase out,
   so ``GET /jobs/{id}`` kept reporting that phase as ``running`` forever. Every poll
   re-lit the pulse the cancel had just put out, which is what made the button look
   like it had done nothing.
3. Nothing killed the process if it ignored SIGTERM.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server.app import _read_current_phase, app

client = TestClient(app)
LOGS = Path(__file__).parent.parent / "data" / "logs"


def _make_job(outcome: str | None = "unknown") -> str:
    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    db.insert_job(
        PrintJob(
            job_id=job_id,
            prompt="a vase",
            printer_id="default",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="default",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome=outcome,
        )
    )
    db.close()
    return job_id


def _write_status(job_id: str, phase: int, status: str) -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"{job_id}.status"
    path.write_text(json.dumps({"phase": phase, "name": "Sculptor", "status": status}) + "\n")
    return path


@pytest.fixture
def status_file():
    written: list[Path] = []
    yield written.append
    for path in written:
        path.unlink(missing_ok=True)


def test_status_file_reader_returns_the_last_line(status_file):
    job_id = _make_job()
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"{job_id}.status"
    path.write_text(
        json.dumps({"phase": 1, "name": "Visualizer", "status": "complete"}) + "\n"
        + json.dumps({"phase": 2, "name": "Sculptor", "status": "running"}) + "\n"
    )
    status_file(path)

    assert _read_current_phase(job_id) == {
        "phase": 2, "name": "Sculptor", "status": "running",
    }


def test_missing_status_file_is_not_an_error():
    assert _read_current_phase(str(uuid.uuid4())) is None


def test_a_running_job_still_reports_its_phase_as_running(status_file):
    """The downgrade must not fire on a job that genuinely is still going."""
    job_id = _make_job(outcome="unknown")
    status_file(_write_status(job_id, 2, "running"))

    body = client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "running"
    assert body["current_phase"]["status"] == "running"


@pytest.mark.parametrize("outcome", ["cancelled", "failure"])
def test_a_stopped_job_never_reports_a_running_phase(status_file, outcome):
    """A frozen `.status` file must not outvote the row's own outcome.

    This is the one that made Stop job look inert: the phase kept pulsing because the
    pipeline was killed before it could write the line that closed the phase out.
    """
    job_id = _make_job(outcome=outcome)
    status_file(_write_status(job_id, 2, "running"))

    body = client.get(f"/jobs/{job_id}").json()

    assert body["outcome"] == outcome
    assert body["current_phase"]["status"] == "error"
    assert body["current_phase"]["phase"] == 2


def test_a_completed_phase_is_left_alone(status_file):
    """Only a stale *running* phase is rewritten; real results are not touched."""
    job_id = _make_job(outcome="cancelled")
    status_file(_write_status(job_id, 3, "complete"))

    body = client.get(f"/jobs/{job_id}").json()

    assert body["current_phase"]["status"] == "complete"


def test_cancelling_records_cancelled_and_flags_the_job(status_file):
    job_id = _make_job(outcome="unknown")
    status_file(_write_status(job_id, 2, "running"))

    res = client.delete(f"/jobs/{job_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.outcome == "cancelled"
    assert job.outcome_source == "machine"
    assert job.completed_at is not None

    # And the derived view agrees, rather than still claiming phase 2 is running.
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "cancelled"
    assert body["current_phase"]["status"] == "error"


def test_cancelling_an_unknown_job_is_a_404():
    assert client.delete(f"/jobs/{uuid.uuid4()}").status_code == 404


def test_a_human_verdict_survives_a_cancel(status_file):
    """`update_job_outcome_verdict`'s precedence rule must still hold here."""
    job_id = _make_job(outcome="unknown")
    db = TelemetryDB()
    db.update_job_outcome_verdict(job_id, "success", source="user")
    db.close()

    client.delete(f"/jobs/{job_id}")

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.outcome == "success"
    assert job.outcome_source == "user"
