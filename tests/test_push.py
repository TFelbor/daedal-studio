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

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from starlette.testclient import TestClient

from pythonsrc.telemetry import db as db_module
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import JOB_EVENT_KINDS, JobEvent, PrintJob
from server import push
from server.app import app
from server.config_store import CONFIG_KEYS, INTERNAL_CONFIG_KEYS


@pytest.fixture
def client():
    return TestClient(app)

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
def awaiting_job():
    """A job whose printer has finished and whose outcome nobody has confirmed.

    Built, not inserted: the tests below choose the database and some of them move
    `completed_at` first, which is the whole subject of the backlog guard.
    """
    return PrintJob(
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


@pytest.fixture
def push_env(isolated_db_url, monkeypatch):
    """An isolated database with both schemas, and the store the server would use.

    `TelemetryDB.init_schema()` deliberately does not create `app_config` — the config
    store owns that table and creates it itself — so a test that touches both has to
    ask for both.
    """
    from server.config_store import ConfigStore

    monkeypatch.setenv("DS_DATABASE_URL", isolated_db_url)
    db = TelemetryDB(isolated_db_url)
    db.init_schema()
    store = ConfigStore(isolated_db_url)
    store.init_schema()
    yield db, store
    db.close()


# ── The VAPID keypair ────────────────────────────────────────────────────────


def test_a_generated_keypair_is_the_two_shapes_web_push_asks_for():
    public, private = push.generate_vapid_keypair()

    point = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    assert len(point) == 65 and point[0] == 0x04, (
        "applicationServerKey is the uncompressed P-256 point, 0x04 || X || Y"
    )
    scalar = base64.urlsafe_b64decode(private + "=" * (-len(private) % 4))
    assert len(scalar) == 32, "py_vapid.Vapid.from_string reads a 32-octet raw key"
    assert "=" not in public and "=" not in private, "web push is base64url, unpadded"


def test_the_private_key_signs_for_the_public_one():
    """The pair has to be a pair: py-vapid is what will sign with it."""
    from py_vapid import Vapid

    public, private = push.generate_vapid_keypair()
    vapid = Vapid.from_string(private_key=private)
    derived = base64.urlsafe_b64encode(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).rstrip(b"=").decode()
    assert derived == public


def test_the_keypair_is_generated_once_and_then_read(push_env):
    _, store = push_env
    first = push.ensure_vapid_keys(store)
    assert push.ensure_vapid_keys(store) == first
    assert store.get("VAPID_PUBLIC_KEY") == first[0]
    assert store.get("VAPID_PRIVATE_KEY") == first[1]


def test_half_a_keypair_is_replaced_rather_than_completed(push_env):
    """A public key with no private key is an identity this server cannot sign for."""
    _, store = push_env
    public, _ = push.ensure_vapid_keys(store)
    store.delete("VAPID_PRIVATE_KEY")

    new_public, new_private = push.ensure_vapid_keys(store)
    assert new_public != public
    assert new_private
    assert store.get("VAPID_PUBLIC_KEY") == new_public


def test_the_subject_falls_back_to_a_placeholder(push_env):
    """A missing `sub` claim is refused by every push service; a placeholder is not."""
    _, store = push_env
    assert push.vapid_subject(store) == push.DEFAULT_VAPID_SUBJECT
    store.set("VAPID_SUBJECT", "mailto:someone@example.com")
    assert push.vapid_subject(store) == "mailto:someone@example.com"


# ── The keys the HTTP surface must not carry ─────────────────────────────────


def test_the_vapid_keys_are_internal_config_keys():
    """Internal is what keeps them off `GET /config`, `POST /config` and `/reveal`."""
    assert "VAPID_PRIVATE_KEY" in INTERNAL_CONFIG_KEYS
    assert "VAPID_PUBLIC_KEY" in INTERNAL_CONFIG_KEYS
    assert "VAPID_SUBJECT" not in INTERNAL_CONFIG_KEYS, (
        "the contact address is the one push value a person may set"
    )


def test_the_key_names_match_the_store():
    """`server/push.py` names them and `config_store` declares them; one typo apart."""
    for name in (push.VAPID_PUBLIC_KEY, push.VAPID_PRIVATE_KEY, push.VAPID_SUBJECT):
        assert name in CONFIG_KEYS


def test_get_config_does_not_carry_the_private_key(client, push_env):
    _, store = push_env
    _, private = push.ensure_vapid_keys(store)

    body = client.get("/config").json()
    assert "VAPID_PRIVATE_KEY" not in body
    assert "VAPID_PUBLIC_KEY" not in body
    assert private not in json.dumps(body)


def test_the_private_key_cannot_be_written_or_revealed(client, push_env):
    assert client.post("/config", json={"key": "VAPID_PRIVATE_KEY", "value": "x"}).status_code == 400
    assert client.get("/config/VAPID_PRIVATE_KEY/reveal").status_code == 400
    assert client.delete("/config/VAPID_PRIVATE_KEY").status_code == 400


# ── The three routes ─────────────────────────────────────────────────────────


SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "BPublicKeyBase64Url", "auth": "AuthSecret"},
}


