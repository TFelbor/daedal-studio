"""SQLite database interactions for telemetry storage."""

from __future__ import annotations
import sqlite3
import os
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
import threading

logger = logging.getLogger(__name__)

from pythonsrc.telemetry.schema import PrintJob, TelemetrySample, FailureEvent, JobEvent

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

# Columns renamed after shipping. Applied before the additive migration below, so an
# existing database keeps the values it already recorded under the old name instead of
# stranding them beside a fresh empty column.
_PRINT_JOB_RENAMED_COLUMNS = {
    "generation_cost_usd": "generation_cost_eur",
}

# Columns added to print_job after the original schema shipped. Kept as data so the
# migration and the INSERT stay in sync.
_PRINT_JOB_EXTRA_COLUMNS = {
    "generation_model": "TEXT",
    "generation_model_version": "TEXT",
    "generation_backend": "TEXT",
    "generation_params": "TEXT",
    # Euro, not dollars: every hosted image-to-3D endpoint this project has priced
    # bills in EUR (Pixazo's TRELLIS.2 is €0,32/generation), and a column named for
    # a currency it does not hold is a number nobody can add up later.
    "generation_cost_eur": "REAL",
    "generation_duration_s": "REAL",
    "mesh_features": "TEXT",
    "printability_score": "REAL",
    "printability_verdict": "TEXT",
    "printability_report": "TEXT",
    # Blueprint provenance (Phase 1).
    "blueprint_model": "TEXT",
    "blueprint_model_version": "TEXT",
    "blueprint_seed": "INTEGER",
    "blueprint_prompt_engineered": "TEXT",
    "blueprint_params": "TEXT",
    "blueprint_sha256": "TEXT",
    "blueprint_duration_s": "REAL",
    # Mesh lineage (before and after repair).
    "raw_mesh_sha256": "TEXT",
    "raw_mesh_features": "TEXT",
    "repaired_mesh_sha256": "TEXT",
    "repaired_mesh_features": "TEXT",
    # Slicing.
    "slice_status": "TEXT",
    "slice_error": "TEXT",
    "slice_duration_s": "REAL",
    "estimated_print_time_s": "INTEGER",
    "filament_used_mm": "REAL",
    "filament_used_mm3": "REAL",
    "filament_used_g": "REAL",
    "support_filament_mm3": "REAL",
    "layer_count": "INTEGER",
    "slice_stats": "TEXT",
    # Target process and material.
    "material_type": "TEXT",
    "material_brand": "TEXT",
    "material_colour": "TEXT",
    "nozzle_diameter_mm": "REAL",
    "process_params": "TEXT",
    # Lineage and engagement.
    "parent_job_id": "TEXT",
    "regeneration_reason": "TEXT",
    "download_count": "INTEGER DEFAULT 0",
    # Human-reported outcome.
    "outcome_source": "TEXT",
    "outcome_reported_at": "TEXT",
    # Run context and dispatch provenance.
    "git_sha": "TEXT",
    "used_reference_assets": "INTEGER",
    "dispatched_printer_url": "TEXT",
    "repair_report": "TEXT",
    "print_duration_s": "REAL",
}

# The subset stored as JSON text and decoded back into dicts on read.
_PRINT_JOB_JSON_COLUMNS = (
    "generation_params",
    "mesh_features",
    "printability_report",
    "blueprint_params",
    "raw_mesh_features",
    "repaired_mesh_features",
    "slice_stats",
    "process_params",
    "repair_report",
)


# Columns holding a datetime, serialized to ISO 8601 text.
_PRINT_JOB_DATETIME_COLUMNS = ("started_at", "completed_at", "outcome_reported_at")

# The nine columns the table shipped with, in declaration order.
_PRINT_JOB_BASE_COLUMNS = (
    "job_id", "prompt", "printer_id", "printer_firmware", "slicer",
    "profile_name", "started_at", "completed_at", "outcome",
)


