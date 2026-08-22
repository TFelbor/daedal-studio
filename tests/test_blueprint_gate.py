"""Phase 2 does not start until a person has looked at the blueprint.

Two problems, one gate. The legal one is that an automated screen cannot be the last
word on whether a render reproduces someone's character — a false positive that fails
Phase 1 has no appeal, and a false negative has no second reader. The product one is
larger: the honest answer to "make me a Pikachu" is that you will get an unpainted,
0.4mm-nozzle approximation, and right now the requester finds that out four minutes
and EUR 0.32 later. This gate shows them in thirty seconds, for nothing.

Modelled on the dispatch gate exactly, and for the same reason it is: **derived state
plus a `job_event`**, no new outcome value and no migration. The outcome column says
what the software did; "a person has not decided yet" is a decision record.

Durability is the part that needs care. `_run_pipeline` holds the `JobRequest` in
memory only, so a gate that parked by awaiting inside it would lose the job on a
server restart. The dispatch gate survives because it is two subprocess invocations
joined by a row in the database — so this is too, which is what `request_params` and
`--stop-after-phase` exist for.
"""

import json

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module
from server.app import app

client = TestClient(app)


# ── The pipeline can be told to stop ─────────────────────────────────────────

def test_the_pipeline_accepts_a_phase_to_stop_after():
    """Without a seam there is no gate: the docker strategies run all five phases in
    one `docker compose run`, so one has to be created."""
    from pythonsrc import pipeline

    args = pipeline._build_parser().parse_args(["a vase", "--stop-after-phase", "1"])
    assert args.stop_after_phase == 1

    default = pipeline._build_parser().parse_args(["a vase"])
    assert default.stop_after_phase is None


@pytest.mark.parametrize("stop_after,phase,expected", [
    (None, 1, False),
    (1, 1, True),
    (1, 2, True),
    (2, 1, False),
    (5, 4, False),
])
def test_the_stop_predicate_is_inclusive_of_the_named_phase(stop_after, phase, expected):
    """`--stop-after-phase 1` means phase 1 ran and nothing after it may."""
    from pythonsrc import pipeline

    assert pipeline._should_stop_after(stop_after, phase) is expected


# ── The request survives the process that received it ────────────────────────

@patch("server.app._run_pipeline", new_callable=AsyncMock)
def test_the_submitted_request_is_persisted(mock_run, printer_configured):
    """The continuation runs in a *different* process, minutes later.

    `pipeline_type` and `mesh_seed` exist nowhere else until Phase 2 has already run,
    so rebuilding the request from the individual columns would silently drop the two
    settings that change the geometry.
    """
    resp = client.post("/jobs", json={
        "prompt": "a vase", "printer_id": "default",
        "pipeline_type": "1024_cascade", "mesh_seed": 99, "target_mm": 80.0,
    })
    assert resp.status_code == 202

    db = TelemetryDB()
    job = db.get_job(resp.json()["job_id"])
    db.close()

    assert job.request_params is not None
    assert job.request_params["pipeline_type"] == "1024_cascade"
    assert job.request_params["mesh_seed"] == 99
    assert job.request_params["target_mm"] == 80.0


# ── The derived state ────────────────────────────────────────────────────────

def _park(db, job_id, *, blueprint=True):
    """Put a job in the state the pipeline leaves it in after a gated Phase 1.

    The hash returned is the **file's own**, not the row's `blueprint_sha256`. Those
    agree in a real run, but it is the file that is rendered and served, so it is the
    file the approval has to be bound to — binding to the recorded value would let a
    replaced image be approved under the original's hash.
    """
    import hashlib
    from pathlib import Path

    from pythonsrc.telemetry.schema import PrintJob

    db.insert_job(PrintJob(
        job_id=job_id, prompt="a vase", printer_id="ender3",
        printer_firmware="octoprint", slicer="cura", profile_name="ender3",
        started_at=None, completed_at=None, outcome="unknown",
        request_params={"prompt": "a vase", "printer_id": "ender3"},
    ))

    payload = b"blueprint bytes for " + job_id.encode()
    digest = hashlib.sha256(payload).hexdigest()
    db.update_job_blueprint(job_id, sha256=digest)
    if blueprint:
        outputs = Path(app_module.__file__).parent.parent / "data" / "outputs" / job_id
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "blueprint.png").write_bytes(payload)
    return digest


