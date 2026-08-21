"""FastAPI application for P2P Mesh Pipeline orchestration.

This module defines the REST API for creating, monitoring, and retrieving
results from the 3D printing pipeline, as well as managing telemetry.
"""
import asyncio
import json
import logging
import os
import sys
import uuid
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

# Add pythonsrc to sys.path so we can import telemetry modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from pythonsrc.telemetry.db import TelemetryDB, _str_to_dt
from pythonsrc.telemetry.schema import PrintJob, FailureEvent, TelemetrySample, VALID_FAILURE_TYPES
from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
from pythonsrc.telemetry.detector import attach_detector
from pythonsrc.operators import PrinterFactory
from pythonsrc.platform_utils import get_execution_strategy, get_phase1_command
import httpx
from server.config_store import ConfigStore, CONFIG_KEYS
from server.job_broadcaster import broadcaster
from server.simulator_manager import SimulatorAvailabilityError, simulator_manager

from server.activity import activity, rule as activity_rule
from server.logging_config import configure_logging, is_high_frequency_path

# At import time, not in a startup event: uvicorn imports this module and runs
# module-level code (config store, strategy resolution) before any startup hook
# fires, and those lines are worth keeping.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="P2P Mesh API", version="1.0.0")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log one line per request: method, path, status and how long it took.

    There was no request log at all, so a failing UI action left no trace on the
    server side and had to be reproduced with a browser open. Duration is included
    because the slow paths here are slow for structural reasons — a slice, a printer
    probe — and knowing which endpoint blocked is most of the diagnosis.

    Status decides the level, so a 500 is visible without turning on DEBUG. Polled
    endpoints drop to DEBUG regardless: the job detail page alone would otherwise
    emit a line every second.
    """
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        # FastAPI's own handler logs this too, but without the path or the timing,
        # and this is the line that says which request died.
        logger.exception(
            "%s %s — unhandled exception after %.0f ms",
            request.method, request.url.path, elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000

    if response.status_code >= 500:
        level = logging.ERROR
    elif response.status_code >= 400:
        level = logging.WARNING
    elif is_high_frequency_path(request.url.path):
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger.log(
        level,
        "%s %s → %d (%.0f ms)",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )

    # Every request that failed reaches the activity feed as a one-liner, whether or
    # not its handler knows how to describe itself. A 4xx or 5xx the handler swallowed
    # was previously invisible to anyone watching the feed, which is the case where
    # watching is most worth doing.
    # The polled-path demotion applies to GET only. A failed POST or DELETE is never a
    # poll, and `/jobs/{id}` matches the high-frequency prefix — so a rejected
    # `DELETE /jobs/{id}` was being suppressed by the heuristic meant for the detail
    # page's read timer, which is the exact failure someone would be watching for.
    if response.status_code >= 400 and (
        request.method != "GET" or not is_high_frequency_path(request.url.path)
    ):
        activity.event(
            f"{request.method} {request.url.path} → {response.status_code} "
            f"({elapsed_ms:.0f} ms)",
            level="ERROR" if response.status_code >= 500 else "WARNING",
            source="http",
        )
    return response

config_store = ConfigStore()

active_collectors = {}
active_detectors: dict[str, asyncio.Task] = {}
active_pipelines: dict[str, asyncio.subprocess.Process] = {}
# Jobs a human has stopped.
#
# A cancelled pipeline dies with a non-zero exit code, which is indistinguishable
# from a crash at the point where `_run_pipeline` decides what to record. Without
# this set the cancel endpoint wrote "cancelled" and `_run_pipeline` overwrote it
# with "failure" a second later — both are machine-sourced writes, so the
# precedence rule in `update_job_outcome_verdict` does not stop it. The user saw
# their stop turn into a failure, and the dataset recorded a crash that never
# happened.
cancelled_jobs: set[str] = set()


def resolve_job_artifact(job_id: str, filename: str) -> Path | None:
    """Locate a job's artifact, preferring its per-job directory.

    The pipeline writes artifacts to ``data/outputs/{job_id}/`` so that jobs cannot
    overwrite each other. Older jobs wrote to the flat ``data/outputs/`` layout, so that
    path is still accepted as a fallback for rows created before the change.

    A debugging run that stood a bundled fixture in for Phase 1 or Phase 2 writes to
    ``dev-{job_id}`` instead, so that directory is searched too — the prefix exists to
    keep fabricated inputs out of the real namespace, not to hide the artifacts from the
    endpoints that serve them.

    Args:
        job_id: The job whose artifact is wanted.
        filename: Artifact filename, e.g. "engineered_mesh.gcode".

    Returns:
        The path to the artifact, or None if no location has it.
    """
    outputs = Path(__file__).parent.parent / "data" / "outputs"
    for directory in (outputs / job_id, outputs / f"dev-{job_id}"):
        candidate = directory / filename
        if candidate.exists():
            return candidate

    legacy = outputs / filename
    if legacy.exists():
        return legacy

    if filename == "blueprint.png":
        shared_input = Path(__file__).parent.parent / "data" / "inputs" / "blueprint.png"
        if shared_input.exists():
            return shared_input

    return None


def resolve_job_profile(job) -> tuple[str, str | None]:
    """Find the printer profile a job's Phase 5 would use.

    The job's own `profile_name` wins when it names a file that still exists, because
    that is what the job was created against; the configured default is the fallback for
    rows that stored "default". Returns the repo-relative name (what a person sees in
    Settings) and the absolute path (what a subprocess needs).

    Args:
        job: A PrintJob row.

    Returns:
        A (relative_profile, absolute_path) tuple. The path is None when nothing exists.
    """
    repo_root = Path(__file__).parent.parent
    for candidate in (job.profile_name, config_store.get("DEFAULT_PROFILE"),
                      "pythonsrc/profiles/ender3.json"):
        if not candidate or candidate == "default":
            continue
        path = repo_root / candidate
        if path.exists():
            return candidate, str(path)
    return "", None


def dispatch_target(job) -> dict:
    """Describe, as of now, what pressing "Send to printer" would send this job to.

    Resolved on read rather than frozen at job creation on purpose: the whole point of
    showing it is that the person confirming can see the *current* target, including one
    that changed in Settings since the job started.

    Args:
        job: A PrintJob row.

    Returns:
        A dict with the profile name, firmware, base URL and machine name.
    """
    profile, profile_path = resolve_job_profile(job)
    firmware, base_url, _api_key = resolve_printer_target(profile_path)
    machine_name = None
    if profile_path:
        try:
            with open(profile_path, "r") as f:
                machine_name = json.load(f).get("machine_name")
        except Exception:  # noqa: BLE001
            pass
    return {
        "profile": profile,
        "firmware": firmware,
        "base_url": base_url,
        "machine_name": machine_name,
    }


def dispatch_state(job, db: TelemetryDB) -> str:
    """Where a job stands with respect to Phase 5.

    Three states, and the middle one is the point: **a print does not leave for a
    machine until a person confirms the target.** The pipeline is launched without
    `--print`, so it stops after slicing; the job then sits in `awaiting_confirmation`
    until `POST /jobs/{id}/print-dispatch` arrives with an explicit confirmation.

    Derived rather than stored. The outcome column says what the software did, and a
    job waiting on a human has not changed what the software did — the decision itself
    is a `dispatch_confirmed` job event, which is where decisions live.

    Args:
        job: A PrintJob row.
        db: An open database handle, used to look for the confirmation event.

    Returns:
        "dispatched", "awaiting_confirmation" or "not_ready".
    """
    if job.outcome == "awaiting_verdict":
        return "dispatched"
    try:
        if db.get_job_events(job.job_id, kind="dispatch_confirmed"):
            return "dispatched"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read dispatch events for %s: %s", job.job_id, exc)

    # Only once nothing else is going to print it: a pipeline still running may have
    # been launched with --print and would dispatch itself.
    if job.outcome == "success" and job.slice_status == "success":
        if resolve_job_artifact(job.job_id, "engineered_mesh.gcode") is not None:
            return "awaiting_confirmation"
    return "not_ready"


def resolve_printer_target(profile_path: str | None = None) -> tuple[str, str | None, str | None]:
    """Resolve which printer a job talks to, from one place.

    Precedence is split deliberately:

    * **firmware** — the profile wins when it names one, because a job asks for a
      specific profile explicitly, which is more specific than a global default.
    * **base_url / api_key** — the config store wins, because those are what the user
      typed into Printer Setup; the values in the bundled profiles are dev defaults
      (and their ``api_key`` is usually null).

    Resolving this in one place stops the telemetry collector from watching a different
    printer than the pipeline is printing to.

    Args:
        profile_path: Optional path to a printer profile JSON.

    Returns:
        A (firmware, base_url, api_key) tuple. Firmware falls back to "octoprint".
    """
    profile_data: dict = {}
    if profile_path:
        try:
            with open(profile_path, "r") as f:
                profile_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read printer profile {profile_path}: {e}")

    firmware = profile_data.get("firmware") or config_store.get("DEFAULT_PRINTER_FIRMWARE") or "octoprint"

    if firmware in ("klipper", "moonraker"):
        base_url = config_store.get("MOONRAKER_URL")
        api_key = config_store.get("MOONRAKER_API_KEY")
    elif firmware == "bambu":
        base_url = config_store.get("BAMBU_IP")
        # The wizard writes BAMBU_CODE; reading BAMBU_ACCESS_CODE (as the old code did)
        # always resolved to None.
        api_key = config_store.get("BAMBU_CODE")
    else:
        base_url = config_store.get("OCTOPRINT_URL")
        api_key = config_store.get("OCTOPRINT_API_KEY")

    base_url = base_url or profile_data.get("base_url")
    api_key = api_key or profile_data.get("api_key")

    return firmware, base_url, api_key

# How long a stopped pipeline gets to exit on SIGTERM before it is killed outright.
PIPELINE_TERM_GRACE_S = 10


def _read_current_phase(job_id: str) -> dict | None:
    """The last phase line the pipeline wrote to its `.status` file, or None.

    Shared by `GET /jobs/{id}` and the cancel endpoint so there is one reader of the
    `.status` protocol. The file is append-only and one JSON object per line; the last
    line is the pipeline's most recent word on where it got to.
    """
    status_file = Path(__file__).parent.parent / "data" / "logs" / f"{job_id}.status"
    if not status_file.exists():
        return None
    try:
        with open(status_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        parsed = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _append_phase_status(job_id: str, phase: int, status: str, error: str | None = None) -> None:
    """Append one phase record to a job's `.status` file.

    The pipeline owns this file for phases 1–4; Phase 5 now runs from the server, and
    without a record here the rail would show phase 05 pending while a printer was
    already extruding. Same shape as `pipeline._write_status` writes — the last line of
    this file *is* `current_phase`.

    Args:
        job_id: The job the record belongs to.
        phase: Phase number.
        status: "running", "complete" or "error".
        error: Optional failure detail.
    """
    log_dir = Path(__file__).parent.parent / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "phase": phase,
            "name": "operator" if phase == 5 else str(phase),
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if error is not None:
            record["error"] = error
        with open(log_dir / f"{job_id}.status", "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Could not write phase status for %s: %s", job_id, exc)


def job_status_from_outcome(outcome: str | None, started_at) -> str:
    """Map a stored outcome onto the synthetic status the API exposes.

    One function for every endpoint: the list and detail views previously mapped
    `failure` to opposite statuses ("completed" vs "failed"). A job awaiting a
    human verdict has finished as far as the software is concerned, so it maps to
    "completed" — the pending state is carried by `awaiting_verdict` rather than
    by overloading a status string every consumer already switches on.
    """
    if outcome == "unknown":
        return "running" if started_at else "queued"
    # `dev` and `declined` are settled rows: the print ran and the question has been
    # closed out. They map to "completed" because that is what the software did — the
    # distinction they carry is about the *data*, not about the run, and lives in the
    # outcome column where a query can see it.
    if outcome in ("success", "awaiting_verdict", "dev", "declined"):
        return "completed"
    if outcome == "cancelled":
        return "cancelled"
    return "failed"


def get_resolved_strategy() -> str:
    override = config_store.get("EXECUTION_STRATEGY_OVERRIDE")
    if override and override in ("mps_native", "nvidia_docker", "cpu_docker"):
        return override
    return get_execution_strategy()

class JobRequest(BaseModel):
    """Pydantic model representing a new print job request."""
    prompt: str = Field(..., min_length=1)
    printer_id: str = Field(..., min_length=1)
    profile: str = ""
    skip_visualizer: bool = False
    skip_sculptor: bool = False
    blueprint_path: Optional[str] = None
    print: bool = False
    start_print: bool = False
    # What the user was aiming at. Material is not decoration: it sets the density
    # behind the filament mass estimate and is the likeliest explanation for a bed
    # adhesion failure, and nothing else in the system records it.
    material_type: Optional[str] = None
    material_brand: Optional[str] = None
    material_colour: Optional[str] = None
    # Reproducibility and lineage.
    seed: Optional[int] = None
    parent_job_id: Optional[str] = None
    regeneration_reason: Optional[str] = None
    # Phase 2 reconstruction settings. Both change the geometry, so both are
    # recorded onto the job's `generation_params` rather than staying implicit.
    pipeline_type: Optional[str] = Field(
        None, pattern="^(512|1024|1024_cascade|1536_cascade)$"
    )
    mesh_seed: Optional[int] = None


class OutcomeRequest(BaseModel):
    """A human's verdict on whether a print actually succeeded.

    Five values, and two of them exist to keep the dataset honest rather than to
    describe a part:

    - `dev` — a developer's test run. Answers the prompt so the job stops being asked
      about, and marks the row as **not real data**. Without it, every pipeline change
      verified by printing a cube lands in the same column the pilot's results are
      measured from.
    - `declined` — the user was asked, asked again, and said don't ask again. Distinct
      from never being asked (which is the absence of an `outcome_prompt_shown` event)
      and from a single skip (`outcome_prompt_dismissed`). Deliberately **not**
      `unknown`: that string is the sentinel for "the pipeline has not finished", so
      writing it here would make a settled job read as running again.
    """
    verdict: str = Field(..., pattern="^(success|failure|cancelled|dev|declined)$")
    failure_type: Optional[str] = None
    notes: Optional[str] = None
    layer_pct: Optional[float] = None

    @field_validator("failure_type")
    @classmethod
    def _known_failure_type(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown failure type before anything is written.

        `FailureEvent.__post_init__` validates this too, but by the time the handler
        constructs one the verdict has already been saved — so a typo produced a 500,
        or later a 422, with the job left marked `failure` regardless. Validating on the
        request model means the handler never runs and the row is untouched.
        """
        if value is None or value in VALID_FAILURE_TYPES:
            return value
        raise ValueError(
            f"Unknown failure_type '{value}'. Expected one of: "
            f"{', '.join(sorted(VALID_FAILURE_TYPES))}."
        )

