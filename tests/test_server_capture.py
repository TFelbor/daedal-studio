"""Server-side capture hygiene.

Four ways meaningless data used to reach the pilot dataset through the API layer:
`dev`/`declined` verdicts counted as failures in the dashboard and as answers in
the response rate; the G-code preview's automatic fetch counted as a human
download; the manual failure endpoint pinned its coordinates to the *oldest*
sample of the print and accepted unknown job ids; and the dispatch target — the
only thing that distinguishes simulator telemetry from real hardware — was never
written to the row.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample
from server.app import app

client = TestClient(app)
OUTPUTS = Path(__file__).parent.parent / "data" / "outputs"


def _insert_job(outcome: str = "awaiting_verdict", **kwargs) -> str:
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
            completed_at=datetime.now(timezone.utc),
            outcome=outcome,
            **kwargs,
        )
    )
    db.close()
    return job_id


def _insert_sample(job_id: str, z: float, when: datetime) -> None:
    db = TelemetryDB()
    db.insert_sample(
        TelemetrySample(
            job_id=job_id,
            sampled_at=when,
            gcode_line=None,
            z_height_mm=z,
            hotend_actual_c=210.0,
            hotend_target_c=210.0,
            bed_actual_c=60.0,
            bed_target_c=60.0,
            print_speed_pct=None,
            extrusion_factor_pct=None,
            fan_speed_pct=None,
        )
    )
    db.close()


# ── dev / declined are not failures and not answers ────────────────────────

def test_dev_and_declined_get_their_own_stats_buckets():
    dev_id = _insert_job("dev")
    declined_id = _insert_job("declined")

    stats = client.get("/jobs").json()["stats"]
    assert stats["dev"] >= 1
    assert stats["declined"] >= 1

    failed_ids = {
        j["job_id"] for j in client.get("/jobs?status=failed&limit=200").json()["jobs"]
    }
    assert dev_id not in failed_ids
    assert declined_id not in failed_ids


def test_declined_and_dev_verdicts_are_not_answers_in_the_funnel(isolated_db_env):
    db = TelemetryDB()

    def job(job_id, verdict):
        db.insert_job(
            PrintJob(
                job_id=job_id, prompt="p", printer_id="pr",
                printer_firmware="octoprint", slicer="cura", profile_name="x",
                started_at=None, completed_at=None, outcome="awaiting_verdict",
            )
        )
        db.record_job_event(job_id, "outcome_prompt_shown")
        db.record_job_event(job_id, "outcome_reported", {"verdict": verdict})

    job("j-success", "success")
    job("j-declined", "declined")
    job("j-dev", "dev")

    funnel = db.feedback_funnel()
    db.close()
    assert funnel["prompted"] == 3
    assert funnel["answered"] == 1, "declined and dev are not evidence answers"
    assert funnel["declined"] == 1


# ── The preview fetch is not a download ─────────────────────────────────────

@pytest.fixture
def sliced_job_with_gcode():
    job_id = _insert_job("success")
    db = TelemetryDB()
    db.update_job_slice(job_id, status="success")
    db.close()
    directory = OUTPUTS / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "engineered_mesh.gcode").write_text(";TIME:600\nG1 X1 Y1 E0.1\n")
    yield job_id
    for f in directory.iterdir():
        f.unlink()
    directory.rmdir()


def _download_events(job_id: str) -> int:
    db = TelemetryDB()
    events = db.get_job_events(job_id, kind="download")
    job = db.get_job(job_id)
    db.close()
    return len(events), job.download_count


def test_preview_fetch_is_not_recorded_as_a_download(sliced_job_with_gcode):
    job_id = sliced_job_with_gcode
    resp = client.get(f"/jobs/{job_id}/download?preview=1")
    assert resp.status_code == 200
    events, count = _download_events(job_id)
    assert events == 0
    assert count == 0


def test_a_real_download_is_still_recorded(sliced_job_with_gcode):
    job_id = sliced_job_with_gcode
    resp = client.get(f"/jobs/{job_id}/download")
    assert resp.status_code == 200
    events, count = _download_events(job_id)
    assert events == 1
    assert count == 1


# ── Manual failure reports ──────────────────────────────────────────────────

def test_manual_failure_for_an_unknown_job_is_refused():
    resp = client.post(
        "/jobs/no-such-job/failure",
        json={"failure_type": "adhesion", "notes": "x"},
    )
    assert resp.status_code == 404


def test_manual_failure_pins_the_newest_sample_not_the_oldest():
    job_id = _insert_job("awaiting_verdict")
    _insert_sample(job_id, z=0.2, when=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc))
    _insert_sample(job_id, z=42.0, when=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc))

    resp = client.post(
        f"/jobs/{job_id}/failure",
        json={"failure_type": "layer_shift", "notes": "shifted near the top"},
    )
    assert resp.status_code == 200
    assert resp.json()["z_height_mm"] == 42.0


# ── The collector no longer starts at job creation ──────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_no_collector_is_attached_at_job_creation(mock_run, printer_configured):
    from server.app import active_collectors

    before = set(active_collectors)
    resp = client.post("/jobs", json={
        "prompt": "idle telemetry regression",
        "printer_id": "default",
        "profile": "default",
        "skip_visualizer": True,
        "print": True,
        "start_print": True,
    })
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id not in active_collectors
    assert set(active_collectors) == before


# ── The dispatch target is written to the row ───────────────────────────────

def test_dispatch_confirmation_persists_the_target_url(sliced_job_with_gcode, printer_configured):
    job_id = sliced_job_with_gcode

    fake_process = AsyncMock()
    fake_process.returncode = 0
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_process)), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})
    assert resp.status_code == 200

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.dispatched_printer_url, "the confirmed target must be written to the row"
