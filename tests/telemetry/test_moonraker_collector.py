import asyncio
import json
import logging
from typing import AsyncGenerator, Callable, Coroutine, Any
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import websockets
from websockets.server import serve

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample, PrintJob
from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector

logger = logging.getLogger(__name__)

# Test constants
TEST_JOB_ID = "job-123"

@pytest.fixture
def in_memory_db(isolated_db):
    db = isolated_db
    
    # Insert a dummy job so foreign key constraints pass
    job = PrintJob(
        job_id=TEST_JOB_ID,
        prompt="Test Prompt",
        printer_id="printer-1",
        printer_firmware="klipper",
        slicer="Cura",
        profile_name="Standard",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown"
    )
    db.insert_job(job)
    
    yield db
    db.close()

class FakeMoonrakerServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.clients = set()
        self._server = None
        self.received_messages = []

    async def start(self):
        self._server = await serve(self.handler, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            
    async def disconnect_clients(self):
        for ws in self.clients:
            await ws.close()

    async def handler(self, websocket):
        self.clients.add(websocket)
        try:
            async for message in websocket:
                self.received_messages.append(json.loads(message))
        finally:
            self.clients.remove(websocket)

    async def broadcast_status(self, data: dict):
        if not self.clients:
            return
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": "notify_status_update",
            "params": [data]
        })
        for ws in self.clients:
            if not ws.closed:
                await ws.send(msg)

@pytest_asyncio.fixture
async def fake_server():
    server = FakeMoonrakerServer("127.0.0.1", 8765)
    await server.start()
    yield server
    await server.stop()

@pytest.mark.asyncio
async def test_moonraker_collector_subscription_and_samples(fake_server, in_memory_db):
    ws_url = f"ws://{fake_server.host}:{fake_server.port}/websocket"
    collector = MoonrakerCollector(ws_url=ws_url, job_id=TEST_JOB_ID, db=in_memory_db)
    
    await collector.start()
    
    # Wait for the client to connect and send the subscription message
    await asyncio.sleep(0.5)
    
    assert len(fake_server.received_messages) > 0
    sub_msg = fake_server.received_messages[0]
    assert sub_msg["method"] == "printer.objects.subscribe"
    
    # Send 10 synthetic messages
    for i in range(10):
        await fake_server.broadcast_status({
            "print_stats": {"file_position": 100 + i},
            "toolhead": {"position": [10.0, 20.0, 0.2 + (i*0.2)]},
            "extruder": {"temperature": 210.0, "target": 210.0},
            "heater_bed": {"temperature": 60.0, "target": 60.0},
            "fan": {"speed": 0.5}, # 50%
            "gcode_move": {"speed_factor": 1.0, "extrude_factor": 1.0}
        })
        
    # Wait for messages to be processed
    await asyncio.sleep(0.5)
    await collector.stop()
    
    # Verify samples in memory DB
    samples = in_memory_db.get_samples(TEST_JOB_ID)
    assert len(samples) == 10
    
    for i, sample in enumerate(samples):
        # We process in order, but get_samples returns DESC order, wait
        # get_samples does `ORDER BY sampled_at DESC` but the code says `# Return in ascending chronological order` `return samples[::-1]`
        # Let's check sample values.
        # i is chronological because get_samples returned in ascending order.
        assert sample.gcode_line == 100 + i
        assert sample.z_height_mm == pytest.approx(0.2 + (i*0.2))
        assert sample.hotend_actual_c == 210.0
        assert sample.hotend_target_c == 210.0
        assert sample.bed_actual_c == 60.0
        assert sample.bed_target_c == 60.0
        assert sample.fan_speed_pct == 50.0
        assert sample.print_speed_pct == 100.0
        assert sample.extrusion_factor_pct == 100.0

@pytest.mark.asyncio
async def test_moonraker_collector_reconnect(fake_server, in_memory_db, caplog):
    ws_url = f"ws://{fake_server.host}:{fake_server.port}/websocket"
    collector = MoonrakerCollector(ws_url=ws_url, job_id=TEST_JOB_ID, db=in_memory_db)
    
    with caplog.at_level(logging.WARNING):
        await collector.start()
        
        # Wait for connect
        await asyncio.sleep(0.5)
        assert len(fake_server.clients) == 1
        
        # Disconnect server clients to trigger reconnect
        await fake_server.disconnect_clients()
        
        # Wait for reconnect (exponential backoff starts at 1s)
        # 1.5 seconds should be enough to see the reconnect
        await asyncio.sleep(1.5)
        
        # Verify it reconnected
        assert len(fake_server.clients) == 1
        
        # Verify warning log was generated
        assert any("Moonraker connection error" in record.message for record in caplog.records)
        
    await collector.stop()

@pytest.mark.asyncio
async def test_moonraker_collector_partial_data(fake_server, in_memory_db):
    ws_url = f"ws://{fake_server.host}:{fake_server.port}/websocket"
    collector = MoonrakerCollector(ws_url=ws_url, job_id=TEST_JOB_ID, db=in_memory_db)
    
    await collector.start()
    await asyncio.sleep(0.5)
    
    # Missing fields
    await fake_server.broadcast_status({
        "print_stats": {},
        "toolhead": {}
        # missing extruder, heater_bed, etc.
    })
    
    await asyncio.sleep(0.5)
    await collector.stop()
    
    samples = in_memory_db.get_samples(TEST_JOB_ID)
    assert len(samples) == 1
    sample = samples[0]
    
    assert sample.gcode_line is None
    assert sample.z_height_mm is None
    assert sample.hotend_actual_c is None
    assert sample.bed_actual_c is None

@pytest.mark.asyncio
async def test_moonraker_collector_invalid_json(fake_server, in_memory_db):
    ws_url = f"ws://{fake_server.host}:{fake_server.port}/websocket"
    collector = MoonrakerCollector(ws_url=ws_url, job_id=TEST_JOB_ID, db=in_memory_db)
    
    await collector.start()
    await asyncio.sleep(0.5)
    
    # Send invalid JSON
    for ws in fake_server.clients:
        if not ws.closed:
            await ws.send("This is not valid JSON {]")
            
    await asyncio.sleep(0.5)
    await collector.stop()
    
    # Should skip without crashing
    samples = in_memory_db.get_samples(TEST_JOB_ID)
    assert len(samples) == 0

@pytest.mark.asyncio
async def test_moonraker_collector_stop_cancels_loop(fake_server, in_memory_db):
    ws_url = f"ws://{fake_server.host}:{fake_server.port}/websocket"
    collector = MoonrakerCollector(ws_url=ws_url, job_id=TEST_JOB_ID, db=in_memory_db)
    
    await collector.start()
    await asyncio.sleep(0.5)
    
    assert collector._task is not None
    assert not collector._task.done()
    
    await collector.stop()
    await asyncio.sleep(0.5)
    
    assert collector._task is None
