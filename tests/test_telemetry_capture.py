"""Capture of the signals that cannot be reconstructed after a print.

Covers the blueprint seed and conditioning, the mesh before and after repair, the
slicer's verdict and material estimates, the target material and process, download and
regeneration engagement, and the human print-outcome verdict.

The recurring theme in every test here is that the value has exactly one moment at which
it is knowable. A seed drawn and discarded cannot be recovered; a profile read at query
time is whatever the file says today; "the printer finished" is not "the part survived".
"""

import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import JOB_EVENT_KINDS, JobEvent, PrintJob
from server.app import app

client = TestClient(app)

# The nine columns the print_job table shipped with, before any provenance work.
OLD_SCHEMA = """
CREATE TABLE print_job (
    job_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    printer_id TEXT NOT NULL,
    printer_firmware TEXT NOT NULL,
    slicer TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    outcome TEXT NOT NULL
)
"""


def make_job(job_id: str, **kwargs) -> PrintJob:
    """Build a PrintJob with sensible defaults."""
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
def db():
    """A throwaway telemetry database with the current schema."""
    with tempfile.TemporaryDirectory() as tmp:
        database = TelemetryDB(str(Path(tmp) / "telemetry.db"))
        database.init_schema()
        yield database
        database.close()


# ── Blueprint provenance ──────────────────────────────────────────────────────


def test_blueprint_fields_round_trip(db):
    """Seed and conditioning survive a write and a read."""
    db.insert_job(make_job("b1"))
    db.update_job_blueprint(
        "b1",
        model="FLUX.2-klein-4B",
        model_version="black-forest-labs/FLUX.2-klein-4B",
        seed=987654321,
        prompt_engineered="3d blender render of a vase, clay material",
        params={"num_inference_steps": 4, "guidance_scale": 3.5},
        sha256="a" * 64,
        duration_s=31.5,
    )
    job = db.get_job("b1")
    assert job.blueprint_seed == 987654321
    assert job.blueprint_params["guidance_scale"] == 3.5
    assert job.blueprint_prompt_engineered.startswith("3d blender render")
    assert job.blueprint_sha256 == "a" * 64


def test_blueprint_partial_update_keeps_the_seed(db):
    """A later hash-only write must not erase the seed recorded at generation time."""
    db.insert_job(make_job("b2"))
    db.update_job_blueprint("b2", seed=42)
    db.update_job_blueprint("b2", sha256="b" * 64)
    job = db.get_job("b2")
    assert job.blueprint_seed == 42
    assert job.blueprint_sha256 == "b" * 64


def test_seed_zero_is_recorded_not_treated_as_absent(db):
    """Zero is a legitimate seed; the skip-None update must not swallow it."""
    db.insert_job(make_job("b3"))
    db.update_job_blueprint("b3", seed=0)
    # _update_job_columns skips None, not falsy — a dropped zero would silently make
    # one job in four billion unreproducible.
    assert db.get_job("b3").blueprint_seed == 0


# ── Mesh lineage ──────────────────────────────────────────────────────────────


def test_mesh_lineage_round_trips(db):
    """The before and after snapshots are stored separately."""
    db.insert_job(make_job("m1"))
    db.update_job_mesh_lineage(
        "m1",
        raw_sha256="c" * 64,
        raw_features={"face_count": 5000, "is_watertight": False},
        repaired_sha256="d" * 64,
        repaired_features={"face_count": 4980, "is_watertight": True},
    )
    job = db.get_job("m1")
    assert job.raw_mesh_features["is_watertight"] is False
    assert job.repaired_mesh_features["is_watertight"] is True
    assert job.raw_mesh_sha256 != job.repaired_mesh_sha256


def test_mesh_lineage_leaves_printed_features_alone(db):
    """`mesh_features` keeps meaning the printed mesh; lineage writes its own columns."""
    db.insert_job(make_job("m2"))
    db.update_job_printability("m2", features={"face_count": 1})
    db.update_job_mesh_lineage("m2", raw_features={"face_count": 999})
    job = db.get_job("m2")
    assert job.mesh_features["face_count"] == 1
    assert job.raw_mesh_features["face_count"] == 999


# ── Slice results ─────────────────────────────────────────────────────────────


