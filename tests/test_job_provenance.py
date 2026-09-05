"""Generation provenance and printability persistence.

These columns exist because they cannot be reconstructed after the fact: once a print
finishes, nothing else records which model produced the mesh, what the generation cost, or
what the geometry looked like before it was sliced.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry import db as db_module
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server.app import app

client = TestClient(app)

OLD_SCHEMA = """
CREATE TABLE print_job (
    job_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    printer_id TEXT NOT NULL,
    printer_firmware TEXT NOT NULL,
    slicer TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    outcome TEXT NOT NULL
)
"""


def make_job(job_id: str, **kwargs) -> PrintJob:
    defaults = dict(
        job_id=job_id,
        prompt="a vase",
        printer_id="printer-1",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="ender3",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown",
    )
    defaults.update(kwargs)
    return PrintJob(**defaults)


@pytest.fixture
def db(isolated_db):
    return isolated_db


# ── Schema ────────────────────────────────────────────────────────────────────


def test_new_fields_default_to_none():
    """Existing callers construct PrintJob positionally; the new columns must be optional."""
    job = make_job("j1")
    assert job.generation_model is None
    assert job.generation_cost_eur is None
    assert job.printability_score is None
    assert job.mesh_features is None


def test_job_round_trips_with_provenance():
    job = make_job(
        "j2",
        generation_model="TRELLIS.2",
        generation_model_version="fal-ai/trellis-2",
        generation_backend="hosted_api",
        generation_params={"resolution": 1024},
        generation_cost_eur=0.30,
        generation_duration_s=41.2,
        mesh_features={"face_count": 20480},
        printability_score=91.5,
        printability_verdict="ready",
        printability_report={"checks": []},
    )
    restored = PrintJob.from_dict(job.to_dict())

    assert restored.generation_model == "TRELLIS.2"
    assert restored.generation_backend == "hosted_api"
    assert restored.generation_cost_eur == 0.30
    assert restored.generation_params == {"resolution": 1024}
    assert restored.printability_score == 91.5


# ── Database ──────────────────────────────────────────────────────────────────


def test_insert_and_read_provenance(db):
    db.insert_job(make_job("j3", generation_model="TripoSR", generation_backend="local"))
    job = db.get_job("j3")

    assert job.generation_model == "TripoSR"
    assert job.generation_backend == "local"


def test_update_job_generation_records_cost_and_latency(db):
    """A pay-per-generation backend bills per call; that number has to land somewhere."""
    db.insert_job(make_job("j4"))
    db.update_job_generation(
        "j4",
        model="TRELLIS.2",
        model_version="fal-ai/trellis-2",
        backend="hosted_api",
        params={"resolution": 1024},
        cost_eur=0.35,
        duration_s=38.9,
    )
    job = db.get_job("j4")

    assert job.generation_model == "TRELLIS.2"
    assert job.generation_model_version == "fal-ai/trellis-2"
    assert job.generation_cost_eur == 0.35
    assert job.generation_duration_s == 38.9
    assert job.generation_params["resolution"] == 1024


def test_partial_update_does_not_erase_earlier_values(db):
    """Cost often arrives after the model name; the later write must not blank the earlier."""
    db.insert_job(make_job("j5"))
    db.update_job_generation("j5", model="TRELLIS.2", backend="hosted_api")
    db.update_job_generation("j5", cost_eur=0.30)
    job = db.get_job("j5")

    assert job.generation_model == "TRELLIS.2"
    assert job.generation_backend == "hosted_api"
    assert job.generation_cost_eur == 0.30


def test_update_job_printability(db):
    db.insert_job(make_job("j6"))
    db.update_job_printability(
        "j6",
        score=72.5,
        verdict="risky",
        features={"min_wall_thickness_mm": 0.6},
        report={"score": 72.5, "checks": [{"check": "min_wall_thickness", "status": "warn"}]},
    )
    job = db.get_job("j6")

    assert job.printability_score == 72.5
    assert job.printability_verdict == "risky"
    assert job.mesh_features["min_wall_thickness_mm"] == 0.6
    assert job.printability_report["checks"][0]["check"] == "min_wall_thickness"


def test_malformed_json_is_refused_at_write_time(db):
    """JSONB validates on write, so a truncated blob can never reach a reader.

    The SQLite version of this test wrote `{not json` into a TEXT column and checked
    the reader degraded to None. The stronger guarantee is that the write itself is
    refused — and the row it targeted is untouched.
    """
    db.insert_job(make_job("j7"))
    with pytest.raises(db_module.DatabaseError):
        db.execute("UPDATE print_job SET mesh_features = %s WHERE job_id = %s", ("{not json", "j7"))

    job = db.get_job("j7")
    assert job.mesh_features is None
    assert job.job_id == "j7"


# ── Migration ─────────────────────────────────────────────────────────────────


def test_migrates_a_pre_existing_database(isolated_db_url):
    """A table carrying only the original nine columns gains the rest, and keeps its rows."""
    legacy = TelemetryDB(isolated_db_url)
    legacy.execute(OLD_SCHEMA)
    legacy.execute(
        "INSERT INTO print_job VALUES ('legacy-1','old prompt','p','octoprint','cura','d',"
        "'2026-01-01T00:00:00+00:00',NULL,'success')"
    )

    database = TelemetryDB(isolated_db_url)
    database.init_schema()

    job = database.get_job("legacy-1")
    assert job.prompt == "old prompt"
    assert job.outcome == "success"
    assert job.printability_score is None

    # The migrated table accepts the new columns.
    database.update_job_printability("legacy-1", score=50.0, verdict="unprintable")
    assert database.get_job("legacy-1").printability_score == 50.0

    database.init_schema()  # idempotent
    assert database.get_job("legacy-1").printability_score == 50.0
    database.close()


# ── API ───────────────────────────────────────────────────────────────────────


def test_printability_endpoint_returns_the_report():
    job_id = str(uuid.uuid4())
    database = TelemetryDB()
    database.init_schema()
    database.insert_job(make_job(job_id))
    report = {
        "job_id": job_id,
        "score": 88.0,
        "verdict": "risky",
        "process": "fdm",
        "evaluated_at": "2026-08-19T12:00:00+00:00",
        "checks": [{"check": "bed_contact", "status": "warn", "detail": "small footprint",
                    "value": 4.0, "threshold": 25.0, "weight": 1.0, "critical": False}],
        "features": {"face_count": 1200},
    }
    database.update_job_printability(job_id, score=88.0, verdict="risky",
                                    features=report["features"], report=report)
    database.close()

    resp = client.get(f"/jobs/{job_id}/printability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 88.0
    assert body["checks"][0]["check"] == "bed_contact"


def test_printability_endpoint_returns_a_recorded_scoring_failure():
    """A scorer that crashed is reported as a crash, not as an absent report.

    The two are different facts and the UI renders them differently: "nothing measured
    this mesh" versus "the measurement broke, here is why". Collapsing them into a 404
    is what let a broken gate look like a clean one.
    """
    job_id = str(uuid.uuid4())
    database = TelemetryDB()
    database.init_schema()
    database.insert_job(make_job(job_id))
    envelope = {
        "job_id": job_id,
        "evaluated_at": "2026-08-21T18:00:00+00:00",
        "status": "error",
        "error": "Voxelisation failed at every pitch",
        "error_type": "MemoryError",
    }
    database.update_job_printability(job_id, report=envelope)
    job = database.get_job(job_id)
    # No score is invented for a run that produced none.
    assert job.printability_score is None
    assert job.printability_verdict is None
    database.close()

    resp = client.get(f"/jobs/{job_id}/printability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["error_type"] == "MemoryError"
    assert "checks" not in body


def test_printability_endpoint_404s_without_a_report():
    job_id = str(uuid.uuid4())
    database = TelemetryDB()
    database.init_schema()
    database.insert_job(make_job(job_id))
    database.close()

    assert client.get(f"/jobs/{job_id}/printability").status_code == 404


def test_printability_endpoint_404s_for_unknown_job():
    assert client.get(f"/jobs/{uuid.uuid4()}/printability").status_code == 404


def test_job_status_exposes_the_score():
    """The job list and progress bar read the score without fetching the whole report."""
    job_id = str(uuid.uuid4())
    database = TelemetryDB()
    database.init_schema()
    database.insert_job(make_job(job_id))
    database.update_job_printability(job_id, score=64.0, verdict="risky")
    database.close()

    body = client.get(f"/jobs/{job_id}").json()
    assert body["printability_score"] == 64.0
    assert body["printability_verdict"] == "risky"