def test_the_public_key_route_answers_and_is_stable(client, push_env):
    first = client.get("/push/vapid-public-key")
    assert first.status_code == 200
    key = first.json()["public_key"]
    assert key
    assert client.get("/push/vapid-public-key").json()["public_key"] == key


def test_subscribing_stores_the_device(client, push_env):
    db, _ = push_env
    response = client.post("/push/subscriptions", json=SUBSCRIPTION)
    assert response.status_code == 201
    assert response.json()["subscriptions"] == 1

    rows = db.get_push_subscriptions()
    assert rows[0]["endpoint"] == SUBSCRIPTION["endpoint"]
    assert rows[0]["p256dh"] == "BPublicKeyBase64Url"
    assert rows[0]["user_agent"], "the user agent is what makes a row recognisable"


def test_subscribing_twice_is_one_device(client, push_env):
    db, _ = push_env
    client.post("/push/subscriptions", json=SUBSCRIPTION)
    second = client.post("/push/subscriptions", json=SUBSCRIPTION)
    assert second.json()["subscriptions"] == 1
    assert len(db.get_push_subscriptions()) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example/insecure",
        "file:///etc/passwd",
        "not-a-url",
        "https://",
    ],
)
def test_an_endpoint_that_no_push_service_issued_is_refused(client, push_env, endpoint):
    """This value is where the server will POST. A typo now is a silent failure later."""
    response = client.post(
        "/push/subscriptions", json={**SUBSCRIPTION, "endpoint": endpoint}
    )
    assert response.status_code == 422


def test_unsubscribing_forgets_the_device(client, push_env):
    db, _ = push_env
    client.post("/push/subscriptions", json=SUBSCRIPTION)

    response = client.request(
        "DELETE", "/push/subscriptions", json={"endpoint": SUBSCRIPTION["endpoint"]}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "unsubscribed", "removed": 1, "subscriptions": 0}
    assert db.get_push_subscriptions() == []


def test_unsubscribing_something_already_gone_is_a_success(client, push_env):
    """The page calls this to turn a switch off; a 404 would leave it stuck on."""
    response = client.request(
        "DELETE", "/push/subscriptions", json={"endpoint": SUBSCRIPTION["endpoint"]}
    )
    assert response.status_code == 200
    assert response.json()["removed"] == 0


def test_the_push_routes_are_authenticated_by_writing_nothing():
    """No `@public`, so `tests/test_api_auth.py`'s matrix already covers them.

    Said here as well because it is the property that matters: a subscription is an
    address this server will POST to, so an open `POST /push/subscriptions` would let
    anyone who can reach the port aim it wherever they liked.
    """
    from server.app import app as fastapi_app
    from server.auth import PUBLIC_MARKER

    for route in fastapi_app.router.routes:
        if getattr(route, "path", "").startswith("/push"):
            assert not getattr(getattr(route, "endpoint", None), PUBLIC_MARKER, False)