def test_slice_success_records_estimates(db):
    """A successful slice stores the time, filament and support figures."""
    db.insert_job(make_job("s1"))
    db.update_job_slice(
        "s1",
        status="success",
        duration_s=4.2,
        estimated_print_time_s=6666,
        filament_used_mm=2408.7,
        filament_used_mm3=5793.5,
        filament_used_g=7.18,
        support_filament_mm3=120.0,
        layer_count=140,
        stats={"filament_mm_by_type": {"WALL-OUTER": 229.1}},
    )
    job = db.get_job("s1")
    assert job.slice_status == "success"
    assert job.estimated_print_time_s == 6666
    assert job.filament_used_g == pytest.approx(7.18)
    assert job.support_filament_mm3 == pytest.approx(120.0)
    assert job.layer_count == 140
    assert job.slice_stats["filament_mm_by_type"]["WALL-OUTER"] == pytest.approx(229.1)


def test_slice_failure_is_recorded_as_a_result(db):
    """A mesh that cannot be sliced is a data point, not an absence of one."""
    db.insert_job(make_job("s2"))
    db.update_job_slice("s2", status="failed", error="CuraEngine exited with code 1")
    job = db.get_job("s2")
    assert job.slice_status == "failed"
    assert "code 1" in job.slice_error


def test_slice_status_is_validated():
    """A typo in the status must fail loudly rather than poison the dataset."""
    with pytest.raises(ValueError):
        make_job("s3", slice_status="sucess")


# ── Target material and process ───────────────────────────────────────────────


def test_material_round_trips(db):
    """Material type, brand and colour are all stored."""
    db.insert_job(make_job("t1", material_type="PETG", material_brand="Prusament",
                           material_colour="Galaxy Black"))
    job = db.get_job("t1")
    assert (job.material_type, job.material_brand) == ("PETG", "Prusament")
    assert job.material_colour == "Galaxy Black"


def test_process_params_are_frozen_on_the_row(db):
    """The profile snapshot lives on the job, not behind a file read."""
    db.insert_job(make_job("t2", process_params={"layer_height": 0.2}, nozzle_diameter_mm=0.4))
    job = db.get_job("t2")
    assert job.process_params["layer_height"] == 0.2
    assert job.nozzle_diameter_mm == pytest.approx(0.4)


# ── Engagement ────────────────────────────────────────────────────────────────


def test_job_event_kind_is_validated():
    """An unrecognised event kind is a bug, not a new category."""
    with pytest.raises(ValueError):
        JobEvent(
            event_id="e", job_id="j",
            occurred_at=datetime.now(timezone.utc), kind="whatever",
        )


def test_all_declared_kinds_are_accepted():
    """Every kind the code emits must construct."""
    for kind in JOB_EVENT_KINDS:
        JobEvent(event_id="e", job_id="j",
                 occurred_at=datetime.now(timezone.utc), kind=kind)


def test_events_round_trip_with_detail(db):
    """Event payloads survive the JSON column."""
    db.insert_job(make_job("e1"))
    db.record_job_event("e1", "download", {"artifact": "engineered_mesh.gcode"})
    events = db.get_job_events("e1")
    assert len(events) == 1
    assert events[0].kind == "download"
    assert events[0].detail["artifact"] == "engineered_mesh.gcode"


def test_events_can_be_filtered_by_kind(db):
    """The response-rate query reads one kind at a time."""
    db.insert_job(make_job("e2"))
    db.record_job_event("e2", "download")
    db.record_job_event("e2", "outcome_prompt_shown")
    assert len(db.get_job_events("e2", kind="download")) == 1
    assert len(db.get_job_events("e2")) == 2


def test_download_count_increments(db):
    """The denormalised counter tracks repeat downloads."""
    db.insert_job(make_job("e3"))
    assert db.get_job("e3").download_count == 0
    db.increment_download_count("e3")
    db.increment_download_count("e3")
    assert db.get_job("e3").download_count == 2


def test_count_job_events_spans_jobs(db):
    """The pilot metric counts across the whole dataset, not per job."""
    db.insert_job(make_job("e4"))
    db.insert_job(make_job("e5"))
    db.record_job_event("e4", "outcome_prompt_shown")
    db.record_job_event("e5", "outcome_prompt_shown")
    db.record_job_event("e5", "outcome_reported")
    assert db.count_job_events("outcome_prompt_shown") == 2
    assert db.count_job_events("outcome_reported") == 1