class JobResponse(BaseModel):
    """Pydantic model representing the immediate response to a job creation."""
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    """Pydantic model representing the detailed status of a print job."""
    job_id: str
    status: str
    prompt: str
    completed_at: Optional[str]
    started_at: Optional[str] = None
    outcome: str
    log_tail: List[str]
    current_phase: Optional[dict] = None
    printer_id: Optional[str] = None
    printer_firmware: Optional[str] = None
    profile_name: Optional[str] = None
    machine_name: Optional[str] = None
    #: [width, depth, height] in mm, for drawing the build envelope in the G-code
    #: preview. None when the profile does not declare one.
    build_volume_mm: Optional[list[float]] = None
    nozzle_diameter_mm: Optional[float] = None
    layer_height_mm: Optional[float] = None
    printability_score: Optional[float] = None
    printability_verdict: Optional[str] = None
    material_type: Optional[str] = None
    material_brand: Optional[str] = None
    material_colour: Optional[str] = None
    blueprint_seed: Optional[int] = None
    parent_job_id: Optional[str] = None
    download_count: int = 0
    slice_status: Optional[str] = None
    estimated_print_time_s: Optional[int] = None
    filament_used_mm3: Optional[float] = None
    filament_used_g: Optional[float] = None
    support_filament_mm3: Optional[float] = None
    layer_count: Optional[int] = None
    outcome_source: Optional[str] = None
    awaiting_verdict: bool = False
    #: "not_ready" | "awaiting_confirmation" | "dispatched". See `dispatch_state`.
    dispatch_state: str = "not_ready"
    #: The printer this job's Phase 5 would go to, resolved now — the thing a person is
    #: being asked to confirm. See `dispatch_target`.
    dispatch_target: Optional[dict] = None


def _profile_snapshot(profile_path: str) -> tuple[Optional[dict], Optional[float]]:
    """Read a printer profile and pull out the nozzle diameter.

    The snapshot is stored on the job because profiles are edited in place. Resolving
    them at query time makes a finished job silently claim whatever settings the file
    holds today, which is how a historical row ends up describing a print that never
    happened.

    Args:
        profile_path: Absolute path to the profile JSON.

    Returns:
        A (profile dict, nozzle diameter) pair; both None when the file is unreadable.
    """
    try:
        with open(profile_path, "r") as handle:
            data = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not snapshot printer profile %s: %s", profile_path, exc)
        return None, None
    try:
        nozzle = float(data.get("machine_nozzle_size") or 0.4)
    except (TypeError, ValueError):
        nozzle = 0.4
    return data, nozzle


#: How many rotating snapshots of the telemetry database to keep.
DB_BACKUP_COPIES = 5

#: Set when the last startup integrity check found damage, so `/health` can say so.
database_problems: list[str] = []


def check_database_health(db: TelemetryDB) -> list[str]:
    """Verify the telemetry database and, if it is sound, snapshot it.

    The database went corrupt once — `telemetry_sample`'s b-tree ended up with pages
    referenced twice — and nothing noticed. It was found only because a query for
    telemetry samples started returning `database disk image is malformed`, by which
    point 346 rows were unreadable and the pages had been reused. There was no
    integrity check anywhere in the codebase and no backup, so there was neither a
    warning nor anything to restore from.

    Running at startup is the right moment: it is the one point where the file is
    known-quiescent from this process's side, and a server that comes up on a broken
    database should say so in its logs rather than fail one endpoint at a time.

    Snapshots are taken **only when the check passes**, so a corrupt file cannot
    overwrite the last good copy — the rotation would otherwise launder the damage
    through every slot in five restarts.

    Args:
        db: An open telemetry database.

    Returns:
        The problems found; empty when the database is sound.
    """
    global database_problems

    problems = db.integrity_check()
    database_problems = problems

    if problems:
        logger.error(
            "Telemetry database FAILED its integrity check (%s). Data is being lost. "
            "Repair it before relying on anything it reports: %s",
            db.db_path, "; ".join(problems),
        )
        return problems

    try:
        source = Path(db.db_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        db.backup_to(source.with_name(f"{source.name}.backup-{stamp}"))

        # Oldest first, so the newest DB_BACKUP_COPIES survive.
        snapshots = sorted(source.parent.glob(f"{source.name}.backup-*"))
        for stale in snapshots[:-DB_BACKUP_COPIES]:
            stale.unlink(missing_ok=True)
    except Exception as exc:
        # A failed backup is not a reason to refuse to start.
        logger.warning("Could not snapshot the telemetry database: %s", exc)

    return problems


@app.on_event("startup")
def startup_event():
    """Handle application startup events."""
    config_store.init_schema()
    strategy = get_resolved_strategy()
    logger.info(f"Resolved execution strategy: {strategy}")
    
    docker_available = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3.0)
        docker_available = res.returncode == 0
    except Exception:
        pass
        
    if not docker_available and strategy in ("nvidia_docker", "cpu_docker"):
        logger.warning(f"Strategy {strategy} requires Docker, but Docker is not available!")
        
    repo_root = Path(__file__).parent.parent
    (repo_root / "data" / "inputs").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "outputs").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "logs").mkdir(parents=True, exist_ok=True)
    
    db = TelemetryDB()
    db.init_schema()
    check_database_health(db)
    db.close()

    for k, v in config_store.get_all().items():
        os.environ[k] = v