def _job_to_row(job: PrintJob) -> dict:
    """Flatten a PrintJob into a column-name → SQL-value mapping.

    Derived from the dataclass fields rather than an explicit column list, so adding a
    field to `PrintJob` and to `_PRINT_JOB_EXTRA_COLUMNS` is all that a new signal
    needs — the INSERT cannot fall out of sync with the schema.

    Args:
        job: The PrintJob to flatten.

    Returns:
        A mapping of column name to a value SQLite can store.
    """
    import dataclasses as _dc

    row = {}
    for field in _dc.fields(job):
        value = getattr(job, field.name)
        if field.name in _PRINT_JOB_JSON_COLUMNS:
            value = _dump_json(value)
        elif field.name in _PRINT_JOB_DATETIME_COLUMNS:
            value = _dt_to_str(value)
        row[field.name] = value
    return row


def _row_to_job(row) -> PrintJob:
    """Rebuild a PrintJob from a print_job row.

    Reads defensively via `.get`: a database migrated mid-session, or a row written by
    an older build, may be missing the newer columns entirely.

    Args:
        row: A `sqlite3.Row` from the print_job table.

    Returns:
        The reconstructed PrintJob.
    """
    import dataclasses as _dc

    keys = {k: row[k] for k in row.keys()}
    kwargs = {}
    for field in _dc.fields(PrintJob):
        value = keys.get(field.name)
        if field.name in _PRINT_JOB_JSON_COLUMNS:
            value = _load_json(value)
        elif field.name in _PRINT_JOB_DATETIME_COLUMNS:
            value = _str_to_dt(value)
        elif value is None and field.default is not _dc.MISSING:
            value = field.default
        kwargs[field.name] = value
    return PrintJob(**kwargs)


def _rename_columns(cursor, table: str, renames: dict[str, str]) -> None:
    """Rename columns that changed name after shipping, preserving their data.

    Must run *before* `_add_missing_columns`, which would otherwise add the new
    name as an empty column beside the old one — leaving the recorded values
    stranded under a name nothing reads. A rename is only attempted when the old
    name is present and the new one is not, so the migration is idempotent and a
    database carrying both (from a half-applied migration) is left alone rather
    than silently losing one of them.

    Args:
        cursor: An open SQLite cursor.
        table: Name of the table to migrate.
        renames: Mapping of old column name to new column name.
    """
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for old, new in renames.items():
        if old in existing and new not in existing:
            logger.info("Migrating %s: renaming column %s to %s", table, old, new)
            cursor.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")


def _add_missing_columns(cursor, table: str, columns: dict[str, str]) -> None:
    """Add any missing columns to a table, leaving existing data untouched.

    Args:
        cursor: An open SQLite cursor.
        table: Name of the table to migrate.
        columns: Mapping of column name to SQL type.
    """
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for name, sql_type in columns.items():
        if name not in existing:
            logger.info("Migrating %s: adding column %s", table, name)
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def _load_json(value):
    """Decode a JSON column, tolerating NULL and malformed values.

    Args:
        value: The raw column value.

    Returns:
        The decoded object, or None when absent or unparseable.
    """
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed JSON column value")
        return None


def _dump_json(value):
    """Encode an object for a JSON column.

    Args:
        value: The object to encode, or None.

    Returns:
        A JSON string, or None when the value is None.
    """
    return None if value is None else json.dumps(value)


