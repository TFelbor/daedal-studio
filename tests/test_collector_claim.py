"""Two collectors must never both write telemetry for the same job."""

import asyncio
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


def test_claim_failure_falls_back_to_collecting(memory_db):
    """If arbitration is unavailable, collect rather than silently drop telemetry."""

    class BrokenDB:
        def try_claim_collector(self, *a, **k):
            raise RuntimeError("no such table: telemetry_collector_claim")

    claim = CollectorClaim(BrokenDB(), JOB_ID, "standalone")
    assert claim.may_write(now=0.0) is True