@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown events.

    Gracefully stops all active telemetry collectors.
    """
    for detector_task in active_detectors.values():
        detector_task.cancel()
    active_detectors.clear()
    for collector in active_collectors.values():
        await collector.stop()
    active_collectors.clear()
    await simulator_manager.stop_moonraker()
    await simulator_manager.stop_octoprint()

# Live log fan-out. Every stdout line reaches the browser, but coalesced: a docker
# build emits thousands of lines in a burst, and one WebSocket frame per line floods
# the socket and the React tree for no visible gain. Batching on a short interval
# still reads as live — roughly eight updates a second — at a fraction of the frames.
LOG_FLUSH_INTERVAL_S = 0.12
LOG_BATCH_MAX = 40


async def _stream_output(process, log_file_obj, job_id: str):
    import re
    phase_re = re.compile(r"\[P2P\] ═══ PHASE (\d+) (START|PASS|FAIL)(.*)═══")
    phase_names = {1: "Visualizer", 2: "Sculptor", 3: "Engineer", 4: "Slicer", 5: "Operator"}

    pending: list[str] = []
    # Monotonic across the whole job, so a client can tell a quiet pipeline from a
    # dropped batch — the two look identical without it.
    seq = 0

    async def flush():
        nonlocal pending, seq
        if not pending:
            return
        batch, pending = pending, []
        seq += 1
        await broadcaster.broadcast(job_id, {
            "type": "log",
            "data": {
                "seq": seq,
                "lines": batch,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        })

    async def flusher():
        # A data-driven flush alone would hold the last few lines forever whenever the
        # pipeline goes quiet — which is exactly when someone is staring at the log
        # wondering whether anything is still happening.
        while True:
            await asyncio.sleep(LOG_FLUSH_INTERVAL_S)
            await flush()

    flusher_task = asyncio.create_task(flusher())
    try:
        async for line_bytes in process.stdout:
            line = line_bytes.decode('utf-8', errors='replace')
            log_file_obj.write(line)
            log_file_obj.flush()

            stripped = line.rstrip("\n")
            if stripped:
                pending.append(stripped)
                if len(pending) >= LOG_BATCH_MAX:
                    await flush()

            m = phase_re.search(line)
            if m:
                phase_num = int(m.group(1))
                action = m.group(2)
                name = phase_names.get(phase_num, "Unknown")

                if action == "START":
                    status = "running"
                    error = None
                elif action == "PASS":
                    status = "complete"
                    error = None
                else:
                    status = "error"
                    error = "Phase failed"

                # A phase banner is the one line that must not wait for the batch
                # timer: the whole UI keys off it.
                await flush()
                # Heavy rule for a START, so a phase boundary is findable by eye in a
                # stream that is otherwise thousands of tool lines.
                if action == "START":
                    activity.boundary(f"phase {phase_num:02d} · {name}")
                else:
                    activity.event(
                        f"phase {phase_num:02d} {name} · {'complete' if action == 'PASS' else 'FAILED'}",
                        level="INFO" if action == "PASS" else "ERROR",
                        source="pipeline",
                    )
                await broadcaster.broadcast(job_id, {
                    "type": "phase_update",
                    "data": {
                        "phase": phase_num,
                        "name": name,
                        "status": status,
                        "error": error,
                        "ts": datetime.now(timezone.utc).isoformat()
                    }
                })
    finally:
        flusher_task.cancel()
        # The tail matters most — it is whatever the pipeline said before it stopped.
        await flush()

async def _run_pipeline(job_id: str, request: JobRequest):
    repo_root = Path(__file__).parent.parent
    log_dir = repo_root / "data" / "logs"
    log_file = log_dir / f"{job_id}.log"
    
    strategy = get_resolved_strategy()
    
    pipeline_args = []
    
    skip_viz = request.skip_visualizer or config_store.get("SKIP_VISUALIZER") == "true"
    skip_sculpt = request.skip_sculptor or config_store.get("SKIP_SCULPTOR") == "true"
    if skip_viz:
        pipeline_args.extend(["--skip-visualizer", "--blueprint", "/app/data/inputs/blueprint.png"])
    if skip_sculpt:
        pipeline_args.append("--skip-sculptor")
        
    profile = request.profile or config_store.get("DEFAULT_PROFILE")
    if profile:
        pipeline_args.extend(["--profile", profile])
        
    pipeline_args.append("--slice")

    # Forwarded so the pipeline can record them: the seed is what makes a blueprint
    # reproducible, and the material selects the density behind the mass estimate.
    if request.seed is not None:
        pipeline_args.extend(["--seed", str(request.seed)])
    if request.material_type:
        pipeline_args.extend(["--material-type", request.material_type])
    # Phase 2's own seed and resolution. `--mesh-seed` is deliberately not `--seed`:
    # one reproduces the blueprint, the other the reconstruction, and a single value
    # for both would make it impossible to re-sculpt one image two ways.
    if request.pipeline_type:
        pipeline_args.extend(["--pipeline-type", request.pipeline_type])
    if request.mesh_seed is not None:
        pipeline_args.extend(["--mesh-seed", str(request.mesh_seed)])

    if request.print:
        pipeline_args.append("--print")
    if request.start_print:
        pipeline_args.append("--start-print")
        
    try:
        # Mark job as started
        db_start = TelemetryDB()
        db_start.update_job_start_time(job_id, datetime.now(timezone.utc))
        db_start.close()

        pipeline_env = os.environ.copy()
        pipeline_env["P2P_LOGS_DIR"] = str(log_dir)
        # Ensure secrets from config store are available to subprocesses
        hf_token = config_store.get("HF_TOKEN")
        if hf_token:
            pipeline_env["HF_TOKEN"] = hf_token
            pipeline_env["HUGGINGFACE_HUB_TOKEN"] = hf_token
            
        # Export printer config to pipeline — resolved in one place so the pipeline
        # and the telemetry collector can never target different printers.
        profile_path = str(repo_root / (request.profile or "pythonsrc/profiles/ender3.json"))
        firmware, url, key = resolve_printer_target(profile_path)
        pipeline_env["P2P_FIRMWARE"] = firmware

        if url:
            # If pipeline is running in docker and the URL is localhost, rewrite it
            if "localhost" in url or "127.0.0.1" in url:
                url = url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
            pipeline_env["P2P_PRINTER_URL"] = url
            
        if key:
            pipeline_env["P2P_PRINTER_KEY"] = key
            
        if strategy == "mps_native":
            pipeline_env["P2P_API_URL"] = "http://127.0.0.1:8000"
        else:
            pipeline_env["P2P_API_URL"] = "http://host.docker.internal:8000"

        with open(log_file, "w") as f:
            docker_env_args = ["-e", "P2P_LOGS_DIR=/app/data/logs"]
            if "TELEMETRY_DB_PATH" in pipeline_env:
                docker_env_args.extend(["-e", f"TELEMETRY_DB_PATH={pipeline_env['TELEMETRY_DB_PATH']}"])
            if "P2P_PRINTER_URL" in pipeline_env:
                docker_env_args.extend(["-e", f"P2P_PRINTER_URL={pipeline_env['P2P_PRINTER_URL']}"])
            if "P2P_PRINTER_KEY" in pipeline_env:
                docker_env_args.extend(["-e", f"P2P_PRINTER_KEY={pipeline_env['P2P_PRINTER_KEY']}"])
            if "P2P_FIRMWARE" in pipeline_env:
                docker_env_args.extend(["-e", f"P2P_FIRMWARE={pipeline_env['P2P_FIRMWARE']}"])
            if "P2P_API_URL" in pipeline_env:
                docker_env_args.extend(["-e", f"P2P_API_URL={pipeline_env['P2P_API_URL']}"])
            # Forward the paid-backend kill switch across the container boundary.
            # Phase 2's hosted backend bills per call and runs *inside* the container,
            # so a guard that only exists in this process cannot stop it. `compose run`
            # passes nothing from the host environment unless it is named here.
            if "P2P_DISABLE_PAID_BACKENDS" in pipeline_env:
                docker_env_args.extend([
                    "-e",
                    f"P2P_DISABLE_PAID_BACKENDS={pipeline_env['P2P_DISABLE_PAID_BACKENDS']}",
                ])
                
            if strategy == "mps_native":
                if not skip_viz:
                    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "running", "error": None, "ts": datetime.now(timezone.utc).isoformat()}})

                    phase1_cmd = ["bash", "infra/scripts/run_phase1_native.sh", request.prompt]
                    process1 = await asyncio.create_subprocess_exec(
                        *phase1_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=repo_root,
                        env=pipeline_env
                    )
                    active_pipelines[job_id] = process1
                    await _stream_output(process1, f, job_id)
                    await process1.wait()
                    
                    if process1.returncode != 0:
                        await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "error", "error": f"Failed with code {process1.returncode}", "ts": datetime.now(timezone.utc).isoformat()}})
                        raise Exception(f"Phase 1 failed with code {process1.returncode}")
                        
                    if not (repo_root / "data" / "inputs" / "blueprint.png").exists():
                        raise Exception("Phase 1 completed but blueprint.png not found")
                        
                    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "complete", "error": None, "ts": datetime.now(timezone.utc).isoformat()}})
                
                clean_args = []
                skip_next = False
                for arg in pipeline_args:
                    if skip_next:
                        skip_next = False
                        continue
                    if arg == "--skip-visualizer":
                        continue
                    if arg == "--blueprint":
                        skip_next = True
                        continue
                    clean_args.append(arg)
                    
                cmd = [
                    "docker", "compose", "-f", "infra/docker-compose.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    "--skip-visualizer", "--blueprint", "/app/data/inputs/blueprint.png",
                    "--job-id", job_id
                ] + clean_args
            elif strategy == "nvidia_docker":
                cmd = [
                    "docker", "compose",
                    "-f", "infra/docker-compose.yml",
                    "-f", "infra/docker-compose.gpu.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    "--job-id", job_id
                ] + pipeline_args
            else:
                cmd = [
                    "docker", "compose",
                    "-f", "infra/docker-compose.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    "--job-id", job_id
                ] + pipeline_args
                
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=repo_root,
                env=pipeline_env
            )
            active_pipelines[job_id] = process
            await _stream_output(process, f, job_id)
            await process.wait()
            returncode = process.returncode
            
            db = TelemetryDB()
            if job_id in cancelled_jobs:
                # A stopped pipeline exits non-zero, exactly like a crash. Only the
                # cancel endpoint knows the difference, and recording "failure" here
                # would both mislead the user and put a crash in the dataset that
                # never happened.
                outcome = "cancelled"
            elif returncode != 0:
                outcome = "failure"
            elif request.print and request.start_print:
                # The pipeline exits as soon as the printer accepts the job, so a zero
                # exit code means "dispatched", not "printed". Recording that as a
                # success is how the outcome column ends up describing the software
                # rather than the part. Only a human can close this out.
                outcome = "awaiting_verdict"
            else:
                outcome = "success"
            db.update_job_outcome_verdict(
                job_id,
                outcome,
                source="machine",
                completed_at=datetime.now(timezone.utc),
            )
            db.close()
            activity.action(
                "pipeline finished",
                [("job", job_id[:8]), ("exit code", returncode), ("outcome", outcome)],
                outcome={
                    "cancelled": "stopped on request — not a failure",
                    "failure": "the pipeline exited non-zero",
                    "awaiting_verdict": "dispatched to the printer; only a person can close this out",
                }.get(outcome, "finished"),
                status="ok" if outcome in ("success", "awaiting_verdict") else "fail",
                level="INFO" if outcome in ("success", "awaiting_verdict") else "WARNING",
                source="pipeline",
            )
            await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": outcome}})
    except Exception as e:
        # Same reasoning as above: a phase raising because its process was killed is
        # a cancellation, not a failure.
        outcome = "cancelled" if job_id in cancelled_jobs else "failure"
        db = TelemetryDB()
        db.update_job_outcome_verdict(
            job_id, outcome, source="machine", completed_at=datetime.now(timezone.utc)
        )
        db.close()
        with open(log_file, "a") as f:
            f.write(f"\nPipeline failed to start: {e}\n")
        activity.action(
            "pipeline aborted",
            [("job", job_id[:8]), ("error", str(e))],
            outcome="stopped on request" if outcome == "cancelled" else "recorded as a failure",
            status="warn" if outcome == "cancelled" else "fail",
            level="WARNING" if outcome == "cancelled" else "ERROR",
            source="pipeline",
        )
        await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": outcome}})
    finally:
        active_pipelines.pop(job_id, None)
        cancelled_jobs.discard(job_id)
        detector_task = active_detectors.pop(job_id, None)
        if detector_task:
            detector_task.cancel()
        collector = active_collectors.pop(job_id, None)
        if collector:
            await collector.stop()

@app.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
async def create_job(request: JobRequest):
    """Create a new print job.

    Validates the job request, generates a unique job ID, inserts a new 'queued' 
    PrintJob record into the TelemetryDB, and launches the pipeline subprocess 
    in the background.

    Args:
        request: The job configuration parameters.

    Returns:
        A JobResponse containing the job ID and 'queued' status immediately.
    """
    status_res = await printer_status()
    if not status_res.get("configured"):
        raise HTTPException(
            status_code=400,
            detail="Cannot start job: no printer or simulator is configured. "
                   "Choose one in Settings.",
        )
    # `configured` only means a target is set. Starting a five-phase run against a
    # printer that will refuse the file at the end wastes the whole pipeline — and on
    # the hosted sculptor backend it wastes real money.
    if not status_res.get("running"):
        raise HTTPException(
            status_code=400,
            detail="Cannot start job: the configured printer did not answer. "
                   + (status_res.get("detail") or "Test the connection in Settings."),
        )

    job_id = str(uuid.uuid4())

    repo_root = Path(__file__).parent.parent
    
    # Clean up artifacts from previous jobs to prevent the UI from loading old images
    for artifact in [
        repo_root / "data" / "inputs" / "blueprint.png",
        repo_root / "data" / "outputs" / "raw_mesh.obj",
        repo_root / "data" / "outputs" / "engineered_mesh.obj",
        repo_root / "data" / "outputs" / "engineered_mesh.stl",
        repo_root / "data" / "outputs" / "engineered_mesh.gcode"
    ]:
        if artifact.exists():
            try:
                artifact.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete old artifact {artifact}: {e}")

    profile_path = str(repo_root / (request.profile or "pythonsrc/profiles/ender3.json"))
    firmware = "octoprint"
    if not os.path.exists(profile_path):
        logger.error(f"Printer profile not found: {profile_path} — disabling print")
        request.print = False
        request.start_print = False

    firmware, base_url, api_key = resolve_printer_target(profile_path)
    base_url = base_url or "http://localhost:5001"

    process_params, nozzle_diameter_mm = _profile_snapshot(profile_path)

    db = TelemetryDB()
    job = PrintJob(
        job_id=job_id,
        prompt=request.prompt,
        printer_id=request.printer_id,
        printer_firmware=firmware,
        slicer="cura",
        profile_name=request.profile or "default",
        started_at=None,
        completed_at=None,
        outcome="unknown",
        material_type=request.material_type,
        material_brand=request.material_brand,
        material_colour=request.material_colour,
        nozzle_diameter_mm=nozzle_diameter_mm,
        process_params=process_params,
        parent_job_id=request.parent_job_id,
        regeneration_reason=request.regeneration_reason,
    )
    db.insert_job(job)

    activity.action(
        "job created",
        [
            ("job", job_id[:8]),
            ("prompt", request.prompt),
            ("profile", request.profile or "default"),
            ("firmware", firmware),
            ("material", request.material_type or "unset"),
            ("seed", request.seed if request.seed is not None else "drawn at run time"),
            ("regen of", request.parent_job_id[:8] if request.parent_job_id else None),
        ],
        outcome="queued; pipeline subprocess starting",
        status="ok",
    )

    # A regeneration is an implicit judgement on the parent — the user looked at that
    # result and asked for another. Recorded against the parent, which is the job the
    # signal is actually about.
    if request.parent_job_id:
        try:
            db.record_job_event(request.parent_job_id, "regenerate", {
                "child_job_id": job_id,
                "reason": request.regeneration_reason,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record regenerate event: %s", exc)

    if request.print:
        collector = None
        if firmware in ("klipper", "moonraker"):
            ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
            if not ws_url.endswith("/websocket"):
                ws_url = ws_url.rstrip("/") + "/websocket"
            collector = MoonrakerCollector(ws_url, job_id, TelemetryDB())
        elif firmware == "octoprint":
            parsed = urlparse(base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 80
            collector = OctoPrintCollector(host, port, api_key or "", job_id, TelemetryDB())
        elif firmware == "bambu":
            logger.warning("Telemetry not yet available for Bambu")

        if collector:
            active_collectors[job_id] = collector
            asyncio.create_task(collector.start())

            # Consume the collector's samples — without this, automated failure
            # detection never runs. Whichever collector process wins the telemetry
            # claim is the one whose queue receives samples.
            try:
                operator = PrinterFactory.create(firmware, base_url, api_key)
            except Exception as e:
                operator = None
                logger.warning(f"No operator for detector ({firmware}): {e}")
            active_detectors[job_id] = attach_detector(collector, TelemetryDB(), operator)

            # These two are the background machinery that was completely silent: a job
            # whose collector never claimed the row, or whose detector had no operator
            # and therefore could not evaluate half its rules, looked identical to a
            # healthy one from the log.
            activity.action(
                "telemetry attached",
                [
                    ("job", job_id[:8]),
                    ("collector", type(collector).__name__),
                    ("firmware", firmware),
                    ("detector", "armed" if operator else "no operator — progress rules off"),
                ],
                outcome="sampling; the single-writer claim is taken on the first sample",
                status="ok" if operator else "warn",
                level="INFO" if operator else "WARNING",
                source="telemetry",
            )
        else:
            activity.event(
                f"no telemetry collector for firmware {firmware!r} · job {job_id[:8]}",
                level="WARNING",
                source="telemetry",
            )

    db.close()

    asyncio.create_task(_run_pipeline(job_id, request))
    
    return JobResponse(job_id=job_id, status="queued")

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """Retrieve the status and details of a specific print job.

    Args:
        job_id: The unique identifier of the print job.

    Returns:
        JobStatusResponse containing metadata, timestamps, status,
        and a tail of the execution log.

    Raises:
        HTTPException: If the job is not found in the database.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    # Phase 5 waits on a person. Derived on the open handle rather than from a second
    # connection, and before the 404 so the row is read exactly once.
    job_dispatch_state = dispatch_state(job, db) if job else "not_ready"
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    repo_root = Path(__file__).parent.parent
    log_dir = repo_root / "data" / "logs"
    log_file = log_dir / f"{job_id}.log"

    log_tail = []
    if log_file.exists():
        with open(log_file, "r") as f:
            lines = f.readlines()
            log_tail = [line.rstrip('\n') for line in lines[-20:]]
            
    current_phase = _read_current_phase(job_id)
    # A killed pipeline leaves its `.status` file frozen mid-phase, so a job that has
    # stopped keeps claiming that phase is running — and every client that polls this
    # endpoint re-lights the pulse the cancel just put out. The row's own outcome is
    # the authority on whether anything is still running.
    if (
        current_phase
        and current_phase.get("status") == "running"
        and job.outcome not in (None, "unknown")
    ):
        current_phase = {**current_phase, "status": "error", "error": "Stopped"}
            
    # Prefer the snapshot frozen when the job was created. Reading the profile file
    # instead means editing a profile retroactively rewrites what old jobs claim to
    # have printed with; the live read stays only as a fallback for rows predating
    # process_params.
    machine_name = None
    layer_height_mm = None
    build_volume_mm = None

    def _volume(source: dict) -> list[float] | None:
        """[width, depth, height] in mm, or None if the profile does not say.

        The G-code preview draws the bed and the build envelope around the toolpath,
        and a wrong envelope is worse than none: a part that fits reads as overflowing
        a machine it was never sliced for.
        """
        keys = ("machine_width", "machine_depth", "machine_height")
        if not all(source.get(k) is not None for k in keys):
            return None
        try:
            return [float(source[k]) for k in keys]
        except (TypeError, ValueError):
            return None

    if job.process_params:
        machine_name = job.process_params.get("machine_name")
        layer_height_mm = job.process_params.get("layer_height")
        build_volume_mm = _volume(job.process_params)
    else:
        profile_path_str = job.profile_name
        if profile_path_str and profile_path_str != "default":
            try:
                profile_full_path = repo_root / profile_path_str
                if profile_full_path.exists():
                    with open(profile_full_path, "r") as pf:
                        profile_data = json.load(pf)
                        machine_name = profile_data.get("machine_name")
                        layer_height_mm = profile_data.get("layer_height")
                        build_volume_mm = _volume(profile_data)
            except Exception:
                pass

    current_status = job_status_from_outcome(job.outcome, job.started_at)

    # The target is resolved on read too, so what a person confirms is the printer as it
    # stands rather than as it was when the job was created.
    job_dispatch_target = dispatch_target(job) if job_dispatch_state != "not_ready" else None

    return JobStatusResponse(
        job_id=job.job_id,
        status=current_status,
        prompt=job.prompt,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        outcome=job.outcome,
        log_tail=log_tail,
        current_phase=current_phase,
        printer_id=job.printer_id,
        printer_firmware=job.printer_firmware,
        profile_name=job.profile_name,
        machine_name=machine_name,
        layer_height_mm=layer_height_mm,
        build_volume_mm=build_volume_mm,
        nozzle_diameter_mm=job.nozzle_diameter_mm,
        printability_score=job.printability_score,
        printability_verdict=job.printability_verdict,
        material_type=job.material_type,
        material_brand=job.material_brand,
        material_colour=job.material_colour,
        blueprint_seed=job.blueprint_seed,
        parent_job_id=job.parent_job_id,
        download_count=job.download_count or 0,
        slice_status=job.slice_status,
        estimated_print_time_s=job.estimated_print_time_s,
        filament_used_mm3=job.filament_used_mm3,
        filament_used_g=job.filament_used_g,
        support_filament_mm3=job.support_filament_mm3,
        layer_count=job.layer_count,
        outcome_source=job.outcome_source,
        awaiting_verdict=job.outcome == "awaiting_verdict",
        dispatch_state=job_dispatch_state,
        dispatch_target=job_dispatch_target,
    )

