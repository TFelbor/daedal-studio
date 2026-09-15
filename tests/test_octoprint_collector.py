import pytest
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone
import json

import aiohttp

from pythonsrc.telemetry.db import OperationalError
from pythonsrc.telemetry.schema import PrintJob
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector

@pytest.fixture
def memory_db(isolated_db):
    db = isolated_db
    job = PrintJob(
        job_id="test-job-123",
        prompt="test prompt",
        printer_id="octoprint-1",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="standard",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    db.insert_job(job)
    yield db
    db.close()

class FakeWebSocket:
    """Minimal stand-in for an aiohttp SockJS WebSocket connection."""

    def __init__(self, frames, on_send=None):
        self._frames = list(frames)
        self.sent = []
        self._on_send = on_send

    async def send_str(self, data):
        self.sent.append(data)
        if self._on_send:
            self._on_send(data)

    def __aiter__(self):
        async def gen():
            for frame in self._frames:
                await asyncio.sleep(0)
                yield frame
            # Keep the connection "open" so the collector does not spin on reconnect.
            while True:
                await asyncio.sleep(0.01)

        return gen()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def text_frame(data):
    """Build a TEXT WSMessage carrying a raw SockJS frame."""
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=data)


class FakeLoginResponse:
    """Response for OctoPrint's passive-login endpoint."""

    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeClientSession:
    """aiohttp.ClientSession stand-in scripting ws_connect and the passive login."""

    def __init__(self, ws=None, error=None, on_connect=None, login_body=None, login_status=200):
        self._ws = ws
        self._error = error
        self._on_connect = on_connect
        self._login_body = login_body if login_body is not None else {"name": "_api", "session": "sess-123"}
        self._login_status = login_status
        self.login_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        self.login_calls.append((url, kwargs))
        return FakeLoginResponse(self._login_body, self._login_status)

    def ws_connect(self, url, **kwargs):
        if self._on_connect:
            self._on_connect(url)
        if self._error:
            raise self._error
        return self._ws


@pytest.fixture
def patch_session():
    """Patch the collector's aiohttp.ClientSession with a scripted fake."""

    def _install(session_factory):
        return patch(
            "pythonsrc.telemetry.octoprint_collector.aiohttp.ClientSession",
            side_effect=lambda *a, **k: session_factory(),
        )

    return _install

@pytest.mark.asyncio
async def test_octoprint_collector_inserts_samples_from_current(memory_db):
    # Test _on_current directly to assert 10 samples
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)

    payload = {
        "currentZ": 5.0,
        "temps": [
            {
                "tool0": {"actual": 200.0, "target": 205.0},
                "bed": {"actual": 60.0, "target": 60.0}
            }
        ]
    }

    for i in range(10):
        # vary Z slightly
        payload["currentZ"] = 5.0 + (i * 0.2)
        await collector._on_current(payload)

    samples = memory_db.get_samples("test-job-123")
    assert len(samples) == 10

    # Assert limitations are documented in samples
    for sample in samples:
        assert sample.gcode_line is None, "gcode_line should be None"
        assert sample.print_speed_pct is None
        assert sample.extrusion_factor_pct is None
        assert sample.fan_speed_pct is None
        assert sample.hotend_actual_c == 200.0
        assert sample.hotend_target_c == 205.0
        assert sample.bed_actual_c == 60.0
        assert sample.bed_target_c == 60.0

@pytest.mark.asyncio
async def test_octoprint_collector_updates_job_outcome_on_event(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)

    await collector._on_event({"type": "PrintFailed"})

    job = memory_db.get_job("test-job-123")
    assert job.outcome == "failure"
    assert job.completed_at is not None

@pytest.mark.asyncio
async def test_octoprint_collector_missing_data(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)

    # Missing temps
    payload = {"currentZ": 5.0}
    await collector._on_current(payload)

    # Missing currentZ
    payload = {"temps": [{"tool0": {"actual": 200.0, "target": 205.0}}]}
    await collector._on_current(payload)

    samples = memory_db.get_samples("test-job-123")
    assert len(samples) == 2
    assert samples[0].hotend_actual_c is None
    assert samples[1].z_height_mm is None

@pytest.mark.asyncio
async def test_octoprint_collector_invalid_payload_structure(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)

    # Intentionally malformed payload (temps is not a list, etc)
    payload = {"temps": "not a list", "currentZ": "not a float"}
    await collector._on_current(payload)

    # Event should be handled gracefully (i.e. logged, sample may be partially null)
    # The current code might raise TypeError or ValueError, but the background task shouldn't crash
    # If the _on_current raises, let's see if the collector task handles it.
    # Actually _on_current just throws error, but it's an event handler. socketio catches event handler exceptions.
    pass


