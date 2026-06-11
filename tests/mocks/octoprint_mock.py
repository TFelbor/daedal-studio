#!/usr/bin/env python3
"""
Minimal OctoPrint API mock for local development and testing.
Simulates the OctoPrint REST API and Socket.IO without requiring hardware.

Run: python3 octoprint_mock.py --port 5001
     Serves on http://localhost:5001
"""

import argparse
import asyncio
import time
from aiohttp import web
import socketio

sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Simulated state
state = {
    "printer_state": {
        "text": "Operational",
        "flags": {
            "operational": True,
            "ready": True,
            "printing": False,
            "error": False,
            "closedOrError": False
        }
    },
    "job_state": {
        "state": "Operational",
        "progress": {
            "completion": 0.0,
            "printTimeLeft": None
        }
    },
    "temperatures": {
        "tool0": {"actual": 22.0, "target": 0.0},
        "bed": {"actual": 22.0, "target": 0.0}
    },
    "z_height": 0.0
}

uploaded_files = []
print_start_time = None

def simulate_temperatures():
    for heater in ["tool0", "bed"]:
        actual = state["temperatures"][heater]["actual"]
        target = state["temperatures"][heater]["target"]
        if target > 0:
            diff = target - actual
            state["temperatures"][heater]["actual"] = round(actual + diff * 0.05 + 0.1, 1)
        else:
            if actual > 22.0:
                state["temperatures"][heater]["actual"] = round(actual - 0.5, 1)

def simulate_print_progress():
    global print_start_time
    if state["printer_state"]["flags"]["printing"] and print_start_time:
        elapsed = time.time() - print_start_time
        progress = min(elapsed / 60.0, 1.0) # 60 sec print
        state["job_state"]["progress"]["completion"] = progress * 100.0
        state["job_state"]["progress"]["printTimeLeft"] = max(0, 60.0 - elapsed)
        state["z_height"] = round(progress * 50.0, 2)
        if progress >= 1.0:
            state["printer_state"]["flags"]["printing"] = False
            state["printer_state"]["flags"]["ready"] = True
            state["printer_state"]["text"] = "Operational"
            state["job_state"]["state"] = "Operational"
            state["temperatures"]["tool0"]["target"] = 0.0
            state["temperatures"]["bed"]["target"] = 0.0

# --- REST endpoints ---

async def get_version(request):
    return web.json_response({
        "server": "1.8.6",
        "api": "0.1",
        "text": "OctoPrint 1.8.6"
    })

async def get_printer(request):
    simulate_temperatures()
    simulate_print_progress()
    return web.json_response({
        "state": state["printer_state"],
        "temperature": state["temperatures"]
    })

async def get_connection(request):
    return web.json_response({
        "current": {
            "state": "Operational",
            "port": "VIRTUAL",
            "baudrate": 250000,
            "printerProfile": "_default"
        }
    })

async def post_connection(request):
    return web.json_response({"result": "ok"})

async def post_settings(request):
    return web.json_response({"result": "ok"})

async def get_files(request):
    return web.json_response({
        "files": [{"name": f, "path": f, "type": "machinecode"} for f in uploaded_files]
    })

async def post_files(request):
    reader = await request.multipart()
    filename = "uploaded.gcode"
    async for field in reader:
        if field.name == "file":
            filename = field.filename or filename
            await field.read()
    uploaded_files.append(filename)
    return web.json_response({
        "files": {
            "local": {
                "name": filename,
                "path": filename,
                "refs": {"resource": f"http://localhost:5001/api/files/local/{filename}"}
            }
        },
        "done": True
    })

async def post_files_command(request):
    return web.json_response({"result": "ok"})

async def post_job(request):
    global print_start_time
    body = await request.json()
    command = body.get("command")
    
    if command == "start":
        state["printer_state"]["flags"]["printing"] = True
        state["printer_state"]["flags"]["ready"] = False
        state["printer_state"]["text"] = "Printing"
        state["job_state"]["state"] = "Printing"
        state["temperatures"]["tool0"]["target"] = 200.0
        state["temperatures"]["bed"]["target"] = 60.0
        print_start_time = time.time()
        
    elif command == "cancel":
        state["printer_state"]["flags"]["printing"] = False
        state["printer_state"]["flags"]["ready"] = True
        state["printer_state"]["text"] = "Operational"
        state["job_state"]["state"] = "Operational"
        state["temperatures"]["tool0"]["target"] = 0.0
        state["temperatures"]["bed"]["target"] = 0.0
        
    elif command == "pause":
        action = body.get("action", "pause")
        if action == "pause":
            state["job_state"]["state"] = "Paused"
        else:
            state["job_state"]["state"] = "Printing"
            
    return web.Response(status=204)

async def get_job(request):
    simulate_print_progress()
    return web.json_response({
        "state": state["job_state"]["state"],
        "progress": state["job_state"]["progress"]
    })

# --- Socket.IO ---

@sio.event
async def connect(sid, environ, auth):
    print(f"[SIO] Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[SIO] Client disconnected: {sid}")

async def broadcast_telemetry():
    while True:
        await asyncio.sleep(2)
        simulate_temperatures()
        simulate_print_progress()
        current_data = {
            "state": state["printer_state"],
            "temps": [
                {
                    "time": time.time(),
                    "tool0": state["temperatures"]["tool0"],
                    "bed": state["temperatures"]["bed"]
                }
            ],
            "job": {
                "file": {"name": "test.gcode"}
            },
            "progress": state["job_state"]["progress"],
            "currentZ": state["z_height"]
        }
        await sio.emit("current", current_data)

# --- App setup ---

app.router.add_get("/api/version", get_version)
app.router.add_get("/api/printer", get_printer)
app.router.add_get("/api/connection", get_connection)
app.router.add_post("/api/connection", post_connection)
app.router.add_post("/api/settings", post_settings)
app.router.add_get("/api/files/local", get_files)
app.router.add_post("/api/files/local", post_files)
app.router.add_post("/api/files/local/{filename}", post_files_command)
app.router.add_get("/api/job", get_job)
app.router.add_post("/api/job", post_job)

async def start_background_tasks(app):
    app["telemetry_task"] = asyncio.create_task(broadcast_telemetry())

async def cleanup_background_tasks(app):
    app["telemetry_task"].cancel()
    try:
        await app["telemetry_task"]
    except asyncio.CancelledError:
        pass

app.on_startup.append(start_background_tasks)
app.on_cleanup.append(cleanup_background_tasks)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    
    print(f"OctoPrint mock server starting on http://localhost:{args.port}")
    web.run_app(app, host="0.0.0.0", port=args.port)