# ── The reconciler ───────────────────────────────────────────────────────────


class FakeSender:
    """A stand-in for `webpush_async` that records what it was asked to deliver.

    A class rather than a lambda because the tests need to see the VAPID claims and
    the payload: what a device is told is half of what this feature promises.
    """

    def __init__(self, fail_with: dict[str, int] | None = None):
        self.calls: list[dict] = []
        self.fail_with = fail_with or {}

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        endpoint = kwargs["subscription_info"]["endpoint"]
        status = self.fail_with.get(endpoint)
        if status:
            from pywebpush import WebPushException

            class _Response:
                def __init__(self, status):
                    self.status = status

            raise WebPushException(f"Push failed: {status}", response=_Response(status))
        return None

    @property
    def endpoints(self) -> list[str]:
        return [call["subscription_info"]["endpoint"] for call in self.calls]

    @property
    def payloads(self) -> list[dict]:
        return [json.loads(call["data"]) for call in self.calls]


def test_the_payload_points_at_the_app_route_not_the_api(awaiting_job):
    """`/jobs/<id>` is JSON. Opening it in the installed app is opening a document."""
    payload = push.notification_payload(awaiting_job)
    assert payload["url"] == f"/dashboard/{awaiting_job.job_id}"
    assert "/jobs/" not in payload["url"]
    assert payload["body"] == awaiting_job.prompt, "a notification says which print"
    assert payload["tag"] == f"job-{awaiting_job.job_id}"


def test_a_job_with_no_label_still_says_something(isolated_db):
    job = PrintJob(
        job_id="job-blank", prompt="", printer_id="p", printer_firmware="octoprint",
        slicer="Cura", profile_name="Standard",
        started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
        outcome="awaiting_verdict",
    )
    assert push.notification_payload(job)["body"]


@pytest.mark.asyncio
async def test_a_finished_job_is_notified_once(push_env, awaiting_job):
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)
    sender = FakeSender()

    first = await push.reconcile_once(db, store, sender=sender)
    assert first["notified"] == [awaiting_job.job_id]
    assert sender.endpoints == ["https://push.example/aaa"]
    assert sender.payloads[0]["job_id"] == awaiting_job.job_id
    assert [e.kind for e in db.get_job_events(awaiting_job.job_id)] == ["push_sent"]

    second = await push.reconcile_once(db, store, sender=sender)
    assert second["notified"] == []
    assert second["already_sent"] == 1
    assert len(sender.calls) == 1, "the second tick must not send again"


@pytest.mark.asyncio
async def test_a_restart_does_not_notify_again(push_env, awaiting_job):
    """The dedup key is in the database, which is the whole reason it is there."""
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)

    await push.reconcile_once(db, store, sender=FakeSender())

    fresh_db = TelemetryDB(db.dsn)
    fresh_sender = FakeSender()
    result = await push.reconcile_once(fresh_db, store, sender=fresh_sender)
    assert result["notified"] == []
    assert fresh_sender.calls == []


@pytest.mark.asyncio
async def test_every_subscribed_device_is_told(push_env, awaiting_job):
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    db.upsert_push_subscription("https://push.example/bbb", "key-b", "auth-b")
    push.ensure_vapid_keys(store)
    sender = FakeSender()

    await push.reconcile_once(db, store, sender=sender)
    assert sorted(sender.endpoints) == ["https://push.example/aaa", "https://push.example/bbb"]
    assert db.get_job_events(awaiting_job.job_id, kind="push_sent")[0].detail["sent"] == 2


@pytest.mark.asyncio
async def test_a_backlog_is_not_announced(push_env, awaiting_job, monkeypatch):
    """The first tick after this ships must not notify for last month's prints."""
    db, store = push_env
    awaiting_job.completed_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)
    sender = FakeSender()

    result = await push.reconcile_once(db, store, sender=sender)
    assert result["skipped_old"] == 1
    assert sender.calls == []
    assert db.get_job_events(awaiting_job.job_id, kind="push_sent") == []