@app.get("/jobs/{job_id}/printer-info")
async def get_printer_info(job_id: str):
    """Get normalized printer metadata for a job."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    repo_root = Path(__file__).parent.parent
    
    service_labels = {
        "octoprint": "OctoPrint",
        "klipper": "Klipper",
        "bambu": "Bambu Lab",
    }
    
    machine_name = None
    layer_height_mm = None
    machine_dimensions = None
    profile_path_str = job.profile_name
    
    if profile_path_str and profile_path_str != "default":
        try:
            profile_full_path = repo_root / profile_path_str
            if profile_full_path.exists():
                with open(profile_full_path, "r") as pf:
                    profile_data = json.load(pf)
                    machine_name = profile_data.get("machine_name")
                    layer_height_mm = profile_data.get("layer_height")
                    w = profile_data.get("machine_width")
                    d = profile_data.get("machine_depth")
                    h = profile_data.get("machine_height")
                    if w and d and h:
                        machine_dimensions = {"width": w, "depth": d, "height": h}
        except Exception:
            pass
    
    firmware = job.printer_firmware or "octoprint"
    connection_status = "unknown"
    stored = config_store.get_all()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            if firmware == "octoprint":
                url = stored.get("OCTOPRINT_URL")
                if url:
                    headers = {}
                    api_key = stored.get("OCTOPRINT_API_KEY")
                    if api_key:
                        headers["X-Api-Key"] = api_key
                    resp = await client.get(f"{url.rstrip('/')}/api/version", headers=headers)
                    connection_status = "online" if resp.status_code == 200 else "offline"
                else:
                    connection_status = "offline"
            elif firmware == "klipper":
                url = stored.get("MOONRAKER_URL")
                if url:
                    resp = await client.get(f"{url.rstrip('/')}/printer/info")
                    connection_status = "online" if resp.status_code == 200 else "offline"
                else:
                    connection_status = "offline"
            else:
                connection_status = "unknown"
    except Exception:
        connection_status = "offline"
    
    return {
        "service": firmware,
        "service_label": service_labels.get(firmware, firmware),
        "printer_name": machine_name or job.printer_id,
        "profile_name": profile_path_str,
        "connection_status": connection_status,
        "layer_height_mm": layer_height_mm,
        "machine_dimensions": machine_dimensions
    }

@app.get("/jobs/{job_id}/download")
async def download_job_output(job_id: str):
    """Download the final .gcode output file for a completed print job.

    Args:
        job_id: The unique identifier of the print job.

    Returns:
        A FileResponse streaming the generated .gcode file.

    Raises:
        HTTPException: If the job is not complete, failed, or the file is missing.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)

    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    gcode_path = resolve_job_artifact(job_id, "engineered_mesh.gcode")

    if gcode_path is None:
        db.close()
        raise HTTPException(status_code=404, detail="File not found")

    # A job that never finished has no G-code of its own. Serving the flat legacy file
    # here would hand the caller some other job's print.
    is_per_job = gcode_path.parent.name == job_id
    if not is_per_job and job.outcome not in ("success", "cancelled", "awaiting_verdict"):
        db.close()
        raise HTTPException(
            status_code=404,
            detail="No G-code for this job yet (job has not completed slicing).",
        )

    # A download is the clearest signal that a result was worth keeping, and it is
    # unrecoverable after the fact — recorded before the bytes stream, since the
    # response is lazy and may be abandoned mid-flight.
    try:
        db.record_job_event(job_id, "download", {"artifact": "engineered_mesh.gcode"})
        db.increment_download_count(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record download event for %s: %s", job_id, exc)
    db.close()

    def iterfile():
        with open(gcode_path, mode="rb") as f:
            while chunk := f.read(8192):
                yield chunk
                
    headers = {
        "Content-Disposition": f'attachment; filename="{job_id}.gcode"'
    }
    from fastapi.responses import StreamingResponse
    return StreamingResponse(iterfile(), media_type="text/plain", headers=headers)

class DispatchRequest(BaseModel):
    """A person's confirmation that this job may go to a machine.

    `confirmed` is required to be true. It is not a formality: nothing else in the
    system stops a print, so the flag is the gate, and a caller that cannot say a human
    approved the dispatch is a caller that must not dispatch. The optional `profile` and
    `base_url` are the target *as it was displayed* — when they are supplied and no
    longer match what the server resolves, the answer is 409 rather than a print to a
    machine nobody chose.
    """
    confirmed: bool = False
    profile: Optional[str] = None
    base_url: Optional[str] = None


@app.post("/jobs/{job_id}/print-dispatch")
async def print_dispatch(job_id: str, request: DispatchRequest | None = None):
    """Run Phase 5 for an already-sliced job, once a person has confirmed the target.

    The pipeline is launched without `--print`, so it stops after the slicer and the job
    waits here. This is the human in the loop: the four checks below are the difference
    between a confirmation step and a button.

    Args:
        job_id: The job to dispatch.
        request: The confirmation, carrying the target the user was shown.

    Returns:
        A dict with the dispatch status and the target it went to.

    Raises:
        HTTPException: 404 unknown job; 400 unconfirmed or nothing to send; 409 when the
            target moved under the user or the printer will not answer.
    """
    confirmation = request or DispatchRequest()
    if not confirmation.confirmed:
        raise HTTPException(
            status_code=400,
            detail="A print is only dispatched on an explicit confirmation. "
                   "Review the printer and send it from the job view.",
        )

    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    state = dispatch_state(job, db)
    if state == "dispatched":
        db.close()
        raise HTTPException(status_code=409, detail="This job has already been sent to a printer.")

    gcode_path = resolve_job_artifact(job_id, "engineered_mesh.gcode")
    if gcode_path is None:
        db.close()
        raise HTTPException(status_code=400, detail="No G-code for this job. Complete phases 1–4 first.")

    target = dispatch_target(job)
    profile_path = resolve_job_profile(job)[1]
    if not profile_path:
        db.close()
        raise HTTPException(status_code=400, detail="Configured printer profile not found.")

    # The target as shown, against the target as it stands. A profile swapped in Settings
    # between the two is exactly the case this step exists to catch.
    drifted = [
        (name, shown, current)
        for name, shown, current in (
            ("profile", confirmation.profile, target["profile"]),
            ("base_url", confirmation.base_url, target["base_url"]),
        )
        if shown and current and shown != current
    ]
    if drifted:
        db.close()
        changes = "; ".join(f"{name}: {shown} → {current}" for name, shown, current in drifted)
        raise HTTPException(
            status_code=409,
            detail=f"The printer changed since you looked ({changes}). Check it and confirm again.",
        )

    # Asked, not assumed. A dead printer discovered here costs a click; discovered by the
    # operator subprocess it costs a job that reads as dispatched and never printed.
    probe = await printer_status()
    if not probe.get("running"):
        db.close()
        raise HTTPException(
            status_code=409,
            detail="The printer did not answer. " + (probe.get("detail") or "Test the connection in Settings."),
        )

    repo_root = Path(__file__).parent.parent
    try:
        db.record_job_event(job_id, "dispatch_confirmed", {
            "profile": target["profile"],
            "firmware": target["firmware"],
            "base_url": target["base_url"],
            "machine_name": target["machine_name"],
            "gcode": gcode_path.name,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record the dispatch confirmation for %s: %s", job_id, exc)

    # Dispatched is not printed. The file leaving for a machine settles nothing about the
    # part, so the row goes to awaiting_verdict and a person closes it out later.
    db.update_job_outcome_verdict(
        job_id, "awaiting_verdict", source="machine", completed_at=datetime.now(timezone.utc)
    )
    db.close()

    activity.action(
        "print dispatch confirmed",
        [
            ("job", job_id[:8]),
            ("profile", target["profile"]),
            ("firmware", target["firmware"]),
            ("printer", target["base_url"]),
        ],
        outcome="operator starting; the row is awaiting a human verdict",
        status="ok",
        source="operator",
    )

    log_dir = repo_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _append_phase_status(job_id, 5, "running")
    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {
        "phase": 5, "name": "Operator", "status": "running", "error": None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }})

    try:
        cmd = [
            sys.executable,
            str(repo_root / "pythonsrc" / "run_operator.py"),
            "--job-id", job_id,
            "--gcode-path", str(gcode_path),
            "--profile", profile_path,
        ]

        env = os.environ.copy()
        octoprint_key = config_store.get("OCTOPRINT_API_KEY")
        if octoprint_key:
            env["OCTOPRINT_API_KEY"] = octoprint_key
        # Without this the operator's telemetry collector has nowhere to relay samples,
        # so the print runs with a live socket open and nothing on it.
        env.setdefault("P2P_API_URL", "http://127.0.0.1:8000")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=repo_root,
            env=env,
        )

        async def _run():
            """Follow the operator to its end, rather than firing and forgetting.

            The old version launched it and returned. A dispatch that failed left the
            job claiming to be printing, with the reason only in a subprocess nobody
            was reading.
            """
            log_file = log_dir / f"{job_id}.log"
            with open(log_file, "a") as handle:
                handle.write(f"\n[dispatch] operator starting for {gcode_path.name}\n")
                await _stream_output(process, handle, job_id)
                await process.wait()
                handle.write(f"[dispatch] operator exited with {process.returncode}\n")

            failed = process.returncode != 0
            _append_phase_status(job_id, 5, "error" if failed else "complete",
                                 error=f"operator exited with {process.returncode}" if failed else None)
            await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {
                "phase": 5, "name": "Operator", "status": "error" if failed else "complete",
                "error": f"The operator exited with {process.returncode}" if failed else None,
                "ts": datetime.now(timezone.utc).isoformat(),
            }})
            if failed:
                # The print never started, so the row must not sit in awaiting_verdict
                # asking a person about a part that does not exist.
                inner = TelemetryDB()
                inner.update_job_outcome_verdict(
                    job_id, "failure", source="machine",
                    completed_at=datetime.now(timezone.utc),
                )
                inner.close()
                await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": "failure"}})

        asyncio.create_task(_run())

        return {"status": "dispatching", "target": target}
    except Exception as e:
        logger.error(f"Error in print-dispatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel the running job and the printer."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Mark the job cancelled *before* killing anything. The pipeline's exit is
    # observed by `_run_pipeline`, which would otherwise read the non-zero code as a
    # crash and overwrite this verdict with "failure".
    cancelled_jobs.add(job_id)

    # Kill the pipeline, then make sure it is actually gone. `terminate()` only asks:
    # a pipeline blocked on a hosted generation or a docker build can sit in SIGTERM
    # handling for a long time, and the endpoint used to return "cancelled" while the
    # work carried on spending money in the background.
    process = active_pipelines.get(job_id)
    if process:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=PIPELINE_TERM_GRACE_S)
        except asyncio.TimeoutError:
            logger.warning(
                "Pipeline for job %s ignored SIGTERM after %ss; killing",
                job_id, PIPELINE_TERM_GRACE_S,
            )
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass

    # The phase the pipeline died inside is still recorded as "running", both in the
    # `.status` file it will never write again and in every client's phase row. Say so
    # explicitly, or the UI keeps a phase pulsing forever on a job that has stopped —
    # which reads as the Stop button having done nothing at all.
    stopped_phase = _read_current_phase(job_id)
    if stopped_phase and stopped_phase.get("status") == "running":
        await broadcaster.broadcast(job_id, {
            "type": "phase_update",
            "data": {
                "phase": stopped_phase.get("phase"),
                "name": stopped_phase.get("name"),
                "status": "error",
                "error": "Stopped",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        })
            
    # Attempt to cancel printer
    repo_root = Path(__file__).parent.parent
    profile_path = str(repo_root / (config_store.get("DEFAULT_PROFILE") or "pythonsrc/profiles/ender3.json"))
    try:
        if os.path.exists(profile_path):
            firmware, base_url, api_key = resolve_printer_target(profile_path)
            from pythonsrc.operators import PrinterFactory
            op = PrinterFactory.create(
                firmware=firmware,
                base_url=base_url or "http://localhost:5001",
                api_key=api_key,
            )
            # Try to cancel
            try:
                op.cancel_print()
            except Exception as e:
                logger.warning(f"Could not cancel print on printer: {e}")
    except Exception as e:
        logger.warning(f"Error instantiating printer factory during cancel: {e}")

    # A machine-sourced write: it must never clobber a verdict a human already gave.
    db.update_job_outcome_verdict(
        job_id, "cancelled", source="machine",
        completed_at=datetime.now(timezone.utc),
    )
    db.close()
    
    activity.action(
        "job stopped by user",
        [
            ("job", job_id[:8]),
            ("phase", (stopped_phase or {}).get("phase")),
            ("printer", "cancel sent" if os.path.exists(profile_path) else "no profile"),
        ],
        outcome="pipeline killed, outcome recorded as cancelled",
        status="warn",
        level="WARNING",
    )
    await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": "cancelled"}})
    return {"status": "cancelled"}

class PrinterActionRequest(BaseModel):
    action: str

@app.post("/jobs/{job_id}/action")
async def printer_action(job_id: str, request: PrinterActionRequest):
    """Execute a printer action (pause, resume, cancel)."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    repo_root = Path(__file__).parent.parent
    profile_path = str(repo_root / (config_store.get("DEFAULT_PROFILE") or "pythonsrc/profiles/ender3.json"))
    
    if not os.path.exists(profile_path):
        raise HTTPException(status_code=400, detail="Printer profile not found")
        
    try:
        firmware, base_url, api_key = resolve_printer_target(profile_path)
        from pythonsrc.operators import PrinterFactory
        op = PrinterFactory.create(
            firmware=firmware,
            base_url=base_url or "http://localhost:5001",
            api_key=api_key,
        )
        
        if request.action == "pause":
            op.pause_print()
        elif request.action == "resume":
            op.resume_print()
        elif request.action == "cancel":
            op.cancel_print()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

        activity.action(
            f"printer {request.action}",
            [("job", job_id[:8]), ("firmware", firmware), ("target", base_url)],
            outcome="the machine accepted it",
            status="ok",
        )
        return {"status": "success", "action": request.action}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to execute printer action {request.action}: {e}")
        activity.action(
            f"printer {request.action}",
            [("job", job_id[:8]), ("error", str(e))],
            outcome="the machine refused it — nothing changed",
            status="fail",
            level="ERROR",
        )
        raise HTTPException(status_code=500, detail=str(e))

class InternalTelemetryRequest(BaseModel):
    type: str
    data: dict

@app.post("/jobs/{job_id}/internal-telemetry")
async def internal_telemetry(job_id: str, request: InternalTelemetryRequest):
    """Internal endpoint for pipeline-runner to push telemetry/state updates."""
    await broadcaster.broadcast(job_id, {"type": request.type, "data": request.data})
    return {"status": "success"}

@app.get("/jobs")
async def list_jobs(limit: int = 20, offset: int = 0, status: str = 'all'):
    """List print jobs with pagination and status filtering."""
    db = TelemetryDB()
    cursor = db.conn.cursor()
    
    where_clause = ""
    params = []
    
    if status == 'running':
        where_clause = "WHERE outcome = 'unknown'"
    elif status == 'completed':
        where_clause = "WHERE outcome = 'success'"
    elif status == 'failed':
        where_clause = "WHERE outcome IN ('failure', 'cancelled')"
    elif status == 'awaiting_verdict':
        where_clause = "WHERE outcome = 'awaiting_verdict'"
    elif status == 'awaiting_dispatch':
        # Sliced, finished, and never sent: the jobs whose Phase 5 is waiting on a
        # person. Without this the confirmation step would not survive a page reload,
        # which for a human-in-the-loop gate means it would not survive at all.
        where_clause = (
            "WHERE outcome = 'success' AND slice_status = 'success' "
            "AND job_id NOT IN (SELECT job_id FROM job_event WHERE kind = 'dispatch_confirmed')"
        )

    count_query = f"SELECT COUNT(*) FROM print_job {where_clause}"
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    global_counts_query = "SELECT outcome, COUNT(*) as count FROM print_job GROUP BY outcome"
    cursor.execute(global_counts_query)
    global_counts = cursor.fetchall()
    
    stats = {"total": 0, "running": 0, "completed": 0, "failed": 0, "awaiting_verdict": 0}
    for row in global_counts:
        outcome = row['outcome']
        c = row['count']
        stats["total"] += c
        if outcome == "unknown":
            stats["running"] += c
        elif outcome == "success":
            stats["completed"] += c
        elif outcome == "awaiting_verdict":
            # Its own bucket: counting an unconfirmed print as a failure would be as
            # wrong as counting it as a success.
            stats["awaiting_verdict"] += c
        else:
            stats["failed"] += c

    query = f"SELECT * FROM print_job {where_clause} ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    
    rows = cursor.fetchall()

    # Which of these have actually been sent. One query rather than one per row, and the
    # only way a list row can tell "finished" from "finished and waiting on a person".
    cursor.execute("SELECT DISTINCT job_id FROM job_event WHERE kind = 'dispatch_confirmed'")
    dispatched = {r['job_id'] for r in cursor.fetchall()}

    jobs = []
    for row in rows:
        job_outcome = row['outcome']
        status_val = job_status_from_outcome(job_outcome, row['started_at'])
        keys = row.keys()
        jobs.append({
            "job_id": row['job_id'],
            "prompt": row['prompt'],
            "printer_id": row['printer_id'],
            "printer_firmware": row['printer_firmware'],
            "started_at": row['started_at'],
            "completed_at": row['completed_at'],
            "outcome": job_outcome,
            "status": status_val,
            # Read via `keys` because a database migrated mid-session may not carry
            # these columns yet.
            "material_type": row['material_type'] if 'material_type' in keys else None,
            "awaiting_verdict": job_outcome == "awaiting_verdict",
            "outcome_source": row['outcome_source'] if 'outcome_source' in keys else None,
            # Sliced, finished, never sent: Phase 5 is waiting for someone to confirm the
            # printer. Reported here so the dashboard can say so instead of calling it
            # "Success" — nothing has been printed.
            "awaiting_dispatch": (
                job_outcome == "success"
                and ('slice_status' in keys and row['slice_status'] == "success")
                and row['job_id'] not in dispatched
            ),
        })
    db.close()
    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset, "stats": stats}

@app.get("/health")
async def health_check():
    """Health check endpoint.

    `database` reports the verdict from the startup integrity check rather than
    re-running it: `PRAGMA integrity_check` walks every page, and this endpoint is
    polled. A degraded database is still reported as reachable — the server does
    work, it is the data underneath that cannot be trusted — so the caller gets the
    problems and decides.
    """
    strategy = get_resolved_strategy()
    detected = get_execution_strategy()
    return {
        "status": "ok" if not database_problems else "degraded",
        "version": app.version,
        "execution_strategy": strategy,
        "detected_strategy": detected,
        "database": {
            "healthy": not database_problems,
            "problems": database_problems,
        },
    }

@app.get("/jobs/{job_id}/telemetry")
async def get_job_telemetry(job_id: str) -> List[Dict[str, Any]]:
    """Retrieve telemetry samples for a specific print job.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A list of up to 100 recent telemetry samples as dictionaries.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
        
    samples = db.get_samples(job_id, limit=100)
    db.close()
    return [s.to_dict() for s in samples]

class FailureRequest(BaseModel):
    """Pydantic model representing a manual failure event report."""
    failure_type: str
    notes: Optional[str] = None

@app.get("/jobs/{job_id}/printability")
async def get_job_printability(job_id: str):
    """Return the pre-print printability report for a job.

    Args:
        job_id: The job whose report is wanted.

    Returns:
        The report as produced by `PrintabilityReport.to_dict()`.

    Raises:
        HTTPException: 404 if the job is unknown, or if it has no report — a job that
            never reached the Engineer has nothing to score.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.printability_report:
        return job.printability_report

    # Jobs run before the report was persisted still have the artifact on disk.
    report_path = resolve_job_artifact(job_id, "printability.json")
    if report_path is not None:
        try:
            with open(report_path, "r") as f:
                return json.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not read printability report for {job_id}: {exc}")

    raise HTTPException(status_code=404, detail="No printability report for this job yet")

@app.post("/jobs/{job_id}/failure")
async def create_failure_event(job_id: str, request: FailureRequest) -> Dict[str, Any]:
    """Manually flag a print job as failed.

    Args:
        job_id: The unique identifier of the job.
        request: The failure details and notes.

    Returns:
        A dictionary representation of the recorded FailureEvent.
    """
    db = TelemetryDB()
    samples = db.get_samples(job_id, limit=50)
    
    event_id = str(uuid.uuid4())
    event = FailureEvent(
        event_id=event_id,
        job_id=job_id,
        detected_at=datetime.now(timezone.utc),
        gcode_line=samples[0].gcode_line if samples else None,
        z_height_mm=samples[0].z_height_mm if samples else None,
        failure_type=request.failure_type,
        source="manual",
        notes=request.notes,
        snapshot=[s.to_dict() for s in samples]
    )
    db.insert_failure_event(event)
    db.close()
    return event.to_dict()

@app.get("/jobs/{job_id}/failure")
async def get_failure_events(job_id: str) -> List[Dict[str, Any]]:
    """Retrieve failure events for a job.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A list of FailureEvent dictionaries.
    """
    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    return [e.to_dict() for e in events]

@app.get("/jobs/{job_id}/provenance")
async def get_job_provenance(job_id: str) -> Dict[str, Any]:
    """Return everything captured about how a job's result was produced.

    Kept off `GET /jobs/{id}`, which is polled by the UI on a timer and would otherwise
    carry a large payload on every tick. This is the endpoint to read when analysing
    the pilot dataset.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary of blueprint, mesh, slice, target and engagement facts.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    events = db.get_job_events(job_id)
    db.close()

    return {
        "job_id": job.job_id,
        "prompt": job.prompt,
        "blueprint": {
            "model": job.blueprint_model,
            "model_version": job.blueprint_model_version,
            "seed": job.blueprint_seed,
            "prompt_engineered": job.blueprint_prompt_engineered,
            "params": job.blueprint_params,
            "sha256": job.blueprint_sha256,
            "duration_s": job.blueprint_duration_s,
        },
        "generation": {
            "model": job.generation_model,
            "model_version": job.generation_model_version,
            "backend": job.generation_backend,
            "params": job.generation_params,
            "cost_eur": job.generation_cost_eur,
            "duration_s": job.generation_duration_s,
        },
        "mesh": {
            "raw_sha256": job.raw_mesh_sha256,
            "raw_features": job.raw_mesh_features,
            "repaired_sha256": job.repaired_mesh_sha256,
            "repaired_features": job.repaired_mesh_features,
            "printed_features": job.mesh_features,
        },
        "printability": {
            "score": job.printability_score,
            "verdict": job.printability_verdict,
        },
        "slice": {
            "status": job.slice_status,
            "error": job.slice_error,
            "duration_s": job.slice_duration_s,
            "estimated_print_time_s": job.estimated_print_time_s,
            "filament_used_mm": job.filament_used_mm,
            "filament_used_mm3": job.filament_used_mm3,
            "filament_used_g": job.filament_used_g,
            "support_filament_mm3": job.support_filament_mm3,
            "layer_count": job.layer_count,
            "stats": job.slice_stats,
        },
        "target": {
            "printer_id": job.printer_id,
            "printer_firmware": job.printer_firmware,
            "profile_name": job.profile_name,
            "process_params": job.process_params,
            "nozzle_diameter_mm": job.nozzle_diameter_mm,
            "material_type": job.material_type,
            "material_brand": job.material_brand,
            "material_colour": job.material_colour,
        },
        "engagement": {
            "download_count": job.download_count or 0,
            "parent_job_id": job.parent_job_id,
            "regeneration_reason": job.regeneration_reason,
            "events": [e.to_dict() for e in events],
        },
        "outcome": {
            "outcome": job.outcome,
            "source": job.outcome_source,
            "reported_at": job.outcome_reported_at.isoformat() if job.outcome_reported_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        },
    }


# ── Print outcome feedback ────────────────────────────────────────────────────
# The signal nothing else can supply. A printer reporting "job finished" says only
# that the file ran to the end; whether the part survived, adhered and came off the
# bed intact is knowable only by the person standing next to it. Everything below
# exists to make saying so take one tap, and to measure how often people bother.

@app.get("/feedback/pending")
async def list_pending_feedback(limit: int = 50) -> Dict[str, Any]:
    """List prints whose outcome no human has confirmed yet.

    Args:
        limit: Maximum number of jobs to return.

    Returns:
        A dictionary with the pending jobs and a count.
    """
    db = TelemetryDB()
    jobs = db.get_jobs_awaiting_verdict(limit=limit)
    db.close()

    return {
        "count": len(jobs),
        "jobs": [
            {
                "job_id": job.job_id,
                "prompt": job.prompt,
                "printer_id": job.printer_id,
                "material_type": job.material_type,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "estimated_print_time_s": job.estimated_print_time_s,
                "printability_score": job.printability_score,
            }
            for job in jobs
        ],
    }


@app.post("/jobs/{job_id}/outcome/prompt-shown")
async def record_outcome_prompt_shown(job_id: str) -> Dict[str, Any]:
    """Record that the outcome prompt was actually put in front of someone.

    Called by the UI when a pending card first renders. Logged once per job — the
    denominator of the pilot's response rate has to be prompts a person saw, not jobs
    that entered the queue, and a re-render or a page refresh must not inflate it.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary reporting whether a new event was recorded.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    if not db.get_job(job_id):
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    already = db.get_job_events(job_id, kind="outcome_prompt_shown")
    if already:
        db.close()
        return {"recorded": False, "reason": "already shown"}

    db.record_job_event(job_id, "outcome_prompt_shown")
    db.close()
    return {"recorded": True}


@app.post("/jobs/{job_id}/outcome/dismiss")
async def dismiss_outcome_prompt(job_id: str) -> Dict[str, Any]:
    """Record that someone was asked for a verdict and chose not to give one.

    A skip is data. Whether pilot users will report outcomes at all is the thing being
    tested, so a declined prompt has to be distinguishable from one never shown. The
    job stays in `awaiting_verdict` and can still be answered later.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary confirming the dismissal was recorded.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    if not db.get_job(job_id):
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    db.record_job_event(job_id, "outcome_prompt_dismissed")
    db.close()
    return {"recorded": True}


@app.post("/jobs/{job_id}/outcome")
async def report_outcome(job_id: str, request: OutcomeRequest) -> Dict[str, Any]:
    """Record a human's verdict on whether a print succeeded.

    Writes `outcome_source="user"`, which is what separates ground truth from the
    printer's own report. A failure verdict also writes a manual `FailureEvent`, so the
    existing detector-versus-human comparison keeps working without a second code path.

    Args:
        job_id: The unique identifier of the job.
        request: The verdict, plus optional failure details.

    Returns:
        A dictionary with the recorded outcome.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    db.update_job_outcome_verdict(job_id, request.verdict, source="user")

    failure_event = None
    if request.verdict == "failure":
        samples = db.get_samples(job_id, limit=50)
        failure_event = FailureEvent(
            event_id=str(uuid.uuid4()),
            job_id=job_id,
            detected_at=datetime.now(timezone.utc),
            # get_samples returns oldest-first; the failure happened at the newest.
            gcode_line=samples[-1].gcode_line if samples else None,
            z_height_mm=samples[-1].z_height_mm if samples else None,
            failure_type=request.failure_type or "unknown",
            source="manual",
            notes=request.notes,
            snapshot=[s.to_dict() for s in samples],
        )
        db.insert_failure_event(failure_event)

    db.record_job_event(job_id, "outcome_reported", {
        "verdict": request.verdict,
        "failure_type": request.failure_type,
        "layer_pct": request.layer_pct,
    })
    db.close()

    activity.action(
        "outcome reported by user",
        [
            ("job", job_id[:8]),
            ("verdict", request.verdict),
            ("failure", request.failure_type),
            ("at layer", f"{request.layer_pct}%" if request.layer_pct is not None else None),
        ],
        # Worth saying out loud: this is the one write a later machine event cannot
        # overturn, which is exactly why it is the label worth having.
        outcome="recorded as ground truth — machine events cannot overwrite it",
        status="ok" if request.verdict == "success" else "warn",
    )

    await broadcaster.broadcast(job_id, {
        "type": "job_complete",
        "data": {"outcome": request.verdict, "outcome_source": "user"},
    })

    return {
        "job_id": job_id,
        "outcome": request.verdict,
        "outcome_source": "user",
        "failure_event_id": failure_event.event_id if failure_event else None,
    }


@app.get("/feedback/stats")
async def feedback_stats() -> Dict[str, Any]:
    """Report how often outcome prompts are actually answered.

    The pilot's headline number. Counted over jobs that were prompted, so a job nobody
    has been shown yet neither helps nor hurts the rate, and a verdict volunteered
    without a prompt cannot push it above 1.

    Returns:
        Funnel counts, raw event totals and the derived response rate.
    """
    db = TelemetryDB()
    funnel = db.feedback_funnel()
    reported_total = db.count_job_events("outcome_reported")
    pending = len(db.get_jobs_awaiting_verdict(limit=1000))
    db.close()

    prompted = funnel["prompted"]
    return {
        "prompts_shown": prompted,
        "outcomes_reported": funnel["answered"],
        "prompts_dismissed": funnel["dismissed"],
        "unanswered": funnel["unanswered"],
        # Includes verdicts given without a prompt, e.g. straight from a job page.
        "outcomes_reported_total": reported_total,
        "pending": pending,
        "response_rate": round(funnel["answered"] / prompted, 4) if prompted else None,
    }


class ConfigUpdate(BaseModel):
    key: str
    value: str

class TestConnectionRequest(BaseModel):
    service: str

@app.get("/config")
async def get_config():
    """Get all configuration keys with their values and metadata."""
    stored = config_store.get_all()
    results = {}
    for key, meta in CONFIG_KEYS.items():
        val = stored.get(key)
        is_set = val is not None
        
        display_val = None
        if is_set:
            display_val = "••••••••" if meta.get("secret") else val
            
        results[key] = {
            "value": display_val,
            "is_set": is_set,
            "label": meta.get("label"),
            "description": meta.get("description"),
            "required": meta.get("required"),
            "secret": meta.get("secret")
        }
    return results

@app.post("/config")
async def update_config(update: ConfigUpdate):
    """Update a configuration value."""
    if update.key not in CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="Invalid config key")
        
    meta = CONFIG_KEYS[update.key]
    secret = bool(meta.get("secret"))
    # Read the old value before overwriting it: "what changed" is the question anyone
    # debugging a configuration has, and it is unanswerable after the write.
    previous = config_store.get(update.key)

    config_store.set(update.key, update.value)
    os.environ[update.key] = update.value

    display_val = "••••••••" if secret else update.value
    # A secret's *value* never reaches the log; whether it went from unset to set does,
    # because that is the fact that explains a connection starting to work.
    activity.action(
        "config changed",
        [
            ("key", update.key),
            ("from", "••••••••" if (secret and previous) else (previous or "(unset)")),
            ("to", display_val),
        ],
        outcome="saved, encrypted at rest; live for the next request",
        status="ok",
    )
    
    return {
        "key": update.key,
        "value": display_val,
        "is_set": True,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "required": meta.get("required"),
        "secret": meta.get("secret")
    }

@app.delete("/config/{key}")
async def delete_config(key: str):
    """Delete a configuration value."""
    if key not in CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="Invalid config key")
    
    config_store.delete(key)
    if key in os.environ:
        del os.environ[key]

    activity.action(
        "config cleared",
        [("key", key)],
        outcome="removed from the store and the environment",
        status="warn",
    )
    return {"status": "success", "key": key}

@app.get("/config/{key}/reveal")
async def reveal_config(key: str):
    """Reveal a secret configuration value."""
    if key not in CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="Invalid config key")
        
    val = config_store.get(key)
    if val is None:
        raise HTTPException(status_code=404, detail="Config key not set")
        
    return {"key": key, "value": val}

@app.post("/config/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test connection to a specific service."""
    service = req.service.lower()
    if service == "klipper":
        # The UI sends firmware names; Moonraker is the HTTP API fronting Klipper.
        # Same alias PrinterFactory accepts — without it every Klipper printer
        # reads "Offline" forever.
        service = "moonraker"
    stored = config_store.get_all()
    
    import time
    start_time = time.time()
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            if service == "octoprint":
                url = stored.get("OCTOPRINT_URL")
                api_key = stored.get("OCTOPRINT_API_KEY")
                if not url:
                    return {"success": False, "message": "OCTOPRINT_URL not configured", "latency_ms": None}
                
                headers = {}
                if api_key:
                    headers["X-Api-Key"] = api_key
                
                resp = await client.get(f"{url.rstrip('/')}/api/version", headers=headers)
                resp.raise_for_status()
                
            elif service == "moonraker":
                url = stored.get("MOONRAKER_URL")
                if not url:
                    return {"success": False, "message": "MOONRAKER_URL not configured", "latency_ms": None}
                    
                resp = await client.get(f"{url.rstrip('/')}/printer/info")
                resp.raise_for_status()
                
            elif service == "bambu":
                # Bambu speaks MQTT over TLS on 8883 in LAN mode, so there is no
                # HTTP endpoint to GET. A TCP connect proves the printer is on the
                # network and listening, which is a real check — but it does not
                # validate the access code, and the message says so rather than
                # implying the credentials are good.
                host = stored.get("BAMBU_IP")
                if not host:
                    return {"success": False, "message": "BAMBU_IP not configured", "latency_ms": None}
                if not stored.get("BAMBU_CODE"):
                    return {
                        "success": False,
                        "message": "No LAN access code yet — find it on the printer under Settings → Network.",
                        "latency_ms": None,
                    }

                host = host.replace("mqtts://", "").replace("https://", "").split("/")[0].split(":")[0]
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, 8883), timeout=5.0
                    )
                    writer.close()
                    await writer.wait_closed()
                except (asyncio.TimeoutError, OSError) as exc:
                    return {
                        "success": False,
                        "message": f"No answer from {host}:8883 — is the printer on and in LAN mode? ({exc})",
                        "latency_ms": None,
                    }

                return {
                    "success": True,
                    "message": f"{host} is reachable on port 8883. The access code is not verified until a print is sent.",
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            elif service == "huggingface":
                token = stored.get("HF_TOKEN")
                if not token:
                    return {"success": False, "message": "HF_TOKEN not configured", "latency_ms": None}
                    
                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get("https://huggingface.co/api/whoami-v2", headers=headers)
                resp.raise_for_status()
                
            else:
                raise HTTPException(status_code=400, detail="Invalid service")
                
            latency_ms = int((time.time() - start_time) * 1000)
            return {"success": True, "message": "Connection successful", "latency_ms": latency_ms}
            
        except httpx.TimeoutException:
            return {"success": False, "message": "Connection timed out", "latency_ms": None}
        except httpx.RequestError as e:
            return {"success": False, "message": f"Connection failed: {str(e)}", "latency_ms": None}
        except httpx.HTTPStatusError as e:
            if service == "huggingface" and e.response.status_code == 401:
                return {"success": False, "message": "Invalid HuggingFace Token", "latency_ms": None}
            # A 401/403 means we reached the printer and it refused us — the opposite
            # diagnosis from "unreachable", and the fix is a key rather than a cable.
            # Dumping the raw body here surfaced OctoPrint's stock Flask 403 page
            # ("You don't have the permission to access the requested resource"),
            # which names neither the printer nor the credential and sent people
            # looking at their network.
            if e.response.status_code in (401, 403):
                where = {
                    "octoprint": "OCTOPRINT_API_KEY",
                    "moonraker": "MOONRAKER_API_KEY",
                }.get(service, "the API key")
                hint = (
                    " For the bundled simulator it must match `accessControl` in "
                    "data/octoprint/octoprint/config.yaml."
                    if service == "octoprint"
                    else ""
                )
                return {
                    "success": False,
                    "message": (
                        f"Reached the printer, but it rejected the credential "
                        f"({e.response.status_code}). Check {where}.{hint}"
                    ),
                    "latency_ms": int((time.time() - start_time) * 1000),
                }
            return {
                "success": False,
                "message": f"HTTP {e.response.status_code} from {service}: {e.response.text[:200]}",
                "latency_ms": None,
            }
        except Exception as e:
            return {"success": False, "message": str(e), "latency_ms": None}

@app.websocket("/ws/jobs/{job_id}")
async def websocket_job_endpoint(websocket: WebSocket, job_id: str):
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        await websocket.accept()
        await websocket.send_json({"type": "error", "data": {"code": 4004, "message": "Job not found"}})
        await websocket.close(code=4004)
        return

    samples = db.get_samples(job_id, limit=20)
    db.close()

    await websocket.accept()
    
    status_resp = await get_job(job_id)
    await websocket.send_json({"type": "job_status", "data": status_resp.dict()})
    
    await websocket.send_json({"type": "telemetry_batch", "data": [s.to_dict() for s in samples]})
    
    await broadcaster.connect(job_id, websocket)
    activity.event(f"watcher attached · job {job_id[:8]}", source="ws")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(job_id, websocket)
        activity.event(f"watcher left · job {job_id[:8]}", source="ws")

class UiEvent(BaseModel):
    """One thing a person did in the browser that never reached another endpoint."""

    action: str = Field(..., min_length=1, max_length=80)
    detail: str | None = Field(default=None, max_length=200)


class UiEventBatch(BaseModel):
    events: list[UiEvent] = Field(default_factory=list, max_length=50)


@app.post("/activity/ui", status_code=status.HTTP_202_ACCEPTED)
async def record_ui_activity(batch: UiEventBatch):
    """Record interactions that change no server state.

    Switching a stage tab, expanding the process log, scrubbing a layer — none of these
    hit another endpoint, so from the server's side a user who spent five minutes
    looking for something was indistinguishable from an idle one. Batched by the client
    and capped here, because this is a debugging aid and must never become a write
    amplifier: nothing is persisted, it goes to the in-memory feed only.
    """
    for event in batch.events[:50]:
        activity.event(
            f"ui · {event.action}" + (f" · {event.detail}" if event.detail else ""),
            level="DEBUG",
            source="ui",
        )
    return {"accepted": len(batch.events[:50])}


@app.get("/activity")
async def get_activity(limit: int = 200):
    """The server's recent activity, newest last.

    Read once on page load; `/ws/activity` carries it from there. In memory only — a
    debugging aid must not add a second reader to the telemetry database.
    """
    return {"entries": activity.recent(limit=max(1, min(limit, 500)))}


@app.websocket("/ws/activity")
async def websocket_activity_endpoint(websocket: WebSocket):
    """Live server activity, in the symbol grammar defined in `server/activity.py`.

    Not scoped to a job, unlike `/ws/jobs/{job_id}`: config edits, simulator lifecycle
    and printer actions belong to no job, and those are exactly the ones that were
    invisible.
    """
    await websocket.accept()
    await websocket.send_json({"type": "activity_batch", "data": activity.recent(limit=200)})

    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    def on_record(record) -> None:
        # `put_nowait` from a synchronous listener, so emitting activity never blocks
        # on a slow socket. A client that cannot keep up loses lines rather than
        # applying backpressure to a print job.
        try:
            queue.put_nowait(record.as_dict())
        except asyncio.QueueFull:
            pass

    unsubscribe = activity.subscribe(on_record)
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json({"type": "activity", "data": entry})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("Activity socket closed", exc_info=True)
    finally:
        unsubscribe()


@app.get("/simulators/status")
async def get_simulators_status():
    return simulator_manager.get_status()

@app.post("/simulators/moonraker/start")
async def start_moonraker_simulator():
    status = await simulator_manager.start_moonraker()

    healthy = False
    async with httpx.AsyncClient(timeout=1.0) as client:
        for _ in range(30):
            try:
                resp = await client.get(f"{status['url']}/printer/info")
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)

    status["healthy"] = healthy
    activity.action(
        "moonraker simulator start",
        [("url", status.get("url")), ("healthy", healthy)],
        outcome="answering /printer/info" if healthy else "started but not answering yet",
        status="ok" if healthy else "warn",
        level="INFO" if healthy else "WARNING",
        source="simulator",
    )
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/moonraker/stop")
async def stop_moonraker_simulator():
    status = await simulator_manager.stop_moonraker()
    activity.event("moonraker simulator stopped", source="simulator", level="WARNING")
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.get("/simulators/moonraker/logs")
async def get_moonraker_simulator_logs():
    repo_root = Path(__file__).parent.parent
    log_file = repo_root / "data" / "logs" / "moonraker_mock.log"
    if not log_file.exists():
        return {"lines": []}
        
    with open(log_file, "r") as f:
        lines = f.readlines()
        
    return {"lines": [line.rstrip() for line in lines[-100:]]}

