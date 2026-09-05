"""How the telemetry layer holds on to PostgreSQL.

The SQLite file this replaced had a whole test module about pragmas, page corruption
and snapshot backups. None of that exists for a network database; what does is the
connection itself — pooled, validated on checkout, typed on the way in and out — and
these tests hold that.
"""

from datetime import datetime, timezone

import psycopg
import pytest

from pythonsrc.telemetry import db as db_module
from pythonsrc.telemetry.db import (
    DatabaseConfigError,
    IntegrityError,
    TelemetryDB,
    redact_dsn,
)
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample

UNREACHABLE = "postgresql://nobody:secret@127.0.0.1:1/none?connect_timeout=1"


def _job(job_id="conn-1", **overrides) -> PrintJob:
    fields = dict(
        job_id=job_id, prompt="a vase", printer_id="p", printer_firmware="octoprint",
        slicer="cura", profile_name="x", started_at=datetime.now(timezone.utc),
        completed_at=None, outcome="unknown",
    )
    fields.update(overrides)
    return PrintJob(**fields)


# ── One pool per process per URL ──────────────────────────────────────────────

def test_instances_on_one_url_share_one_pool(isolated_db_url):
    a = TelemetryDB(isolated_db_url)
    b = TelemetryDB(isolated_db_url)
    a.init_schema()
    b.insert_job(_job())
    assert a.get_job("conn-1") is not None
    assert db_module._pool_for(isolated_db_url) is db_module._pool_for(isolated_db_url)
    # `close()` is deliberately a no-op: the pool outlives any one handle.
    a.close()
    assert b.get_job("conn-1") is not None


def test_a_connection_supabase_dropped_is_replaced_on_checkout(isolated_db):
    """Idle connections get closed by the server; the next caller must not inherit one.

    Simulated by terminating every other backend of this role from a fresh
    connection — what a pooler timeout or a database restart does from the client's
    point of view. The pool validates on checkout, so the following operation sees a
    live connection rather than `server closed the connection unexpectedly`.
    """
    isolated_db.insert_job(_job("survivor"))
    with psycopg.connect(isolated_db.dsn, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name = 'ds-mvp' AND pid <> pg_backend_pid()"
        )
    assert isolated_db.get_job("survivor") is not None


# ── Configuration and failure are told apart ──────────────────────────────────

def test_no_url_is_a_configuration_error_not_a_connection_error(monkeypatch):
    monkeypatch.delenv("DS_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigError, match="DS_DATABASE_URL"):
        TelemetryDB()


def test_an_unreachable_database_reports_rather_than_raises(monkeypatch):
    monkeypatch.setenv("DS_DATABASE_TIMEOUT_S", "2")
    db = TelemetryDB(UNREACHABLE)
    try:
        problems = db.health_check()
    finally:
        db_module.close_pool(UNREACHABLE)
    assert problems and problems[0].startswith("cannot reach the telemetry database")
    assert "secret" not in problems[0], "the password must not reach the log"


def test_writes_to_an_unreachable_database_raise_operational_errors(monkeypatch):
    monkeypatch.setenv("DS_DATABASE_TIMEOUT_S", "2")
    db = TelemetryDB(UNREACHABLE)
    try:
        with pytest.raises(Exception) as excinfo:
            db.insert_job(_job())
    finally:
        db_module.close_pool(UNREACHABLE)
    # PoolTimeout is an OperationalError subclass — the collectors' "the database is
    # unreachable" branch keys off exactly that.
    assert isinstance(excinfo.value, db_module.OperationalError)


def test_the_password_is_redacted():
    assert "secret" not in redact_dsn(UNREACHABLE)
    assert "nobody" in redact_dsn(UNREACHABLE)
    assert "secret" not in TelemetryDB(UNREACHABLE).describe


# ── Types ─────────────────────────────────────────────────────────────────────

def test_foreign_keys_are_enforced(isolated_db):
    with pytest.raises(IntegrityError):
        isolated_db.insert_sample(TelemetrySample(
            "no-such-job", datetime.now(timezone.utc), None, None, None, None, None,
            None, None, None, None,
        ))


def test_timestamps_come_back_utc_aware(isolated_db):
    when = datetime(2026, 9, 5, 12, 34, 56, 789012, tzinfo=timezone.utc)
    isolated_db.insert_job(_job("ts", started_at=when))
    got = isolated_db.get_job("ts").started_at
    assert got == when
    assert got.tzinfo is not None and got.utcoffset().total_seconds() == 0
    assert got.microsecond == 789012


def test_json_payloads_round_trip_as_objects(isolated_db):
    payload = {"layer_height_mm": 0.2, "nested": {"list": [1, 2.5, "x", None, True]}}
    isolated_db.insert_job(_job("json", process_params=payload))
    assert isolated_db.get_job("json").process_params == payload


def test_malformed_json_is_refused_at_write_time(isolated_db):
    isolated_db.insert_job(_job("bad-json"))
    with pytest.raises(db_module.DatabaseError):
        isolated_db.execute(
            "UPDATE print_job SET mesh_features = %s WHERE job_id = %s", ("{not json", "bad-json")
        )
    assert isolated_db.get_job("bad-json").mesh_features is None


def test_a_boolean_lands_in_an_integer_column_as_0_or_1(isolated_db):
    """SQLite stored bools as 0/1 without asking; PostgreSQL has to be told."""
    isolated_db.insert_job(_job("flag", used_reference_assets=True))
    assert isolated_db.get_job("flag").used_reference_assets == 1


def test_raw_helpers(isolated_db):
    isolated_db.insert_job(_job("raw"))
    assert isolated_db.query_one("SELECT COUNT(*) AS n FROM print_job")["n"] == 1
    assert isolated_db.execute("DELETE FROM print_job WHERE job_id = %s", ("raw",)) == 1
    assert isolated_db.query("SELECT job_id FROM print_job") == []
    assert isolated_db.query_one("SELECT job_id FROM print_job") is None
