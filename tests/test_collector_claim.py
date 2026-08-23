"""Two collectors must never both write telemetry for the same job."""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from pythonsrc.telemetry.collector_claim import CollectorClaim
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
from pythonsrc.telemetry.schema import PrintJob

JOB_ID = "claim-job-1"

CURRENT_PAYLOAD = {
    "currentZ": 2.0,
    "temps": [{"tool0": {"actual": 200.0, "target": 205.0}, "bed": {"actual": 60.0, "target": 60.0}}],
}


@pytest.fixture
def memory_db():
    db = TelemetryDB(":memory:")
    db.init_schema()
    db.insert_job(
        PrintJob(
            job_id=JOB_ID,
            prompt="a vase",
            printer_id="octoprint-1",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="standard",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome="unknown",
        )
    )
    yield db
    db.close()


@pytest.mark.asyncio
async def test_second_collector_does_not_duplicate_samples(memory_db):
    """The API server and the pipeline both collecting must yield one row per update."""
    server_side = OctoPrintCollector("localhost", 5000, "key", JOB_ID, memory_db)
    pipeline_side = OctoPrintCollector("localhost", 5000, "key", JOB_ID, memory_db)

    for _ in range(5):
        await server_side._on_current(dict(CURRENT_PAYLOAD))
        await pipeline_side._on_current(dict(CURRENT_PAYLOAD))

    assert len(memory_db.get_samples(JOB_ID)) == 5


@pytest.mark.asyncio
async def test_standby_collector_starts_writing_after_owner_releases(memory_db):
    """Releasing the claim on stop() hands collection over rather than ending it."""
    first = OctoPrintCollector("localhost", 5000, "key", JOB_ID, memory_db)
    second = OctoPrintCollector("localhost", 5000, "key", JOB_ID, memory_db)

    await first._on_current(dict(CURRENT_PAYLOAD))
    await second._on_current(dict(CURRENT_PAYLOAD))
    assert len(memory_db.get_samples(JOB_ID)) == 1

    await first.stop()

    await second._on_current(dict(CURRENT_PAYLOAD))
    assert len(memory_db.get_samples(JOB_ID)) == 2


def test_claim_is_granted_to_first_caller_only(memory_db):
    a = CollectorClaim(memory_db, JOB_ID, "A")
    b = CollectorClaim(memory_db, JOB_ID, "B")

    assert a.may_write(now=0.0) is True
    assert b.may_write(now=0.0) is False
    assert memory_db.get_collector_claim(JOB_ID) == a.owner


def test_stale_claim_is_taken_over(memory_db):
    """A crashed collector's claim must not block the job forever."""
    dead = CollectorClaim(memory_db, JOB_ID, "dead")
    assert dead.may_write(now=0.0) is True

    stale = datetime.now(timezone.utc) - timedelta(seconds=600)
    with memory_db._lock:
        memory_db.conn.execute(
            "UPDATE telemetry_collector_claim SET heartbeat_at = ? WHERE job_id = ?",
            (stale.isoformat(), JOB_ID),
        )
        memory_db.conn.commit()

    live = CollectorClaim(memory_db, JOB_ID, "live")
    assert live.may_write(now=0.0) is True
    assert memory_db.get_collector_claim(JOB_ID) == live.owner


def test_owner_keeps_claim_across_heartbeats(memory_db):
    owner = CollectorClaim(memory_db, JOB_ID, "owner")
    assert owner.may_write(now=0.0) is True
    # Well past the heartbeat interval, but the same owner — still granted.
    assert owner.may_write(now=1000.0) is True
    assert memory_db.get_collector_claim(JOB_ID) == owner.owner


def test_missing_claim_table_falls_back_to_collecting(memory_db):
    """With no claim table there is no rival collector either, so collect."""

    class NoClaimTableDB:
        def try_claim_collector(self, *a, **k):
            raise RuntimeError("no such table: telemetry_collector_claim")

    claim = CollectorClaim(NoClaimTableDB(), JOB_ID, "standalone")
    assert claim.may_write(now=0.0) is True


class UnreachableDB:
    """A database that cannot be opened at all — root-owned directory, corrupt file."""

    def try_claim_collector(self, *a, **k):
        raise sqlite3.OperationalError("unable to open database file")


