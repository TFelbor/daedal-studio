"""Guards on detecting and surviving telemetry database corruption.

The telemetry database went corrupt and nothing noticed. `telemetry_sample`'s
b-tree ended up with two pages referenced twice —

    Tree 4 page 4 cell 0: 2nd reference to page 44

— and the only symptom was that querying samples began answering `database disk
image is malformed`. By then 346 rows were unreadable and their pages had been
reused, so `.recover` salvaged none of them. There was no integrity check anywhere
in the codebase and no backup, so there was neither a warning nor anything to
restore from.

`synchronous` was already FULL and there was no hot journal, so it was not a crash
mid-write. The database is bind-mounted into the containers, and on macOS those run
in a Linux VM — host and container are two machines sharing a file, and SQLite does
not support that for concurrent writers. Pragmas cannot fix that; these tests cover
the part that can be fixed, which is noticing and having a copy.
"""

import sqlite3
from pathlib import Path

import pytest

from pythonsrc.telemetry.db import TelemetryDB


def _insert_stub_job(database: TelemetryDB, job_id: str = "job-1") -> None:
    """Foreign keys are enforced, so event rows need a parent job to exist."""
    database.conn.execute(
        "INSERT INTO print_job (job_id, prompt, printer_id, printer_firmware, "
        "slicer, profile_name, outcome) VALUES (?, 'p', 'pr', 'octoprint', 'cura', "
        "'ender3', 'unknown')",
        (job_id,),
    )
    database.conn.commit()


@pytest.fixture
def db(tmp_path):
    database = TelemetryDB(db_path=str(tmp_path / "telemetry.db"))
    database.init_schema()
    _insert_stub_job(database)
    yield database
    database.close()


def _corrupt(path: Path) -> None:
    """Scribble over a b-tree page so SQLite reports the file as malformed.

    Page 1 is the schema; the pages after it hold table data. Writing garbage into
    the middle of one is the closest reproduction of the real damage that does not
    require two racing processes.
    """
    blob = bytearray(path.read_bytes())
    page_size = int.from_bytes(blob[16:18], "big") or 4096
    start = page_size * 2  # third page: past the header and the schema
    blob[start:start + page_size] = b"\xa5" * page_size
    path.write_bytes(bytes(blob))


# ── Pragmas ──────────────────────────────────────────────────────────────────


def test_a_busy_timeout_is_set_so_a_concurrent_writer_waits(db):
    assert db.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000


def test_writes_are_flushed_to_disk_on_commit(db):
    """synchronous=FULL. Write volume is a sample every couple of seconds."""
    assert db.conn.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_wal_is_deliberately_not_enabled(db):
    """WAL is persisted in the file and needs shared memory between all writers.

    Switching it on from the host would leave the pipeline container — a different
    machine, as far as VirtioFS is concerned — unable to open the database at all,
    rather than merely unable to lock it properly.
    """
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"


# ── Detection ────────────────────────────────────────────────────────────────


def test_a_sound_database_reports_no_problems(db):
    assert db.integrity_check() == []


def test_a_corrupt_database_is_reported_rather_than_raising(tmp_path):
    """The caller's question is "is this usable"; an unreadable file answers it."""
    path = tmp_path / "telemetry.db"
    sound = TelemetryDB(db_path=str(path))
    sound.init_schema()
    _insert_stub_job(sound)
    for i in range(200):
        sound.conn.execute(
            "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
            "VALUES (?, ?, ?, ?)",
            (f"e{i}", "job-1", "2026-08-21T08:00:00+00:00", "download"),
        )
    sound.conn.commit()
    sound.close()

    _corrupt(path)

    broken = TelemetryDB(db_path=str(path))
    try:
        problems = broken.integrity_check()
    finally:
        broken.close()

    assert problems, "corruption must be reported, not silently passed"
    assert all(isinstance(p, str) for p in problems)


# ── Backup ───────────────────────────────────────────────────────────────────


def test_a_backup_is_a_usable_database_with_the_same_rows(db, tmp_path):
    db.conn.execute(
        "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
        "VALUES ('e1', 'job-1', '2026-08-21T08:00:00+00:00', 'download')"
    )
    db.conn.commit()

    target = db.backup_to(tmp_path / "snapshots" / "telemetry.db.backup-1")

    assert target.exists()
    restored = sqlite3.connect(str(target))
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT COUNT(*) FROM job_event").fetchone()[0] == 1
    finally:
        restored.close()


def test_backup_refuses_rather_than_hanging_on_an_open_transaction(db, tmp_path):
    """The copy would wait for a lock only the caller can release — forever.

    Found by this test hanging: `Connection.backup` retries on a busy source with no
    upper bound, and a write transaction on the *same* connection is a lock that will
    never clear on its own.
    """
    db.conn.execute("BEGIN")
    db.conn.execute(
        "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
        "VALUES ('uncommitted', 'job-1', '2026-08-21T08:00:00+00:00', 'download')"
    )
    try:
        with pytest.raises(RuntimeError, match="open transaction"):
            db.backup_to(tmp_path / "mid-transaction.db")
    finally:
        db.conn.rollback()


def test_a_concurrent_writer_does_not_spoil_the_snapshot(db, tmp_path):
    """The case the online API exists for: another connection mid-write.

    Copying the file with `cp` here is one of the ways to *produce* a corrupt
    database. The snapshot must be sound and must hold committed data only.
    """
    db.conn.execute(
        "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
        "VALUES ('committed', 'job-1', '2026-08-21T08:00:00+00:00', 'download')"
    )
    db.conn.commit()

    other = sqlite3.connect(db.db_path, timeout=5.0)
    try:
        other.execute("BEGIN")
        other.execute(
            "INSERT INTO job_event (event_id, job_id, occurred_at, kind) "
            "VALUES ('in-flight', 'job-1', '2026-08-21T08:00:01+00:00', 'download')"
        )

        target = db.backup_to(tmp_path / "concurrent.db")
        other.rollback()
    finally:
        other.close()

    restored = sqlite3.connect(str(target))
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        kinds = {r[0] for r in restored.execute("SELECT event_id FROM job_event")}
        assert kinds == {"committed"}
    finally:
        restored.close()