def test_regeneration_lineage_is_queryable(db):
    """A child job points at the parent it was regenerated from."""
    db.insert_job(make_job("p1"))
    db.insert_job(make_job("p2", parent_job_id="p1", regeneration_reason="too thin"))
    child = db.get_job("p2")
    assert child.parent_job_id == "p1"
    assert child.regeneration_reason == "too thin"


# ── Human outcome ─────────────────────────────────────────────────────────────


def test_awaiting_verdict_is_a_valid_outcome():
    """The pending state must construct like any other outcome."""
    assert make_job("o0", outcome="awaiting_verdict").outcome == "awaiting_verdict"


def test_invalid_outcome_still_rejected():
    """Widening the enum must not have disabled its validation."""
    with pytest.raises(ValueError):
        make_job("o0b", outcome="probably fine")


def test_user_verdict_records_its_source_and_time(db):
    """A human verdict is distinguishable from the printer's own report."""
    db.insert_job(make_job("o1", outcome="awaiting_verdict"))
    db.update_job_outcome_verdict("o1", "failure", source="user")
    job = db.get_job("o1")
    assert job.outcome == "failure"
    assert job.outcome_source == "user"
    assert job.outcome_reported_at is not None


def test_machine_verdict_does_not_claim_a_report_time(db):
    """Only a person reports an outcome; the machine merely finished."""
    db.insert_job(make_job("o2"))
    db.update_job_outcome_verdict("o2", "success", source="machine",
                                  completed_at=datetime.now(timezone.utc))
    job = db.get_job("o2")
    assert job.outcome_source == "machine"
    assert job.outcome_reported_at is None
    assert job.completed_at is not None


def test_outcome_source_is_validated():
    """Only two things decide an outcome."""
    with pytest.raises(ValueError):
        make_job("o3", outcome_source="vibes")


def test_machine_outcome_never_overwrites_a_human_one(db):
    """Printer events arrive late; a person's answer outranks them.

    Regression guard: OctoPrint emits PrintDone whenever the file ends, which would
    otherwise replace "I watched it fail" with a success and destroy the only reliable
    label on the row.
    """
    db.insert_job(make_job("w1", outcome="awaiting_verdict"))
    db.update_job_outcome_verdict("w1", "failure", source="user")
    db.update_job_outcome_verdict("w1", "success", source="machine",
                                  completed_at=datetime.now(timezone.utc))
    job = db.get_job("w1")
    assert job.outcome == "failure"
    assert job.outcome_source == "user"


def test_machine_outcome_may_replace_another_machine_outcome(db):
    """Two machine signals about the same job are still allowed to update it."""
    db.insert_job(make_job("w2"))
    db.update_job_outcome_verdict("w2", "awaiting_verdict", source="machine")
    db.update_job_outcome_verdict("w2", "failure", source="machine")
    assert db.get_job("w2").outcome == "failure"


def test_a_person_can_correct_their_own_verdict(db):
    """The precedence rule blocks machines, not people changing their minds."""
    db.insert_job(make_job("w3", outcome="awaiting_verdict"))
    db.update_job_outcome_verdict("w3", "success", source="user")
    db.update_job_outcome_verdict("w3", "failure", source="user")
    assert db.get_job("w3").outcome == "failure"


@pytest.mark.parametrize(
    "event_type,expected",
    [
        # The printer knows it reached the end of the file. It does not know the part
        # survived, so this is a question, not a result.
        ("PrintDone", "awaiting_verdict"),
        ("PrintFailed", "failure"),
        ("Error", "failure"),
        ("PrintCancelled", "cancelled"),
    ],
)
async def test_octoprint_events_map_to_outcomes(db, event_type, expected):
    """PrintDone must not be recorded as a success."""
    from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector

    db.insert_job(make_job("oc1"))
    collector = OctoPrintCollector("localhost", 5001, "key", "oc1", db)
    await collector._on_event({"type": event_type})

    job = db.get_job("oc1")
    assert job.outcome == expected
    assert job.outcome_source == "machine"


