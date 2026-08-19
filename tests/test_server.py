import os
import subprocess
import time
import requests
import pytest
from pathlib import Path

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.real_printer
def test_pipeline_status():
    env = os.environ.copy()
    env["P2P_LOGS_DIR"] = str(Path("data/logs").absolute())

    # Start the server
    server_process = subprocess.Popen(
        ["uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    base_url = "http://localhost:8001"
    server_started = False
    for _ in range(30):
        try:
            resp = requests.get(f"{base_url}/health")
            if resp.status_code == 200:
                server_started = True
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
        
    assert server_started, "Server failed to start in time"
    
    try:
        # POST a job
        response = requests.post(f"{base_url}/jobs", json={
            "prompt": "a test prompt",
            "printer_id": "default",
            "profile": "test",
            "skip_visualizer": True,
            "skip_sculptor": True,
            "print": False,
            "start_print": False
        })
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        
        # Poll until status is completed
        max_retries = 30
        status = "queued"
        final_data = None
        for _ in range(max_retries):
            resp = requests.get(f"{base_url}/jobs/{job_id}")
            assert resp.status_code == 200
            data = resp.json()
            status = data["status"]
            final_data = data
            if status == "completed":
                break
            time.sleep(1)
            
        assert status == "completed", f"Job failed to complete within time limit. Last data: {final_data}"
        
        # Verify current_phase is included only if it successfully started phases
        assert "current_phase" in final_data
        if final_data["outcome"] == "success":
            phase = final_data["current_phase"]
            assert phase is not None, f"current_phase should not be None. Log tail: {final_data.get('log_tail', [])}"
            assert "phase" in phase
            assert "name" in phase
            assert "status" in phase
    finally:
        # Cleanup server
        server_process.terminate()
        server_process.wait()

from fastapi.testclient import TestClient
from server.app import app
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
import uuid
from datetime import datetime, timezone

client = TestClient(app)

def test_health_check_empty_db():
    # Empty DB
    db = TelemetryDB()
    db.init_schema()
    db.conn.execute('DELETE FROM print_job')
    db.conn.commit()
    db.close()
    
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_health_check_with_jobs():
    # DB with job
    db = TelemetryDB()
    db.init_schema()
    job = PrintJob(
        job_id="test_health_job",
        prompt="prompt",
        printer_id="pid",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="default",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    db.insert_job(job)
    db.close()
    
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_get_job_telemetry_not_found():
    response = client.get("/jobs/non-existent-job-id/telemetry")
    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}

def test_get_job_telemetry_empty_samples():
    db = TelemetryDB()
    db.init_schema()
    job_id = str(uuid.uuid4())
    job = PrintJob(job_id=job_id, prompt="test", printer_id="pid", printer_firmware="octoprint", slicer="cura", profile_name="default", started_at=datetime.now(timezone.utc), completed_at=None, outcome="unknown")
    db.insert_job(job)
    db.close()
    
    response = client.get(f"/jobs/{job_id}/telemetry")
    assert response.status_code == 200
    assert response.json() == []

def test_post_jobs_triggers_background(printer_configured):
    response = client.post("/jobs", json={
        "prompt": "Test background trigger",
        "printer_id": "default",
        "profile": "default",
        "skip_visualizer": True,
        "print": False,
        "start_print": False
    })
    assert response.status_code == 202
    assert "job_id" in response.json()

