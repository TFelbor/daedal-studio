import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Add pythonsrc to sys.path so we can import telemetry modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from pythonsrc.telemetry.db import TelemetryDB, _str_to_dt
from pythonsrc.telemetry.schema import PrintJob, FailureEvent, TelemetrySample
from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector

logger = logging.getLogger(__name__)

app = FastAPI(title="P2P Mesh API", version="1.0.0")

active_collectors = {}

class JobRequest(BaseModel):
    prompt: str
    printer_id: str
    profile: str
    skip_visualizer: bool
    skip_sculptor: bool = False
    blueprint_path: Optional[str] = None
    print: bool
    start_print: bool

class JobResponse(BaseModel):
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    prompt: str
    started_at: str
    completed_at: Optional[str]
    outcome: str
    log_tail: List[str]
    current_phase: Optional[dict] = None

@app.on_event("startup")
def startup_event():
    db = TelemetryDB()
    db.init_schema()
    db.close()

@app.on_event("shutdown")
async def shutdown_event():
    for collector in active_collectors.values():
        await collector.stop()
    active_collectors.clear()

async def _run_pipeline(job_id: str, request: JobRequest):
    log_dir = Path.home() / ".p2p-mesh" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{job_id}.log"
    
    cmd = [sys.executable, "pythonsrc/pipeline.py", request.prompt, "--job-id", job_id]
    if request.profile:
        cmd.extend(["--profile", request.profile])
    if request.skip_visualizer:
        cmd.append("--skip-visualizer")
    if request.skip_sculptor:
        cmd.append("--skip-sculptor")
    if request.blueprint_path:
        cmd.extend(["--blueprint", request.blueprint_path])
    if request.print:
        cmd.append("--print")
    if request.start_print:
        cmd.append("--start-print")
        
    try:
        with open(log_file, "w") as f:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=f,
                stderr=f,
                cwd=os.path.join(os.path.dirname(__file__), "..")
            )
            await process.wait()
            
            db = TelemetryDB()
            outcome = "success" if process.returncode == 0 else "failure"
            db.update_job_outcome(job_id, outcome, datetime.now(timezone.utc))
            db.close()
    except Exception as e:
        db = TelemetryDB()
        db.update_job_outcome(job_id, "failure", datetime.now(timezone.utc))
        db.close()
        with open(log_file, "a") as f:
            f.write(f"\nPipeline failed to start: {e}\n")
    finally:
        collector = active_collectors.pop(job_id, None)
        if collector:
            await collector.stop()

@app.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
async def create_job(request: JobRequest):
    """
    Create a new print job.

    Validates the job request, generates a unique job ID, inserts a new 'queued' 
    PrintJob record into the TelemetryDB, and launches the pipeline subprocess 
    in the background.

    Returns the job ID and 'queued' status immediately.
    """
    job_id = str(uuid.uuid4())
    
    profile_path = request.profile or "pythonsrc/profiles/ender3.json"
    firmware = "octoprint"
    base_url = "http://localhost:5001"
    api_key = None
    try:
        with open(profile_path, "r") as f:
            profile_data = json.load(f)
            firmware = profile_data.get("firmware", "octoprint")
            base_url = profile_data.get("base_url", "http://localhost:5001")
            api_key = profile_data.get("api_key")
    except Exception as e:
        logger.warning(f"Could not load profile {profile_path}: {e}")
        
    db = TelemetryDB()
    job = PrintJob(
        job_id=job_id,
        prompt=request.prompt,
        printer_id=request.printer_id,
        printer_firmware=firmware,
        slicer="cura",
        profile_name=request.profile or "default",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    db.insert_job(job)
    
    if request.print:
        collector = None
        if firmware == "klipper":
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
            
    db.close()
    
    asyncio.create_task(_run_pipeline(job_id, request))
    
    return JobResponse(job_id=job_id, status="queued")

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """
    Retrieve the status and details of a specific print job.

    Returns job metadata including started/completed timestamps, current status,
    and a tail of the last 20 lines from the job's execution log.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    log_dir = Path.home() / ".p2p-mesh" / "logs"
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
            
    # Determine synthetic status based on outcome
    current_status = "queued" if job.outcome == "unknown" else "completed"
    if job.outcome == "unknown" and job.started_at:
        current_status = "running"
            
    return JobStatusResponse(
        job_id=job.job_id,
        status=current_status,
        prompt=job.prompt,
        started_at=job.started_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        outcome=job.outcome,
        log_tail=log_tail,
        current_phase=current_phase
    )

@app.get("/jobs/{job_id}/download")
async def download_job_output(job_id: str):
    """
    Download the final .gcode output file for a completed print job.

    Returns a 404 error if the job is not complete, failed, or the file 
    is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.outcome != "success":
        raise HTTPException(status_code=404, detail="Job is not complete or failed")
        
    outputs_dir = os.path.join(os.path.dirname(__file__), "..", "data", "outputs")
    gcode_path = os.path.join(outputs_dir, "engineered_mesh.gcode")
    
    if not os.path.exists(gcode_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(gcode_path, media_type="text/plain", filename=f"{job_id}.gcode")

@app.get("/jobs")
async def list_jobs():
    """
    List all print jobs.

    Returns a list of all print jobs (up to the most recent 50), including
    their status, timestamps, and job metadata.
    """
    db = TelemetryDB()
    cursor = db.conn.cursor()
    cursor.execute('SELECT * FROM print_job ORDER BY started_at DESC LIMIT 50')
    rows = cursor.fetchall()
    
    jobs = []
    for row in rows:
        job_outcome = row['outcome']
        status_val = "running" if job_outcome == "unknown" else "completed"
        jobs.append({
            "job_id": row['job_id'],
            "prompt": row['prompt'],
            "printer_id": row['printer_id'],
            "started_at": row['started_at'],
            "completed_at": row['completed_at'],
            "outcome": job_outcome,
            "status": status_val
        })
    db.close()
    return jobs

@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns a simple OK status and the current API version to verify 
    that the server is running.
    """
    return {"status": "ok", "version": app.version}

@app.get("/jobs/{job_id}/telemetry")
async def get_job_telemetry(job_id: str) -> List[Dict[str, Any]]:
    db = TelemetryDB()
    samples = db.get_samples(job_id, limit=100)
    db.close()
    return [s.to_dict() for s in samples]

class FailureRequest(BaseModel):
    failure_type: str
    notes: Optional[str] = None

@app.post("/jobs/{job_id}/failure")
async def create_failure_event(job_id: str, request: FailureRequest) -> Dict[str, Any]:
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

# --- Serve SPA ---
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    Catch-all route to serve the React SPA and its static assets.
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

