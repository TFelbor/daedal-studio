"""Telemetry storage on PostgreSQL — Supabase in every deployed mode.

The database is the product's dataset, and it used to be one SQLite file bind-mounted
into containers. That file corrupted once: a host process and a Linux VM sharing it
over VirtioFS are two machines as far as file locking goes, which SQLite does not
support for concurrent writers. Everything this module grew afterwards — integrity
checks, snapshots, a mirror, "WAL deliberately off" — compensated for the storage.
A network PostgreSQL removes the failure class instead, so all of that is gone.

Three things about the shape of this module are load-bearing:

* **One URL, no default.** `DS_DATABASE_URL` is the only way to name the database.
  An unset value raises `DatabaseConfigError` rather than falling back to anything,
  because a silent default is how a month of rows once landed in a database nobody
  could see.
* **One pool per process per URL.** `TelemetryDB` is constructed dozens of times per
  request cycle across the server, the pipeline and the collectors; each instance
  borrows a connection from a shared `psycopg_pool.ConnectionPool` for the duration
  of one operation and hands it back. `close()` is therefore a no-op kept for the
  callers that already pair it with construction. Prepared statements are disabled so
  the same code works behind Supabase's transaction pooler.
* **Typed columns.** JSON payloads are `JSONB`, timestamps are `TIMESTAMPTZ`, so a
  malformed JSON blob is refused at write time and ordering by time is ordering by
  time. `_row_to_job` still reads defensively — a row written by an older build may
  lack newer columns.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pythonsrc.telemetry.schema import FailureEvent, JobEvent, PrintJob, TelemetrySample

logger = logging.getLogger(__name__)

#: Re-exported so callers and tests can name the driver's failures without importing
#: it — `IntegrityError` covers a foreign-key or unique violation, `OperationalError`
#: an unreachable or dropped connection, `DatabaseError` anything the driver raises.
DatabaseError = psycopg.Error
OperationalError = psycopg.OperationalError
IntegrityError = psycopg.IntegrityError

#: The one environment variable naming the database.
DATABASE_URL_ENV = "DS_DATABASE_URL"
#: Upper bound on pooled connections per process. Supabase's direct connection limit
#: is shared by every process talking to the project, so this stays small.
POOL_MAX_ENV = "DS_DATABASE_POOL_MAX"
DEFAULT_POOL_MAX = 6
#: Seconds a caller waits for a connection before the operation fails. Ten, not the
#: pool's default thirty: a request that hangs half a minute on a dead database is
#: worse than one that fails and says why.
POOL_TIMEOUT_ENV = "DS_DATABASE_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 10.0

#: Every table this module owns, in dependency order. `health_check` verifies each is
#: present; the migration file lists them in this order.
TELEMETRY_TABLES = (
    "print_job",
    "telemetry_sample",
    "failure_event",
    "telemetry_collector_claim",
    "job_event",
)
#: The config store's table, kept here so one schema renderer covers the whole
#: database — `server/config_store.py` imports its DDL from here.
CONFIG_TABLE = "app_config"

#: Advisory lock key serialising concurrent `init_schema` calls. Two processes running
#: `CREATE TABLE IF NOT EXISTS` at the same instant can both pass the existence check
#: and one then fails on the catalogue's unique index; the lock makes them queue.
_SCHEMA_LOCK_KEY = 7314159


class DatabaseConfigError(RuntimeError):
    """The database is not configured, as opposed to not reachable."""


def get_database_url() -> str:
    """Return the PostgreSQL URL from `$DS_DATABASE_URL`.

    Raises:
        DatabaseConfigError: If the variable is unset or blank. There is deliberately
            no fallback: the previous storage had one, and it split native runs and
            container runs across two databases without anything saying so.
    """
    raw = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not raw:
        raise DatabaseConfigError(
            f"{DATABASE_URL_ENV} is not set. Point it at the Supabase project's "
            "PostgreSQL connection string (Project Settings → Database → Connection "
            "string; use the *session* pooler or the direct connection), e.g. "
            "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
        )
    return raw


def redact_dsn(dsn: str) -> str:
    """The connection string with its password removed, for logs and errors."""
    try:
        parts = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        return "<unparseable database URL>"
    if "password" in parts:
        parts["password"] = "***"
    return make_conninfo(**parts)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Connection pooling ─────────────────────────────────────────────────────────

_POOLS: dict[str, ConnectionPool] = {}
_POOLS_LOCK = threading.Lock()


def _configure_connection(conn: psycopg.Connection) -> None:
    """Run once per new pooled connection.

    UTC is pinned per session rather than per URL so a test URL carrying its own
    `options=` (the per-test schema) is not overridden, and so the datetimes psycopg
    hands back are always UTC-aware regardless of the server's default.
    """
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()


def _pool_for(dsn: str) -> ConnectionPool:
    """The shared pool for `dsn`, created on first use."""
    with _POOLS_LOCK:
        pool = _POOLS.get(dsn)
        if pool is not None and not pool.closed:
            return pool
        timeout = _env_float(POOL_TIMEOUT_ENV, DEFAULT_TIMEOUT_S)
        pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=max(2, _env_int(POOL_MAX_ENV, DEFAULT_POOL_MAX)),
            timeout=timeout,
            open=True,
            configure=_configure_connection,
            # Validated on checkout, so a connection Supabase closed while idle is
            # replaced rather than handed to the caller to fail on.
            check=ConnectionPool.check_connection,
            kwargs={
                "row_factory": dict_row,
                # No server-side prepared statements: Supabase's transaction pooler
                # multiplexes sessions and does not support them.
                "prepare_threshold": None,
                "connect_timeout": max(1, int(timeout)),
                "application_name": "ds-mvp",
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
            },
            name=f"ds-mvp-{len(_POOLS) + 1}",
        )
        _POOLS[dsn] = pool
        logger.debug("Opened connection pool for %s", redact_dsn(dsn))
        return pool


@contextmanager
def connection(dsn: str) -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection for one unit of work.

    Commits on a clean exit and rolls back on an exception, then returns the
    connection to the pool — the same contract the SQLite handle's `with` had.
    """
    pool = _pool_for(dsn)
    with pool.connection() as conn:
        yield conn


