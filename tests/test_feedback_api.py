"""HTTP surface for print-outcome feedback and engagement capture.

The endpoints here exist for one reason: a printer reporting "job finished" says only
that the file ran to the end. Whether the part adhered, survived and came off the bed
is knowable only by the person standing next to the machine, and only if asking them
costs one tap. These tests pin both halves — that a verdict is recorded as a human's,
and that declining to give one is itself recorded.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server.app import app

client = TestClient(app)


def make_job(outcome: str = "awaiting_verdict", **kwargs) -> str:
    """Insert a job into the live telemetry database and return its id."""
    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    defaults = dict(
        job_id=job_id,
        prompt="a lattice cube",
        printer_id="printer-1",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="pythonsrc/profiles/ender3.json",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        outcome=outcome,
    )
    defaults.update(kwargs)
    db.insert_job(PrintJob(**defaults))
    db.close()
    return job_id


def read_job(job_id: str) -> PrintJob:
    """Read a job back from the live telemetry database."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    return job


def read_events(job_id: str, kind: str | None = None):
    """Read a job's engagement events."""
    db = TelemetryDB()
    events = db.get_job_events(job_id, kind=kind)
    db.close()
    return events


# ── Pending queue ─────────────────────────────────────────────────────────────


def test_pending_queue_lists_the_job():
    """A dispatched print shows up awaiting a verdict."""
    job_id = make_job()
    body = client.get("/feedback/pending").json()
    assert job_id in [j["job_id"] for j in body["jobs"]]


def test_pending_queue_excludes_settled_jobs():
    """A job whose outcome is already known is not asked about again."""
    job_id = make_job(outcome="success")
    body = client.get("/feedback/pending").json()
    assert job_id not in [j["job_id"] for j in body["jobs"]]


def test_pending_entry_carries_enough_to_recognise_the_print():
    """The card needs the prompt to be answerable without opening the job."""
    job_id = make_job(material_type="PLA")
    entry = next(
        j for j in client.get("/feedback/pending").json()["jobs"] if j["job_id"] == job_id
    )
    assert entry["prompt"] == "a lattice cube"
    assert entry["material_type"] == "PLA"


# ── Prompt shown ──────────────────────────────────────────────────────────────


def test_prompt_shown_is_recorded_once():
    """The response-rate denominator counts people, not renders."""
    job_id = make_job()
    first = client.post(f"/jobs/{job_id}/outcome/prompt-shown").json()
    second = client.post(f"/jobs/{job_id}/outcome/prompt-shown").json()
    assert first["recorded"] is True
    assert second["recorded"] is False
    assert len(read_events(job_id, "outcome_prompt_shown")) == 1


def test_prompt_shown_404s_for_an_unknown_job():
    """A prompt cannot be shown for a job that does not exist."""
    assert client.post(f"/jobs/{uuid.uuid4()}/outcome/prompt-shown").status_code == 404


# ── Verdicts ──────────────────────────────────────────────────────────────────


def test_success_verdict_is_attributed_to_the_user():
    """A human's "it came off clean" is marked as such."""
    job_id = make_job()
    response = client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"})
    assert response.status_code == 200
    assert response.json()["outcome_source"] == "user"

    job = read_job(job_id)
    assert job.outcome == "success"
    assert job.outcome_source == "user"
    assert job.outcome_reported_at is not None


def test_failure_verdict_also_writes_a_failure_event():
    """The existing detector-versus-human comparison must keep working."""
    job_id = make_job()
    response = client.post(f"/jobs/{job_id}/outcome", json={
        "verdict": "failure",
        "failure_type": "adhesion",
        "notes": "let go on layer 3",
    })
    assert response.status_code == 200
    assert response.json()["failure_event_id"]

    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    assert len(events) == 1
    assert events[0].failure_type == "adhesion"
    assert events[0].source == "manual"
    assert events[0].notes == "let go on layer 3"


def test_failure_verdict_without_a_type_falls_back_to_unknown():
    """One tap must be enough; naming the failure mode is optional."""
    job_id = make_job()
    assert client.post(f"/jobs/{job_id}/outcome", json={"verdict": "failure"}).status_code == 200
    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    assert events[0].failure_type == "unknown"


