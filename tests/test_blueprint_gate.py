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
from unittest.mock import AsyncMock, patch

import pytest
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

def _park(db, job_id, *, blueprint=True, parked=True):
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
    # `parked=False` reproduces the case the gate used to get wrong: an ungated run,
    # which snapshots a blueprint into its own directory like every other run but never
    # stopped and is not waiting for anybody.
    if parked:
        db.record_job_event(job_id, "blueprint_gate_parked", {"sha256": digest})
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


# ── The approval must bind to the image Phase 2 actually consumes ─────────────
#
# Found in review, and it defeated the whole gate. `_snapshot_blueprint` exists because
# `POST /jobs` deletes the shared `data/inputs/blueprint.png` on every submission — but
# the continuation was still launched with `--blueprint /app/data/inputs/blueprint.png`.
# So: job A parks; job B is submitted, deleting the shared PNG and writing its own;
# someone approves A; A's Phase 2 reconstructs **B's** image, and the sidecar beside it
# stamps B's seed, prompt and model onto A's `blueprint_*` columns. A paid
# reconstruction of an image nobody approved, with fabricated Phase 1 provenance, and
# the sha256 the person confirmed was of a file that was never read.

def test_the_continuation_reads_the_snapshot_it_was_approved_from():
    """The resumed run must name the per-job snapshot, not the shared input path."""
    resumed = app_module.JobRequest(
        prompt="a vase", printer_id="d", skip_visualizer=True,
        blueprint_path="/app/data/outputs/JOBA/blueprint.png",
    )
    args = app_module._pipeline_args(
        resumed, skip_viz=True, skip_sculpt=False, profile=None,
    )

    assert args[args.index("--blueprint") + 1] == "/app/data/outputs/JOBA/blueprint.png"
    assert "/app/data/inputs/blueprint.png" not in args


def test_a_first_run_still_uses_the_shared_input_path():
    """Phase 1 writes there, so an ungated first run must keep reading there."""
    args = app_module._pipeline_args(
        app_module.JobRequest(prompt="a vase", printer_id="d", skip_visualizer=True),
        skip_viz=True, skip_sculpt=False, profile=None,
    )

    assert args[args.index("--blueprint") + 1] == "/app/data/inputs/blueprint.png"


