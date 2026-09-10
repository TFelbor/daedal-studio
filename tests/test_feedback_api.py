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


# ── Preview reached ───────────────────────────────────────────────────────────
#
# The activation metric's numerator (PRD §7). Its denominator was always there — every
# job carries a prompt — and nothing recorded that anyone ever saw the geometry.


def test_preview_reached_is_recorded_once():
    """A reload of the running view must not count as a second activation."""
    job_id = make_job()
    first = client.post(f"/jobs/{job_id}/events/preview-reached").json()
    second = client.post(f"/jobs/{job_id}/events/preview-reached").json()
    assert first["recorded"] is True
    assert second["recorded"] is False
    assert len(read_events(job_id, "preview_reached")) == 1


def test_preview_reached_404s_for_an_unknown_job():
    """No preview without a job — foreign keys are enforced, so the row could not be
    written anyway, and a 404 says which half is wrong."""
    assert client.post(f"/jobs/{uuid.uuid4()}/events/preview-reached").status_code == 404


def test_preview_reached_is_a_recognised_event_kind():
    """An unknown kind is still refused; this one is no longer unknown."""
    from pythonsrc.telemetry.schema import JOB_EVENT_KINDS, JobEvent

    assert "preview_reached" in JOB_EVENT_KINDS
    JobEvent(
        event_id="e-preview",
        job_id="j",
        occurred_at=datetime.now(timezone.utc),
        kind="preview_reached",
    )
    with pytest.raises(ValueError):
        JobEvent(
            event_id="e-nope",
            job_id="j",
            occurred_at=datetime.now(timezone.utc),
            kind="preview_looked_at",
        )


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


# ── Activation rate ───────────────────────────────────────────────────────────


def test_stats_report_the_activation_rate_over_jobs(isolated_db_env):
    """Previews reached over prompts submitted — PRD §7's activation metric."""
    previewed = make_job(outcome="unknown")
    make_job(outcome="unknown")
    make_job(outcome="unknown")
    client.post(f"/jobs/{previewed}/events/preview-reached")

    body = client.get("/feedback/stats").json()
    assert body["jobs_submitted"] == 3
    assert body["previews_reached"] == 1
    assert body["activation_rate"] == pytest.approx(1 / 3, abs=1e-4)


def test_activation_rate_counts_jobs_not_events(isolated_db_env):
    """Looking at the mesh and then the toolpath is one activation, not two.

    Guarded twice on purpose: the endpoint deduplicates, and the query counts
    `DISTINCT job_id`. Either alone would let a raw event total push the ratio above 1
    — the same defect `response_rate` was fixed for.
    """
    job_id = make_job(outcome="unknown")
    for _ in range(4):
        client.post(f"/jobs/{job_id}/events/preview-reached")

    body = client.get("/feedback/stats").json()
    assert body["jobs_submitted"] == 1
    assert body["previews_reached"] == 1
    assert body["activation_rate"] == pytest.approx(1.0)


def test_activation_rate_excludes_developer_runs(isolated_db_env):
    """A cube printed to verify a pipeline change is not a pilot user.

    `dev` is kept out of `feedback_funnel`'s answers for the same reason; leaving it in
    here would let a developer's own session move the number the pilot is measured by.
    """
    make_job(outcome="dev")
    dev_previewed = make_job(outcome="dev")
    real = make_job(outcome="unknown")
    client.post(f"/jobs/{dev_previewed}/events/preview-reached")
    client.post(f"/jobs/{real}/events/preview-reached")

    body = client.get("/feedback/stats").json()
    assert body["jobs_submitted"] == 1
    assert body["previews_reached"] == 1
    assert body["activation_rate"] == pytest.approx(1.0)


def test_activation_rate_is_null_when_nothing_was_submitted(isolated_db_env):
    """A rate over zero jobs is undefined, not zero."""
    body = client.get("/feedback/stats").json()
    assert body["jobs_submitted"] == 0
    assert body["previews_reached"] == 0
    assert body["activation_rate"] is None


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


# ── Developer and declined verdicts ───────────────────────────────────────────
#
# Two outcomes that exist to keep the dataset honest rather than to describe a part.
# `dev` marks a test run so a cube printed to verify a pipeline change does not land in
# the column the pilot is measured from. `declined` records that someone was asked
# twice and does not want to be asked again.

