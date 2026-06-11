import json
import asyncio
from fastapi.testclient import TestClient
from server.app import app
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from datetime import datetime, timezone

def setup_db():
    db = TelemetryDB()
    db.init_schema()
    job = PrintJob(
        job_id="test_ws_job_123",
        prompt="Test",
        printer_id="TestPrinter",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name="default",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    # Insert job, ignore if exists
    try:
        db.insert_job(job)
    except Exception:
        pass
    db.close()

def run_tests():
    setup_db()
    with TestClient(app) as client:
        # Test 1: valid job_id connects successfully and receives job_status
        with client.websocket_connect("/ws/jobs/test_ws_job_123") as websocket:
            data = websocket.receive_json()
            assert data["type"] == "job_status", f"Expected job_status, got {data['type']}"
            assert data["data"]["job_id"] == "test_ws_job_123"
            
            # Should also receive telemetry_batch immediately after
            data2 = websocket.receive_json()
            assert data2["type"] == "telemetry_batch"
            assert isinstance(data2["data"], list)
            print("Valid WS connection test - OK")

        # Test 2: non-existent job_id returns close frame with code 4004
        from starlette.websockets import WebSocketDisconnect
        try:
            with client.websocket_connect("/ws/jobs/does_not_exist_999") as websocket:
                pass
            print("Failed: Should have raised WebSocketDisconnect")
            exit(1)
        except WebSocketDisconnect as e:
            assert e.code == 4004, f"Expected 4004, got {e.code}"
            print("Invalid WS connection 4004 - OK")

        # Test 3: GET /simulators/status returns expected shape
        resp = client.get("/simulators/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "moonraker" in data and "octoprint" in data
        assert data["moonraker"]["running"] is False
        assert data["octoprint"]["running"] is False
        print("GET /simulators/status - OK")

if __name__ == "__main__":
    run_tests()
    print("All websocket tests passed!")
