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
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Add pythonsrc to sys.path so we can import telemetry modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from pythonsrc.telemetry.db import TelemetryDB, _str_to_dt
from pythonsrc.telemetry.schema import PrintJob, FailureEvent, TelemetrySample
from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
from pythonsrc.telemetry.detector import attach_detector
from pythonsrc.operators import PrinterFactory
from pythonsrc.platform_utils import get_execution_strategy, get_phase1_command
import httpx
from server.config_store import ConfigStore, CONFIG_KEYS
from server.job_broadcaster import broadcaster
from server.simulator_manager import simulator_manager

logger = logging.getLogger(__name__)

app = FastAPI(title="P2P Mesh API", version="1.0.0")

config_store = ConfigStore()

active_collectors = {}
active_detectors: dict[str, asyncio.Task] = {}
active_pipelines: dict[str, asyncio.subprocess.Process] = {}


def resolve_job_artifact(job_id: str, filename: str) -> Path | None:
    """Locate a job's artifact, preferring its per-job directory.

    The pipeline writes artifacts to ``data/outputs/{job_id}/`` so that jobs cannot
    overwrite each other. Older jobs wrote to the flat ``data/outputs/`` layout, so that
    path is still accepted as a fallback for rows created before the change.

    Args:
        job_id: The job whose artifact is wanted.
        filename: Artifact filename, e.g. "engineered_mesh.gcode".

    Returns:
        The path to the artifact, or None if neither location has it.
    """
    outputs = Path(__file__).parent.parent / "data" / "outputs"
    per_job = outputs / job_id / filename
    if per_job.exists():
        return per_job

    legacy = outputs / filename
    if legacy.exists():
        return legacy

    if filename == "blueprint.png":
        shared_input = Path(__file__).parent.parent / "data" / "inputs" / "blueprint.png"
        if shared_input.exists():
            return shared_input

    return None


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
    if outcome in ("success", "awaiting_verdict"):
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
    """A human's verdict on whether a print actually succeeded."""
    verdict: str = Field(..., pattern="^(success|failure|cancelled)$")
    failure_type: Optional[str] = None
    notes: Optional[str] = None
    layer_pct: Optional[float] = None

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

