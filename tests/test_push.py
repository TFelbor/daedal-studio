"""Web push for a job reaching `awaiting_verdict`.

The one thing this feature has to get right is **once**. A print finishes, the row
goes to `awaiting_verdict`, and the person who started it is somewhere else — that is
the whole reason a notification exists. Sending it twice, or once per server tick, or
once again after a restart, turns the one useful notification this product sends into
the kind people switch off.

Nothing hooks the three writers that move a job into `awaiting_verdict`
(`server/app.py` twice and `pythonsrc/telemetry/octoprint_collector.py`, which never
touches the broadcaster). A reconciler reads the state instead, and `push_sent` in
`job_event` is the dedup key — a fact in the database rather than a flag in one
process's memory, because a restart between the send and the next tick would otherwise
notify again.

The halves that need a real device — that Chrome on Android renders it, that iOS
delivers it in the installed standalone app — are on the pull request as a manual
checklist. What is asserted here is everything that is decidable without one: the
table, the keys, the routes, the reconciler's arithmetic, and the service worker's
two new handlers.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pythonsrc.telemetry import db as db_module
from pythonsrc.telemetry.schema import JOB_EVENT_KINDS, JobEvent, PrintJob

# ── The table ────────────────────────────────────────────────────────────────


def test_the_subscription_table_is_one_of_the_modules_own():
    """In `TELEMETRY_TABLES`, so `init_schema` creates it and `health_check` misses it.

    A table the schema renders but the table list does not name is a table a fresh
    database gets and an existing one never hears about, because `health_check` is
    what reports a missing one and `check_database_health` is what then runs the DDL.
    """
    assert "push_subscription" in db_module.TELEMETRY_TABLES


def test_the_subscription_is_not_a_fact_about_a_job():
    """No foreign key and no job column: it outlives every job it is told about."""
    ddl = next(s for s in db_module.schema_statements() if "CREATE TABLE IF NOT EXISTS push_subscription" in s)
    assert "FOREIGN KEY" not in ddl
    assert "job_id" not in ddl
    assert "endpoint TEXT PRIMARY KEY" in ddl, (
        "the endpoint is the identity of a subscription everywhere; without the "
        "primary key the upsert has nothing to conflict on"
    )


def test_push_sent_is_a_recognised_event_kind():
    assert "push_sent" in JOB_EVENT_KINDS
    JobEvent(
        event_id="e1",
        job_id="j1",
        occurred_at=datetime.now(timezone.utc),
        kind="push_sent",
    )


# ── Storing a subscription ───────────────────────────────────────────────────


def test_a_subscription_round_trips(isolated_db):
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a", "Chrome")
    rows = isolated_db.get_push_subscriptions()
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "https://push.example/aaa"
    assert rows[0]["p256dh"] == "key-a"
    assert rows[0]["auth"] == "auth-a"
    assert rows[0]["user_agent"] == "Chrome"
    assert rows[0]["created_at"] is not None


def test_the_same_device_subscribing_again_is_one_row(isolated_db):
    """A browser hands the page the subscription it already has, on every load."""
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-b", "auth-b", "Firefox")

    rows = isolated_db.get_push_subscriptions()
    assert len(rows) == 1
    assert (rows[0]["p256dh"], rows[0]["auth"]) == ("key-b", "auth-b")
    assert rows[0]["user_agent"] == "Firefox"


def test_re_subscribing_keeps_the_day_the_device_first_asked(isolated_db):
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    first = isolated_db.get_push_subscriptions()[0]["created_at"]

    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-b", "auth-b")
    again = isolated_db.get_push_subscriptions()[0]

    assert again["created_at"] == first
    assert again["last_seen_at"] >= first


def test_a_subscription_can_be_forgotten(isolated_db):
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    assert isolated_db.delete_push_subscription("https://push.example/aaa") == 1
    assert isolated_db.get_push_subscriptions() == []
    assert isolated_db.delete_push_subscription("https://push.example/aaa") == 0


def test_two_devices_are_two_rows(isolated_db):
    isolated_db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    isolated_db.upsert_push_subscription("https://push.example/bbb", "key-b", "auth-b")
    assert {row["endpoint"] for row in isolated_db.get_push_subscriptions()} == {
        "https://push.example/aaa",
        "https://push.example/bbb",
    }


# ── Fixtures shared by the reconciler tests below ────────────────────────────


@pytest.fixture
def awaiting_job(isolated_db):
    """A job whose printer has finished and whose outcome nobody has confirmed."""
    job = PrintJob(
        job_id="job-awaiting",
        prompt="deck box · 100 double-sleeved standard cards",
        printer_id="test_printer_1",
        printer_firmware="octoprint",
        slicer="Cura",
        profile_name="Standard",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        outcome="awaiting_verdict",
    )
    isolated_db.insert_job(job)
    return job