class TelemetryDB:
    """Database wrapper for telemetry storage using SQLite."""

    def __init__(self, db_path: str | None = None):
        """Initialize the TelemetryDB.

        Args:
            db_path: The path to the SQLite database. If None, resolves using get_default_db_path().
        """
        if db_path is None:
            db_path = get_default_db_path()

        self.db_path = db_path
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


        self.conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._configure_connection()

    def _configure_connection(self) -> None:
        """Apply the durability pragmas. None of these were set before.

        `busy_timeout` is set explicitly rather than relying on the `timeout=`
        connect argument alone, so it survives anyone constructing a connection by
        another route, and so the value is visible where the reasoning is.

        **WAL is deliberately not enabled**, which is the opposite of the usual
        advice for a multi-process SQLite database. `~/.p2p-mesh` is bind-mounted
        into the containers (`~/.p2p-mesh:/root/.p2p-mesh`), and on macOS those
        containers run inside a Linux VM — so the host process and the pipeline
        container are, as far as file locking is concerned, two different machines
        sharing a file over VirtioFS. SQLite's WAL requires shared memory between
        every process touching the database and does not work across that boundary;
        worse, the journal mode is persisted *in the file*, so switching it on from
        the host would leave the container unable to open the database at all rather
        than merely unable to lock it properly.

        That boundary is also the likeliest explanation for the corruption this
        guards against: `synchronous` was already FULL and there was no hot journal,
        so it was not a crash mid-write — it was two writers whose locks did not see
        each other. Pragmas cannot fix that; only one writer can. `integrity_check`
        below exists so the next occurrence is noticed immediately instead of being
        discovered by a query failing weeks later.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA busy_timeout = 10000")
            # Flush to disk on every commit. Write volume here is a sample every
            # couple of seconds, so the cost is irrelevant next to losing the row.
            cursor.execute("PRAGMA synchronous = FULL")
            # SQLite defaults this to OFF, which made every REFERENCES clause in the
            # schema decorative — the root cause of the orphaned-events incident that
            # count_orphaned_job_events() measures. Per-connection, so it must be set
            # here and not in init_schema. Existing orphans are unaffected (the check
            # runs on write); new child rows for a job that does not exist are refused.
            cursor.execute("PRAGMA foreign_keys = ON")

    def integrity_check(self, max_errors: int = 10) -> list[str]:
        """Check the database for structural damage.

        Args:
            max_errors: Stop after this many problems.

        Returns:
            An empty list when the database is sound, otherwise the problems SQLite
            reports — e.g. `Tree 4 page 4 cell 0: 2nd reference to page 44`, which is
            what a page referenced by two b-trees looks like.

            A database too damaged to answer the question at all reports that as a
            problem rather than raising, because the caller's question — "is this
            usable" — has the same answer either way.
        """
        try:
            with self._lock:
                rows = self.conn.execute(
                    f"PRAGMA integrity_check({int(max_errors)})"
                ).fetchall()
        except sqlite3.DatabaseError as exc:
            return [f"integrity_check could not run: {exc}"]

        problems = [r[0] for r in rows if r[0] != "ok"]
        return problems

    def backup_to(self, destination: str | Path) -> Path:
        """Copy the database to `destination` using SQLite's online backup API.

        Copying the file with `cp` while another process is mid-transaction is one of
        the ways to *produce* a corrupt database. The backup API takes the read lock
        and copies page by page, so the result is a consistent snapshot even under
        concurrent writes.

        Another connection may be mid-write while this runs; that is the case the
        backup API exists for. What it cannot survive is *this* connection holding an
        open write transaction: the copy waits for a lock that only the caller can
        release, and waits forever. That is refused up front, because a clear error
        is worth more than a server that never finishes starting.

        Args:
            destination: Path to write the snapshot to. Parent dirs are created.

        Returns:
            The path written.

        Raises:
            RuntimeError: If this connection has an open transaction.
        """
        if self.conn.in_transaction:
            raise RuntimeError(
                "Cannot snapshot the database while this connection has an open "
                "transaction — commit or roll back first. Backing up regardless "
                "would block on a lock only this caller can release."
            )

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(str(destination))
            try:
                self.conn.backup(target)
            finally:
                target.close()
        return destination

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def init_schema(self) -> None:
        """Create tables if they do not exist (idempotent)."""
        with self._lock:
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
                    started_at TEXT,
                    completed_at TEXT,
                    outcome TEXT NOT NULL
                )
            ''')

            # Migrate existing table if started_at has NOT NULL constraint
            cursor.execute("PRAGMA table_info(print_job)")
            cols = {row[1]: row for row in cursor.fetchall()}
            started_at_col = cols.get("started_at")
            if started_at_col and started_at_col[3] == 1:  # notnull=1 means NOT NULL
                logger.info("Migrating print_job.started_at to allow NULL")
                cursor.execute("ALTER TABLE print_job RENAME TO print_job_old")
                cursor.execute('''
                    CREATE TABLE print_job (
                        job_id TEXT PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        printer_id TEXT NOT NULL,
                        printer_firmware TEXT NOT NULL,
                        slicer TEXT NOT NULL,
                        profile_name TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        outcome TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    INSERT INTO print_job
                    SELECT * FROM print_job_old
                ''')
                cursor.execute("DROP TABLE print_job_old")
                self.conn.commit()
            
            # Add the generation-provenance and printability columns to databases
            # created before they existed. ALTER TABLE ADD COLUMN is the only safe
            # migration here — the started_at migration above copies with SELECT *, so it
            # must keep running against the original nine columns.
            _rename_columns(cursor, "print_job", _PRINT_JOB_RENAMED_COLUMNS)
            _add_missing_columns(cursor, "print_job", _PRINT_JOB_EXTRA_COLUMNS)
            self.conn.commit()

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

            # Telemetry collector claim table.
            #
            # More than one process can legitimately try to collect telemetry for the
            # same job (the API server, pipeline.py's Phase 5 monitor, and
            # run_operator.py all construct collectors). Two collectors writing the
            # same print produces duplicate telemetry_sample rows, which corrupts the
            # dataset. A claim row lets exactly one of them win, across processes.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS telemetry_collector_claim (
                    job_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES print_job (job_id)
                )
            ''')

            # Job engagement events.
            #
            # Downloads, regenerations and feedback prompts are all "did the user do
            # this, and when" signals that nothing else in the system records. Kept as
            # rows rather than columns so that the pilot metric — how often a shown
            # outcome prompt is actually answered — is a query rather than a migration.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS job_event (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT,
                    FOREIGN KEY (job_id) REFERENCES print_job (job_id)
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_event_job_kind "
                "ON job_event (job_id, kind)"
            )

            self.conn.commit()

    def insert_job(self, job: PrintJob) -> None:
        """Insert a PrintJob into the database.

        Args:
            job: The PrintJob object to insert.
        """
        row = _job_to_row(job)
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"INSERT INTO print_job ({columns}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            self.conn.commit()

    def update_job_start_time(self, job_id: str, started_at: datetime) -> None:
        """Update the start time for a print job when the pipeline begins.

        Args:
            job_id: The unique identifier of the job to update.
            started_at: The timestamp when the pipeline actually started.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
            UPDATE print_job
            SET started_at = ?
            WHERE job_id = ?
            ''', (_dt_to_str(started_at), job_id))
            self.conn.commit()

    def update_job_outcome(self, job_id: str, outcome: str, completed_at: datetime) -> None:
        """Update the outcome and completion time for a specific print job.

        Args:
            job_id: The unique identifier of the job to update.
            outcome: The final outcome status of the job.
            completed_at: The timestamp indicating when the job finished.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
            UPDATE print_job
            SET outcome = ?, completed_at = ?
            WHERE job_id = ?
            ''', (outcome, _dt_to_str(completed_at), job_id))
            self.conn.commit()

    def insert_sample(self, sample: TelemetrySample) -> None:
        """Insert a TelemetrySample into the database.

        Args:
            sample: The TelemetrySample object to insert.
        """
        with self._lock:
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

    def update_job_generation(
        self,
        job_id: str,
        model: str | None = None,
        model_version: str | None = None,
        backend: str | None = None,
        params: dict | None = None,
        cost_eur: float | None = None,
        duration_s: float | None = None,
    ) -> None:
        """Record which model produced this job's mesh, and what it cost.

        Only the arguments provided are written, so a hosted-API caller can add cost
        after the fact without clearing the model name.

        Args:
            job_id: The job to update.
            model: Model name, e.g. "TRELLIS.2".
            model_version: Version, revision or endpoint id.
            backend: "local", "remote_worker", "hosted_api" or "unknown".
            params: Generation settings used.
            cost_eur: Charge for this generation in euro, for pay-per-generation
                endpoints.
            duration_s: Wall-clock generation time in seconds.
        """
        updates = {
            "generation_model": model,
            "generation_model_version": model_version,
            "generation_backend": backend,
            "generation_params": _dump_json(params),
            "generation_cost_eur": cost_eur,
            "generation_duration_s": duration_s,
        }
        self._update_job_columns(job_id, updates)

    def update_job_printability(
        self,
        job_id: str,
        score: float | None = None,
        verdict: str | None = None,
        features: dict | None = None,
        report: dict | None = None,
    ) -> None:
        """Record the pre-print printability assessment for a job.

        Args:
            job_id: The job to update.
            score: Composite printability score 0–100.
            verdict: "ready", "risky" or "unprintable".
            features: Mesh feature snapshot.
            report: Full per-check report.
        """
        updates = {
            "printability_score": score,
            "printability_verdict": verdict,
            "mesh_features": _dump_json(features),
            "printability_report": _dump_json(report),
        }
        self._update_job_columns(job_id, updates)

    def update_job_blueprint(
        self,
        job_id: str,
        model: str | None = None,
        model_version: str | None = None,
        seed: int | None = None,
        prompt_engineered: str | None = None,
        params: dict | None = None,
        sha256: str | None = None,
        duration_s: float | None = None,
    ) -> None:
        """Record how this job's blueprint image was produced.

        The seed is the point of this method. It was previously derived from the wall
        clock inside the visualizer and discarded, which made every result in the
        system unreproducible; without it a good print cannot be repeated and two runs
        cannot be compared.

        Args:
            job_id: The job to update.
            model: Text-to-image model name.
            model_version: Model revision or repo id.
            seed: The RNG seed actually used.
            prompt_engineered: The full string fed to the model, suffix included.
            params: Conditioning settings (steps, guidance_scale, width, height).
            sha256: Hash of the blueprint PNG.
            duration_s: Wall-clock generation seconds.
        """
        self._update_job_columns(job_id, {
            "blueprint_model": model,
            "blueprint_model_version": model_version,
            "blueprint_seed": seed,
            "blueprint_prompt_engineered": prompt_engineered,
            "blueprint_params": _dump_json(params),
            "blueprint_sha256": sha256,
            "blueprint_duration_s": duration_s,
        })

    def update_job_mesh_lineage(
        self,
        job_id: str,
        raw_sha256: str | None = None,
        raw_features: dict | None = None,
        repaired_sha256: str | None = None,
        repaired_features: dict | None = None,
        repair_report: dict | None = None,
    ) -> None:
        """Record the mesh before and after repair.

        Stored as hashes plus feature snapshots rather than geometry: the .obj files
        stay on disk under data/outputs, but the row must remain queryable after those
        directories are pruned.

        Args:
            job_id: The job to update.
            raw_sha256: Hash of the sculptor's raw mesh.
            raw_features: Geometry features of the raw mesh.
            repaired_sha256: Hash of the engineered mesh.
            repaired_features: Geometry features of the engineered mesh.
            repair_report: What repair actually did — which path ran, how many
                rounds, whether the volumetric remesh fired, the scale factor.
        """
        self._update_job_columns(job_id, {
            "raw_mesh_sha256": raw_sha256,
            "raw_mesh_features": _dump_json(raw_features),
            "repaired_mesh_sha256": repaired_sha256,
            "repaired_mesh_features": _dump_json(repaired_features),
            "repair_report": _dump_json(repair_report),
        })

    def update_job_run_context(
        self,
        job_id: str,
        git_sha: str | None = None,
        used_reference_assets: bool | None = None,
    ) -> None:
        """Record which code ran this job and whether its inputs were real.

        `used_reference_assets=False` is written as 0, not skipped: "the pipeline
        confirmed no fixture was substituted" is information, and leaving it NULL
        would make a verified-real run indistinguishable from a pre-migration row.

        Args:
            job_id: The job to update.
            git_sha: Short commit hash of the running code.
            used_reference_assets: Whether the bundled dev-reference assets were
                substituted for a missing blueprint or mesh.
        """
        self._update_job_columns(job_id, {
            "git_sha": git_sha,
            "used_reference_assets": (
                None if used_reference_assets is None else int(used_reference_assets)
            ),
        })

    def update_job_dispatch(self, job_id: str, printer_url: str | None = None) -> None:
        """Record the printer base URL the G-code was actually sent to.

        Captured at the moment of dispatch because that is the only moment it is
        true: profiles are resolved on read and edited in place, so nothing else
        can later say whether a row's telemetry came from the simulator on
        localhost:5001 or from real hardware.

        Args:
            job_id: The job to update.
            printer_url: The target's base URL as dispatched.
        """
        self._update_job_columns(job_id, {"dispatched_printer_url": printer_url})

    def update_job_print_duration(self, job_id: str, duration_s: float | None) -> None:
        """Record the printer-reported print duration at its terminal event.

        Deliberately not routed through `update_job_outcome_verdict`: the
        machine-never-overwrites-human guard there would discard the duration
        whenever a person answered before the printer's terminal event arrived,
        and the duration is a measurement, not a verdict.

        Args:
            job_id: The job to update.
            duration_s: Seconds the printer says the print ran.
        """
        self._update_job_columns(job_id, {"print_duration_s": duration_s})

    def update_job_slice(
        self,
        job_id: str,
        status: str | None = None,
        error: str | None = None,
        duration_s: float | None = None,
        estimated_print_time_s: int | None = None,
        filament_used_mm: float | None = None,
        filament_used_mm3: float | None = None,
        filament_used_g: float | None = None,
        support_filament_mm3: float | None = None,
        layer_count: int | None = None,
        stats: dict | None = None,
    ) -> None:
        """Record the slicer's verdict and material estimates.

        Args:
            job_id: The job to update.
            status: "success", "failed" or "skipped".
            error: Slicer error text when the slice failed.
            duration_s: Wall-clock slicing seconds.
            estimated_print_time_s: Slicer print time estimate.
            filament_used_mm: Filament length extruded.
            filament_used_mm3: Filament volume extruded.
            filament_used_g: Filament mass, when the material is known.
            support_filament_mm3: Volume spent on supports.
            layer_count: Number of layers.
            stats: Full `SliceStats.to_dict()` payload.
        """
        self._update_job_columns(job_id, {
            "slice_status": status,
            "slice_error": error,
            "slice_duration_s": duration_s,
            "estimated_print_time_s": estimated_print_time_s,
            "filament_used_mm": filament_used_mm,
            "filament_used_mm3": filament_used_mm3,
            "filament_used_g": filament_used_g,
            "support_filament_mm3": support_filament_mm3,
            "layer_count": layer_count,
            "slice_stats": _dump_json(stats),
        })

    def update_job_outcome_verdict(
        self,
        job_id: str,
        outcome: str,
        source: str,
        completed_at: datetime | None = None,
        reported_at: datetime | None = None,
    ) -> None:
        """Record a print outcome together with who decided it.

        Unlike `update_job_outcome`, this writes `outcome_source`, distinguishing a
        human's "it came off the bed" from the printer merely reaching the end of the
        file. Only the former is ground truth for training or evaluation.

        A machine write never overwrites a human one. Printer events can arrive long
        after someone has already answered, and replacing "I watched it fail" with "the
        file finished" would destroy the only reliable label on the row. The rule lives
        here rather than at each call site because there are several machine writers —
        the pipeline, the OctoPrint collector, the cancel endpoint — and any one of them
        forgetting it silently corrupts the dataset.

        Args:
            job_id: The job to update.
            outcome: The outcome value to store.
            source: "machine" or "user".
            completed_at: When the job finished, if it is being closed out now.
            reported_at: When the verdict was given; defaults to now for user reports.
        """
        if source == "machine":
            existing = self.get_job(job_id)
            if existing is not None and existing.outcome_source == "user":
                logger.info(
                    "Job %s already has a user-reported outcome (%s); ignoring machine "
                    "outcome %s", job_id, existing.outcome, outcome,
                )
                return

        if source == "user" and reported_at is None:
            reported_at = datetime.now(timezone.utc)
        # outcome is written unconditionally: _update_job_columns skips None, and an
        # outcome always has a value, so no branch is needed here.
        self._update_job_columns(job_id, {
            "outcome": outcome,
            "outcome_source": source,
            "completed_at": _dt_to_str(completed_at),
            "outcome_reported_at": _dt_to_str(reported_at),
        })

    # ── Job events ────────────────────────────────────────────────────────────
    def insert_job_event(self, event: JobEvent) -> None:
        """Insert an engagement event for a job.

        Args:
            event: The JobEvent to store.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO job_event (event_id, job_id, occurred_at, kind, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.job_id,
                    _dt_to_str(event.occurred_at),
                    event.kind,
                    _dump_json(event.detail),
                ),
            )
            self.conn.commit()

    def record_job_event(self, job_id: str, kind: str, detail: dict | None = None) -> JobEvent:
        """Build, store and return a job event stamped with the current time.

        Args:
            job_id: The job the event belongs to.
            kind: One of `JOB_EVENT_KINDS`.
            detail: Optional event-specific payload.

        Returns:
            The stored JobEvent.
        """
        event = JobEvent(
            event_id=str(uuid.uuid4()),
            job_id=job_id,
            occurred_at=datetime.now(timezone.utc),
            kind=kind,
            detail=detail,
        )
        self.insert_job_event(event)
        return event

    def get_job_events(self, job_id: str, kind: str | None = None) -> list[JobEvent]:
        """Retrieve a job's engagement events in chronological order.

        Args:
            job_id: The job to look up.
            kind: Restrict to a single event kind when given.

        Returns:
            A list of JobEvent objects, oldest first.
        """
        sql = "SELECT * FROM job_event WHERE job_id = ?"
        params: list = [job_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY occurred_at ASC"

        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

        return [
            JobEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                occurred_at=_str_to_dt(row["occurred_at"]),  # type: ignore
                kind=row["kind"],
                detail=_load_json(row["detail"]),
            )
            for row in rows
        ]

    def count_job_events(self, kind: str) -> int:
        """Count events of one kind across all jobs that still exist.

        The join is not decoration. `job_event` has no foreign key onto `print_job`,
        so deleting a job leaves its events behind — a test-suite bug once removed
        312 job rows and left 411 events pointing at nothing, and every one of them
        went on being counted in the pilot's headline response rate. An event whose
        job is gone describes nobody, so it is not counted.

        Args:
            kind: The event kind to count.

        Returns:
            The number of matching events belonging to a job that still exists.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM job_event e "
                "JOIN print_job j ON j.job_id = e.job_id WHERE e.kind = ?",
                (kind,),
            )
            return int(cursor.fetchone()[0])

    def count_orphaned_job_events(self) -> int:
        """Events whose job no longer exists.

        Exposed so the debris is measurable rather than merely excluded — a non-zero
        count means something deleted jobs without their events.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM job_event e "
                "LEFT JOIN print_job j ON j.job_id = e.job_id WHERE j.job_id IS NULL"
            )
            return int(cursor.fetchone()[0])

    def feedback_funnel(self) -> dict:
        """Count how many prompted jobs actually got an answer.

        Counted over *jobs that were prompted*, not raw event totals. A verdict can be
        given through a path that never showed a prompt — opening a job directly, for
        instance — so dividing total reports by total prompts can exceed 1 and stops
        meaning anything. The denominator here is the set of people who were asked.

        Returns:
            A mapping with `prompted`, `answered`, `dismissed` and `unanswered` job
            counts. `answered` and `dismissed` are subsets of `prompted`.
        """
        def distinct_jobs(cursor, kind: str) -> set:
            # Joined to `print_job` so an event orphaned by a deleted job cannot
            # contribute. Without it this rate is computed over jobs that no longer
            # exist: on one real database it reported 114 prompted / 46 answered —
            # a confident 40% — when every one of those jobs had been deleted and
            # the honest answer was "no data yet".
            cursor.execute(
                "SELECT DISTINCT e.job_id FROM job_event e "
                "JOIN print_job j ON j.job_id = e.job_id WHERE e.kind = ?",
                (kind,),
            )
            return {row[0] for row in cursor.fetchall()}

        with self._lock:
            cursor = self.conn.cursor()
            prompted = distinct_jobs(cursor, "outcome_prompt_shown")
            answered = distinct_jobs(cursor, "outcome_reported") & prompted
            dismissed = distinct_jobs(cursor, "outcome_prompt_dismissed") & prompted

        return {
            "prompted": len(prompted),
            "answered": len(answered),
            # A job can be dismissed and later answered; the two overlap by design.
            "dismissed": len(dismissed - answered),
            "unanswered": len(prompted - answered),
        }

    def increment_download_count(self, job_id: str) -> None:
        """Bump a job's denormalised download counter.

        The authoritative per-download records are `job_event` rows; this column exists
        so the common "was this ever downloaded" query needs no join.

        Args:
            job_id: The job that was downloaded.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE print_job SET download_count = COALESCE(download_count, 0) + 1 "
                "WHERE job_id = ?",
                (job_id,),
            )
            self.conn.commit()

    def get_jobs_awaiting_verdict(self, limit: int = 50) -> list[PrintJob]:
        """Retrieve jobs whose printer finished but whose outcome no human has confirmed.

        Args:
            limit: Maximum number of jobs to return.

        Returns:
            PrintJob rows in `awaiting_verdict`, most recently completed first.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM print_job WHERE outcome = 'awaiting_verdict' "
                "ORDER BY completed_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        return [_row_to_job(row) for row in rows]

    def _update_job_columns(self, job_id: str, updates: dict) -> None:
        """Write the non-None entries of `updates` to a print_job row.

        Args:
            job_id: The job to update.
            updates: Mapping of column name to value; None values are skipped so a
                partial update never erases a previously recorded field.
        """
        fields = {k: v for k, v in updates.items() if v is not None}
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"UPDATE print_job SET {assignments} WHERE job_id = ?",
                (*fields.values(), job_id),
            )
            self.conn.commit()

    # ── Collector claims ──────────────────────────────────────────────────────
    def try_claim_collector(self, job_id: str, owner: str, stale_after_s: float = 120.0) -> bool:
        """Try to become the single telemetry collector for a job.

        The claim is taken by whichever collector calls this first, and is only taken
        over from a previous owner once that owner has stopped sending heartbeats for
        ``stale_after_s``. Claiming at the point where telemetry actually arrives (not
        at connect time) means a collector that cannot authenticate or reach the
        printer never takes the claim away from one that can.

        Args:
            job_id: The job being collected.
            owner: Stable identifier for the claiming collector.
            stale_after_s: Seconds without a heartbeat before a claim can be taken over.

        Returns:
            True if this owner now holds the claim, False if another owner holds it.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT owner, heartbeat_at FROM telemetry_collector_claim WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()

            if row is not None:
                current_owner = row["owner"]
                if current_owner == owner:
                    cursor.execute(
                        "UPDATE telemetry_collector_claim SET heartbeat_at = ? WHERE job_id = ?",
                        (_dt_to_str(now), job_id),
                    )
                    self.conn.commit()
                    return True

                last_beat = _str_to_dt(row["heartbeat_at"])
                if last_beat is not None and (now - last_beat).total_seconds() < stale_after_s:
                    return False

                logger.warning(
                    "Taking over stale telemetry claim for job %s from %s", job_id, current_owner
                )
                cursor.execute(
                    "UPDATE telemetry_collector_claim SET owner = ?, claimed_at = ?, heartbeat_at = ? "
                    "WHERE job_id = ?",
                    (owner, _dt_to_str(now), _dt_to_str(now), job_id),
                )
                self.conn.commit()
                return True

            try:
                cursor.execute(
                    "INSERT INTO telemetry_collector_claim (job_id, owner, claimed_at, heartbeat_at) "
                    "VALUES (?, ?, ?, ?)",
                    (job_id, owner, _dt_to_str(now), _dt_to_str(now)),
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Another process inserted between the SELECT and the INSERT.
                return False

    def release_collector_claim(self, job_id: str, owner: str) -> None:
        """Release a job's collector claim, if this owner still holds it.

        Args:
            job_id: The job whose claim should be released.
            owner: The claiming collector's identifier.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "DELETE FROM telemetry_collector_claim WHERE job_id = ? AND owner = ?",
                (job_id, owner),
            )
            self.conn.commit()

    def get_collector_claim(self, job_id: str) -> Optional[str]:
        """Return the owner currently holding a job's collector claim, if any.

        Args:
            job_id: The job to look up.

        Returns:
            The owner identifier, or None if the job is unclaimed.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT owner FROM telemetry_collector_claim WHERE job_id = ?", (job_id,)
            )
            row = cursor.fetchone()
            return row["owner"] if row else None

    def insert_failure_event(self, event: FailureEvent) -> None:
        """Insert a FailureEvent into the database.

        Args:
            event: The FailureEvent object to insert.
        """
        with self._lock:
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
        """Retrieve a PrintJob by ID, or None if not found.

        Args:
            job_id: The unique identifier of the job to retrieve.

        Returns:
            The corresponding PrintJob if it exists, otherwise None.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM print_job WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            if not row:
                return None

        return _row_to_job(row)

    def get_samples(self, job_id: str, limit: int = 500) -> list[TelemetrySample]:
        """Retrieve TelemetrySamples for a specific print job.

        Args:
            job_id: The unique identifier of the job.
            limit: The maximum number of samples to retrieve. Defaults to 500.

        Returns:
            A list of TelemetrySample objects ordered by timestamp ascending.
        """
        with self._lock:
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
        """Retrieve FailureEvents for a specific print job.

        Args:
            job_id: The unique identifier of the job.

        Returns:
            A list of FailureEvent objects associated with the given job.
        """
        with self._lock:
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
