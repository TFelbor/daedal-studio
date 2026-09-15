import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pythonsrc.operators.base import BasePrinterOperator
from pythonsrc.operators.moonraker_operator import MoonrakerOperator
from pythonsrc.operators.octoprint_operator import OctoPrintOperator
from pythonsrc.telemetry.detector import AnomalyDetector
from pythonsrc.telemetry.schema import FailureEvent, TelemetrySample


@pytest.fixture
def mock_db():
    db = MagicMock()
    # By default, mock get_job to return a job that is printing
    job_mock = MagicMock()
    job_mock.outcome = "unknown"
    db.get_job.return_value = job_mock
    return db

def make_sample(job_id="job_1", z_height_mm=1.0, gcode_line=100,
                hotend_actual=200, hotend_target=200, extrusion_factor_pct=100.0):
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
        extrusion_factor_pct=extrusion_factor_pct,
        fan_speed_pct=100
    )

@pytest.mark.asyncio
async def test_rule1_thermal_runaway(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # Needs to be > 150C target and actual < target - 25 for 5 samples
    for _i in range(5):
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
    for _i in range(4):
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
    for _i in range(10):
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

    for _i in range(10):
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

    for _i in range(5):
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

    for _i in range(5):
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

@pytest.mark.asyncio
async def test_empty_db_does_not_crash(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    mock_db.get_job.return_value = None

    # Send a sample for a non-existent job
    await queue.put(make_sample(job_id="non_existent"))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0

@pytest.mark.asyncio
async def test_db_less_than_10_samples(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # 5 samples -> no clogged detection (requires 10)
    detector._state_cache["job_1"] = {"time": 0, "state": "printing", "progress": 10.0, "prev_state": "printing"}
    for _i in range(5):
        s = make_sample(gcode_line=500)
        await queue.put(s)

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0

@pytest.mark.asyncio
async def test_massive_layer_shift(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    await queue.put(make_sample(z_height_mm=10.0))
    # Sudden drop by 5mm (Z goes down)
    await queue.put(make_sample(z_height_mm=5.0))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "layer_shift"

@pytest.mark.asyncio
async def test_very_slow_extrusion(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # Rule might be: if extrusion_factor_pct < 15 or 50?
    # I need to check the actual rule in AnomalyDetector for slow extrusion.
    # Currently AnomalyDetector rules are: thermal_runaway, clog (gcode_line stuck), layer_shift (Z drop), adhesion.
    # The prompt explicitly asks to add "Very slow extrusion (extrusion_factor drops to 10%) -> detected".
    # I should add the test and also I might need to update AnomalyDetector to support it.
    await queue.put(make_sample(extrusion_factor_pct=10.0))
    await queue.put(make_sample(extrusion_factor_pct=10.0))
    await queue.put(make_sample(extrusion_factor_pct=10.0))
    await queue.put(make_sample(extrusion_factor_pct=10.0))
    await queue.put(make_sample(extrusion_factor_pct=10.0))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count >= 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.failure_type == "extrusion_issue"

@pytest.mark.asyncio
async def test_multiple_jobs_isolation(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # Job 1 is printing normally
    await queue.put(make_sample(job_id="job_1", hotend_target=200, hotend_actual=200))
    await queue.put(make_sample(job_id="job_1", hotend_target=200, hotend_actual=200))
    await queue.put(make_sample(job_id="job_1", hotend_target=200, hotend_actual=200))
    await queue.put(make_sample(job_id="job_1", hotend_target=200, hotend_actual=200))
    await queue.put(make_sample(job_id="job_1", hotend_target=200, hotend_actual=200))

    # Job 2 is suffering thermal runaway
    await queue.put(make_sample(job_id="job_2", hotend_target=200, hotend_actual=170))
    await queue.put(make_sample(job_id="job_2", hotend_target=200, hotend_actual=170))
    await queue.put(make_sample(job_id="job_2", hotend_target=200, hotend_actual=170))
    await queue.put(make_sample(job_id="job_2", hotend_target=200, hotend_actual=170))
    await queue.put(make_sample(job_id="job_2", hotend_target=200, hotend_actual=170))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 1
    event = mock_db.insert_failure_event.call_args[0][0]
    assert event.job_id == "job_2"
    assert event.failure_type == "thermal_runaway"
    assert isinstance(event, FailureEvent)


# ── Heating up is not thermal runaway ────────────────────────────────────────
#
# A real job was labelled "thermal runaway / automated / Triggered by rule
# thermal_runaway" seconds after Phase 5 dispatched it, and the operator then
# cancelled it by hand. Nothing was wrong with the printer: a cold hotend climbing
# toward 210 C is, sample for sample, indistinguishable from a hotend that cannot
# hold 210 C — unless the rule looks at whether the gap is closing. This was the
# only rule of the five with no state gate and no trend test.


@pytest.mark.asyncio
async def test_a_cold_hotend_warming_up_is_not_thermal_runaway(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # The ramp that triggered it in production: ambient to near-target.
    for actual in (25, 60, 95, 130, 165):
        await queue.put(make_sample(hotend_target=210, hotend_actual=actual))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0


@pytest.mark.asyncio
async def test_a_heater_that_stalls_below_target_is_still_thermal_runaway(mock_db):
    """The gap has to be *closing*. A heater stuck 40 C short is a real fault."""
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    for _ in range(5):
        await queue.put(make_sample(hotend_target=210, hotend_actual=170))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 1
    assert mock_db.insert_failure_event.call_args[0][0].failure_type == "thermal_runaway"


@pytest.mark.asyncio
async def test_a_hotend_falling_away_from_target_is_thermal_runaway(mock_db):
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    # All five already below target-25; the gap widens sample over sample.
    for actual in (180, 175, 170, 165, 160):
        await queue.put(make_sample(hotend_target=210, hotend_actual=actual))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 1


@pytest.mark.asyncio
async def test_a_cancelled_job_accrues_no_automated_failures(mock_db):
    """Once a human has cancelled, the printer cooling down is not a fault report."""
    job_mock = MagicMock()
    job_mock.outcome = "cancelled"
    mock_db.get_job.return_value = job_mock

    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    for _ in range(5):
        await queue.put(make_sample(hotend_target=210, hotend_actual=170))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0


# ── State guards: rules must not fabricate evidence off-print ─────────────────


@pytest.mark.asyncio
async def test_layer_shift_does_not_fire_after_the_print_ends(mock_db):
    """End-of-print parking and homing legitimately drop Z by far more than
    0.5mm; a completed job must not collect a layer_shift for it."""
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    done = MagicMock()
    done.outcome = "success"
    mock_db.get_job.return_value = done

    await queue.put(make_sample(z_height_mm=42.0))
    await queue.put(make_sample(z_height_mm=0.0))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0


@pytest.mark.asyncio
async def test_extrusion_issue_does_not_fire_when_not_printing(mock_db):
    """An idle extruder factor after the print settles is not a fault."""
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)

    done = MagicMock()
    done.outcome = "success"
    mock_db.get_job.return_value = done

    for _ in range(5):
        await queue.put(make_sample(z_height_mm=1.0, extrusion_factor_pct=5.0))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0


@pytest.mark.asyncio
async def test_user_cancellation_is_not_adhesion_evidence(mock_db):
    """A person cancelling 30 seconds in — for any reason, including changing
    their mind — used to be written up as a machine-observed adhesion failure.
    Only an error state is evidence; the human's own verdict covers the rest."""
    queue = asyncio.Queue()
    detector = AnomalyDetector(queue, mock_db, operator=None)
    detector._state_cache["job_1"] = {
        "time": 0, "state": "printing", "progress": 5.0, "prev_state": "printing",
    }

    await queue.put(make_sample(z_height_mm=0.5))

    cancelled = MagicMock()
    cancelled.outcome = "cancelled"
    mock_db.get_job.return_value = cancelled

    await queue.put(make_sample(z_height_mm=0.6))

    task = asyncio.create_task(detector.run())
    await asyncio.sleep(0.1)
    task.cancel()

    assert mock_db.insert_failure_event.call_count == 0
