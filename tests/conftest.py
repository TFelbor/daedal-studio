import pytest
import tempfile
import asyncio
import uuid
from datetime import datetime, timezone
import json
import websockets
import socketio
from aiohttp import web

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob, TelemetrySample

@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = TelemetryDB(db_path=tmp.name)
        db.init_schema()
        yield db
        db.close()

@pytest.fixture
def sample_job(tmp_db):
    job = PrintJob(
        job_id=str(uuid.uuid4()),
        prompt="test prompt",
        printer_id="test_printer_1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    tmp_db.insert_job(job)
    return job

@pytest.fixture
def sample_samples(tmp_db, sample_job):
    import time
    with open("tests/fixtures/sample_telemetry.json") as f:
        samples_data = json.load(f)
    
    samples = []
    for data in samples_data:
        data["job_id"] = sample_job.job_id
        sample = TelemetrySample.from_dict(data)
        tmp_db.insert_sample(sample)
        samples.append(sample)
    
    # Ensure there are 60 samples as requested by the test requirements
    if len(samples) < 60:
        for i in range(len(samples), 60):
            data = samples_data[i % len(samples_data)].copy()
            data["job_id"] = sample_job.job_id
            data["sampled_at"] = datetime.now(timezone.utc).isoformat()
            data["gcode_line"] = i * 10
            sample = TelemetrySample.from_dict(data)
            tmp_db.insert_sample(sample)
            samples.append(sample)
    return samples

@pytest.fixture
async def fake_moonraker_ws(unused_tcp_port):
    async def handler(websocket):
        try:
            async for message in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass

    async with websockets.serve(handler, "127.0.0.1", unused_tcp_port) as server:
        yield f"ws://127.0.0.1:{unused_tcp_port}/websocket"

@pytest.fixture
async def fake_octoprint_sio(unused_tcp_port):
    sio = socketio.AsyncServer(async_mode='aiohttp')
    app = web.Application()
    sio.attach(app)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', unused_tcp_port)
    await site.start()
    
    yield f"http://127.0.0.1:{unused_tcp_port}"
    
    await runner.cleanup()
