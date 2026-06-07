from __future__ import annotations
import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from pythonsrc.telemetry.schema import PrintJob, TelemetrySample, FailureEvent

def get_default_db_path() -> str:
    """Get the default telemetry database path from environment or home directory."""
    env_path = os.environ.get("TELEMETRY_DB_PATH")
    if env_path:
        return env_path
    return str(Path.home() / ".p2p-mesh" / "telemetry.db")

def _dt_to_str(dt: datetime | None) -> str | None:
    """Helper to serialize datetime to ISO 8601 string."""
    return dt.isoformat() if dt else None

def _str_to_dt(s: str | None) -> datetime | None:
    """Helper to deserialize ISO 8601 string to datetime."""
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)

class TelemetryDB:
    """Database wrapper for telemetry storage using SQLite."""
    
    def __init__(self, db_path: str | None = None):
        """
        Initialize the TelemetryDB.
        
        Args:
            db_path: The path to the SQLite database. If None, resolves using get_default_db_path().
        """
        if db_path is None:
            db_path = get_default_db_path()
            
        self.db_path = db_path
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def init_schema(self) -> None:
        """Create tables if they do not exist (idempotent)."""
        cursor = self.conn.cursor()
        
        # PrintJob table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS print_job (
                job_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                printer_id TEXT NOT NULL,
                printer_firmware TEXT NOT NULL,
                slicer TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                outcome TEXT NOT NULL
            )
        ''')
        
        # TelemetrySample table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telemetry_sample (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                sampled_at TEXT NOT NULL,
                gcode_line INTEGER,
                z_height_mm REAL,
                hotend_actual_c REAL,
                hotend_target_c REAL,
                bed_actual_c REAL,
                bed_target_c REAL,
                print_speed_pct REAL,
                extrusion_factor_pct REAL,
                fan_speed_pct REAL,
                FOREIGN KEY (job_id) REFERENCES print_job (job_id)
            )
        ''')
        
        # FailureEvent table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS failure_event (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                gcode_line INTEGER,
                z_height_mm REAL,
                failure_type TEXT NOT NULL,
                source TEXT NOT NULL,
                notes TEXT,
                snapshot TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES print_job (job_id)
            )
        ''')
        
        self.conn.commit()

    def insert_job(self, job: PrintJob) -> None:
        """Insert a PrintJob into the database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO print_job (
                job_id, prompt, printer_id, printer_firmware, slicer, profile_name,
                started_at, completed_at, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.job_id, job.prompt, job.printer_id, job.printer_firmware,
            job.slicer, job.profile_name, _dt_to_str(job.started_at),
            _dt_to_str(job.completed_at), job.outcome
        ))
        self.conn.commit()

    def update_job_outcome(self, job_id: str, outcome: str, completed_at: datetime) -> None:
        """Update the outcome and completion time for a specific print job."""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE print_job
            SET outcome = ?, completed_at = ?
            WHERE job_id = ?
        ''', (outcome, _dt_to_str(completed_at), job_id))
        self.conn.commit()

    def insert_sample(self, sample: TelemetrySample) -> None:
        """Insert a TelemetrySample into the database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO telemetry_sample (
                job_id, sampled_at, gcode_line, z_height_mm,
                hotend_actual_c, hotend_target_c, bed_actual_c, bed_target_c,
                print_speed_pct, extrusion_factor_pct, fan_speed_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sample.job_id, _dt_to_str(sample.sampled_at), sample.gcode_line,
            sample.z_height_mm, sample.hotend_actual_c, sample.hotend_target_c,
            sample.bed_actual_c, sample.bed_target_c, sample.print_speed_pct,
            sample.extrusion_factor_pct, sample.fan_speed_pct
        ))
        self.conn.commit()

    def insert_failure_event(self, event: FailureEvent) -> None:
        """Insert a FailureEvent into the database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO failure_event (
                event_id, job_id, detected_at, gcode_line, z_height_mm,
                failure_type, source, notes, snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            event.event_id, event.job_id, _dt_to_str(event.detected_at),
            event.gcode_line, event.z_height_mm, event.failure_type,
            event.source, event.notes, json.dumps(event.snapshot)
        ))
        self.conn.commit()

    def get_job(self, job_id: str) -> PrintJob | None:
        """Retrieve a PrintJob by ID, or None if not found."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM print_job WHERE job_id = ?', (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        return PrintJob(
            job_id=row['job_id'],
            prompt=row['prompt'],
            printer_id=row['printer_id'],
            printer_firmware=row['printer_firmware'],  # type: ignore
            slicer=row['slicer'],
            profile_name=row['profile_name'],
            started_at=_str_to_dt(row['started_at']),  # type: ignore
            completed_at=_str_to_dt(row['completed_at']),
            outcome=row['outcome']  # type: ignore
        )

    def get_samples(self, job_id: str, limit: int = 500) -> list[TelemetrySample]:
        """Retrieve TelemetrySamples for a specific print job."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM telemetry_sample
            WHERE job_id = ?
            ORDER BY sampled_at DESC
            LIMIT ?
        ''', (job_id, limit))
        rows = cursor.fetchall()
        
        samples = []
        for row in rows:
            samples.append(TelemetrySample(
                job_id=row['job_id'],
                sampled_at=_str_to_dt(row['sampled_at']),  # type: ignore
                gcode_line=row['gcode_line'],
                z_height_mm=row['z_height_mm'],
                hotend_actual_c=row['hotend_actual_c'],
                hotend_target_c=row['hotend_target_c'],
                bed_actual_c=row['bed_actual_c'],
                bed_target_c=row['bed_target_c'],
                print_speed_pct=row['print_speed_pct'],
                extrusion_factor_pct=row['extrusion_factor_pct'],
                fan_speed_pct=row['fan_speed_pct']
            ))
        
        # Return in ascending chronological order
        return samples[::-1]

    def get_failure_events(self, job_id: str) -> list[FailureEvent]:
        """Retrieve FailureEvents for a specific print job."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM failure_event
            WHERE job_id = ?
            ORDER BY detected_at ASC
        ''', (job_id,))
        rows = cursor.fetchall()
        
        events = []
        for row in rows:
            events.append(FailureEvent(
                event_id=row['event_id'],
                job_id=row['job_id'],
                detected_at=_str_to_dt(row['detected_at']),  # type: ignore
                gcode_line=row['gcode_line'],
                z_height_mm=row['z_height_mm'],
                failure_type=row['failure_type'],  # type: ignore
                source=row['source'],  # type: ignore
                notes=row['notes'],
                snapshot=json.loads(row['snapshot'])
            ))
        
        return events