def test_unreachable_database_does_not_grant_a_claim(memory_db):
    """An unopenable database must not read as "arbitration unavailable".

    Failing open here told the collector it had won a claim it never took: it went on
    to insert the sample, died there instead, and the caller reported the result as a
    connection error.
    """
    claim = CollectorClaim(UnreachableDB(), JOB_ID, "server")

    assert claim.may_write(now=0.0) is False
    assert claim.may_write(now=1.0) is False
    # Nothing was claimed, so nothing is released — UnreachableDB has no release
    # method, and calling one would raise AttributeError.
    claim.release()


def test_unreachable_database_is_reported_once_and_loudly(memory_db, caplog):
    """Silence would strand a print with no telemetry and no explanation.

    One ERROR, not one per sample: telemetry arrives about every second and the cause
    does not change between them.
    """
    claim = CollectorClaim(UnreachableDB(), JOB_ID, "server")

    with caplog.at_level(logging.DEBUG, logger="pythonsrc.telemetry.collector_claim"):
        claim.may_write(now=0.0)
        claim.may_write(now=1.0)
        claim.may_write(now=2.0)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "unable to open database file" in errors[0].getMessage()
    assert JOB_ID in errors[0].getMessage()


def test_claim_is_taken_once_the_database_comes_back(memory_db):
    """A locked database is transient; a collector that gave up on it forever is not."""

    class FlakyDB:
        def __init__(self, real):
            self.real = real
            self.broken = True

        def try_claim_collector(self, *a, **k):
            if self.broken:
                raise sqlite3.OperationalError("database is locked")
            return self.real.try_claim_collector(*a, **k)

    db = FlakyDB(memory_db)
    claim = CollectorClaim(db, JOB_ID, "server")
    assert claim.may_write(now=0.0) is False

    db.broken = False
    assert claim.may_write(now=1.0) is True
    assert memory_db.get_collector_claim(JOB_ID) == claim.owner


# ── The claim is a compare-and-swap, not a read-then-write ──────────────────
#
# `try_claim_collector` reads the row, decides, then writes. Between those two steps
# another process can change what it decided about — and the write used to be a bare
# `WHERE job_id = ?`, which lands regardless. Two collectors that both saw the same
# stale claim therefore both updated it and both returned True: exactly the double
# writer this table exists to prevent, and it only becomes reachable after a collector
# has already crashed, which is when the telemetry matters most.
#
# These tests need two *connections*, not two `CollectorClaim` objects sharing one.
# The single-writer bug is a cross-process one, `TelemetryDB` serialises its own calls
# behind an instance lock, and `:memory:` cannot be shared — so the database is a file
# and each side opens it the way a separate process would.
#
# The interleaving is forced through `_dt_to_str`, which the claim path calls after it
# has read the row and settled on a decision but before its UPDATE reaches SQLite. The
# rival's entire claim runs inside that window.


@pytest.fixture
def shared_db_path(tmp_path):
    """A file-backed telemetry database with the job row already in it."""
    path = tmp_path / "telemetry.db"
    seed = TelemetryDB(str(path))
    seed.init_schema()
    seed.insert_job(
        PrintJob(
            job_id=JOB_ID,
            prompt="a vase",
            printer_id="octoprint-1",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="standard",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome="unknown",
        )
    )
    seed.close()
    return str(path)


@pytest.fixture
def connect(shared_db_path):
    """Open another connection to the same file, as another process would."""
    handles = []

    def open_one() -> TelemetryDB:
        db = TelemetryDB(shared_db_path)
        handles.append(db)
        return db

    yield open_one
    for db in handles:
        db.close()


@pytest.fixture
def rival_in_the_window(monkeypatch):
    """Let another connection act between our SELECT and our UPDATE.

    Returns a function taking the rival's action; it fires once, on the next
    serialisation of a timestamp, then gets out of the way so the rival's own database
    calls behave normally. The returned list is non-empty once it has fired, so a test
    can prove the race was actually exercised rather than silently skipped.
    """
    import pythonsrc.telemetry.db as db_module

    real = db_module._dt_to_str

    def arrange(action):
        fired = []

        def hook(value):
            if not fired:
                fired.append(True)
                action()
            return real(value)

        monkeypatch.setattr(db_module, "_dt_to_str", hook)
        return fired

    return arrange