def close_pools() -> None:
    """Close every pool this process opened. For tests and orderly shutdown."""
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        try:
            pool.close()
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            logger.debug("Closing a connection pool failed: %s", exc)


def close_pool(dsn: str) -> None:
    """Close the pool for one URL, if it exists."""
    with _POOLS_LOCK:
        pool = _POOLS.pop(dsn, None)
    if pool is not None:
        pool.close()


# ── Column maps ───────────────────────────────────────────────────────────────

#: The nine columns the table shipped with, in declaration order, with their types.
_PRINT_JOB_BASE_DDL = (
    ("job_id", "TEXT PRIMARY KEY"),
    ("prompt", "TEXT NOT NULL"),
    ("printer_id", "TEXT NOT NULL"),
    ("printer_firmware", "TEXT NOT NULL"),
    ("slicer", "TEXT NOT NULL"),
    ("profile_name", "TEXT NOT NULL"),
    ("started_at", "TIMESTAMPTZ"),
    ("completed_at", "TIMESTAMPTZ"),
    ("outcome", "TEXT NOT NULL"),
)
_PRINT_JOB_BASE_COLUMNS = tuple(name for name, _ in _PRINT_JOB_BASE_DDL)

# Columns added to print_job after the original schema shipped. Kept as data so the
# CREATE, the additive migration and the INSERT stay in sync: a new capture column is
# one entry here plus a field on `PrintJob` (and a stage in `trace.STAGES`).
_PRINT_JOB_EXTRA_COLUMNS = {
    "generation_model": "TEXT",
    "generation_model_version": "TEXT",
    "generation_backend": "TEXT",
    "generation_params": "JSONB",
    # Euro, not dollars: every hosted image-to-3D endpoint this project has priced
    # bills in EUR (Pixazo's TRELLIS.2 is €0,32/generation), and a column named for
    # a currency it does not hold is a number nobody can add up later.
    "generation_cost_eur": "DOUBLE PRECISION",
    "generation_duration_s": "DOUBLE PRECISION",
    "mesh_features": "JSONB",
    "printability_score": "DOUBLE PRECISION",
    "printability_verdict": "TEXT",
    "printability_report": "JSONB",
    # Blueprint provenance (Phase 1).
    "blueprint_model": "TEXT",
    "blueprint_model_version": "TEXT",
    "blueprint_seed": "BIGINT",
    "blueprint_prompt_engineered": "TEXT",
    "blueprint_params": "JSONB",
    "blueprint_sha256": "TEXT",
    "blueprint_duration_s": "DOUBLE PRECISION",
    # Mesh lineage (before and after repair).
    "raw_mesh_sha256": "TEXT",
    "raw_mesh_features": "JSONB",
    "repaired_mesh_sha256": "TEXT",
    "repaired_mesh_features": "JSONB",
    # Slicing.
    "slice_status": "TEXT",
    "slice_error": "TEXT",
    "slice_duration_s": "DOUBLE PRECISION",
    "estimated_print_time_s": "BIGINT",
    "filament_used_mm": "DOUBLE PRECISION",
    "filament_used_mm3": "DOUBLE PRECISION",
    "filament_used_g": "DOUBLE PRECISION",
    "support_filament_mm3": "DOUBLE PRECISION",
    "layer_count": "INTEGER",
    "slice_stats": "JSONB",
    # Target process and material.
    "material_type": "TEXT",
    "material_brand": "TEXT",
    "material_colour": "TEXT",
    "nozzle_diameter_mm": "DOUBLE PRECISION",
    "process_params": "JSONB",
    # The submitted request, so a gated run can be resumed by another process.
    "request_params": "JSONB",
    # Requested size.
    "requested_size_mm": "DOUBLE PRECISION",
    "size_source": "TEXT",
    "requested_scale_axis": "TEXT",
    # Lineage and engagement.
    "parent_job_id": "TEXT",
    "regeneration_reason": "TEXT",
    "download_count": "INTEGER DEFAULT 0",
    # Human-reported outcome.
    "outcome_source": "TEXT",
    "outcome_reported_at": "TIMESTAMPTZ",
    # Run context and dispatch provenance.
    "git_sha": "TEXT",
    "used_reference_assets": "INTEGER",
    "dispatched_printer_url": "TEXT",
    "repair_report": "JSONB",
    "print_duration_s": "DOUBLE PRECISION",
    # The fit photo a person took of the printed part. Evidence, not a verdict —
    # see `update_job_fit_photo`.
    "fit_photo_path": "TEXT",
}

