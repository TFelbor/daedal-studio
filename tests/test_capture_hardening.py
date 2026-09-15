"""Capture-hardening guards: run context, dispatch provenance, repair report,
actual print duration, and real foreign-key enforcement.

Each of these exists because the value has exactly one moment at which it is
knowable (see docs/SYSTEM-AS-BUILT.md, "the capture principle") — or, for the FK pragma,
because the orphaned-events incident proved a declared-but-unenforced foreign
key is how a dataset quietly rots.
"""
from datetime import datetime, timezone

import pytest

from pythonsrc.telemetry.db import IntegrityError, TelemetryDB
from pythonsrc.telemetry.schema import (
    JOB_EVENT_KINDS,
    FailureEvent,
    JobEvent,
    PrintJob,
    TelemetrySample,
)


@pytest.fixture
def db(isolated_db):
    return isolated_db


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
    with pytest.raises(IntegrityError):
        db.insert_sample(_sample("no-such-job"))


def test_job_event_for_nonexistent_job_is_refused(db):
    with pytest.raises(IntegrityError):
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
    with pytest.raises(IntegrityError):
        db.insert_failure_event(event)


def test_writes_for_existing_job_still_succeed(db):
    db.insert_job(_job("real-job"))
    db.insert_sample(_sample("real-job"))
    db.record_job_event("real-job", "download")
    assert len(db.get_samples("real-job")) == 1
    assert len(db.get_job_events("real-job")) == 1


# ── Blueprint provenance survives the process boundary ─────────────────────
#
# The primary Mac workflow runs Phase 1 as a separate native process
# (visualizer.py) and the pipeline with --skip-visualizer, which used to record
# only the image hash: seed, prompt, model, params all NULL for every job on
# that path. The sidecar is how the BlueprintResult crosses the boundary.

def _blueprint_result(tmp_path):
    from pythonsrc.blueprint_spec import BlueprintResult

    image = tmp_path / "blueprint.png"
    image.write_bytes(b"\x89PNG fake image bytes")
    return image, BlueprintResult(
        path=image,
        seed=1234567,
        prompt="a vase",
        engineered_prompt="3d blender render of a vase, ...",
        params={"num_inference_steps": 4, "guidance_scale": 3.5},
        duration_s=31.2,
        model_id="black-forest-labs/FLUX.2-klein-4B",
    )


def test_sidecar_round_trips_the_blueprint_result(tmp_path):
    from pythonsrc.blueprint_spec import read_sidecar, write_sidecar

    image, result = _blueprint_result(tmp_path)
    write_sidecar(result)

    loaded = read_sidecar(image)
    assert loaded is not None
    assert loaded.seed == 1234567
    assert loaded.engineered_prompt == result.engineered_prompt
    assert loaded.params == result.params
    assert loaded.model_id == result.model_id
    assert loaded.duration_s == 31.2


def test_sidecar_for_a_replaced_image_is_rejected(tmp_path):
    """The blueprint path is shared; a stale sidecar describing an image that has
    since been overwritten must not attribute the old seed to the new image."""
    from pythonsrc.blueprint_spec import read_sidecar, write_sidecar

    image, result = _blueprint_result(tmp_path)
    write_sidecar(result)
    image.write_bytes(b"a different image entirely")

    assert read_sidecar(image) is None


def test_missing_sidecar_reads_as_none(tmp_path):
    from pythonsrc.blueprint_spec import read_sidecar

    image = tmp_path / "blueprint.png"
    image.write_bytes(b"img")
    assert read_sidecar(image) is None


# ── Phase 3 reports what it actually did ───────────────────────────────────

def test_engineer_exposes_a_repair_report(tmp_path):
    import numpy as np
    import trimesh

    from pythonsrc.engineer import Engineer

    # A closed sphere with one tetrahedral fin: three non-manifold edges, the
    # defect the repair chain exists for.
    sphere = trimesh.creation.icosphere(subdivisions=2)
    vertices, faces = sphere.vertices.copy(), sphere.faces.copy()
    a, b, c = faces[0]
    apex = len(vertices)
    vertices = np.vstack([vertices, [vertices[[a, b, c]].mean(axis=0) * 1.4]])
    finned = trimesh.Trimesh(
        vertices=vertices,
        faces=np.vstack([faces, [[a, b, apex], [b, c, apex], [c, a, apex]]]),
        process=False,
    )
    raw = tmp_path / "raw.obj"
    finned.export(str(raw))

    eng = Engineer()
    eng.process(input_path=raw, output_path=tmp_path / "out.obj", target_mm=50.0)

    report = eng.last_report
    assert report is not None
    assert report["repair_method"] in {"manifold", "trimesh_fallback", "voxel_remesh"}
    # Against the Z extent, not the longest edge: `process` now defaults to height
    # mode. This assertion used to read `finned.extents.max()` and kept passing on a
    # rel=0.2 tolerance while the two extents differ by 6.4% — a green test
    # documenting a formula the code had stopped using. Tight tolerance so it cannot
    # do that again, and the axis is asserted explicitly.
    assert report["scale_axis"] == "height"
    assert report["scale_factor"] == pytest.approx(50.0 / finned.extents[2], rel=1e-3)
    assert report["hollowed"] is False
    assert "faces_dropped" in report
    assert "close_rounds" in report
    assert report["watertight_after"] is True


# ── Run context is written by the pipeline ─────────────────────────────────

def test_resolve_git_sha_finds_this_repo():
    import re

    from pythonsrc import pipeline

    sha = pipeline._resolve_git_sha()
    assert sha is not None
    assert re.fullmatch(r"[0-9a-f]{7,40}", sha)


def test_record_run_context_writes_the_row(isolated_db_env):
    import argparse

    from pythonsrc import pipeline

    handle = TelemetryDB()
    handle.init_schema()
    handle.insert_job(_job("ctx-job"))
    handle.close()

    args = argparse.Namespace(job_id="ctx-job")
    pipeline._record_run_context(args, used_reference_assets=True)

    handle = TelemetryDB()
    job = handle.get_job("ctx-job")
    handle.close()
    assert job.used_reference_assets == 1
    assert job.git_sha is not None