@pytest.mark.asyncio
async def test_the_backlog_window_is_configurable(push_env, awaiting_job, monkeypatch):
    db, store = push_env
    awaiting_job.completed_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)
    monkeypatch.setenv(push.PUSH_MAX_AGE_ENV, str(30 * 24 * 3600))

    result = await push.reconcile_once(db, store, sender=FakeSender())
    assert result["notified"] == [awaiting_job.job_id]


@pytest.mark.asyncio
async def test_a_job_nobody_subscribed_for_is_not_recorded_as_sent(push_env, awaiting_job):
    """Otherwise the first device to subscribe misses the print it subscribed for."""
    db, store = push_env
    db.insert_job(awaiting_job)
    push.ensure_vapid_keys(store)

    result = await push.reconcile_once(db, store, sender=FakeSender())
    assert result["notified"] == []
    assert db.get_job_events(awaiting_job.job_id, kind="push_sent") == []


@pytest.mark.asyncio
async def test_a_gone_subscription_is_forgotten(push_env, awaiting_job):
    """404 and 410 are the push service saying the device is gone for good."""
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/dead", "key-a", "auth-a")
    db.upsert_push_subscription("https://push.example/live", "key-b", "auth-b")
    push.ensure_vapid_keys(store)
    sender = FakeSender(fail_with={"https://push.example/dead": 410})

    await push.reconcile_once(db, store, sender=sender)

    assert [row["endpoint"] for row in db.get_push_subscriptions()] == [
        "https://push.example/live"
    ]
    detail = db.get_job_events(awaiting_job.job_id, kind="push_sent")[0].detail
    assert detail == {"sent": 1, "failed": 1, "removed": 1}


@pytest.mark.asyncio
async def test_a_bad_afternoon_keeps_the_subscription(push_env, awaiting_job):
    """A 502 is the push service failing, not the device disappearing."""
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)
    sender = FakeSender(fail_with={"https://push.example/aaa": 502})

    await push.reconcile_once(db, store, sender=sender)
    assert len(db.get_push_subscriptions()) == 1


@pytest.mark.asyncio
async def test_a_job_somebody_has_already_answered_is_not_notified(push_env, awaiting_job):
    """`get_jobs_awaiting_verdict` is the only source, so an answered job is out."""
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    push.ensure_vapid_keys(store)
    db.update_job_outcome_verdict(awaiting_job.job_id, "success", source="user")

    result = await push.reconcile_once(db, store, sender=FakeSender())
    assert result["considered"] == 0
    assert result["notified"] == []


@pytest.mark.asyncio
async def test_the_claims_carry_a_contact_and_the_key_signs_them(push_env, awaiting_job):
    db, store = push_env
    db.insert_job(awaiting_job)
    db.upsert_push_subscription("https://push.example/aaa", "key-a", "auth-a")
    _, private = push.ensure_vapid_keys(store)
    store.set("VAPID_SUBJECT", "mailto:someone@example.com")
    sender = FakeSender()

    await push.reconcile_once(db, store, sender=sender)
    call = sender.calls[0]
    assert call["vapid_claims"] == {"sub": "mailto:someone@example.com"}
    assert call["vapid_private_key"] == private
    assert call["ttl"] == push.PUSH_TTL_S


# ── The loop's knobs ─────────────────────────────────────────────────────────


def test_the_reconciler_can_be_switched_off(monkeypatch):
    """The same `0 disables` shape as `$DS_DB_HEALTH_INTERVAL_S`."""
    monkeypatch.setenv(push.PUSH_INTERVAL_ENV, "0")
    assert push.push_interval_s() is None
    monkeypatch.setenv(push.PUSH_INTERVAL_ENV, "5")
    assert push.push_interval_s() == 5.0
    monkeypatch.delenv(push.PUSH_INTERVAL_ENV)
    assert push.push_interval_s() == push.DEFAULT_PUSH_INTERVAL_S