#: The subset stored as JSONB and decoded back into dicts on read.
_PRINT_JOB_JSON_COLUMNS = tuple(
    name for name, sql_type in _PRINT_JOB_EXTRA_COLUMNS.items() if sql_type == "JSONB"
)

#: Columns holding a datetime.
_PRINT_JOB_DATETIME_COLUMNS = ("started_at", "completed_at", "outcome_reported_at")


# ── Schema ────────────────────────────────────────────────────────────────────

def _print_job_ddl() -> str:
    columns = [f"    {name} {sql_type}" for name, sql_type in _PRINT_JOB_BASE_DDL]
    columns += [f"    {name} {sql_type}" for name, sql_type in _PRINT_JOB_EXTRA_COLUMNS.items()]
    return "CREATE TABLE IF NOT EXISTS print_job (\n" + ",\n".join(columns) + "\n)"


CONFIG_TABLE_DDL = (
    f"CREATE TABLE IF NOT EXISTS {CONFIG_TABLE} (\n"
    "    key TEXT PRIMARY KEY,\n"
    "    value_encrypted BYTEA,\n"
    "    updated_at TIMESTAMPTZ\n"
    ")"
)


def schema_statements(include_config: bool = True) -> list[str]:
    """Every DDL statement the database needs, idempotent and in dependency order.

    This is the single source: `init_schema` executes it, and
    `supabase/migrations/*_telemetry_schema.sql` is rendered from it by
    `render_schema_sql`, with a guard test keeping the two identical.

    Row-level security is enabled on every table with no policies. Supabase exposes
    the `public` schema through PostgREST to its `anon` and `authenticated` roles;
    with RLS on and no policy those roles see nothing, while this project's server,
    connecting as the tables' owner, is unaffected.

    Args:
        include_config: Also emit the encrypted config store's table.
    """
    statements = [
        _print_job_ddl(),
        "CREATE INDEX IF NOT EXISTS idx_print_job_started_at ON print_job (started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_print_job_outcome ON print_job (outcome)",
        # A sample every second or so per print; the collectors and the UI read them by
        # job, most recent first.
        "CREATE TABLE IF NOT EXISTS telemetry_sample (\n"
        "    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,\n"
        "    job_id TEXT NOT NULL,\n"
        "    sampled_at TIMESTAMPTZ NOT NULL,\n"
        "    gcode_line BIGINT,\n"
        "    z_height_mm DOUBLE PRECISION,\n"
        "    hotend_actual_c DOUBLE PRECISION,\n"
        "    hotend_target_c DOUBLE PRECISION,\n"
        "    bed_actual_c DOUBLE PRECISION,\n"
        "    bed_target_c DOUBLE PRECISION,\n"
        "    print_speed_pct DOUBLE PRECISION,\n"
        "    extrusion_factor_pct DOUBLE PRECISION,\n"
        "    fan_speed_pct DOUBLE PRECISION,\n"
        "    CONSTRAINT telemetry_sample_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)\n"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_sample_job_time "
        "ON telemetry_sample (job_id, sampled_at)",
        "CREATE TABLE IF NOT EXISTS failure_event (\n"
        "    event_id TEXT PRIMARY KEY,\n"
        "    job_id TEXT NOT NULL,\n"
        "    detected_at TIMESTAMPTZ NOT NULL,\n"
        "    gcode_line BIGINT,\n"
        "    z_height_mm DOUBLE PRECISION,\n"
        "    failure_type TEXT NOT NULL,\n"
        "    source TEXT NOT NULL,\n"
        "    notes TEXT,\n"
        "    snapshot JSONB NOT NULL,\n"
        "    CONSTRAINT failure_event_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)\n"
        ")",
        # More than one process can legitimately try to collect telemetry for the same
        # job (the API server, pipeline.py's Phase 5 monitor, run_operator.py). A claim
        # row lets exactly one of them win, across processes.
        # PostgreSQL does not index a foreign key's referencing column by itself; every
        # read here is by job.
        "CREATE INDEX IF NOT EXISTS idx_failure_event_job ON failure_event (job_id)",
        "CREATE TABLE IF NOT EXISTS telemetry_collector_claim (\n"
        "    job_id TEXT PRIMARY KEY,\n"
        "    owner TEXT NOT NULL,\n"
        "    claimed_at TIMESTAMPTZ NOT NULL,\n"
        "    heartbeat_at TIMESTAMPTZ NOT NULL,\n"
        "    CONSTRAINT telemetry_collector_claim_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)\n"
        ")",
        # Downloads, regenerations and feedback prompts are all "did the user do this,
        # and when" signals. Rows rather than columns, so the pilot metric — how often a
        # shown outcome prompt is answered — is a query rather than a migration.
        "CREATE TABLE IF NOT EXISTS job_event (\n"
        "    event_id TEXT PRIMARY KEY,\n"
        "    job_id TEXT NOT NULL,\n"
        "    occurred_at TIMESTAMPTZ NOT NULL,\n"
        "    kind TEXT NOT NULL,\n"
        "    detail JSONB,\n"
        "    CONSTRAINT job_event_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)\n"
        ")",
        "CREATE INDEX IF NOT EXISTS idx_job_event_job_kind ON job_event (job_id, kind)",
    ]
    tables = list(TELEMETRY_TABLES)
    if include_config:
        statements.append(CONFIG_TABLE_DDL)
        tables.append(CONFIG_TABLE)
    statements += [f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" for table in tables]
    return statements


def render_schema_sql() -> str:
    """The schema as one SQL script, for `supabase/migrations/`."""
    header = (
        "-- Telemetry schema for Daedal Studio (ds-mvp).\n"
        "--\n"
        "-- GENERATED from pythonsrc/telemetry/db.py: `python -m pythonsrc.telemetry.db --ddl`.\n"
        "-- Do not edit by hand; tests/test_supabase_migration.py fails if this file and the\n"
        "-- code disagree. Every statement is idempotent, and the server runs the same DDL\n"
        "-- on startup, so applying this file is optional but keeps Supabase's migration\n"
        "-- history truthful.\n\n"
    )
    return header + ";\n\n".join(schema_statements()) + ";\n"


# ── Value adapters ────────────────────────────────────────────────────────────

def _dt_param(dt: datetime | None) -> datetime | None:
    """A datetime as a query parameter.

    psycopg adapts datetimes natively, so this is the identity — kept as a named
    seam because the claim tests interleave a rival connection exactly here, between
    the SELECT that read a claim and the UPDATE that acts on it.
    """
    return dt


def _str_to_dt(value: datetime | str | None) -> datetime | None:
    """A TIMESTAMPTZ value as a datetime, tolerating the ISO text older callers pass."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _load_json(value: Any) -> Any:
    """Decode a JSONB column, tolerating NULL and a legacy text payload.

    JSONB arrives already decoded; text is only seen when a caller passes a string
    through, and a malformed one degrades to None rather than failing the read.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed JSON column value")
        return None


def _json_param(value: Any) -> Jsonb | None:
    """An object as a JSONB parameter, or NULL for None."""
    return None if value is None else Jsonb(value)


def _job_to_row(job: PrintJob) -> dict[str, Any]:
    """Flatten a PrintJob into a column-name → parameter mapping.

    Derived from the dataclass fields rather than an explicit column list, so adding a
    field to `PrintJob` and to `_PRINT_JOB_EXTRA_COLUMNS` is all that a new signal
    needs — the INSERT cannot fall out of sync with the schema.
    """
    row: dict[str, Any] = {}
    for field in dataclasses.fields(job):
        value = getattr(job, field.name)
        if field.name in _PRINT_JOB_JSON_COLUMNS:
            value = _json_param(value)
        elif field.name in _PRINT_JOB_DATETIME_COLUMNS:
            value = _dt_param(value)
        elif isinstance(value, bool):
            # No column is boolean; SQLite stored a bool as 0/1 and PostgreSQL would
            # refuse it against an INTEGER column.
            value = int(value)
        row[field.name] = value
    return row


def _row_to_job(row: dict[str, Any]) -> PrintJob:
    """Rebuild a PrintJob from a print_job row.

    Reads defensively via `.get`: a database migrated mid-session, or a row written by
    an older build, may be missing the newer columns entirely.
    """
    keys = dict(row)
    kwargs = {}
    for field in dataclasses.fields(PrintJob):
        value = keys.get(field.name)
        if field.name in _PRINT_JOB_JSON_COLUMNS:
            value = _load_json(value)
        elif field.name in _PRINT_JOB_DATETIME_COLUMNS:
            value = _str_to_dt(value)
        elif value is None and field.default is not dataclasses.MISSING:
            value = field.default
        kwargs[field.name] = value
    return PrintJob(**kwargs)


def _existing_columns(cursor: psycopg.Cursor, table: str) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {row["column_name"] for row in cursor.fetchall()}


def _add_missing_columns(cursor: psycopg.Cursor, table: str, columns: dict[str, str]) -> None:
    """Add any missing columns to a table, leaving existing data untouched.

    The one migration this module performs. A column added to
    `_PRINT_JOB_EXTRA_COLUMNS` reaches an existing database here; a fresh database
    gets it from the CREATE.
    """
    existing = _existing_columns(cursor, table)
    for name, sql_type in columns.items():
        if name not in existing:
            logger.info("Migrating %s: adding column %s", table, name)
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {sql_type}")


# ── The database ──────────────────────────────────────────────────────────────

class TelemetryDB:
    """Telemetry storage, one operation per borrowed pooled connection."""

    def __init__(self, dsn: str | None = None):
        """Bind to a database.

        Args:
            dsn: PostgreSQL connection URL. Defaults to `$DS_DATABASE_URL`.

        Raises:
            DatabaseConfigError: If no URL is given and the variable is unset.
        """
        self.dsn = dsn if dsn is not None else get_database_url()

    @property
    def describe(self) -> str:
        """The connection string with its password removed."""
        return redact_dsn(self.dsn)

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor]:
        """One transaction on a pooled connection; committed on clean exit."""
        with connection(self.dsn) as conn:
            with conn.cursor() as cur:
                yield cur

    def close(self) -> None:
        """Kept for callers pairing it with construction; the pool owns connections."""

    # ── Raw access ────────────────────────────────────────────────────────────

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return every row as a dict."""
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())

    def query_one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        """Run a SELECT and return the first row as a dict, or None."""
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        """Run a statement in its own transaction and return the row count."""
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount

    def table_columns(self, table: str) -> set[str]:
        """The column names of `table` in the current schema."""
        with self._cursor() as cur:
            return _existing_columns(cur, table)

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> list[str]:
        """Is the database reachable and does it carry the schema?

        Returns:
            An empty list when the database answers and every table in
            `TELEMETRY_TABLES` exists; otherwise one string per problem. A missing
            table is reported as `missing table: <name>` so a caller can tell "run
            init_schema" from "the network is down". Never raises: the caller's
            question is "is this usable", and an unreachable server answers it.
        """
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
                present = {row["table_name"] for row in cur.fetchall()}
        except Exception as exc:  # noqa: BLE001 — every failure is the same answer
            return [f"cannot reach the telemetry database ({self.describe}): {exc}"]
        return [f"missing table: {name}" for name in TELEMETRY_TABLES if name not in present]

    # ── Schema ────────────────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """Create tables that do not exist and add columns that are missing (idempotent)."""
        with self._cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            for statement in schema_statements(include_config=False):
                cur.execute(statement)
            _add_missing_columns(cur, "print_job", _PRINT_JOB_EXTRA_COLUMNS)

    # ── Jobs ──────────────────────────────────────────────────────────────────

    def insert_job(self, job: PrintJob) -> None:
        """Insert a PrintJob."""
        row = _job_to_row(job)
        columns = ", ".join(row)
        placeholders = ", ".join("%s" for _ in row)
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO print_job ({columns}) VALUES ({placeholders})",
                tuple(row.values()),
            )

    def update_job_start_time(self, job_id: str, started_at: datetime) -> None:
        """Record when the job began — the first time, and only the first time.

        First-write-wins because a job can be launched more than once for the same row:
        the blueprint approval gate resumes it as a second subprocess, and the dispatch
        gate runs the operator as a third. `started_at` means "when this job began",
        and a later invocation overwriting it destroys the only record of that, which
        also makes every duration computed against it wrong.
        """
        with self._cursor() as cur:
            cur.execute(
                "UPDATE print_job SET started_at = %s WHERE job_id = %s AND started_at IS NULL",
                (_dt_param(started_at), job_id),
            )

    def update_job_outcome(self, job_id: str, outcome: str, completed_at: datetime) -> None:
        """Update the outcome and completion time for a job."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE print_job SET outcome = %s, completed_at = %s WHERE job_id = %s",
                (outcome, _dt_param(completed_at), job_id),
            )

    def insert_sample(self, sample: TelemetrySample) -> None:
        """Insert a TelemetrySample."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO telemetry_sample ("
                "    job_id, sampled_at, gcode_line, z_height_mm,"
                "    hotend_actual_c, hotend_target_c, bed_actual_c, bed_target_c,"
                "    print_speed_pct, extrusion_factor_pct, fan_speed_pct"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    sample.job_id, _dt_param(sample.sampled_at), sample.gcode_line,
                    sample.z_height_mm, sample.hotend_actual_c, sample.hotend_target_c,
                    sample.bed_actual_c, sample.bed_target_c, sample.print_speed_pct,
                    sample.extrusion_factor_pct, sample.fan_speed_pct,
                ),
            )

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
        """
        self._update_job_columns(job_id, {
            "generation_model": model,
            "generation_model_version": model_version,
            "generation_backend": backend,
            "generation_params": _json_param(params),
            "generation_cost_eur": cost_eur,
            "generation_duration_s": duration_s,
        })

    def update_job_printability(
        self,
        job_id: str,
        score: float | None = None,
        verdict: str | None = None,
        features: dict | None = None,
        report: dict | None = None,
    ) -> None:
        """Record the pre-print printability assessment for a job."""
        self._update_job_columns(job_id, {
            "printability_score": score,
            "printability_verdict": verdict,
            "mesh_features": _json_param(features),
            "printability_report": _json_param(report),
        })

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

        The seed is the point of this method: derived from the wall clock and
        discarded, it made every result unreproducible.
        """
        self._update_job_columns(job_id, {
            "blueprint_model": model,
            "blueprint_model_version": model_version,
            "blueprint_seed": seed,
            "blueprint_prompt_engineered": prompt_engineered,
            "blueprint_params": _json_param(params),
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
        """Record the mesh before and after repair, as hashes plus feature snapshots."""
        self._update_job_columns(job_id, {
            "raw_mesh_sha256": raw_sha256,
            "raw_mesh_features": _json_param(raw_features),
            "repaired_mesh_sha256": repaired_sha256,
            "repaired_mesh_features": _json_param(repaired_features),
            "repair_report": _json_param(repair_report),
        })

    def update_job_run_context(
        self,
        job_id: str,
        git_sha: str | None = None,
        used_reference_assets: bool | None = None,
    ) -> None:
        """Record which code ran this job and whether its inputs were real.

        `used_reference_assets=False` is written as 0, not skipped: "the pipeline
        confirmed no fixture was substituted" is information, and NULL would make a
        verified-real run indistinguishable from a pre-migration row.
        """
        self._update_job_columns(job_id, {
            "git_sha": git_sha,
            "used_reference_assets": (
                None if used_reference_assets is None else int(used_reference_assets)
            ),
        })

    def update_job_dispatch(self, job_id: str, printer_url: str | None = None) -> None:
        """Record the printer base URL the G-code was actually sent to."""
        self._update_job_columns(job_id, {"dispatched_printer_url": printer_url})

    def update_job_print_duration(self, job_id: str, duration_s: float | None) -> None:
        """Record the printer-reported print duration at its terminal event.

        Not routed through `update_job_outcome_verdict`: the machine-never-overwrites-
        human guard there would discard the duration whenever a person answered before
        the printer's terminal event arrived, and the duration is a measurement.
        """
        self._update_job_columns(job_id, {"print_duration_s": duration_s})

    def update_job_fit_photo(self, job_id: str, path: str | None) -> None:
        """Record where the photo of the printed part was stored.

        Deliberately not routed through `update_job_outcome_verdict`: a photo is
        evidence, not a verdict. Someone can photograph a part that did not fit and
        then say nothing, and the job must stay `awaiting_verdict` — the moment this
        wrote `outcome` it would be answering on their behalf, and the human-wins rule
        would then refuse the answer they gave a minute later.

        Args:
            job_id: The job the photo is of.
            path: Repo-relative path to the stored image.
        """
        self._update_job_columns(job_id, {"fit_photo_path": path})

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
        """Record the slicer's verdict and material estimates — on failure too."""
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
            "slice_stats": _json_param(stats),
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

        A machine write never overwrites a human one. Printer events can arrive long
        after someone has already answered, and replacing "I watched it fail" with "the
        file finished" would destroy the only reliable label on the row. The rule lives
        here rather than at each call site because there are several machine writers.
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
        self._update_job_columns(job_id, {
            "outcome": outcome,
            "outcome_source": source,
            "completed_at": _dt_param(completed_at),
            "outcome_reported_at": _dt_param(reported_at),
        })

    # ── Job events ────────────────────────────────────────────────────────────

    def insert_job_event(self, event: JobEvent) -> None:
        """Insert an engagement event for a job."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO job_event (event_id, job_id, occurred_at, kind, detail) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    event.event_id,
                    event.job_id,
                    _dt_param(event.occurred_at),
                    event.kind,
                    _json_param(event.detail),
                ),
            )

    def record_job_event(self, job_id: str, kind: str, detail: dict | None = None) -> JobEvent:
        """Build, store and return a job event stamped with the current time."""
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
        """Retrieve a job's engagement events in chronological order."""
        sql = "SELECT * FROM job_event WHERE job_id = %s"
        params: list = [job_id]
        if kind is not None:
            sql += " AND kind = %s"
            params.append(kind)
        sql += " ORDER BY occurred_at ASC"
        rows = self.query(sql, params)
        return [
            JobEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                occurred_at=_str_to_dt(row["occurred_at"]),  # type: ignore[arg-type]
                kind=row["kind"],
                detail=_load_json(row["detail"]),
            )
            for row in rows
        ]

    def count_job_events(self, kind: str) -> int:
        """Count events of one kind across all jobs that still exist.

        The join is deliberate: databases written before foreign keys were enforced
        carry events whose job is gone, and an event whose job is gone describes
        nobody.
        """
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM job_event e "
            "JOIN print_job j ON j.job_id = e.job_id WHERE e.kind = %s",
            (kind,),
        )
        return int(row["n"]) if row else 0

    def count_orphaned_job_events(self) -> int:
        """Events whose job no longer exists — measurable rather than merely excluded."""
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM job_event e "
            "LEFT JOIN print_job j ON j.job_id = e.job_id WHERE j.job_id IS NULL"
        )
        return int(row["n"]) if row else 0

    def feedback_funnel(self) -> dict:
        """Count how many prompted jobs actually got an answer.

        Counted over *jobs that were prompted*, not raw event totals: a verdict can be
        given through a path that never showed a prompt, so dividing reports by prompts
        can exceed 1. `declined` and `dev` are responses but not answers.
        """
        def distinct_jobs(cur: psycopg.Cursor, kind: str, verdicts_sql: str = "") -> set:
            cur.execute(
                "SELECT DISTINCT e.job_id FROM job_event e "
                "JOIN print_job j ON j.job_id = e.job_id WHERE e.kind = %s"
                + verdicts_sql,
                (kind,),
            )
            return {row["job_id"] for row in cur.fetchall()}

        with self._cursor() as cur:
            prompted = distinct_jobs(cur, "outcome_prompt_shown")
            answered = distinct_jobs(
                cur,
                "outcome_reported",
                " AND COALESCE(e.detail ->> 'verdict', '') NOT IN ('declined', 'dev')",
            ) & prompted
            declined = distinct_jobs(
                cur,
                "outcome_reported",
                " AND e.detail ->> 'verdict' = 'declined'",
            ) & prompted
            dismissed = distinct_jobs(cur, "outcome_prompt_dismissed") & prompted

        return {
            "prompted": len(prompted),
            "answered": len(answered),
            "declined": len(declined - answered),
            # A job can be dismissed and later answered; the two overlap by design.
            "dismissed": len(dismissed - answered),
            "unanswered": len(prompted - answered - declined),
        }

    def activation_funnel(self) -> dict:
        """Count how many prompt submitters reached a preview.

        The PRD's activation metric (§7: "≥ 60 % of prompt submitters reach a
        preview"). Counted over *jobs*, exactly like `feedback_funnel`: the numerator
        is jobs with at least one `preview_reached` row, so a reload, a second look at
        the same mesh or a tab switch between the mesh and the toolpath cannot move it,
        and the denominator is every job submitted — `prompt` is required on
        `POST /jobs`, so a job row *is* a prompt submission.

        A `dev` outcome is excluded from both halves. That is a developer verifying the
        pipeline by printing a cube, which is the reason `dev` exists at all, and it
        must not enter the number the pilot is measured by — the same rule that keeps
        it out of `feedback_funnel`'s `answered`.
        """
        real_job = "COALESCE(j.outcome, '') <> 'dev'"
        submitted = self.query_one(
            f"SELECT COUNT(*) AS n FROM print_job j WHERE {real_job}"
        )
        previewed = self.query_one(
            "SELECT COUNT(DISTINCT e.job_id) AS n FROM job_event e "
            "JOIN print_job j ON j.job_id = e.job_id "
            f"WHERE e.kind = 'preview_reached' AND {real_job}"
        )
        return {
            "submitted": int(submitted["n"]) if submitted else 0,
            "previewed": int(previewed["n"]) if previewed else 0,
        }

    def increment_download_count(self, job_id: str) -> None:
        """Bump a job's denormalised download counter."""
        self.execute(
            "UPDATE print_job SET download_count = COALESCE(download_count, 0) + 1 "
            "WHERE job_id = %s",
            (job_id,),
        )

    def get_jobs_awaiting_verdict(self, limit: int = 50) -> list[PrintJob]:
        """Jobs whose printer finished but whose outcome no human has confirmed."""
        rows = self.query(
            "SELECT * FROM print_job WHERE outcome = 'awaiting_verdict' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
        return [_row_to_job(row) for row in rows]

    def _update_job_columns(self, job_id: str, updates: dict) -> None:
        """Write the non-None entries of `updates` to a print_job row."""
        fields = {k: v for k, v in updates.items() if v is not None}
        if not fields:
            return
        assignments = ", ".join(f"{k} = %s" for k in fields)
        self.execute(
            f"UPDATE print_job SET {assignments} WHERE job_id = %s",
            (*fields.values(), job_id),
        )

    # ── Collector claims ──────────────────────────────────────────────────────

    def try_claim_collector(self, job_id: str, owner: str, stale_after_s: float = 120.0) -> bool:
        """Try to become the single telemetry collector for a job.

        The claim is taken by whichever collector calls this first, and is only taken
        over from a previous owner once that owner has stopped sending heartbeats for
        ``stale_after_s``. Every write is a compare-and-swap guarded on the
        `(owner, heartbeat_at)` the SELECT read, with `rowcount` as the verdict — two
        collectors that both saw the same stale claim must not both be told they won.

        Returns:
            True if this owner now holds the claim, False if another owner holds it.
        """
        now = datetime.now(timezone.utc)
        with self._cursor() as cur:
            cur.execute(
                "SELECT owner, heartbeat_at FROM telemetry_collector_claim WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()

            if row is not None:
                current_owner = row["owner"]
                current_beat = row["heartbeat_at"]

                if current_owner == owner:
                    # Guarded on the owner we just read: a rival may have taken the
                    # claim over between the SELECT and here, and an unguarded write
                    # would silently take it back.
                    cur.execute(
                        "UPDATE telemetry_collector_claim SET heartbeat_at = %s "
                        "WHERE job_id = %s AND owner = %s",
                        (_dt_param(now), job_id, owner),
                    )
                    if cur.rowcount == 1:
                        return True
                    logger.warning(
                        "Lost the telemetry claim for job %s while heartbeating", job_id
                    )
                    return False

                last_beat = _str_to_dt(current_beat)
                if last_beat is not None and (now - last_beat).total_seconds() < stale_after_s:
                    return False

                cur.execute(
                    "UPDATE telemetry_collector_claim "
                    "SET owner = %s, claimed_at = %s, heartbeat_at = %s "
                    "WHERE job_id = %s AND owner = %s AND heartbeat_at = %s",
                    (
                        owner,
                        _dt_param(now),
                        _dt_param(now),
                        job_id,
                        current_owner,
                        current_beat,
                    ),
                )
                if cur.rowcount == 1:
                    logger.warning(
                        "Took over stale telemetry claim for job %s from %s",
                        job_id,
                        current_owner,
                    )
                    return True
                logger.info(
                    "Another collector took the stale claim for job %s first", job_id
                )
                return False

            # `ON CONFLICT DO NOTHING` rather than catching the unique violation: an
            # error inside a PostgreSQL transaction aborts it, and the row count says
            # the same thing without one.
            cur.execute(
                "INSERT INTO telemetry_collector_claim (job_id, owner, claimed_at, heartbeat_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (job_id) DO NOTHING",
                (job_id, owner, _dt_param(now), _dt_param(now)),
            )
            return cur.rowcount == 1

    def release_collector_claim(self, job_id: str, owner: str) -> None:
        """Release a job's collector claim, if this owner still holds it."""
        self.execute(
            "DELETE FROM telemetry_collector_claim WHERE job_id = %s AND owner = %s",
            (job_id, owner),
        )

    def get_collector_claim(self, job_id: str) -> Optional[str]:
        """The owner currently holding a job's collector claim, if any."""
        row = self.query_one(
            "SELECT owner FROM telemetry_collector_claim WHERE job_id = %s", (job_id,)
        )
        return row["owner"] if row else None

    # ── Failures and reads ────────────────────────────────────────────────────

    def insert_failure_event(self, event: FailureEvent) -> None:
        """Insert a FailureEvent."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO failure_event ("
                "    event_id, job_id, detected_at, gcode_line, z_height_mm,"
                "    failure_type, source, notes, snapshot"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    event.event_id, event.job_id, _dt_param(event.detected_at),
                    event.gcode_line, event.z_height_mm, event.failure_type,
                    event.source, event.notes, Jsonb(event.snapshot),
                ),
            )

    def get_job(self, job_id: str) -> PrintJob | None:
        """Retrieve a PrintJob by ID, or None if not found."""
        row = self.query_one("SELECT * FROM print_job WHERE job_id = %s", (job_id,))
        return _row_to_job(row) if row else None

    def get_samples(self, job_id: str, limit: int = 500) -> list[TelemetrySample]:
        """The most recent `limit` samples for a job, in ascending chronological order."""
        rows = self.query(
            "SELECT * FROM telemetry_sample WHERE job_id = %s "
            "ORDER BY sampled_at DESC, id DESC LIMIT %s",
            (job_id, limit),
        )
        samples = [
            TelemetrySample(
                job_id=row["job_id"],
                sampled_at=_str_to_dt(row["sampled_at"]),  # type: ignore[arg-type]
                gcode_line=row["gcode_line"],
                z_height_mm=row["z_height_mm"],
                hotend_actual_c=row["hotend_actual_c"],
                hotend_target_c=row["hotend_target_c"],
                bed_actual_c=row["bed_actual_c"],
                bed_target_c=row["bed_target_c"],
                print_speed_pct=row["print_speed_pct"],
                extrusion_factor_pct=row["extrusion_factor_pct"],
                fan_speed_pct=row["fan_speed_pct"],
            )
            for row in rows
        ]
        return samples[::-1]

    def get_failure_events(self, job_id: str) -> list[FailureEvent]:
        """FailureEvents for a job, oldest first."""
        rows = self.query(
            "SELECT * FROM failure_event WHERE job_id = %s ORDER BY detected_at ASC",
            (job_id,),
        )
        return [
            FailureEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                detected_at=_str_to_dt(row["detected_at"]),  # type: ignore[arg-type]
                gcode_line=row["gcode_line"],
                z_height_mm=row["z_height_mm"],
                failure_type=row["failure_type"],  # type: ignore[arg-type]
                source=row["source"],  # type: ignore[arg-type]
                notes=row["notes"],
                snapshot=_load_json(row["snapshot"]),
            )
            for row in rows
        ]


def _main(argv: list[str] | None = None) -> int:
    """`python -m pythonsrc.telemetry.db --ddl` prints the schema; `--init` applies it."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m pythonsrc.telemetry.db")
    parser.add_argument("--ddl", action="store_true", help="Print the schema as SQL and exit.")
    parser.add_argument(
        "--init", action="store_true",
        help="Create or migrate the schema in $DS_DATABASE_URL and report health.",
    )
    args = parser.parse_args(argv)
    if args.ddl:
        sys.stdout.write(render_schema_sql())
        return 0
    if args.init:
        db = TelemetryDB()
        db.init_schema()
        with connection(db.dsn) as conn:
            conn.execute(CONFIG_TABLE_DDL)
            conn.execute(f"ALTER TABLE {CONFIG_TABLE} ENABLE ROW LEVEL SECURITY")
        problems = db.health_check()
        print(f"{db.describe}: " + ("healthy" if not problems else "; ".join(problems)))
        return 0 if not problems else 1
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