async def _stream_output(process, log_file_obj, job_id: str):
    import re
    phase_re = re.compile(r"\[P2P\] ═══ PHASE (\d+) (START|PASS|FAIL)(.*)═══")
    phase_names = {1: "Visualizer", 2: "Sculptor", 3: "Engineer", 4: "Slicer", 5: "Operator"}
    
    async for line_bytes in process.stdout:
        line = line_bytes.decode('utf-8', errors='replace')
        log_file_obj.write(line)
        log_file_obj.flush()
        
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
                
            asyncio.create_task(broadcaster.broadcast(job_id, {
                "type": "phase_update",
                "data": {
                    "phase": phase_num,
                    "name": name,
                    "status": status,
                    "error": error,
                    "ts": datetime.now(timezone.utc).isoformat()
                }
            }))

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
            if returncode != 0:
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
            await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": outcome}})
    except Exception as e:
        db = TelemetryDB()
        db.update_job_outcome_verdict(
            job_id, "failure", source="machine", completed_at=datetime.now(timezone.utc)
        )
        db.close()
        with open(log_file, "a") as f:
            f.write(f"\nPipeline failed to start: {e}\n")
        await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": "failure"}})
    finally:
        active_pipelines.pop(job_id, None)
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
    if not status_res["configured"]:
        raise HTTPException(status_code=400, detail="Cannot start job: No real printer or simulator is configured and running. Please check your Printer Setup.")

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
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    repo_root = Path(__file__).parent.parent
    log_dir = repo_root / "data" / "logs"
    log_file = log_dir / f"{job_id}.log"
    status_file = log_dir / f"{job_id}.status"
    
    log_tail = []
    if log_file.exists():
        with open(log_file, "r") as f:
            lines = f.readlines()
            log_tail = [line.rstrip('\n') for line in lines[-20:]]
            
    current_phase = None
    if status_file.exists():
        with open(status_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
            if lines:
                try:
                    current_phase = json.loads(lines[-1])
                except json.JSONDecodeError:
                    pass
            
    # Prefer the snapshot frozen when the job was created. Reading the profile file
    # instead means editing a profile retroactively rewrites what old jobs claim to
    # have printed with; the live read stays only as a fallback for rows predating
    # process_params.
    machine_name = None
    layer_height_mm = None
    if job.process_params:
        machine_name = job.process_params.get("machine_name")
        layer_height_mm = job.process_params.get("layer_height")
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
            except Exception:
                pass

    current_status = job_status_from_outcome(job.outcome, job.started_at)

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

@app.post("/jobs/{job_id}/print-dispatch")
async def print_dispatch(job_id: str):
    """Trigger Phase 5 (Operator) only, using an already-sliced gcode file."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    repo_root = Path(__file__).parent.parent
    gcode_path = resolve_job_artifact(job_id, "engineered_mesh.gcode")

    if gcode_path is None:
        raise HTTPException(status_code=400, detail="Gcode file not found. Complete phases 1-4 first.")

    profile_path = str(repo_root / (config_store.get("DEFAULT_PROFILE") or "pythonsrc/profiles/ender3.json"))
    if not os.path.exists(profile_path):
        raise HTTPException(status_code=400, detail="Configured printer profile not found.")
        
    try:
        cmd = [
            sys.executable,
            str(repo_root / "pythonsrc" / "run_operator.py"),
            "--job-id", job_id,
            "--gcode-path", str(gcode_path),
            "--profile", profile_path
        ]
        
        env = os.environ.copy()
        octoprint_key = config_store.get("OCTOPRINT_API_KEY")
        if octoprint_key:
            env["OCTOPRINT_API_KEY"] = octoprint_key

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=repo_root,
            env=env
        )
        
        # We don't block the API, but we track it or just let it finish.
        # For simplicity, we could await it or just launch and return. The prompt says "runs operator subprocess"
        # We'll just await it so we can return error if it fails, or since we have a WebSocket, we could just fire & forget.
        # Let's fire & forget so the UI doesn't hang, but since it's just dispatch we can wait a bit or let it run.
        # Let's fire and forget.
        async def _run():
            await process.wait()
            
        asyncio.create_task(_run())
        
        return {"status": "dispatching"}
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
        
    # Kill pipeline
    process = active_pipelines.get(job_id)
    if process:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
            
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
            
        return {"status": "success", "action": request.action}
    except Exception as e:
        logger.error(f"Failed to execute printer action {request.action}: {e}")
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
        })
    db.close()
    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset, "stats": stats}

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    strategy = get_resolved_strategy()
    detected = get_execution_strategy()
    return {"status": "ok", "version": app.version, "execution_strategy": strategy, "detected_strategy": detected}

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
        
    config_store.set(update.key, update.value)
    os.environ[update.key] = update.value
    
    meta = CONFIG_KEYS[update.key]
    display_val = "••••••••" if meta.get("secret") else update.value
    
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
            return {"success": False, "message": f"HTTP Error {e.response.status_code}: {e.response.text}", "latency_ms": None}
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
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(job_id, websocket)

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
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/moonraker/stop")
async def stop_moonraker_simulator():
    status = await simulator_manager.stop_moonraker()
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

@app.post("/simulators/octoprint/start")
async def start_octoprint_simulator():
    status = await simulator_manager.start_octoprint()

    healthy = False
    async with httpx.AsyncClient(timeout=1.0) as client:
        for _ in range(30):
            try:
                resp = await client.get(f"{status['url']}/api/version")
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)

    status["healthy"] = healthy
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/octoprint/stop")
async def stop_octoprint_simulator():
    status = await simulator_manager.stop_octoprint()
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
    """Verify if a simulator or real printer is configured and running."""
    # Check simulator
    sim_status = simulator_manager.get_status()
    if sim_status.get("octoprint", {}).get("running"):
        return {"configured": True, "type": "simulator", "running": True}
        
    # Check real printer profile
    profile = config_store.get("DEFAULT_PROFILE")
    if profile:
        profile_path = Path(__file__).parent.parent / profile
        if profile_path.exists():
            if profile in ["pythonsrc/profiles/ender3.json", "pythonsrc/profiles/bambu_test.json"]:
                # These are dummy profiles that require the simulator, which is not running
                return {"configured": False, "type": "none", "running": False}
            return {"configured": True, "type": "real", "running": True} 
            
    return {"configured": False, "type": "none", "running": False}

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

