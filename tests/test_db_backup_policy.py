"""Backup policy: off-disk mirroring, periodic cadence, configurable rotation.

The startup snapshot lands in the same directory — the same filesystem — as the
live database, so a directory-level loss (the incident this all exists for was an
accidental deletion) takes the backups with it. The mirror copies each verified
snapshot to a second location, typically a cloud-synced folder.

Two properties are load-bearing:

* **The mirror must never run on the serving path.** The intended destination is
  a Google Drive File Provider mount, and listing that directory was measured
  blocking for 10+ seconds. Everything Drive-facing happens on a daemon thread
  against an already-closed snapshot file.
* **Off by default.** `P2P_DB_BACKUP_MIRROR_DIR` unset means nothing is copied
  anywhere — the mirror is enabled deliberately, once the data is worth keeping.
"""

import os
import sqlite3
import time
from pathlib import Path

import pytest

from pythonsrc.telemetry.db import TelemetryDB
from server import app as app_module


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    """A healthy database at a temp path, with the default path pointed at it."""
    db_path = tmp_path / "telemetry.db"
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(db_path))
    db = TelemetryDB(str(db_path))
    db.init_schema()
    yield db
    db.close()


def _wait_for_mirror():
    thread = app_module.last_mirror_thread
    if thread is not None:
        thread.join(timeout=10)


# ── Mirroring ────────────────────────────────────────────────────────────────

def test_no_mirror_directory_means_nothing_is_copied(live_db, tmp_path, monkeypatch):
    monkeypatch.delenv("P2P_DB_BACKUP_MIRROR_DIR", raising=False)
    problems = app_module.check_database_health(live_db)
    assert problems == []
    _wait_for_mirror()
    # The local snapshot exists; no second copy anywhere else was made.
    assert list(tmp_path.glob("telemetry.db.backup-*"))
    assert app_module.last_mirror_thread is None


def test_a_verified_snapshot_is_mirrored(live_db, tmp_path, monkeypatch):
    mirror = tmp_path / "drive" / "01_Data_Collection"
    monkeypatch.setenv("P2P_DB_BACKUP_MIRROR_DIR", str(mirror))

    problems = app_module.check_database_health(live_db)
    assert problems == []
    _wait_for_mirror()

    copies = sorted(mirror.glob("telemetry.db.backup-*"))
    assert len(copies) == 1
    # The mirrored copy is a usable database, not a torn file.
    restored = sqlite3.connect(str(copies[0]))
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        restored.close()
    # No half-written temp file left behind.
    assert not list(mirror.glob("*.part"))


def test_a_corrupt_database_is_never_mirrored(tmp_path, monkeypatch):
    db_path = tmp_path / "telemetry.db"
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(db_path))
    mirror = tmp_path / "mirror"
    monkeypatch.setenv("P2P_DB_BACKUP_MIRROR_DIR", str(mirror))

    db = TelemetryDB(str(db_path))
    db.init_schema()
    db.conn.execute(
        "INSERT INTO print_job (job_id, prompt, printer_id, printer_firmware, "
        "slicer, profile_name, outcome) VALUES ('j', 'p', 'pr', 'octoprint', "
        "'cura', 'x', 'unknown')"
    )
    for i in range(200):
        db.conn.execute(
            "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
            "VALUES (?, 'j', '2026-08-21T08:00:00+00:00', 'download')",
            (f"e{i}",),
        )
    db.conn.commit()
    db.close()

    blob = bytearray(db_path.read_bytes())
    page = int.from_bytes(blob[16:18], "big") or 4096
    blob[page * 2:page * 3] = b"\xa5" * page
    db_path.write_bytes(bytes(blob))

    broken = TelemetryDB(str(db_path))
    try:
        problems = app_module.check_database_health(broken)
    finally:
        broken.close()
    assert problems
    _wait_for_mirror()
    assert not mirror.exists() or not list(mirror.glob("telemetry.db.backup-*"))


def test_the_mirror_is_pruned_to_its_own_copy_count(live_db, tmp_path, monkeypatch):
    mirror = tmp_path / "mirror"
    monkeypatch.setenv("P2P_DB_BACKUP_MIRROR_DIR", str(mirror))
    monkeypatch.setenv("P2P_DB_BACKUP_MIRROR_COPIES", "2")

    for _ in range(3):
        app_module.check_database_health(live_db)
        _wait_for_mirror()
        time.sleep(1.1)  # the snapshot stamp has one-second resolution

    assert len(list(mirror.glob("telemetry.db.backup-*"))) == 2


# ── Rotation and cadence configuration ──────────────────────────────────────

def test_local_copy_count_is_configurable(live_db, tmp_path, monkeypatch):
    monkeypatch.setenv("P2P_DB_BACKUP_COPIES", "2")
    for _ in range(3):
        app_module.check_database_health(live_db)
        time.sleep(1.1)
    assert len(list(tmp_path.glob("telemetry.db.backup-*"))) == 2


def test_backup_interval_parses_and_disables():
    assert app_module.backup_interval_s({"P2P_DB_BACKUP_INTERVAL_MIN": "360"}) == 360 * 60
    assert app_module.backup_interval_s({"P2P_DB_BACKUP_INTERVAL_MIN": "0"}) is None
    assert app_module.backup_interval_s({"P2P_DB_BACKUP_INTERVAL_MIN": "junk"}) == 360 * 60
    assert app_module.backup_interval_s({}) == 360 * 60


# ── Manual flash ─────────────────────────────────────────────────────────────

def test_manual_backup_endpoint_takes_a_snapshot(live_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("P2P_DB_BACKUP_MIRROR_DIR", raising=False)
    live_db.close()

    client = TestClient(app_module.app)
    before = len(list(tmp_path.glob("telemetry.db.backup-*")))
    resp = client.post("/system/database/backup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert len(list(tmp_path.glob("telemetry.db.backup-*"))) == before + 1