#: OctoPrint takes roughly half a minute to come up — intermediary server, plugin
#: load, then the real server. The old budget was 30 × 0.1s = 3 seconds, so a cold
#: start was always reported unhealthy.
_OCTOPRINT_BOOT_TIMEOUT_S = 90
_OCTOPRINT_POLL_INTERVAL_S = 1.0


@app.post("/simulators/octoprint/start")
async def start_octoprint_simulator():
    try:
        status = await simulator_manager.start_octoprint()
    except SimulatorAvailabilityError as exc:
        # Docker being down is an environment problem the user can fix, not a bug:
        # report it as such instead of a 500 with a stack trace.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # The probe must authenticate: OctoPrint answers an unauthenticated
    # /api/version with 403, so a keyless poll can never see it come up.
    api_key = status.get("api_key") or config_store.get("OCTOPRINT_API_KEY")
    headers = {"X-Api-Key": api_key} if api_key else {}

    healthy = False
    deadline = asyncio.get_event_loop().time() + _OCTOPRINT_BOOT_TIMEOUT_S
    async with httpx.AsyncClient(timeout=5.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"{status['url']}/api/version", headers=headers)
                if resp.status_code == 200:
                    healthy = True
                    break
                if resp.status_code in (401, 403):
                    logger.warning(
                        "OctoPrint simulator is up but rejected our API key (%s). "
                        "Is OCTOPRINT_API_KEY in sync with "
                        "data/octoprint/octoprint/config.yaml?",
                        resp.status_code,
                    )
                    break
            except Exception:
                pass  # still booting
            await asyncio.sleep(_OCTOPRINT_POLL_INTERVAL_S)

    status["healthy"] = healthy
    activity.action(
        "octoprint simulator start",
        [
            ("url", status.get("url")),
            ("api key", "present" if api_key else "MISSING"),
            ("healthy", healthy),
        ],
        outcome=(
            "answering /api/version"
            if healthy
            else "up but not authenticating — check OCTOPRINT_API_KEY against "
                 "data/octoprint/octoprint/config.yaml"
        ),
        status="ok" if healthy else "fail",
        level="INFO" if healthy else "WARNING",
        source="simulator",
    )
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/octoprint/stop")
async def stop_octoprint_simulator():
    status = await simulator_manager.stop_octoprint()
    activity.event("octoprint simulator stopped", source="simulator", level="WARNING")
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.get("/simulators/octoprint/logs")
async def get_octoprint_simulator_logs():
    repo_root = Path(__file__).parent.parent
    log_file = repo_root / "data" / "logs" / "octoprint_mock.log"
    if not log_file.exists():
        return {"lines": []}
        
    with open(log_file, "r") as f:
        lines = f.readlines()
        
    return {"lines": [line.rstrip() for line in lines[-100:]]}