def test_an_unreadable_interval_falls_back(monkeypatch, caplog):
    monkeypatch.setenv(push.PUSH_INTERVAL_ENV, "soon")
    assert push.push_interval_s() == push.DEFAULT_PUSH_INTERVAL_S


# ── The browser half ─────────────────────────────────────────────────────────
#
# There is no frontend test runner in this repository, so the claims the worker and the
# page make are asserted against the source, the way `tests/test_pwa_shell.py` does it.

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_WORKER = REPO_ROOT / "web" / "src" / "sw.ts"
PUSH_API = REPO_ROOT / "web" / "src" / "api" / "push.ts"
SETTINGS_PAGE = REPO_ROOT / "web" / "src" / "pages" / "PrinterSetup.tsx"
VITE_CONFIG = REPO_ROOT / "web" / "vite.config.ts"


def _executable_lines(path: Path) -> str:
    """The file with its comment lines dropped — prose is not a promise."""
    out = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "/*", "//")):
            continue
        out.append(line)
    return "\n".join(out)


def test_the_worker_handles_a_push_and_a_tap():
    source = SERVICE_WORKER.read_text()
    assert "addEventListener('push'" in source
    assert "addEventListener('notificationclick'" in source
    assert "showNotification(" in source


def test_the_worker_shows_something_for_every_push():
    """`userVisibleOnly: true` is the only subscription a browser grants.

    A push that ends without a notification is one Chrome shows its own message for,
    and after a few of those it revokes the permission — so the handler must have no
    path that returns without showing one.
    """
    source = _executable_lines(SERVICE_WORKER)
    handler = source.split("addEventListener('push'", 1)[1].split("addEventListener(", 1)[0]
    assert "catch" in handler, "a payload that will not parse still has to show something"
    assert "??" in handler, "the title and body need defaults, not a bail-out"
    assert "return" not in handler, "no early exit: every push owes a visible notification"


def test_the_tap_opens_the_app_route_and_not_the_api():
    """`/jobs/<id>` is JSON; opening it in the installed app opens a document."""
    source = _executable_lines(SERVICE_WORKER)
    assert "/jobs" not in source, "the worker has grown a rule about a job route"
    assert "openWindow(" in source


def test_the_worker_still_asks_the_api_for_nothing():
    """The payload is decrypted by the browser. The worker holds no token and needs none."""
    source = _executable_lines(SERVICE_WORKER)
    assert "/push" not in source, (
        "the worker must not call the push API: it cannot authenticate, and the "
        "notification's contents arrive on the event"
    )
    assert "Authorization" not in source


def test_push_is_a_proxied_api_prefix():
    """Unproxied, `npm run dev` answers `/push/...` with index.html and the parse throws."""
    assert "'/push'" in VITE_CONFIG.read_text()


def test_the_page_never_holds_a_key_of_its_own():
    """The application server key is fetched, not embedded — rotating it is a server act."""
    source = PUSH_API.read_text()
    assert "/push/vapid-public-key" in source
    assert "applicationServerKey" in source
    assert "userVisibleOnly: true" in source


def test_the_permission_prompt_is_behind_a_click():
    """Safari refuses it outside a gesture, and an unprompted ask is held against the origin."""
    assert "requestPermission" in PUSH_API.read_text()
    assert "requestPermission" not in SETTINGS_PAGE.read_text(), (
        "asking belongs in api/push.ts, reached from the button below"
    )
    page = SETTINGS_PAGE.read_text()
    assert "enablePush" in page and "onClick" in page


def test_settings_says_what_ios_needs():
    """A button that cannot work in a Safari tab is worse than no button."""
    page = SETTINGS_PAGE.read_text()
    assert "Home Screen" in page
    assert "settings-notifications" in page, "the section has to be in the index too"