def test_a_parked_job_reads_as_awaiting_approval():
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000001"
    _park(db, job_id)
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "awaiting_approval"
    db.close()


def test_a_job_with_no_blueprint_yet_is_not_ready():
    """Phase 1 may still be running. "Nothing to look at" is not "waiting for you"."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000002"
    _park(db, job_id, blueprint=False)
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "not_ready"
    db.close()


def test_an_approved_job_stays_approved():
    """Derived from the event, so it survives a restart and cannot be re-asked."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000003"
    digest = _park(db, job_id)
    db.record_job_event(job_id, "blueprint_approved", {"sha256": digest})
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "approved"
    db.close()


def test_a_rejected_job_is_not_asked_again():
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000004"
    digest = _park(db, job_id)
    db.record_job_event(job_id, "blueprint_rejected", {"sha256": digest})
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "rejected"
    db.close()


# ── The endpoint ─────────────────────────────────────────────────────────────

def test_an_unconfirmed_post_is_refused_before_anything_is_read():
    """`confirmed: true` *is* the gate. There must be no unconfirmed code path."""
    resp = client.post("/jobs/whatever/blueprint-approval", json={"confirmed": False})

    assert resp.status_code == 400


def test_approving_an_unknown_job_is_a_404():
    resp = client.post(
        "/jobs/00000000-0000-0000-0000-00000000dead/blueprint-approval",
        json={"confirmed": True},
    )
    assert resp.status_code == 404


def test_a_blueprint_that_changed_under_you_is_refused():
    """Approving an image you are no longer looking at is not approving.

    The composer sends the sha256 it displayed; a mismatch is a 409, exactly as the
    dispatch gate 409s when the printer it showed you is no longer the target.
    """
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000005"
    _park(db, job_id)
    db.close()

    resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
        "confirmed": True, "sha256": "b" * 64,
    })

    assert resp.status_code == 409


def test_approval_records_the_event_and_launches_the_continuation():
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000006"
    digest = _park(db, job_id)
    db.close()

    with patch("server.app._continue_pipeline", new_callable=AsyncMock) as cont:
        resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
            "confirmed": True, "sha256": digest,
        })

    assert resp.status_code == 200, resp.text

    db = TelemetryDB()
    events = db.get_job_events(job_id)
    db.close()

    assert any(e.kind == "blueprint_approved" for e in events)
    cont.assert_called_once()


def test_approving_twice_is_a_conflict_not_a_second_run():
    """Two clicks must not reconstruct the same blueprint twice — that is EUR 0.64."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000007"
    digest = _park(db, job_id)
    db.record_job_event(job_id, "blueprint_approved", {"sha256": digest})
    db.close()

    with patch("server.app._continue_pipeline", new_callable=AsyncMock) as cont:
        resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
            "confirmed": True, "sha256": digest,
        })

    assert resp.status_code == 409
    cont.assert_not_called()


def test_rejecting_records_a_rejection_and_starts_nothing():
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000008"
    digest = _park(db, job_id)
    db.close()

    with patch("server.app._continue_pipeline", new_callable=AsyncMock) as cont:
        resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
            "confirmed": True, "sha256": digest, "approve": False,
        })

    assert resp.status_code == 200
    cont.assert_not_called()

    db = TelemetryDB()
    kinds = [e.kind for e in db.get_job_events(job_id)]
    db.close()
    assert "blueprint_rejected" in kinds


# ── Surviving a page reload ──────────────────────────────────────────────────

def test_the_gate_survives_a_reload_via_the_job_list():
    """A parked job is invisible to `status=running`, so without its own filter the
    pending decision vanishes on refresh — the exact bug `awaiting_dispatch` fixed."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-000000000009"
    _park(db, job_id)
    db.close()

    resp = client.get("/jobs?status=awaiting_blueprint_approval")
    assert resp.status_code == 200
    assert any(row["job_id"] == job_id for row in resp.json()["jobs"])


def test_an_unknown_status_filter_is_still_a_400():
    """Adding a filter must not reopen the hole where an unknown one returned
    everything, newest first — which dropped a browser one deploy ahead of the
    server into the running view for a finished job."""
    assert client.get("/jobs?status=not_a_real_status").status_code == 400
