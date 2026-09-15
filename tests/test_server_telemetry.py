import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample
from server.app import active_collectors, app

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_db():
    db = TelemetryDB()
    db.init_schema()
    db.execute("DELETE FROM failure_event")
    db.execute("DELETE FROM telemetry_sample")
    # job_event and the collector claim table reference print_job too, and
    # foreign keys are enforced — children go first.
    db.execute("DELETE FROM job_event")
    db.execute("DELETE FROM telemetry_collector_claim")
    db.execute("DELETE FROM print_job")
    db.close()

    # clear background collectors
    active_collectors.clear()
    yield
    for c in list(active_collectors.values()):
        try:
            asyncio.run(c.stop())
        except Exception:
            pass
    active_collectors.clear()

@patch('server.app._run_pipeline', new_callable=AsyncMock)
@patch('pythonsrc.telemetry.moonraker_collector.MoonrakerCollector.start', new_callable=AsyncMock)
def test_klipper_telemetry(mock_moonraker_start, mock_run_pipeline, printer_configured):
    """Integration test (Klipper path).

    The collector is attached when Phase 5 begins — at job creation it wrote an
    idle-printer sample per second for the whole pipeline — so this exercises
    `_attach_job_telemetry`, the hook `_run_pipeline` fires on the Phase 5 banner.
    """
    from server.app import _attach_job_telemetry

    resp = client.post("/jobs", json={
        "prompt": "test klipper",
        "printer_id": "test_klipper",
        "profile": "pythonsrc/profiles/klipper_test.json",
        "skip_visualizer": True,
        "print": True,
        "start_print": True
    })
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    mock_run_pipeline.assert_called_once()

    async def attach():
        _attach_job_telemetry(job_id, "klipper", "http://localhost:7125", None)
        await asyncio.sleep(0)

    asyncio.run(attach())

    assert job_id in active_collectors
    collector = active_collectors[job_id]
    from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
    assert isinstance(collector, MoonrakerCollector)
    assert collector.ws_url == "ws://localhost:7125/websocket"

    mock_moonraker_start.assert_called_once()

    # Manually inject telemetry samples to simulate collector
    db = TelemetryDB()
    for i in range(5):
        db.insert_sample(TelemetrySample(
            job_id=job_id,
            sampled_at=datetime.now(timezone.utc),
            gcode_line=i,
            z_height_mm=i * 0.2,
            hotend_actual_c=200,
            hotend_target_c=200,
            bed_actual_c=60,
            bed_target_c=60,
            print_speed_pct=100,
            extrusion_factor_pct=100,
            fan_speed_pct=100
        ))
    db.close()

    # GET /jobs/{id}/telemetry
    resp_tel = client.get(f"/jobs/{job_id}/telemetry")
    assert resp_tel.status_code == 200
    samples = resp_tel.json()
    assert len(samples) == 5
    assert samples[0]["gcode_line"] == 0

@patch('pythonsrc.telemetry.octoprint_collector.OctoPrintCollector.start', new_callable=AsyncMock)
def test_octoprint_telemetry(mock_octoprint_start):
    """Integration test (OctoPrint path) — attach fires at Phase 5, not creation."""
    from server.app import _attach_job_telemetry

    job_id = str(uuid.uuid4())

    async def attach():
        _attach_job_telemetry(job_id, "octoprint", "http://localhost:5001", "key")
        await asyncio.sleep(0)

    asyncio.run(attach())

    assert job_id in active_collectors
    collector = active_collectors[job_id]
    from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
    assert isinstance(collector, OctoPrintCollector)
    assert collector.host == "localhost"
    assert collector.port == 5001
    assert collector.gcode_filename == "engineered_mesh.gcode"

    mock_octoprint_start.assert_called_once()

@patch('server.app.logger.warning')
def test_bambu_telemetry(mock_logger_warning):
    """A Bambu attach logs the warning and registers nothing."""
    from server.app import _attach_job_telemetry

    job_id = str(uuid.uuid4())

    async def attach():
        _attach_job_telemetry(job_id, "bambu", "http://bambu-printer", None)
        await asyncio.sleep(0)

    asyncio.run(attach())

    # Collector shouldn't be registered
    assert job_id not in active_collectors
    mock_logger_warning.assert_called_with("Telemetry not yet available for Bambu")

def test_failure_event_endpoint():
    """POST /jobs/{id}/failure creates a FailureEvent row with a non-empty snapshot field"""
    # Create a job first
    db = TelemetryDB()
    from pythonsrc.telemetry.schema import PrintJob
    job_id = str(uuid.uuid4())
    db.insert_job(PrintJob(
        job_id=job_id,
        prompt="test fail",
        printer_id="printer",
        printer_firmware="klipper",
        slicer="cura",
        profile_name="default",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    ))
    # Insert 2 samples
    for i in range(2):
        db.insert_sample(TelemetrySample(
            job_id=job_id,
            sampled_at=datetime.now(timezone.utc),
            gcode_line=i,
            z_height_mm=i * 0.2,
            hotend_actual_c=200,
            hotend_target_c=200,
            bed_actual_c=60,
            bed_target_c=60,
            print_speed_pct=100,
            extrusion_factor_pct=100,
            fan_speed_pct=100
        ))
    db.close()

    resp = client.post(f"/jobs/{job_id}/failure", json={
        "failure_type": "adhesion",
        "notes": "came off bed"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["failure_type"] == "adhesion"
    assert data["notes"] == "came off bed"
    assert data["source"] == "manual"
    assert len(data["snapshot"]) == 2

    # Check DB
    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    assert len(events) == 1
    assert events[0].failure_type == "adhesion"
    assert len(events[0].snapshot) == 2

@patch('pythonsrc.telemetry.moonraker_collector.MoonrakerCollector.stop', new_callable=AsyncMock)
def test_shutdown_stops_collectors(mock_stop):
    """Stopping the server cleanly stops all running collectors"""
    from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
    collector = MoonrakerCollector("ws://localhost", "job1", TelemetryDB())
    active_collectors["job1"] = collector

    # Trigger shutdown event
    # Using client to trigger lifecycle events
    with TestClient(app) as lifecycle_client:
        pass  # Startup and shutdown are called

    mock_stop.assert_called_once()
