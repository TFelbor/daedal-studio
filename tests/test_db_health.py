"""The server's view of database health: checked on a cadence, cached for `/health`.

Replaces the SQLite-era startup integrity check and snapshot rotation. What is kept
from that design: a server on a broken database says so in its logs and on `/health`
rather than failing one endpoint at a time; the verdict is cached because the
endpoint is polled; and the check is what heals a server that started while the
database was away.
"""

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module

UNREACHABLE = "postgresql://nobody:secret@127.0.0.1:1/none?connect_timeout=1"


@pytest.fixture(autouse=True)
def _restore_verdict(monkeypatch):
    """Every test here writes the module-level verdict; none may leave it behind."""
    monkeypatch.setattr(app_module, "database_problems", list(app_module.database_problems))
    monkeypatch.setattr(app_module, "database_checked_at", app_module.database_checked_at)


def test_a_healthy_database_reports_no_problems(isolated_db):
    assert app_module.check_database_health(isolated_db) == []
    assert app_module.database_problems == []
    assert app_module.database_checked_at is not None


def test_missing_tables_are_created_rather_than_reported(isolated_db_url):
    """The schema is idempotent DDL, so this is the one problem the check fixes itself."""
    db = TelemetryDB(isolated_db_url)
    assert db.health_check(), "a fresh schema has no tables yet"
    assert app_module.check_database_health(db) == []
    assert db.health_check() == []


def test_an_unreachable_database_is_reported(monkeypatch):
    monkeypatch.setenv("DS_DATABASE_TIMEOUT_S", "2")
    from pythonsrc.telemetry import db as db_module

    db = TelemetryDB(UNREACHABLE)
    try:
        problems = app_module.check_database_health(db)
    finally:
        db_module.close_pool(UNREACHABLE)
    assert problems
    assert problems[0].startswith("cannot reach")
    assert app_module.database_problems == problems


def test_health_interval_parses_and_disables():
    assert app_module.health_interval_s({"DS_DB_HEALTH_INTERVAL_S": "30"}) == 30.0
    assert app_module.health_interval_s({"DS_DB_HEALTH_INTERVAL_S": "0"}) is None
    assert app_module.health_interval_s({"DS_DB_HEALTH_INTERVAL_S": "junk"}) == 60.0
    assert app_module.health_interval_s({}) == 60.0


def test_the_health_endpoint_reports_the_cached_verdict(monkeypatch):
    client = TestClient(app_module.app)

    monkeypatch.setattr(app_module, "database_problems", ["cannot reach the telemetry database"])
    degraded = client.get("/health").json()
    assert degraded["status"] == "degraded"
    assert degraded["database"]["healthy"] is False
    assert degraded["database"]["problems"] == ["cannot reach the telemetry database"]

    monkeypatch.setattr(app_module, "database_problems", [])
    healthy = client.get("/health").json()
    assert healthy["status"] == "ok"
    assert healthy["database"]["healthy"] is True
    assert "checked_at" in healthy["database"]


def test_startup_creates_the_schema_before_reading_config(isolated_db_url, monkeypatch):
    """The strategy override is read from `app_config` during startup.

    On a brand-new database that table does not exist until startup creates it, so
    the schema has to come first. Found by booting the server against an empty
    PostgreSQL: `relation "app_config" does not exist`, and the process exited. The
    suite had not caught it because conftest pre-creates the table — which is why
    this test takes the bare URL rather than `isolated_db_env`, which does too.
    """
    from pythonsrc.telemetry.db import TelemetryDB

    monkeypatch.setenv("DS_DATABASE_URL", isolated_db_url)
    db = TelemetryDB()
    assert db.health_check(), "the fixture schema must start empty for this test"
    with TestClient(app_module.app) as client:
        assert client.get("/health").json()["database"]["healthy"] is True
        assert client.get("/config").status_code == 200
    assert db.health_check() == []
    assert "app_config" in {
        r["table_name"]
        for r in db.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    }