@app.get("/system/info")
async def system_info():
    detected = get_execution_strategy()
    resolved = get_resolved_strategy()
    
    docker_available = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3.0)
        docker_available = res.returncode == 0
    except Exception:
        pass
        
    labels = {
        "mps_native": "macOS Apple Silicon (MPS native Phase 1, Docker Phases 2-5)",
        "nvidia_docker": "NVIDIA GPU (full pipeline via Docker with GPU)",
        "cpu_docker": "CPU only (full pipeline via Docker)"
    }
    
    return {
        "detected_strategy": detected,
        "resolved_strategy": resolved,
        "override_active": config_store.get("EXECUTION_STRATEGY_OVERRIDE") is not None and config_store.get("EXECUTION_STRATEGY_OVERRIDE") in ("mps_native", "nvidia_docker", "cpu_docker"),
        "strategy_label": labels.get(resolved, "Unknown"),
        "docker_available": docker_available,
        "platform": sys.platform,
        "python_version": platform.python_version()
    }

@app.get("/system/printer/status")
async def printer_status():
    """Whether there is a printer that will actually accept a job right now.

    This used to answer `running: True` for any profile file that existed, without
    opening a single connection — so a profile pointing at a switched-off printer
    reported ready, the pipeline view opened, and the failure surfaced four phases
    later at dispatch. `configured` means "a target is set"; `running` now means
    "we asked it and it answered", and only the second one should gate a job.

    The container reachability check is `test_connection`'s, reused rather than
    reimplemented: two probes that can disagree about the same printer is how a
    "ready" badge ends up next to a dead machine.
    """
    sim_status = simulator_manager.get_status()
    if sim_status.get("octoprint", {}).get("running"):
        # The container being up is not the same as OctoPrint answering inside it, and
        # the boot takes tens of seconds.
        probe = await test_connection(TestConnectionRequest(service="octoprint"))
        return {
            "configured": True,
            "type": "simulator",
            "running": bool(probe.get("success")),
            "detail": probe.get("message"),
        }

    profile = config_store.get("DEFAULT_PROFILE")
    if not profile:
        return {"configured": False, "type": "none", "running": False,
                "detail": "No printer profile selected."}

    profile_path = Path(__file__).parent.parent / profile
    if not profile_path.exists():
        return {"configured": False, "type": "none", "running": False,
                "detail": f"Profile file not found: {profile}"}

    try:
        firmware, _base_url, _api_key = resolve_printer_target(str(profile_path))
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "type": "real", "running": False,
                "detail": f"Could not read {profile}: {exc}"}

    service = {"klipper": "moonraker", "moonraker": "moonraker",
               "bambu": "bambu"}.get(firmware, "octoprint")
    probe = await test_connection(TestConnectionRequest(service=service))
    return {
        "configured": True,
        "type": "real",
        "running": bool(probe.get("success")),
        "detail": probe.get("message"),
    }

