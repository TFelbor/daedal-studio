import asyncio
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from pythonsrc.telemetry.detector import AnomalyDetector
from pythonsrc.telemetry.schema import TelemetrySample, FailureEvent
from pythonsrc.operators.base import BasePrinterOperator
from pythonsrc.operators.moonraker_operator import MoonrakerOperator
from pythonsrc.operators.octoprint_operator import OctoPrintOperator

@pytest.fixture
def mock_db():
    db = MagicMock()
    # By default, mock get_job to return a job that is printing
    job_mock = MagicMock()
    job_mock.outcome = "unknown"
    db.get_job.return_value = job_mock
    return db

def make_sample(job_id="job_1", z_height_mm=1.0, gcode_line=100, 
                hotend_actual=200, hotend_target=200):
    return TelemetrySample(
        job_id=job_id,
        sampled_at=datetime.now(timezone.utc),
        gcode_line=gcode_line,
        z_height_mm=z_height_mm,
        hotend_actual_c=hotend_actual,
        hotend_target_c=hotend_target,
        bed_actual_c=60,
        bed_target_c=60,
        print_speed_pct=100,
        extrusion_factor_pct=100,
        fan_speed_pct=100
    )

@pytest.mark.asyncio
async def test_rule1_thermal_runaway(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    
    # Needs to be > 150C target and actual < target - 25 for 5 samples
    for i in range(5):
        s = make_sample(hotend_target=200, hotend_actual=170)
        await queue.put(s)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)  # allow it to process
    
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "thermal_runaway"

@pytest.mark.asyncio
async def test_rule1_thermal_runaway_no_false_positive(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    
    # 4 samples bad, 1 sample good -> no trigger
    for i in range(4):
        s = make_sample(hotend_target=200, hotend_actual=170)
        await queue.put(s)
    s_good = make_sample(hotend_target=200, hotend_actual=190)
    await queue.put(s_good)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 0

@pytest.mark.asyncio
async def test_rule2_extrusion_stall(mock_db):
    queue = asyncio.Queue()
    # To trigger Rule 2, progress must be > 5%. Since operator is None, 
    # the detector defaults to 0% progress unless we inject cache state.
    detector = AnomalyDetector(queue, mock_db, operator=None)
    detector._state_cache["job_1"] = {"time": 0, "state": "printing", "progress": 10.0, "prev_state": "printing"}
    
    # 10 samples with same gcode_line
    for i in range(10):
        s = make_sample(gcode_line=500)
        await queue.put(s)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "clog"

@pytest.mark.asyncio
async def test_rule2_extrusion_stall_gcode_none(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    detector._state_cache["job_1"] = {"time": 0, "state": "printing", "progress": 10.0, "prev_state": "printing"}
    
    for i in range(10):
        s = make_sample(gcode_line=None)
        await queue.put(s)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    # Should not fire if gcode_line is None (like in OctoPrint)
    assert mock_db.insert_failure_event.call_count == 0

@pytest.mark.asyncio
async def test_rule3_layer_shift(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    
    await queue.put(make_sample(z_height_mm=10.0))
    await queue.put(make_sample(z_height_mm=9.4)) # diff > 0.5
    
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "layer_shift"

@pytest.mark.asyncio
async def test_rule4_bed_adhesion(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    
    # Z < 1.0mm, progress < 10%, transition from printing to error
    detector._state_cache["job_1"] = {"time": 0, "state": "printing", "progress": 5.0, "prev_state": "printing"}
    
    await queue.put(make_sample(z_height_mm=0.5))
    
    # Next, simulate state transition from printing to error via DB outcome
    job_err = MagicMock()
    job_err.outcome = "failure"
    mock_db.get_job.return_value = job_err
    
    await queue.put(make_sample(z_height_mm=0.6))
    
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "adhesion"

@pytest.mark.asyncio
async def test_integration_moonraker_mock(mock_db):
    # Integration test with Moonraker mock: simulate thermal runaway -> FailureEvent inserted
    queue = asyncio.Queue()
    moon_op = MagicMock(spec=MoonrakerOperator)
    moon_op.get_printer_state.return_value = {
        "state": "printing",
        "progress": 0.5
    }
    
    detector = AnomalyDetector(queue, mock_db, operator=moon_op)
    
    for i in range(5):
        s = make_sample(hotend_target=210, hotend_actual=180)
        await queue.put(s)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "thermal_runaway"

@pytest.mark.asyncio
async def test_integration_octoprint_mock(mock_db):
    # Integration test with OctoPrint mock: simulate thermal runaway -> FailureEvent inserted
    queue = asyncio.Queue()
    octo_op = MagicMock(spec=OctoPrintOperator)
    octo_op.get_printer_state.return_value = {
        "state": {"flags": {"printing": True}}
    }
    octo_op.get_job_status.return_value = {
        "progress": {"completion": 50.0}
    }
    
    detector = AnomalyDetector(queue, mock_db, operator=octo_op)
    
    for i in range(5):
        s = make_sample(hotend_target=210, hotend_actual=180)
        await queue.put(s)
        
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "thermal_runaway"

@pytest.mark.asyncio
@patch.dict(os.environ, {"PAUSE_ON_FAILURE": "true"})
async def test_pause_on_failure(mock_db):
    queue = asyncio.Queue()
    mock_op = MagicMock(spec=BasePrinterOperator)
    mock_op.pause_print = MagicMock()
    
    detector = AnomalyDetector(queue, mock_db, operator=mock_op)
    
    # Trigger layer shift (Rule 3)
    await queue.put(make_sample(z_height_mm=10.0))
    await queue.put(make_sample(z_height_mm=9.0))
    
    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.2) # wait enough for task to process and pause_print thread to run
    task.cancel()
    
    assert mock_db.insert_failure_event.call_count == 1
    assert mock_op.pause_print.call_count >= 1