async def test_octoprint_ignores_unknown_events(db):
    """An unrelated event leaves the outcome alone."""
    from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector

    db.insert_job(make_job("oc2"))
    collector = OctoPrintCollector("localhost", 5001, "key", "oc2", db)
    await collector._on_event({"type": "ZChange"})
    assert db.get_job("oc2").outcome == "unknown"


def test_pending_queue_lists_only_unconfirmed_prints(db):
    """The feedback queue is exactly the awaiting_verdict rows."""
    db.insert_job(make_job("q1", outcome="awaiting_verdict",
                           completed_at=datetime.now(timezone.utc)))
    db.insert_job(make_job("q2", outcome="success"))
    db.insert_job(make_job("q3", outcome="failure"))
    pending = db.get_jobs_awaiting_verdict()
    assert [j.job_id for j in pending] == ["q1"]


# ── Migration ─────────────────────────────────────────────────────────────────


def test_migrates_a_database_predating_every_new_column():
    """Real databases predate all of this, including the NOT NULL started_at era."""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "legacy.db")
        legacy = sqlite3.connect(path)
        legacy.execute(OLD_SCHEMA)
        legacy.execute(
            "INSERT INTO print_job VALUES ('legacy-1','old prompt','p','octoprint','cura','d',"
            "'2026-01-01T00:00:00+00:00',NULL,'success')"
        )
        legacy.commit()
        legacy.close()

        database = TelemetryDB(path)
        database.init_schema()

        job = database.get_job("legacy-1")
        assert job.prompt == "old prompt"
        # Nothing is backfilled: a seed that was never recorded cannot be invented, and
        # a partial backfill would be indistinguishable from captured data.
        assert job.blueprint_seed is None
        assert job.material_type is None
        assert job.slice_status is None
        assert job.download_count == 0

        database.update_job_blueprint("legacy-1", seed=7)
        database.update_job_slice("legacy-1", status="success")
        database.record_job_event("legacy-1", "download")
        assert database.get_job("legacy-1").blueprint_seed == 7
        assert len(database.get_job_events("legacy-1")) == 1

        database.init_schema()  # idempotent
        assert database.get_job("legacy-1").blueprint_seed == 7
        database.close()


def test_insert_job_carries_every_new_column(db):
    """The dynamic INSERT must not silently drop a field added to the dataclass."""
    job = make_job(
        "full",
        blueprint_seed=1, blueprint_model="FLUX", blueprint_params={"a": 1},
        raw_mesh_sha256="e" * 64, raw_mesh_features={"face_count": 2},
        repaired_mesh_sha256="f" * 64, repaired_mesh_features={"face_count": 3},
        slice_status="success", estimated_print_time_s=10, filament_used_mm3=4.0,
        support_filament_mm3=1.0, layer_count=5, slice_stats={"b": 2},
        material_type="PLA", material_brand="X", material_colour="red",
        nozzle_diameter_mm=0.6, process_params={"c": 3},
        parent_job_id="full-parent", regeneration_reason="why not",
        outcome_source="machine",
    )
    db.insert_job(job)
    read = db.get_job("full")
    for field in (
        "blueprint_seed", "blueprint_model", "blueprint_params",
        "raw_mesh_sha256", "raw_mesh_features",
        "repaired_mesh_sha256", "repaired_mesh_features",
        "slice_status", "estimated_print_time_s", "filament_used_mm3",
        "support_filament_mm3", "layer_count", "slice_stats",
        "material_type", "material_brand", "material_colour",
        "nozzle_diameter_mm", "process_params",
        "parent_job_id", "regeneration_reason", "outcome_source",
    ):
        assert getattr(read, field) == getattr(job, field), field


# ── Pipeline recorders ────────────────────────────────────────────────────────


class _Args:
    """Stand-in for the pipeline's parsed argparse namespace."""

    def __init__(self, job_id="rec-1", profile=None, material_type=None):
        self.job_id = job_id
        self.profile = profile
        self.material_type = material_type