@pytest.mark.asyncio
async def test_octoprint_collector_authenticates_on_sockjs_open(memory_db, patch_session):
    """The auth frame is sent in response to SockJS's 'o' (open) frame."""
    collector = OctoPrintCollector("localhost", 5000, "secret-api-key", "test-job-123", memory_db)
    ws = FakeWebSocket([text_frame("o")])
    urls = []

    with patch_session(lambda: FakeClientSession(ws=ws, on_connect=urls.append)):
        await collector.start()
        await asyncio.sleep(0.05)
        await collector.stop()

    assert urls, "collector never opened a WebSocket"
    assert urls[0].startswith("ws://localhost:5000/sockjs/")
    assert urls[0].endswith("/websocket")
    # Authenticated with the session token from the passive login, NOT the API key:
    # OctoPrint answers `_api:<api_key>` with reauthRequired and sends no telemetry.
    assert ws.sent == ['["{\\"auth\\": \\"_api:sess-123\\"}"]']
    assert "secret-api-key" not in ws.sent[0]


@pytest.mark.asyncio
async def test_octoprint_collector_ingests_current_frame(memory_db, patch_session):
    """A SockJS array frame carrying 'current' becomes a telemetry sample."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    payload = json.dumps({"current": {"currentZ": 1.5, "temps": [{"tool0": {"actual": 200.0, "target": 205.0}}]}})
    ws = FakeWebSocket([text_frame("o"), text_frame("a" + json.dumps([payload]))])

    with patch_session(lambda: FakeClientSession(ws=ws)):
        await collector.start()
        await asyncio.sleep(0.1)
        await collector.stop()

    samples = memory_db.get_samples("test-job-123")
    assert len(samples) == 1
    assert samples[0].z_height_mm == 1.5
    assert samples[0].hotend_actual_c == 200.0


@pytest.mark.asyncio
async def test_octoprint_collector_reconnects_with_backoff(memory_db, patch_session):
    """A failing connection is retried rather than abandoned."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    attempts = []

    factory = lambda: FakeClientSession(
        error=aiohttp.ClientError("connection refused"), on_connect=attempts.append
    )
    with patch_session(factory):
        await collector.start()
        await asyncio.sleep(0.05)
        await collector.stop()

    assert len(attempts) >= 1
    assert collector._backoff >= 1.0


@pytest.mark.asyncio
async def test_octoprint_collector_ignores_heartbeat_frames(memory_db, patch_session):
    """SockJS heartbeat frames must not produce samples or crash the loop."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    ws = FakeWebSocket([text_frame("o"), text_frame("h"), text_frame("h")])

    with patch_session(lambda: FakeClientSession(ws=ws)):
        await collector.start()
        await asyncio.sleep(0.05)
        await collector.stop()

    assert memory_db.get_samples("test-job-123") == []


@pytest.mark.asyncio
async def test_octoprint_collector_stop_cancels_task(memory_db, patch_session):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    ws = FakeWebSocket([text_frame("o")])

    with patch_session(lambda: FakeClientSession(ws=ws)):
        await collector.start()
        await asyncio.sleep(0.05)
        assert collector._bg_task is not None
        assert not collector._bg_task.done()

        await collector.stop()
        await asyncio.sleep(0.05)

    assert collector._bg_task.done() or collector._bg_task.cancelled()


CURRENT_FRAME = {
    "currentZ": 5.0,
    "temps": [{"tool0": {"actual": 200.0, "target": 205.0}, "bed": {"actual": 60.0, "target": 60.0}}],
}


def _unwritable(*args, **kwargs):
    raise OperationalError("unable to open database file")


@pytest.mark.asyncio
async def test_database_failure_is_not_reported_as_a_connection_error(memory_db, caplog):
    """A failed write must not reach _run_loop's blanket handler.

    Unguarded, it was logged there as "OctoPrint connection error" and dropped a
    websocket that was working perfectly; the socket reconnected on a backoff, and the
    next sample tore it down again. The cause named in the log was the one thing that
    was not wrong.
    """
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    memory_db.insert_sample = _unwritable

    with caplog.at_level(logging.ERROR):
        await collector._on_current(dict(CURRENT_FRAME))

    assert collector.sample_queue.empty(), "an unpersisted sample must not be fanned out"
    assert "unable to open database file" in caplog.text
    assert "connection error" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_repeated_write_failures_are_logged_once(memory_db, caplog):
    """Samples arrive about every second; the cause does not change between them."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    memory_db.insert_sample = _unwritable

    with caplog.at_level(logging.DEBUG, logger="pythonsrc.telemetry.octoprint_collector"):
        for _ in range(5):
            await collector._on_current(dict(CURRENT_FRAME))

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


