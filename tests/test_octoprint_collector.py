import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone
import json

import aiohttp

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector

@pytest.fixture
def memory_db():
    db = TelemetryDB(":memory:")
    db.init_schema()
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