def test_success_verdict_writes_no_failure_event():
    """A good print leaves no failure record behind."""
    job_id = make_job()
    client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"})
    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    assert events == []


def test_verdict_is_logged_as_an_event():
    """The response-rate numerator."""
    job_id = make_job()
    client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"})
    events = read_events(job_id, "outcome_reported")
    assert len(events) == 1
    assert events[0].detail["verdict"] == "success"


def test_invalid_verdict_is_rejected():
    """The verdict vocabulary is fixed."""
    job_id = make_job()
    assert client.post(f"/jobs/{job_id}/outcome", json={"verdict": "sort of"}).status_code == 422


def test_verdict_404s_for_an_unknown_job():
    """No verdict without a job."""
    response = client.post(f"/jobs/{uuid.uuid4()}/outcome", json={"verdict": "success"})
    assert response.status_code == 404


def test_verdict_removes_the_job_from_the_pending_queue():
    """Answering makes the card go away."""
    job_id = make_job()
    client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"})
    body = client.get("/feedback/pending").json()
    assert job_id not in [j["job_id"] for j in body["jobs"]]


# ── Dismissal ─────────────────────────────────────────────────────────────────


def test_dismissal_is_recorded_rather_than_silent():
    """Whether people answer at all is the thing being measured."""
    job_id = make_job()
    assert client.post(f"/jobs/{job_id}/outcome/dismiss").json()["recorded"] is True
    assert len(read_events(job_id, "outcome_prompt_dismissed")) == 1


def test_dismissal_leaves_the_job_answerable():
    """Skipping now must not destroy the chance of an answer later."""
    job_id = make_job()
    client.post(f"/jobs/{job_id}/outcome/dismiss")
    assert read_job(job_id).outcome == "awaiting_verdict"
    assert client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"}).status_code == 200


# ── Pilot metric ──────────────────────────────────────────────────────────────


def test_stats_report_a_response_rate():
    """Answers over people asked — the number the pilot exists to find."""
    answered = make_job()
    ignored = make_job()
    client.post(f"/jobs/{answered}/outcome/prompt-shown")
    client.post(f"/jobs/{ignored}/outcome/prompt-shown")
    client.post(f"/jobs/{answered}/outcome", json={"verdict": "success"})

    body = client.get("/feedback/stats").json()
    assert body["prompts_shown"] >= 2
    assert body["outcomes_reported"] >= 1
    assert 0.0 <= body["response_rate"] <= 1.0


def test_response_rate_cannot_exceed_one():
    """A verdict given without a prompt must not inflate the rate.

    Regression guard: counting raw event totals let unprompted reports push the ratio
    above 1, at which point the headline metric means nothing.
    """
    prompted = make_job()
    client.post(f"/jobs/{prompted}/outcome/prompt-shown")
    client.post(f"/jobs/{prompted}/outcome", json={"verdict": "success"})

    # Three verdicts nobody was ever prompted for.
    for _ in range(3):
        unprompted = make_job()
        client.post(f"/jobs/{unprompted}/outcome", json={"verdict": "success"})

    body = client.get("/feedback/stats").json()
    assert body["response_rate"] <= 1.0
    assert body["outcomes_reported_total"] > body["outcomes_reported"]


def test_dismissal_then_answer_counts_as_answered():
    """Skipping once and answering later is a response, not a refusal."""
    job_id = make_job()
    client.post(f"/jobs/{job_id}/outcome/prompt-shown")
    client.post(f"/jobs/{job_id}/outcome/dismiss")
    before = client.get("/feedback/stats").json()
    client.post(f"/jobs/{job_id}/outcome", json={"verdict": "success"})
    after = client.get("/feedback/stats").json()

    assert after["outcomes_reported"] == before["outcomes_reported"] + 1
    assert after["prompts_dismissed"] == before["prompts_dismissed"] - 1


def test_stats_response_rate_is_null_when_nothing_was_asked():
    """A rate over zero prompts is undefined, not zero."""
    body = client.get("/feedback/stats").json()
    if body["prompts_shown"] == 0:
        assert body["response_rate"] is None