def _make_stale(db: TelemetryDB, seconds: int = 600) -> None:
    """Backdate the claim's heartbeat so it reads as abandoned."""
    stale = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    with db._lock:
        db.conn.execute(
            "UPDATE telemetry_collector_claim SET heartbeat_at = ? WHERE job_id = ?",
            (stale.isoformat(), JOB_ID),
        )
        db.conn.commit()


def test_only_one_of_two_collectors_takes_over_a_stale_claim(connect, rival_in_the_window):
    """Both read the same abandoned claim; exactly one may end up owning it.

    Without the guard both UPDATEs succeed, both callers are told they hold the claim,
    and the job's telemetry is doubled from then on — every sample written twice, with
    nothing anywhere reporting an error.
    """
    dead_db, rival_db, late_db = connect(), connect(), connect()

    assert CollectorClaim(dead_db, JOB_ID, "dead").may_write(now=0.0) is True
    _make_stale(dead_db)

    rival = CollectorClaim(rival_db, JOB_ID, "rival")
    fired = rival_in_the_window(lambda: rival.may_write(now=0.0))

    late = CollectorClaim(late_db, JOB_ID, "late")
    assert late.may_write(now=0.0) is False, (
        "the second collector took over a claim another had already taken"
    )
    assert fired, "the rival never ran — the interleaving was not exercised"
    assert late_db.get_collector_claim(JOB_ID) == rival.owner


def test_a_heartbeat_cannot_take_back_a_claim_another_collector_won(connect, rival_in_the_window):
    """A heartbeat must confirm ownership, not assert it.

    The owner's SELECT sees its own claim, a rival takes over inside the window — after
    a stall long enough to look like a crash — and the heartbeat UPDATE lands last.
    Unguarded it silently restores the old owner, leaving two processes each convinced
    it is the single writer.
    """
    owner_db, rival_db = connect(), connect()

    owner = CollectorClaim(owner_db, JOB_ID, "owner")
    assert owner.may_write(now=0.0) is True

    rival = CollectorClaim(rival_db, JOB_ID, "rival")

    def take_over():
        _make_stale(rival_db)
        rival.may_write(now=0.0)

    fired = rival_in_the_window(take_over)

    # Past the heartbeat interval, so this re-consults the database rather than
    # trusting the cached grant.
    assert owner.may_write(now=1000.0) is False
    assert fired
    assert owner_db.get_collector_claim(JOB_ID) == rival.owner


def test_the_winner_of_a_contested_takeover_keeps_writing(connect, rival_in_the_window):
    """A contested takeover must leave a working collector behind, not a stalemate.

    Declining is the safe answer for the loser, but a guard that also locked the winner
    out would leave the print with no telemetry at all — worse than the duplication it
    replaced.
    """
    dead_db, rival_db, late_db = connect(), connect(), connect()

    assert CollectorClaim(dead_db, JOB_ID, "dead").may_write(now=0.0) is True
    _make_stale(dead_db)

    rival = CollectorClaim(rival_db, JOB_ID, "rival")
    rival_in_the_window(lambda: rival.may_write(now=0.0))

    assert CollectorClaim(late_db, JOB_ID, "late").may_write(now=0.0) is False

    assert rival.may_write(now=1000.0) is True
    assert rival.may_write(now=2000.0) is True
    assert late_db.get_collector_claim(JOB_ID) == rival.owner


@pytest.mark.asyncio
async def test_the_loser_of_a_contested_takeover_writes_no_samples(connect, rival_in_the_window):
    """The point of the guard, measured where it matters: rows in the table.

    A collector that loses the compare-and-swap must decline at `insert_sample`, not
    merely log about it — the whole mechanism exists so the dataset has one row per
    printer update rather than two.
    """
    dead_db, rival_db, late_db = connect(), connect(), connect()

    assert CollectorClaim(dead_db, JOB_ID, "dead").may_write(now=0.0) is True
    _make_stale(dead_db)

    rival = CollectorClaim(rival_db, JOB_ID, "rival")
    rival_in_the_window(lambda: rival.may_write(now=0.0))

    loser = OctoPrintCollector("localhost", 5000, "key", JOB_ID, late_db)
    for _ in range(3):
        await loser._on_current(dict(CURRENT_PAYLOAD))

    assert late_db.get_samples(JOB_ID) == []