def test_record_slice_parses_the_gcode(tmp_path, monkeypatch):
    """The recorder derives its numbers from the file, not the header."""
    from pythonsrc import pipeline

    gcode = tmp_path / "job.gcode"
    gcode.write_text(
        ";FLAVOR:Marlin\n;TIME:600\n;Filament used: 0m\n"
        "M83\n;LAYER:0\n;TYPE:WALL-OUTER\nG1 X1 E5.0\n"
        ";TYPE:SUPPORT\nG1 X2 E2.0\n"
    )

    database = TelemetryDB(str(tmp_path / "t.db"))
    database.init_schema()
    database.insert_job(make_job("rec-1"))
    database.close()

    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "t.db"))
    pipeline._record_slice(_Args(material_type="PLA"), gcode, 3.0, status="success")

    database = TelemetryDB(str(tmp_path / "t.db"))
    job = database.get_job("rec-1")
    database.close()

    assert job.slice_status == "success"
    assert job.estimated_print_time_s == 600
    # 7mm total despite the header's "0m".
    assert job.filament_used_mm == pytest.approx(7.0)
    assert job.support_filament_mm3 > 0
    assert job.filament_used_g is not None
    assert job.layer_count == 1


def test_record_slice_without_a_job_id_is_a_no_op(tmp_path, monkeypatch):
    """Manual CLI runs have no telemetry row to write to."""
    from pythonsrc import pipeline

    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "absent.db"))
    pipeline._record_slice(_Args(job_id=None), None, 1.0, status="success")
    assert not (tmp_path / "absent.db").exists()


def test_recorders_swallow_database_errors(tmp_path, monkeypatch, caplog):
    """Telemetry must never be the reason a print fails."""
    from pythonsrc import pipeline

    with patch("pythonsrc.telemetry.db.TelemetryDB", side_effect=RuntimeError("disk on fire")):
        pipeline._record_slice(_Args(), None, 1.0, status="failed", error="x")
        pipeline._record_blueprint(_Args(), tmp_path / "nope.png", None)
        pipeline._record_mesh_lineage(_Args(), tmp_path / "a.obj", tmp_path / "b.obj")


def test_file_sha256_hashes_and_tolerates_absence(tmp_path):
    """Hashing a missing artifact returns None rather than raising."""
    from pythonsrc import pipeline

    path = tmp_path / "x.bin"
    path.write_bytes(b"hello")
    digest = pipeline._file_sha256(path)
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert pipeline._file_sha256(tmp_path / "missing.bin") is None


def test_filament_diameter_falls_back_to_default(tmp_path):
    """A profile without material_diameter still yields a usable number."""
    from pythonsrc import pipeline
    from pythonsrc.gcode_stats import DEFAULT_FILAMENT_DIAMETER_MM

    profile = tmp_path / "p.json"
    profile.write_text('{"layer_height": 0.2}')
    assert pipeline._filament_diameter(_Args(profile=str(profile))) == DEFAULT_FILAMENT_DIAMETER_MM
    assert pipeline._filament_diameter(_Args(profile=None)) == DEFAULT_FILAMENT_DIAMETER_MM


def test_filament_diameter_reads_the_profile(tmp_path):
    """A 2.85mm setup must not be costed as 1.75mm."""
    from pythonsrc import pipeline

    profile = tmp_path / "p.json"
    profile.write_text('{"material_diameter": 2.85}')
    assert pipeline._filament_diameter(_Args(profile=str(profile))) == pytest.approx(2.85)


# ── Visualizer seed ───────────────────────────────────────────────────────────


def test_resolve_seed_honours_an_explicit_value():
    """Passing a seed reproduces a previous run."""
    from pythonsrc.blueprint_spec import resolve_seed

    assert resolve_seed(12345) == 12345
    assert resolve_seed(0) == 0


def test_resolve_seed_draws_distinct_values_within_one_second():
    """The old wall-clock seed gave same-second jobs an identical image.

    Regression guard: `int(time.time())` collides for every job started in the same
    second, which made the seed useless both as an identifier and as a control.
    """
    from pythonsrc.blueprint_spec import SEED_SPACE, resolve_seed

    seeds = {resolve_seed() for _ in range(200)}
    assert len(seeds) > 190
    assert all(0 <= s < SEED_SPACE for s in seeds)


def test_engineer_prompt_is_recorded_separately_from_the_user_prompt():
    """The model never sees the user's prompt verbatim."""
    from pythonsrc.blueprint_spec import engineer_prompt

    engineered = engineer_prompt("a vase")
    assert "a vase" in engineered
    assert engineered != "a vase"
    assert "clay material" in engineered
