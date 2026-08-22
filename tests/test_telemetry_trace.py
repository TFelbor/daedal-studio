"""The trace tool's map of the capture path must stay level with the schema.

`pythonsrc/telemetry/trace.py` holds `STAGES`: a hand-written list of every write
to `print_job`, in the order a job encounters them. That list is the whole value of
the tool — it is what turns fifty nullable columns into "these were written at
Phase 2". A map that has drifted from the schema is worse than no map, because it
reports a real gap as complete coverage, or invents a column that no longer exists.

So the first test below is the load-bearing one: the union of `STAGES`' columns must
equal `print_job`'s columns exactly, in both directions. Adding a capture column
without adding it to the map fails here rather than being silently invisible in
every trace.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample
from pythonsrc.telemetry.trace import (
    STAGES,
    Palette,
    build_json,
    format_value,
    list_jobs,
    main,
    open_readonly,
    read_extras,
    render,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def traced_db(tmp_path):
    """A database holding one fully populated job and one that stopped early.

    Written through the real `TelemetryDB` writers rather than raw SQL, so the rows
    are the same shape the pipeline produces. "Fully populated" means every stage
    in `STAGES` wrote something — run context and dispatch included, since a job
    that reached a human verdict necessarily passed through both. A stage left
    empty here reads as a coverage hole in the tool rather than in the fixture.

    Returns:
        A tuple of (db_path, complete_job_id, partial_job_id).
    """
    db_path = tmp_path / "telemetry.db"
    db = TelemetryDB(db_path=str(db_path))
    db.init_schema()
    now = datetime.now(timezone.utc)

    complete = "aaaaaaaa-0000-0000-0000-000000000001"
    db.insert_job(PrintJob(
        job_id=complete, prompt="a low-poly fox", printer_id="ender3",
        printer_firmware="octoprint", slicer="cura", profile_name="ender3",
        started_at=None, completed_at=None, outcome="unknown",
        material_type="PLA", nozzle_diameter_mm=0.4,
        process_params={"layer_height_mm": 0.2},
    ))
    db.update_job_start_time(complete, now)
    db.update_job_run_context(complete, git_sha="edffae7", used_reference_assets=False)
    db.update_job_blueprint(
        complete, model="FLUX.1-schnell", model_version="black-forest-labs/FLUX.1-schnell",
        seed=839201753, prompt_engineered="a low-poly fox, clay render",
        params={"steps": 4}, sha256="a" * 64, duration_s=31.4,
    )
    db.update_job_generation(
        complete, model="TRELLIS.2", model_version="microsoft/TRELLIS.2-4B",
        backend="remote_worker", params={"pipeline_type": "1024_cascade"},
        cost_eur=None, duration_s=224.1,
    )
    db.update_job_mesh_lineage(
        complete, raw_sha256="b" * 64, raw_features={"faces": 196733},
        repaired_sha256="c" * 64, repaired_features={"faces": 100004},
        repair_report={"path": "manifold", "rounds": 2, "scale_factor": 0.254},
    )
    db.update_job_printability(
        complete, score=82.5, verdict="risky",
        features={"faces": 100004}, report={"score": 82.5},
    )
    db.update_job_slice(
        complete, status="success", duration_s=4.8, estimated_print_time_s=6666,
        filament_used_mm=2413.7, filament_used_mm3=5806.4, filament_used_g=7.2,
        layer_count=214, stats={"extrusion_mode": "absolute"},
    )
    for i in range(5):
        db.insert_sample(TelemetrySample(
            job_id=complete, sampled_at=now + timedelta(seconds=i * 4),
            gcode_line=None, z_height_mm=i * 0.2, hotend_actual_c=209.0,
            hotend_target_c=210.0, bed_actual_c=60.0, bed_target_c=60.0,
            print_speed_pct=100.0, extrusion_factor_pct=100.0, fan_speed_pct=100.0,
        ))
    db.update_job_dispatch(complete, printer_url="http://localhost:5001")
    db.try_claim_collector(complete, owner="api-server")
    db.record_job_event(complete, "download", {"artifact": "engineered_mesh.gcode"})
    db.increment_download_count(complete)
    db.update_job_print_duration(complete, 1783.0)
    db.update_job_outcome_verdict(
        complete, "failure", source="user", completed_at=now + timedelta(minutes=30),
    )

    partial = "bbbbbbbb-0000-0000-0000-000000000002"
    db.insert_job(PrintJob(
        job_id=partial, prompt="a hex bolt", printer_id="ender3",
        printer_firmware="octoprint", slicer="cura", profile_name="ender3",
        started_at=None, completed_at=None, outcome="unknown",
    ))
    db.close()
    return str(db_path), complete, partial


# ── The map matches the schema ─────────────────────────────────────────────────

def test_stages_cover_every_print_job_column(tmp_path):
    """No column may exist without a stage claiming it, and none may be invented.

    This is the test that keeps the tool honest. A capture column added to
    `_PRINT_JOB_EXTRA_COLUMNS` but not to `STAGES` would never appear in a trace,
    so a reader would conclude it was already covered by an existing stage.
    """
    db = TelemetryDB(db_path=str(tmp_path / "schema.db"))
    db.init_schema()
    columns = {row[1] for row in db.conn.execute("PRAGMA table_info(print_job)")}
    db.close()

    mapped = {name for stage in STAGES for name in stage.columns}
    # job_id is the key the trace is looked up by, not something a stage writes.
    mapped.add("job_id")

    assert columns - mapped == set(), (
        "print_job columns with no stage in trace.STAGES: "
        f"{sorted(columns - mapped)}"
    )
    assert mapped - columns == set(), (
        f"trace.STAGES names columns that do not exist: {sorted(mapped - columns)}"
    )


def test_each_column_is_claimed_by_exactly_one_stage():
    """Two stages claiming one column would double-count the coverage total."""
    seen = {}
    for stage in STAGES:
        for name in stage.columns:
            assert name not in seen, (
                f"{name} is claimed by both {seen[name]} and {stage.key}"
            )
            seen[name] = stage.key


def test_every_stage_names_a_real_writer():
    """A renamed `TelemetryDB` method must not leave the map pointing at nothing."""
    for stage in STAGES:
        method = stage.writer.removeprefix("db.").removesuffix("()")
        assert hasattr(TelemetryDB, method), (
            f"{stage.key} names TelemetryDB.{method}, which does not exist"
        )


def test_every_call_site_file_exists_and_mentions_the_writer():
    """The `file:line` pointers must at least point at the right file.

    Line numbers drift with every edit and are not asserted; the file containing
    the call is the part a reader actually needs, and a moved call site shows up
    here as a missing method name.
    """
    for stage in STAGES:
        method = stage.writer.removeprefix("db.").removesuffix("()")
        found = False
        for reference in stage.call_site.split("·"):
            path = reference.strip().split(":")[0]
            candidates = [REPO_ROOT / path, *REPO_ROOT.rglob(Path(path).name)]
            for candidate in candidates:
                if candidate.is_file() and method in candidate.read_text():
                    found = True
                    break
            if found:
                break
        assert found, f"{stage.key}: no file in '{stage.call_site}' calls {method}"


# ── Rendering a real row ───────────────────────────────────────────────────────

def test_render_reports_full_coverage_for_a_complete_job(traced_db):
    """A job that ran end to end shows every stage as at least partly filled."""
    db_path, complete, _ = traced_db
    conn = open_readonly(db_path)
    row = conn.execute("SELECT * FROM print_job WHERE job_id = ?", (complete,)).fetchone()
    from pythonsrc.telemetry.db import _row_to_job

    job = _row_to_job(row)
    extras = read_extras(conn, complete)
    output = render(job, dict(row), extras, palette=Palette(False), verbose=False)
    conn.close()

    assert "Phase 1 · Visualizer" in output
    assert "839201753" in output          # the seed, the reason capture exists
    assert "remote_worker" in output
    assert "5 rows" in output             # telemetry_sample
    assert "owner=api-server" in output
    assert "○" not in output              # no stage completely empty


def test_render_shows_an_early_exit_as_empty_stages(traced_db):
    """A job that never reached Phase 1 must read as empty, not as absent."""
    db_path, _, partial = traced_db
    conn = open_readonly(db_path)
    row = conn.execute("SELECT * FROM print_job WHERE job_id = ?", (partial,)).fetchone()
    from pythonsrc.telemetry.db import _row_to_job

    job = _row_to_job(row)
    output = render(
        job, dict(row), read_extras(conn, partial),
        palette=Palette(False), verbose=False,
    )
    conn.close()

    assert "○" in output                  # at least one stage wrote nothing
    assert "0 rows" in output


def test_expected_nulls_are_not_reported_as_gaps(traced_db):
    """`generation_cost_eur` is None for every self-hosted run, by design.

    Marking it as a missing value would train the reader to ignore the marker that
    matters.
    """
    db_path, complete, _ = traced_db
    conn = open_readonly(db_path)
    row = conn.execute("SELECT * FROM print_job WHERE job_id = ?", (complete,)).fetchone()
    from pythonsrc.telemetry.db import _row_to_job

    output = render(
        _row_to_job(row), dict(row), read_extras(conn, complete),
        palette=Palette(False), verbose=False,
    )
    conn.close()

    assert "not billed unless backend is hosted_api" in output
    assert "✗ generation_cost_eur" not in output


def test_json_output_is_a_stage_by_stage_coverage_map(traced_db):
    """`--json` must be queryable without parsing the report."""
    db_path, complete, _ = traced_db
    conn = open_readonly(db_path)
    row = conn.execute("SELECT * FROM print_job WHERE job_id = ?", (complete,)).fetchone()
    from pythonsrc.telemetry.db import _row_to_job

    payload = build_json(_row_to_job(row), dict(row), read_extras(conn, complete))
    conn.close()

    keys = [stage["key"] for stage in payload["stages"]]
    assert keys == [stage.key for stage in STAGES]
    phase2 = next(s for s in payload["stages"] if s["key"] == "phase2")
    assert phase2["columns"]["generation_backend"] is True
    assert phase2["columns"]["generation_cost_eur"] is False
    assert payload["satellite"]["telemetry_sample_rows"] == 5


def test_download_count_of_zero_is_not_a_populated_column(traced_db):
    """`download_count` defaults to 0, which is an absence of downloads."""
    db_path, _, partial = traced_db
    conn = open_readonly(db_path)
    row = conn.execute("SELECT * FROM print_job WHERE job_id = ?", (partial,)).fetchone()
    from pythonsrc.telemetry.db import _row_to_job

    payload = build_json(_row_to_job(row), dict(row), read_extras(conn, partial))
    conn.close()
    engagement = next(s for s in payload["stages"] if s["key"] == "engagement")
    assert engagement["columns"]["download_count"] is False


# ── Value formatting ──────────────────────────────────────────────────────────

def test_json_columns_are_summarised_not_dumped():
    """A `printability_report` is thousands of characters; a trace line is one."""
    summary = format_value(
        "printability_report", '{"a": 1, "b": 2, "c": 3}', verbose=False
    )
    assert summary.startswith("{3 keys}")
    expanded = format_value("printability_report", '{"a": 1}', verbose=True)
    assert "\n" in expanded


def test_hashes_are_truncated_unless_verbose():
    """64 hex characters per line would push every value off the screen."""
    digest = "a" * 64
    assert format_value("blueprint_sha256", digest, verbose=False) == "a" * 12 + "…"
    assert format_value("blueprint_sha256", digest, verbose=True) == digest


# ── Read-only guarantee ───────────────────────────────────────────────────────

def test_tracing_cannot_write_to_the_database(traced_db):
    """The database has one writer by design; this tool must never be a second.

    Asserted on the connection rather than by comparing mtimes, so the guarantee
    holds even for a code path that has not been exercised yet.
    """
    db_path, complete, _ = traced_db
    conn = open_readonly(db_path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE print_job SET prompt = 'x' WHERE job_id = ?", (complete,))
    conn.close()


def test_a_missing_database_is_an_error_not_a_new_file(tmp_path):
    """`TelemetryDB` creates its parent directory; the tracer must not."""
    missing = tmp_path / "nested" / "absent.db"
    assert main(["--db", str(missing), "--latest"]) == 1
    assert not missing.exists()
    assert not missing.parent.exists()


def test_listing_an_empty_database_explains_itself(tmp_path):
    """A developer with no jobs yet should get a next step, not a blank page."""
    db = TelemetryDB(db_path=str(tmp_path / "empty.db"))
    db.init_schema()
    db.close()
    conn = open_readonly(str(tmp_path / "empty.db"))
    output = list_jobs(conn, 20, Palette(False))
    conn.close()
    assert "No jobs" in output


def test_a_job_id_prefix_is_enough(traced_db, capsys):
    """Nobody types a UUID in full."""
    db_path, complete, _ = traced_db
    assert main(["--db", db_path, complete[:8]]) == 0
    assert complete in capsys.readouterr().out


def test_an_ambiguous_prefix_is_refused(traced_db, capsys):
    """Guessing which of two jobs was meant would be worse than asking again."""
    db_path, complete, partial = traced_db
    # Both seeded ids contain a hyphen at position 8; LIKE 'a%' and LIKE 'b%' each
    # match one, so ambiguity is provoked with a prefix common to both.
    assert main(["--db", db_path, partial[:1]]) == 0

    db = TelemetryDB(db_path=db_path)
    db.insert_job(PrintJob(
        job_id=partial[:8] + "-dupe", prompt="collides", printer_id="ender3",
        printer_firmware="octoprint", slicer="cura", profile_name="ender3",
        started_at=None, completed_at=None, outcome="unknown",
    ))
    db.close()

    assert main(["--db", db_path, partial[:8]]) == 1
    assert "matches 2 jobs" in capsys.readouterr().err