@app.get("/jobs/{job_id}/blueprint")
async def get_blueprint(job_id: str):
    """Serve the blueprint image this job used.

    Args:
        job_id: The job whose blueprint is wanted.

    Returns:
        The PNG image, from the job's own directory when the pipeline snapshotted it.
    """
    blueprint_path = resolve_job_artifact(job_id, "blueprint.png")
    if blueprint_path is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return FileResponse(str(blueprint_path), media_type="image/png")



@app.get("/jobs/{job_id}/mesh")
async def get_mesh(job_id: str):
    """Serve the engineered mesh this job produced.

    Args:
        job_id: The job whose mesh is wanted.

    Returns:
        The .obj file, from the job's own directory when it exists.
    """
    mesh_path = resolve_job_artifact(job_id, "engineered_mesh.obj")
    if mesh_path is None:
        raise HTTPException(status_code=404, detail="Mesh not found")
    return FileResponse(str(mesh_path), media_type="application/octet-stream")

# --- Serve SPA ---
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Catch-all route to serve the React SPA and its static assets.

    Args:
        full_path: The requested path.

    Returns:
        A FileResponse containing the requested asset or index.html.

    Raises:
        HTTPException: If the frontend is not built or found.
    """
    dist_dir = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
    file_path = os.path.join(dist_dir, full_path)
    
    # If a specific static file is requested and exists, serve it
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Otherwise, fallback to index.html for client-side routing
    index_path = os.path.join(dist_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
        
    raise HTTPException(status_code=404, detail="Frontend not built or not found")