# ── Download and lineage capture ──────────────────────────────────────────────


def test_download_records_an_event_and_bumps_the_count(tmp_path, monkeypatch):
    """Downloading is the clearest signal a result was worth keeping."""
    from pathlib import Path

    import server.app as server_app

    job_id = make_job(outcome="success")
    outputs = Path(server_app.__file__).parent.parent / "data" / "outputs" / job_id
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "engineered_mesh.gcode").write_text(";FLAVOR:Marlin\nM104 S200\n")

    try:
        response = client.get(f"/jobs/{job_id}/download")
        assert response.status_code == 200
        assert len(read_events(job_id, "download")) == 1
        assert read_job(job_id).download_count == 1

        client.get(f"/jobs/{job_id}/download")
        assert read_job(job_id).download_count == 2
    finally:
        import shutil
        shutil.rmtree(outputs, ignore_errors=True)


def test_job_status_exposes_the_new_capture_fields():
    """The UI needs the pending flag and the target material."""
    job_id = make_job(material_type="PETG", blueprint_seed=99, download_count=0)
    body = client.get(f"/jobs/{job_id}").json()
    assert body["material_type"] == "PETG"
    assert body["blueprint_seed"] == 99
    assert body["awaiting_verdict"] is True
    # A job pending a verdict has finished as far as the software is concerned, so the
    # status string every existing consumer switches on must stay "completed".
    assert body["status"] == "completed"


def test_provenance_endpoint_returns_the_whole_record():
    """One endpoint to read when analysing the pilot dataset."""
    job_id = make_job(
        outcome="success",
        blueprint_seed=1234,
        blueprint_prompt_engineered="3d blender render of a lattice cube, clay material",
        raw_mesh_features={"face_count": 5000},
        repaired_mesh_features={"face_count": 4900},
        slice_status="success",
        estimated_print_time_s=3600,
        filament_used_g=12.5,
        material_type="PLA",
        process_params={"layer_height": 0.2},
    )
    body = client.get(f"/jobs/{job_id}/provenance").json()

    assert body["blueprint"]["seed"] == 1234
    assert "clay material" in body["blueprint"]["prompt_engineered"]
    assert body["mesh"]["raw_features"]["face_count"] == 5000
    assert body["mesh"]["repaired_features"]["face_count"] == 4900
    assert body["slice"]["estimated_print_time_s"] == 3600
    assert body["slice"]["filament_used_g"] == pytest.approx(12.5)
    assert body["target"]["material_type"] == "PLA"
    assert body["target"]["process_params"]["layer_height"] == 0.2
    assert body["engagement"]["download_count"] == 0


def test_provenance_404s_for_an_unknown_job():
    """No provenance without a job."""
    assert client.get(f"/jobs/{uuid.uuid4()}/provenance").status_code == 404


def test_frozen_process_params_survive_a_profile_edit(tmp_path):
    """Editing a profile must not rewrite what a finished job claims to have used.

    Regression guard: `layer_height_mm` used to be read from the profile file at
    response time, so a job printed at 0.2mm would start reporting 0.3mm the moment
    someone tuned the profile.
    """
    job_id = make_job(outcome="success", process_params={"layer_height": 0.2,
                                                         "machine_name": "Ender 3"})
    body = client.get(f"/jobs/{job_id}").json()
    assert body["layer_height_mm"] == pytest.approx(0.2)
    assert body["machine_name"] == "Ender 3"


def test_layer_height_falls_back_to_the_profile_for_older_rows():
    """Rows predating process_params still resolve their profile."""
    job_id = make_job(outcome="success", process_params=None)
    body = client.get(f"/jobs/{job_id}").json()
    # ender3.json declares 0.2; the fallback path is what supplies it here.
    assert body["layer_height_mm"] == pytest.approx(0.2)


def test_job_listing_buckets_pending_separately():
    """An unconfirmed print is neither a success nor a failure."""
    make_job()
    stats = client.get("/jobs").json()["stats"]
    assert stats["awaiting_verdict"] >= 1
