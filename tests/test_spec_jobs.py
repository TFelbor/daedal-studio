"""A spec reaches the pipeline through `POST /jobs`, and the row says the spec decided.

`size_source` had three values — `default`, `user`, `prompt_hint` — and a spec job fit
none of them: its row read `size_source="default"`, a claim that the 50 mm default applied
to a part whose every dimension the spec fixed. The request model now carries the spec,
validated on the model with the stdlib-only schema (the reason `pythonsrc.organizer`
imports nothing heavy), written canonically into the job's own input directory, and
forwarded as `--spec`. The row records `size_source="spec"` with no size and no axis: the
spec is the size.

A spec run is also never a Phase 1 run. It must not be handed the shared blueprint path,
must not arm the blueprint gate, and must not be combinable with a requested size.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.organizer.spec import OrganizerSpec, canonical_json
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import VALID_SIZE_SOURCES, PrintJob
from server import app as app_module
from server.app import app

client = TestClient(app)
REPO_ROOT = Path(app_module.__file__).parent.parent

SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}


def _request(**overrides):
    payload = {"prompt": "a 100-card commander deck box", "printer_id": "default"}
    payload.update(overrides)
    return app_module.JobRequest(**payload)


def _row_count():
    db = TelemetryDB()
    n = db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"]
    db.close()
    return n


@pytest.fixture
def clean_inputs():
    """Remove the per-job input directory a spec job writes under the real `data/`."""
    created = []
    yield created
    for job_id in created:
        shutil.rmtree(REPO_ROOT / "data" / "inputs" / job_id, ignore_errors=True)


# ── the schema ────────────────────────────────────────────────────────────────

def test_spec_is_a_valid_size_source():
    assert "spec" in VALID_SIZE_SOURCES
    PrintJob(job_id="j", prompt="p", printer_id="d", printer_firmware="octoprint",
             slicer="cura", profile_name="default", started_at=None, completed_at=None,
             outcome="unknown", size_source="spec")


# ── the argv ──────────────────────────────────────────────────────────────────

def test_a_spec_path_reaches_the_pipeline_as_the_spec_flag():
    request = _request(spec=SPEC)
    request.spec_path = "/app/data/inputs/j1/spec.json"
    args = app_module._pipeline_args(request, skip_viz=True, skip_sculpt=True, profile=None)
    assert args[args.index("--spec") + 1] == "/app/data/inputs/j1/spec.json"


def test_a_spec_run_is_not_handed_the_shared_blueprint():
    """`--skip-visualizer --blueprint <shared>` is how a skip-Phase-1 run reuses an image
    someone put there. A spec run has no image; given that path it would snapshot another
    job's render and record its hash as this job's provenance."""
    request = _request(spec=SPEC)
    request.spec_path = "/app/data/inputs/j1/spec.json"
    args = app_module._pipeline_args(request, skip_viz=True, skip_sculpt=True, profile=None)
    assert "--blueprint" not in args
    assert "--skip-visualizer" not in args and "--skip-sculptor" not in args
    assert "--target-mm" not in args and "--scale-axis" not in args


def test_a_spec_request_skips_both_generative_phases_and_is_not_gated():
    skip_viz, skip_sculpt = app_module._phase_skips(_request(spec=SPEC))
    assert skip_viz is True and skip_sculpt is True


def test_without_a_spec_the_skips_come_from_the_request():
    skip_viz, skip_sculpt = app_module._phase_skips(_request())
    assert skip_viz is False and skip_sculpt is False
    skip_viz, skip_sculpt = app_module._phase_skips(_request(skip_visualizer=True))
    assert skip_viz is True


# ── the row ───────────────────────────────────────────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_job_records_that_the_spec_decided_the_size(mock_run, printer_configured, clean_inputs):
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": SPEC})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    assert job.size_source == "spec"
    assert job.requested_size_mm is None
    assert job.requested_scale_axis is None
    assert job.request_params["spec"] == SPEC
    assert job.request_params["spec_path"] == f"/app/data/inputs/{job_id}/spec.json"


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_spec_is_written_canonically_into_the_jobs_own_input_directory(mock_run, printer_configured, clean_inputs):
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": SPEC})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    clean_inputs.append(job_id)

    written = REPO_ROOT / "data" / "inputs" / job_id / "spec.json"
    assert written.exists()
    on_disk = OrganizerSpec.from_json(written.read_text())
    assert canonical_json(on_disk) == canonical_json(OrganizerSpec.from_dict(SPEC))
    # The subprocess was launched with a request that names the container path.
    launched = mock_run.call_args.args[1]
    assert launched.spec_path == f"/app/data/inputs/{job_id}/spec.json"


# ── refusals, on the model, before a row exists ───────────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_and_a_requested_size_are_refused_together(mock_run, printer_configured):
    before = _row_count()
    resp = client.post("/jobs", json={
        "prompt": "a deck box", "printer_id": "default", "spec": SPEC, "target_mm": 80.0,
    })
    assert resp.status_code == 422
    assert "spec" in resp.text and "target_mm" in resp.text
    assert _row_count() == before
    mock_run.assert_not_called()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_an_invalid_spec_is_refused_with_every_problem_named(mock_run, printer_configured):
    before = _row_count()
    bad = dict(SPEC, compartments=[], lid=dict(SPEC["lid"], clearance_mm=-1))
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": bad})
    assert resp.status_code == 422
    assert "compartments" in resp.text and "clearance_mm" in resp.text
    assert _row_count() == before
    mock_run.assert_not_called()


@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_a_spec_the_archetype_refuses_is_a_422_not_a_failed_phase_2(mock_run, printer_configured):
    """`deck_box.validate` is not importable in the api-server image (it needs the
    kernel), so the server can only run the schema. It must at least not accept what
    the schema refuses."""
    before = _row_count()
    bad = dict(SPEC, archetype="dragon")
    resp = client.post("/jobs", json={"prompt": "a deck box", "printer_id": "default", "spec": bad})
    assert resp.status_code == 422
    assert "archetype" in resp.text
    assert _row_count() == before


def test_a_client_cannot_claim_spec_as_a_size_source():
    """Only the server derives it, from the presence of a spec."""
    with pytest.raises(Exception):
        _request(target_mm=80.0, size_source="spec")
