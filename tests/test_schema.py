import pytest
import json
from datetime import datetime, timezone
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample, FailureEvent

def test_print_job_serialization():
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dt_end = datetime(2023, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
    
    job = PrintJob(
        job_id="123e4567-e89b-12d3-a456-426614174000",
        prompt="A nice vase",
        printer_id="printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=dt_start,
        completed_at=dt_end,
        outcome="success"
    )
    
    d = job.to_dict()
    # verify json serialization
    json_str = json.dumps(d)
    
    job_restored = PrintJob.from_dict(json.loads(json_str))
    assert job == job_restored

def test_print_job_serialization_no_completed_at():
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    job = PrintJob(
        job_id="123e4567-e89b-12d3-a456-426614174000",
        prompt="A nice vase",
        printer_id="printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=dt_start,
        completed_at=None,
        outcome="unknown"
    )
    
    d = job.to_dict()
    json_str = json.dumps(d)
    
    job_restored = PrintJob.from_dict(json.loads(json_str))
    assert job == job_restored

def test_telemetry_sample_serialization():
    dt = datetime(2023, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    sample = TelemetrySample(
        job_id="123e4567-e89b-12d3-a456-426614174000",
        sampled_at=dt,
        gcode_line=1000,
        z_height_mm=2.5,
        hotend_actual_c=210.0,
        hotend_target_c=210.0,
        bed_actual_c=60.0,
        bed_target_c=60.0,
        print_speed_pct=100.0,
        extrusion_factor_pct=100.0,
        fan_speed_pct=50.0
    )
    
    d = sample.to_dict()
    json_str = json.dumps(d)
    
    sample_restored = TelemetrySample.from_dict(json.loads(json_str))
    assert sample == sample_restored

def test_telemetry_sample_serialization_with_none():
    dt = datetime(2023, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    sample = TelemetrySample(
        job_id="123e4567-e89b-12d3-a456-426614174000",
        sampled_at=dt,
        gcode_line=None,
        z_height_mm=None,
        hotend_actual_c=None,
        hotend_target_c=None,
        bed_actual_c=None,
        bed_target_c=None,
        print_speed_pct=None,
        extrusion_factor_pct=None,
        fan_speed_pct=None
    )
    
    d = sample.to_dict()
    json_str = json.dumps(d)
    
    sample_restored = TelemetrySample.from_dict(json.loads(json_str))
    assert sample == sample_restored

def test_failure_event_serialization():
    dt = datetime(2023, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
    event = FailureEvent(
        event_id="987e6543-e21b-12d3-a456-426614174000",
        job_id="123e4567-e89b-12d3-a456-426614174000",
        detected_at=dt,
        gcode_line=2500,
        z_height_mm=6.2,
        failure_type="layer_shift",
        source="automated",
        notes="Shift detected on X axis",
        snapshot={"samples": [{"job_id": "123e4567-e89b-12d3-a456-426614174000", "sampled_at": "2023-01-01T12:05:00+00:00"}]}
    )
    
    d = event.to_dict()
    json_str = json.dumps(d)
    
    event_restored = FailureEvent.from_dict(json.loads(json_str))
    assert event == event_restored

def test_print_job_invalid_outcome():
    with pytest.raises(ValueError):
        PrintJob(
            job_id="123e", prompt="A", printer_id="p1", printer_firmware="klipper",
            slicer="Cura", profile_name="Standard", started_at=datetime.now(timezone.utc),
            completed_at=None, outcome="invalid_value"
        )

def test_from_dict_missing_optional_field():
    d = {
        "job_id": "123e4567",
        "prompt": "Test",
        "printer_id": "p1",
        "printer_firmware": "klipper",
        "slicer": "Cura",
        "profile_name": "Standard",
        "started_at": "2023-01-01T12:00:00+00:00",
        "outcome": "unknown"
        # completed_at is missing
    }
    job = PrintJob.from_dict(d)
    assert job.completed_at is None

def test_from_dict_unknown_extra_key():
    d = {
        "job_id": "123e4567",
        "prompt": "Test",
        "printer_id": "p1",
        "printer_firmware": "klipper",
        "slicer": "Cura",
        "profile_name": "Standard",
        "started_at": "2023-01-01T12:00:00+00:00",
        "completed_at": None,
        "outcome": "unknown",
        "some_extra_key_that_should_be_ignored": 123
    }
    job = PrintJob.from_dict(d)
    assert not hasattr(job, "some_extra_key_that_should_be_ignored")

def test_failure_event_empty_snapshot():
    event = FailureEvent(
        event_id="id", job_id="job", detected_at=datetime.now(timezone.utc),
        gcode_line=None, z_height_mm=None, failure_type="clog",
        source="manual", notes=None, snapshot={}
    )
    d = event.to_dict()
    restored = FailureEvent.from_dict(json.loads(json.dumps(d)))
    assert restored.snapshot == {}