def test_a_dev_verdict_is_accepted_and_settles_the_job():
    job_id = make_job(outcome="awaiting_verdict")

    res = client.post(f"/jobs/{job_id}/outcome", json={"verdict": "dev"})
    assert res.status_code == 200

    job = read_job(job_id)
    assert job.outcome == "dev"
    assert job.outcome_source == "user"

    # Settled, so the banner stops asking about it.
    pending = client.get("/feedback/pending").json()
    assert all(j["job_id"] != job_id for j in pending["jobs"])
    # And it reads as finished rather than as still running.
    assert client.get(f"/jobs/{job_id}").json()["status"] == "completed"


def test_a_declined_verdict_settles_the_job_without_claiming_an_outcome():
    job_id = make_job(outcome="awaiting_verdict")

    assert client.post(f"/jobs/{job_id}/outcome", json={"verdict": "declined"}).status_code == 200

    assert read_job(job_id).outcome == "declined"

    pending = client.get("/feedback/pending").json()
    assert all(j["job_id"] != job_id for j in pending["jobs"])


def test_declined_is_not_the_unknown_sentinel():
    """`unknown` means "the pipeline has not finished" — reusing it would resurrect the job.

    This is the trap the `declined` value exists to avoid: `job_status_from_outcome`
    maps `unknown` back to `running`, so a "don't ask again" written as `unknown` would
    make a settled job start claiming it was still in the pipeline.
    """
    from server.app import job_status_from_outcome

    started = datetime.now(timezone.utc)
    assert job_status_from_outcome("unknown", started) == "running"
    assert job_status_from_outcome("declined", started) == "completed"
    assert job_status_from_outcome("dev", started) == "completed"


def test_a_machine_event_cannot_overwrite_a_dev_verdict():
    """`dev` is user-sourced, so the precedence rule has to protect it like any verdict."""
    job_id = make_job(outcome="awaiting_verdict")
    client.post(f"/jobs/{job_id}/outcome", json={"verdict": "dev"})

    db = TelemetryDB()
    db.update_job_outcome_verdict(job_id, "failure", source="machine")
    db.close()
    assert read_job(job_id).outcome == "dev"


def test_a_nonsense_verdict_is_still_rejected():
    job_id = make_job(outcome="awaiting_verdict")
    assert client.post(f"/jobs/{job_id}/outcome", json={"verdict": "probably"}).status_code == 422


def test_a_failure_carries_a_free_text_reason():
    """The "Other:" path — the failures worth hearing about are the unlisted ones."""
    job_id = make_job(outcome="awaiting_verdict")

    res = client.post(
        f"/jobs/{job_id}/outcome",
        json={
            "verdict": "failure",
            "failure_type": "other",
            "notes": "the bed levelling probe caught on a clip",
        },
    )
    assert res.status_code == 200

    events = client.get(f"/jobs/{job_id}/failure").json()
    assert len(events) == 1
    assert events[0]["failure_type"] == "other"
    assert "clip" in events[0]["notes"]


def test_every_failure_option_the_ui_offers_is_accepted():
    """The UI's dropdown and the schema's allowed set must not drift apart.

    They did: six of the eleven options added to the form were rejected by
    `FailureEvent.__post_init__`, and the rejection surfaced as an unhandled 500 that
    threw the verdict away with it. This is the test that keeps the two lists in step.
    """
    offered = [
        "adhesion", "layer_shift", "extrusion_issue", "clog", "thermal_runaway",
        "detached", "supports", "surface", "dimensional", "filament_out", "other",
    ]
    for failure_type in offered:
        job_id = make_job(outcome="awaiting_verdict")
        res = client.post(
            f"/jobs/{job_id}/outcome",
            json={"verdict": "failure", "failure_type": failure_type, "notes": "n"},
        )
        assert res.status_code == 200, f"{failure_type} was rejected: {res.text}"
        assert read_job(job_id).outcome == "failure"


def test_an_unknown_failure_type_is_a_422_not_a_500():
    job_id = make_job(outcome="awaiting_verdict")
    res = client.post(
        f"/jobs/{job_id}/outcome",
        json={"verdict": "failure", "failure_type": "invented", "notes": "n"},
    )
    assert res.status_code == 422
    assert "invented" in res.text
    # The verdict was not half-written before the refusal: validation happens on the
    # request model, so the handler never ran.
    assert read_job(job_id).outcome == "awaiting_verdict"