def test_approval_hands_the_continuation_the_snapshot_path():
    """End to end: what the endpoint builds must point at this job's own image."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000a"
    digest = _park(db, job_id)
    db.close()

    with patch("server.app._continue_pipeline", new_callable=AsyncMock) as cont:
        resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
            "confirmed": True, "sha256": digest,
        })

    assert resp.status_code == 200, resp.text
    resumed = cont.call_args[0][1]
    assert resumed.blueprint_path == f"/app/data/outputs/{job_id}/blueprint.png"
    assert resumed.skip_visualizer is True


# ── Only a job that actually parked is awaiting approval ─────────────────────
#
# Also from review. The state was derived from "a per-job blueprint.png exists and no
# decision event exists" — but `pipeline.py` snapshots the blueprint into the per-job
# directory on *every* run with a `--job-id`, and a run with `SKIP_VISUALIZER=true` or
# `print: true` is never gated. So a job that was never parked reported
# `awaiting_approval` seconds into its run, the UI drew the gate over a pipeline already
# in Phase 2, and approving it started a **second** full pipeline for the same job:
# two hosted reconstructions billed, two containers writing one output directory.

def test_a_job_that_never_parked_is_not_awaiting_approval():
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000b"
    _park(db, job_id, parked=False)      # snapshot exists, but the run never stopped
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "not_ready"
    db.close()


def test_a_finished_job_is_not_awaiting_approval():
    """A settled outcome means nothing is waiting, whatever is on disk."""
    from datetime import datetime, timezone

    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000c"
    _park(db, job_id)
    db.update_job_outcome_verdict(
        job_id, "success", source="machine", completed_at=datetime.now(timezone.utc),
    )
    job = db.get_job(job_id)

    assert app_module.blueprint_gate_state(job, db) == "not_ready"
    db.close()


def test_approving_a_job_that_never_parked_is_refused():
    """The endpoint re-checks, so an approval racing a running pipeline cannot land."""
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000d"
    digest = _park(db, job_id, parked=False)
    db.close()

    with patch("server.app._continue_pipeline", new_callable=AsyncMock) as cont:
        resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
            "confirmed": True, "sha256": digest,
        })

    assert resp.status_code == 409
    cont.assert_not_called()


# ── A rejection has to settle the row ────────────────────────────────────────

def test_rejecting_settles_the_outcome():
    """`outcome='unknown'` reads as *running* everywhere.

    Left unknown, a rejected job stays in the running list forever and `NewJob`
    re-attaches to it on every page load — so declining a blueprint would make the
    landing composer unreachable. `cancelled` is the existing value for "stopped on
    request, not a failure" and is already excluded from the success-rate query.
    """
    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000e"
    digest = _park(db, job_id)
    db.close()

    resp = client.post(f"/jobs/{job_id}/blueprint-approval", json={
        "confirmed": True, "sha256": digest, "approve": False,
    })
    assert resp.status_code == 200

    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    assert job.outcome == "cancelled"
    assert job.completed_at is not None


# ── The start time is the job's, not the invocation's ────────────────────────

def test_a_continuation_does_not_overwrite_the_original_start_time():
    """`started_at` is when the job began. The continuation is a second invocation of
    the same job, and overwriting it destroys the only record of the first."""
    from datetime import datetime, timedelta, timezone

    db = TelemetryDB()
    job_id = "gate-0000-0000-0000-00000000000f"
    _park(db, job_id)

    first = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.update_job_start_time(job_id, first)
    db.update_job_start_time(job_id, datetime.now(timezone.utc))

    job = db.get_job(job_id)
    db.close()

    assert abs((job.started_at - first).total_seconds()) < 1


# ── The list filter arbitrates rather than approximating ─────────────────────

def test_the_awaiting_approval_filter_excludes_jobs_that_never_parked():
    """The SQL is the candidate set; `blueprint_gate_state` is the arbiter.

    Without the second step the filter returns every job whose outcome is still
    unknown — which is every running job — and the dashboard would offer to approve
    blueprints that do not exist.
    """
    db = TelemetryDB()
    parked = "gate-0000-0000-0000-000000000010"
    running = "gate-0000-0000-0000-000000000011"
    _park(db, parked)
    _park(db, running, blueprint=False, parked=False)
    db.close()

    rows = client.get("/jobs?status=awaiting_blueprint_approval").json()["jobs"]
    ids = {row["job_id"] for row in rows}

    assert parked in ids
    assert running not in ids


# ── A parked job is waiting, not running ─────────────────────────────────────

def test_a_parked_job_is_not_in_the_running_list():
    """Otherwise it owns the landing page for as long as nobody decides.

    `NewJob`'s mount effect attaches to the newest `status=running` job, so a parked
    job left as "running" would drop every new tab into its running view and make the
    landing composer unreachable — the same failure `awaiting_dispatch` was introduced
    to fix, in a new place. A parked job has its own filter; it does not belong in this
    one.
    """
    db = TelemetryDB()
    parked = "gate-0000-0000-0000-000000000012"
    _park(db, parked)
    db.close()

    ids = {row["job_id"] for row in client.get("/jobs?status=running").json()["jobs"]}
    assert parked not in ids


def test_a_job_still_in_phase_1_is_in_the_running_list():
    """The exclusion must be about the gate, not about being unfinished."""
    db = TelemetryDB()
    running = "gate-0000-0000-0000-000000000013"
    _park(db, running, blueprint=False, parked=False)
    db.close()

    ids = {row["job_id"] for row in client.get("/jobs?status=running").json()["jobs"]}
    assert running in ids


def test_a_decided_job_returns_to_the_running_list_while_phase_2_runs():
    """Once approved it is genuinely running again, and must read that way."""
    db = TelemetryDB()
    approved = "gate-0000-0000-0000-000000000014"
    digest = _park(db, approved)
    db.record_job_event(approved, "blueprint_approved", {"sha256": digest})
    db.close()

    ids = {row["job_id"] for row in client.get("/jobs?status=running").json()["jobs"]}
    assert approved in ids


# ── The snapshot has to find the image Phase 1 actually wrote ─────────────────
#
# Per-job blueprints and this gate were built on separate branches, and the seam
# between them conflicts in no file: `_snapshot_blueprint` read only the flat
# `data/inputs/blueprint.png`, while a gated run renders to
# `data/inputs/{job_id}/blueprint.png` so that two concurrent jobs cannot overwrite
# each other's image. So every gated job found nothing to approve —
# `_park_at_blueprint_gate` returned False and `_run_pipeline` failed a job whose
# Phase 1 had just succeeded — and with a stale shared PNG present it was worse: the
# gate snapshotted another job's render and bound this approval to it. Neither branch's
# suite noticed, because each was green on its own.

def _clear(*paths):
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def test_the_snapshot_prefers_this_jobs_own_input_directory():
    """Phase 1 renders per job; the shared path belongs to whoever wrote it last."""
    from pathlib import Path

    repo_root = Path(app_module.__file__).parent.parent
    job_id = "gate-snap-0000-0000-000000000001"
    per_job = repo_root / "data" / "inputs" / job_id / "blueprint.png"
    shared = repo_root / "data" / "inputs" / "blueprint.png"
    snapshot = repo_root / "data" / "outputs" / job_id / "blueprint.png"

    per_job.parent.mkdir(parents=True, exist_ok=True)
    shared.parent.mkdir(parents=True, exist_ok=True)
    per_job.write_bytes(b"this job's render")
    shared.write_bytes(b"some other job's render")
    try:
        assert app_module._snapshot_blueprint(job_id) == snapshot
        assert snapshot.read_bytes() == b"this job's render"
    finally:
        _clear(per_job, shared, snapshot)


def test_the_snapshot_falls_back_to_the_shared_input_path():
    """The skip-Phase-1 configuration deliberately reuses the flat path."""
    from pathlib import Path

    repo_root = Path(app_module.__file__).parent.parent
    job_id = "gate-snap-0000-0000-000000000002"
    shared = repo_root / "data" / "inputs" / "blueprint.png"
    sidecar = shared.with_name("blueprint.provenance.json")
    snapshot = repo_root / "data" / "outputs" / job_id / "blueprint.png"

    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_bytes(b"reused render")
    # Carried across with the PNG, or the continuation's skip-visualizer path records
    # NULL for seed, prompt and model.
    sidecar.write_text(json.dumps({"seed": 7}))
    try:
        assert app_module._snapshot_blueprint(job_id) == snapshot
        assert snapshot.read_bytes() == b"reused render"
        assert (snapshot.parent / sidecar.name).exists()
    finally:
        _clear(shared, sidecar, snapshot, snapshot.parent / sidecar.name)


def test_a_job_with_no_blueprint_anywhere_does_not_park():
    """Parking on an empty gate would ask a person to approve nothing."""
    from pathlib import Path

    repo_root = Path(app_module.__file__).parent.parent
    shared = repo_root / "data" / "inputs" / "blueprint.png"
    if shared.exists():
        pytest.skip("a shared blueprint is present in this working tree")

    assert app_module._snapshot_blueprint("gate-snap-0000-0000-000000000003") is None
