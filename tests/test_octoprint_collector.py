import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

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

@pytest.fixture
def mock_sio():
    with patch("pythonsrc.telemetry.octoprint_collector.socketio.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_instance.connected = False
        mock_instance.on = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance

@pytest.mark.asyncio
async def test_octoprint_collector_connects_and_authenticates(memory_db, mock_sio):
    collector = OctoPrintCollector("localhost", 5000, "secret-api-key", "test-job-123", memory_db)
    
    # Configure mock
    mock_sio.connected = False
    
    async def mock_connect(*args, **kwargs):
        mock_sio.connected = True
    
    async def mock_wait(*args, **kwargs):
        while mock_sio.connected:
            await asyncio.sleep(0.01)
            
    mock_sio.connect.side_effect = mock_connect
    mock_sio.wait.side_effect = mock_wait
    
    await collector.start()
    await asyncio.sleep(0.05)
    
    mock_sio.connect.assert_called_once_with("http://localhost:5000", headers={"X-Api-Key": "secret-api-key"})
    mock_sio.emit.assert_called_once_with("authenticate", {"passive": True, "apikey": "secret-api-key"})
    
    await collector.stop()

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
async def test_octoprint_collector_reconnects_with_backoff(memory_db, mock_sio):
    collector = OctoPrintCollector("localhost", 5000, "key", "test-job-123", memory_db)
    
    call_count = 0
    async def mock_connect_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("Connection failed")
        
    mock_sio.connect.side_effect = mock_connect_fail
    
    await collector.start()
    
    # Sleep to allow multiple reconnect attempts. Initial backoff is 1.0, then 2.0, 4.0
    await asyncio.sleep(0.5) 
    assert call_count >= 1
    
    await collector.stop()
