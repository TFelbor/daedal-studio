import pytest
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pythonsrc.telemetry.schema import PrintJob, TelemetrySample, FailureEvent
from pythonsrc.telemetry.db import TelemetryDB, get_default_db_path

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_telemetry.db"
    db = TelemetryDB(str(db_file))
    db.init_schema()
    yield db
    db.close()

def test_idempotent_schema_init(tmp_path):
    db_file = tmp_path / "test_init.db"
    db = TelemetryDB(str(db_file))
    db.init_schema()
    # Calling it again should not fail
    db.init_schema()
    
    # Verify tables exist
    cursor = db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"print_job", "telemetry_sample", "failure_event"}.issubset(tables)
    db.close()

def test_insert_retrieve_job(temp_db):
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job = PrintJob(
        job_id="job_1",
        prompt="A nice vase",
        printer_id="printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=dt_start,
        completed_at=None,
        outcome="unknown"
    )
    
    temp_db.insert_job(job)
    retrieved = temp_db.get_job("job_1")
    assert retrieved is not None
    assert retrieved == job

def test_update_job_outcome(temp_db):
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job = PrintJob(
        job_id="job_2",
        prompt="Vase",
        printer_id="printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=dt_start,
        completed_at=None,
        outcome="unknown"
    )
    temp_db.insert_job(job)
    
    dt_end = datetime(2023, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    temp_db.update_job_outcome("job_2", "success", dt_end)
    
    retrieved = temp_db.get_job("job_2")
    assert retrieved.outcome == "success"
    assert retrieved.completed_at == dt_end

def test_insert_retrieve_sample(temp_db):
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job = PrintJob(
        job_id="job_3", prompt="Vase", printer_id="printer_1",
        printer_firmware="klipper", slicer="Cura", profile_name="Standard",
        started_at=dt_start, completed_at=None, outcome="unknown"
    )
    temp_db.insert_job(job)
    
    dt_sample = datetime(2023, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    sample = TelemetrySample(
        job_id="job_3",
        sampled_at=dt_sample,
        gcode_line=100,
        z_height_mm=1.0,
        hotend_actual_c=210.0, hotend_target_c=210.0,
        bed_actual_c=60.0, bed_target_c=60.0,
        print_speed_pct=100.0, extrusion_factor_pct=100.0, fan_speed_pct=50.0
    )
    temp_db.insert_sample(sample)
    
    samples = temp_db.get_samples("job_3")
    assert len(samples) == 1
    assert samples[0] == sample

def test_insert_retrieve_failure_event(temp_db):
    dt_start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    job = PrintJob(
        job_id="job_4", prompt="Vase", printer_id="printer_1",
        printer_firmware="klipper", slicer="Cura", profile_name="Standard",
        started_at=dt_start, completed_at=None, outcome="unknown"
    )
    temp_db.insert_job(job)
    
    dt_fail = datetime(2023, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
    event = FailureEvent(
        event_id="evt_1",
        job_id="job_4",
        detected_at=dt_fail,
        gcode_line=200,
        z_height_mm=2.5,
        failure_type="layer_shift",
        source="automated",
        notes="X-axis shift",
        snapshot={"samples": []}
    )
    temp_db.insert_failure_event(event)
    
    events = temp_db.get_failure_events("job_4")
    assert len(events) == 1
    assert events[0] == event

def test_get_default_db_path(monkeypatch):
    monkeypatch.setenv("TELEMETRY_DB_PATH", "/tmp/custom_telemetry.db")
    assert get_default_db_path() == "/tmp/custom_telemetry.db"
    
    monkeypatch.delenv("TELEMETRY_DB_PATH", raising=False)
    assert Path(get_default_db_path()).name == "telemetry.db"
    assert ".p2p-mesh" in get_default_db_path()
