"""Artifacts must belong to the job that produced them.

Every job used to write ``data/outputs/engineered_mesh.*``, so ``/download`` handed out
whatever the last run left behind — including for jobs that never finished slicing.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import DOWNLOAD_FORMATS, app, resolve_job_artifact
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob

client = TestClient(app)
OUTPUTS = Path(__file__).parent.parent / "data" / "outputs"


def _make_job(outcome: str = "success") -> str:
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


@pytest.fixture
def job_dir():
    """A per-job output directory, removed afterwards."""
    created = []

    def _make(job_id: str) -> Path:
        d = OUTPUTS / job_id
        d.mkdir(parents=True, exist_ok=True)
        created.append(d)
        return d

    yield _make

    for d in created:
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


def test_per_job_artifact_wins_over_legacy(job_dir):
    job_id = _make_job()
    d = job_dir(job_id)
    (d / "engineered_mesh.gcode").write_text("G28 ; this job\n")

    resolved = resolve_job_artifact(job_id, "engineered_mesh.gcode")
    assert resolved == d / "engineered_mesh.gcode"
    assert resolved.read_text() == "G28 ; this job\n"


def test_missing_artifact_resolves_to_none():
    assert resolve_job_artifact(str(uuid.uuid4()), "no_such_file.gcode") is None


def test_download_serves_the_jobs_own_gcode(job_dir):
    job_id = _make_job()
    d = job_dir(job_id)
    (d / "engineered_mesh.gcode").write_text("G28 ; mine\n")

    resp = client.get(f"/jobs/{job_id}/download")
    assert resp.status_code == 200
    assert resp.text == "G28 ; mine\n"
    assert job_id in resp.headers["content-disposition"]


def test_download_refuses_legacy_file_for_unfinished_job():
    """An in-flight job must not be handed the shared legacy artifact."""
    job_id = _make_job(outcome="unknown")
    legacy = OUTPUTS / "engineered_mesh.gcode"
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    pre_existing = legacy.exists()
    if not pre_existing:
        legacy.write_text("G28 ; someone else's print\n")

    try:
        resp = client.get(f"/jobs/{job_id}/download")
        assert resp.status_code == 404
    finally:
        if not pre_existing:
            legacy.unlink()


def test_download_404_for_unknown_job():
    assert client.get(f"/jobs/{uuid.uuid4()}/download").status_code == 404


# ── ?format= ─────────────────────────────────────────────────────────────────
#
# One endpoint with a parameter, because the download *event* means "a person kept
# this result" and that fact does not subdivide by extension. `gcode` stays the
# default so callers written before the parameter are unaffected.

def _write_all_formats(directory: Path) -> None:
    for filename, _ in DOWNLOAD_FORMATS.values():
        (directory / filename).write_bytes(f"bytes of {filename}".encode())


@pytest.mark.parametrize("fmt,media_type", [
    ("gcode", "text/plain"),
    ("stl", "model/stl"),
    ("3mf", "model/3mf"),
])
def test_download_serves_each_format_with_its_type_and_filename(job_dir, fmt, media_type):
    job_id = _make_job()
    _write_all_formats(job_dir(job_id))

    resp = client.get(f"/jobs/{job_id}/download?format={fmt}")
    assert resp.status_code == 200
    assert resp.content == f"bytes of engineered_mesh.{fmt}".encode()
    assert resp.headers["content-type"].startswith(media_type)
    assert resp.headers["content-disposition"] == f'attachment; filename="{job_id}.{fmt}"'


def test_the_default_format_is_still_the_gcode(job_dir):
    """The parameter is additive: an existing caller sends nothing and gets G-code."""
    job_id = _make_job()
    _write_all_formats(job_dir(job_id))

    resp = client.get(f"/jobs/{job_id}/download")
    assert resp.status_code == 200
    assert resp.content == b"bytes of engineered_mesh.gcode"
    assert resp.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("fmt", ["obj", "amf", "", "STL", "gcode.stl"])
def test_an_unknown_format_is_a_400_naming_the_ones_that_work(job_dir, fmt):
    """A 404 would send someone looking for a missing file when the spelling is what
    is wrong, so the format is decided before the job is even looked up."""
    job_id = _make_job()
    _write_all_formats(job_dir(job_id))

    resp = client.get(f"/jobs/{job_id}/download?format={fmt}")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "3mf" in detail and "stl" in detail and "gcode" in detail


def test_an_unknown_format_is_refused_for_an_unknown_job_too():
    resp = client.get(f"/jobs/{uuid.uuid4()}/download?format=nonsense")
    assert resp.status_code == 400


def test_a_missing_file_for_a_known_format_is_a_404(job_dir):
    """The 3MF predates nothing: jobs engineered before this change have no `.3mf`,
    and that is a missing file rather than a bad request."""
    job_id = _make_job()
    d = job_dir(job_id)
    (d / "engineered_mesh.gcode").write_text("G28\n")

    assert client.get(f"/jobs/{job_id}/download?format=gcode").status_code == 200
    assert client.get(f"/jobs/{job_id}/download?format=3mf").status_code == 404
    assert client.get(f"/jobs/{job_id}/download?format=stl").status_code == 404
