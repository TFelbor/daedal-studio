import os
import subprocess
import time
import requests
import pytest

def test_pipeline_status():
    # Start the server
    server_process = subprocess.Popen(
        ["uvicorn", "server.app:app", "--port", "8001"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
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
        
        # Verify current_phase is included
        assert "current_phase" in final_data
        phase = final_data["current_phase"]
        assert phase is not None, "current_phase should not be None"
        assert "phase" in phase
        assert "name" in phase
        assert "status" in phase
    finally:
        # Cleanup server
        server_process.terminate()
        server_process.wait()
