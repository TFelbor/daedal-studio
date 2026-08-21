"""Capture-hardening guards: run context, dispatch provenance, repair report,
actual print duration, and real foreign-key enforcement.

Each of these exists because the value has exactly one moment at which it is
knowable (see CLAUDE.md, "the capture principle") — or, for the FK pragma,
because the orphaned-events incident proved a declared-but-unenforced foreign
key is how a dataset quietly rots.
"""
import sqlite3
from datetime import datetime, timezone

import pytest

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import (
    PrintJob,
    TelemetrySample,
    FailureEvent,
    JobEvent,
    JOB_EVENT_KINDS,
)


@pytest.fixture
def db(tmp_path):
    handle = TelemetryDB(str(tmp_path / "capture.db"))
    handle.init_schema()
    yield handle
    handle.close()


def _job(job_id="job-ctx") -> PrintJob:
    return PrintJob(
        job_id=job_id,
        prompt="a vase",
        printer_id="default_printer",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="ender3",
        started_at=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
        completed_at=None,
        outcome="unknown",
    )


# ── Run context: git sha + fixture marking ─────────────────────────────────

def test_run_context_records_git_sha_and_reference_flag(db):
    db.insert_job(_job())
    db.update_job_run_context("job-ctx", git_sha="abc1234", used_reference_assets=True)
    job = db.get_job("job-ctx")
    assert job.git_sha == "abc1234"
    assert job.used_reference_assets == 1


def test_reference_flag_false_is_recorded_not_skipped(db):
    """False is information — "the pipeline confirmed no fixture was used" —
    and must not be dropped by the None-skipping update helper."""
    db.insert_job(_job())
    db.update_job_run_context("job-ctx", used_reference_assets=False)
    job = db.get_job("job-ctx")
    assert job.used_reference_assets == 0


# ── Dispatch provenance: which machine actually got the G-code ─────────────

def test_dispatch_target_url_is_persisted(db):
    db.insert_job(_job())
    db.update_job_dispatch("job-ctx", printer_url="http://localhost:5001")
    job = db.get_job("job-ctx")
    assert job.dispatched_printer_url == "http://localhost:5001"


# ── Repair report: which repair actually ran ───────────────────────────────

def test_mesh_lineage_carries_repair_report(db):
    db.insert_job(_job())
    report = {"voxel_remesh": False, "close_rounds": 2, "scale_factor": 3.7}
    db.update_job_mesh_lineage("job-ctx", raw_sha256="aa", repair_report=report)
    job = db.get_job("job-ctx")
    assert job.repair_report == report
    assert job.raw_mesh_sha256 == "aa"


# ── Actual print duration, written at the terminal printer event ───────────

def test_print_duration_is_persisted_independently_of_outcome(db):
    """The duration write must not go through the outcome-precedence guard:
    a user verdict given before PrintDone arrives must not cost the duration."""
    db.insert_job(_job())
    db.update_job_outcome_verdict("job-ctx", "success", "user")
    db.update_job_print_duration("job-ctx", 5423.0)
    job = db.get_job("job-ctx")
    assert job.outcome == "success"
    assert job.outcome_source == "user"
    assert job.print_duration_s == 5423.0


# ── New engagement event kinds ─────────────────────────────────────────────

def test_printer_lifecycle_event_kinds_are_recognised():
    for kind in ("print_paused", "print_resumed", "printer_terminal"):
        assert kind in JOB_EVENT_KINDS
        JobEvent(
            event_id="e-" + kind,
            job_id="j",
            occurred_at=datetime.now(timezone.utc),
            kind=kind,
            detail={"reason": "test"},
        )


# ── Foreign keys are enforced, not decorative ──────────────────────────────

def _sample(job_id) -> TelemetrySample:
    return TelemetrySample(
        job_id=job_id,
        sampled_at=datetime.now(timezone.utc),
        gcode_line=None,
        z_height_mm=None,
        hotend_actual_c=210.0,
        hotend_target_c=210.0,
        bed_actual_c=60.0,
        bed_target_c=60.0,
        print_speed_pct=None,
        extrusion_factor_pct=None,
        fan_speed_pct=None,
    )


def test_sample_for_nonexistent_job_is_refused(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_sample(_sample("no-such-job"))


def test_job_event_for_nonexistent_job_is_refused(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.record_job_event("no-such-job", "download")


def test_failure_event_for_nonexistent_job_is_refused(db):
    event = FailureEvent(
        event_id="f1",
        job_id="no-such-job",
        detected_at=datetime.now(timezone.utc),
        gcode_line=None,
        z_height_mm=None,
        failure_type="adhesion",
        source="automated",
        notes=None,
        snapshot=[],
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_failure_event(event)


def test_writes_for_existing_job_still_succeed(db):
    db.insert_job(_job("real-job"))
    db.insert_sample(_sample("real-job"))
    db.record_job_event("real-job", "download")
    assert len(db.get_samples("real-job")) == 1
    assert len(db.get_job_events("real-job")) == 1