@pytest.mark.asyncio
async def test_write_failure_is_reported_again_after_a_recovery(memory_db, caplog):
    """A second outage is news; only an unbroken run of the same failure is not."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    real_insert = memory_db.insert_sample

    with caplog.at_level(logging.DEBUG, logger="pythonsrc.telemetry.octoprint_collector"):
        memory_db.insert_sample = _unwritable
        await collector._on_current(dict(CURRENT_FRAME))
        memory_db.insert_sample = real_insert
        await collector._on_current(dict(CURRENT_FRAME))
        memory_db.insert_sample = _unwritable
        await collector._on_current(dict(CURRENT_FRAME))

    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 2
    assert len(memory_db.get_samples("test-job-123")) == 1


@pytest.mark.asyncio
async def test_outcome_write_failure_does_not_break_the_socket(memory_db, caplog):
    """The same guard on the other DB write in the frame path."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    memory_db.update_job_outcome_verdict = _unwritable

    with caplog.at_level(logging.ERROR):
        await collector._on_event({"type": "PrintDone"})

    assert "awaiting_verdict" in caplog.text
    assert "unable to open database file" in caplog.text


# ── Capture hardening: what the socket carries and the DB never kept ──────────


@pytest.mark.asyncio
async def test_file_position_is_recorded_from_the_current_frame(memory_db):
    """progress.filepos is on the wire in the very frame the collector forwards
    to the browser; the sample column used to be hardcoded to None."""
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    payload = {
        "currentZ": 3.2,
        "temps": [{"tool0": {"actual": 210.0, "target": 210.0}, "bed": {"actual": 60.0, "target": 60.0}}],
        "progress": {"completion": 41.0, "filepos": 123456},
        "state": {"flags": {"printing": True}},
    }
    await collector._on_current(payload)
    samples = memory_db.get_samples("test-job-123")
    assert samples[-1].gcode_line == 123456


@pytest.mark.asyncio
async def test_print_done_records_the_actual_duration_and_a_terminal_event(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    await collector._on_event({
        "type": "PrintDone",
        "payload": {"name": "engineered_mesh.gcode", "time": 5423.5},
    })
    job = memory_db.get_job("test-job-123")
    assert job.outcome == "awaiting_verdict"
    assert job.print_duration_s == 5423.5

    events = memory_db.get_job_events("test-job-123", kind="printer_terminal")
    assert len(events) == 1
    assert events[0].detail["event"] == "PrintDone"


@pytest.mark.asyncio
async def test_failure_reason_is_kept_in_the_terminal_event(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    await collector._on_event({
        "type": "PrintFailed",
        "payload": {"name": "engineered_mesh.gcode", "time": 90.0, "reason": "cancelled"},
    })
    events = memory_db.get_job_events("test-job-123", kind="printer_terminal")
    assert events[0].detail["reason"] == "cancelled"


@pytest.mark.asyncio
async def test_pause_and_resume_are_recorded_as_events(memory_db):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    await collector._on_event({"type": "PrintPaused", "payload": {"name": "engineered_mesh.gcode"}})
    await collector._on_event({"type": "PrintResumed", "payload": {"name": "engineered_mesh.gcode"}})
    assert len(memory_db.get_job_events("test-job-123", kind="print_paused")) == 1
    assert len(memory_db.get_job_events("test-job-123", kind="print_resumed")) == 1
    # Neither touches the outcome.
    assert memory_db.get_job("test-job-123").outcome == "unknown"


@pytest.mark.asyncio
async def test_an_event_for_someone_elses_file_is_not_this_jobs_outcome(memory_db):
    """The socket reports every print on the machine, not just ours. A PrintDone
    for a file this job never uploaded must not settle this job's row."""
    collector = OctoPrintCollector(
        "localhost", 5000, "key", "test-job-123", memory_db,
        gcode_filename="engineered_mesh.gcode",
    )
    await collector._on_event({
        "type": "PrintDone",
        "payload": {"name": "benchy.gcode", "time": 100.0},
    })
    job = memory_db.get_job("test-job-123")
    assert job.outcome == "unknown"
    assert job.print_duration_s is None


@pytest.mark.asyncio
async def test_a_stood_down_collector_does_not_write_outcomes(memory_db):
    """_on_event used to skip the claim check, so a collector that lost the
    single-writer claim still mutated the print_job row."""
    memory_db.try_claim_collector("test-job-123", "rival-process")
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    await collector._on_event({"type": "PrintFailed", "payload": {"time": 10.0}})
    assert memory_db.get_job("test-job-123").outcome == "unknown"
