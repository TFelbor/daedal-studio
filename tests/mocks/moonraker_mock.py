#!/usr/bin/env python3
"""
Minimal Moonraker API mock for local development and testing.
Simulates the Moonraker REST and WebSocket APIs without requiring
Klipper or any printer hardware.

Run: python3 moonraker_mock.py
     Serves on http://localhost:7125
"""

import asyncio
import json
import math
import time
from aiohttp import web
import aiohttp

# --- Simulated printer state ---
state = {
    "print_stats": {
        "state": "standby",
        "filename": "",
        "total_duration": 0,
        "print_duration": 0,
        "filament_used": 0,
        "message": ""
    },
    "toolhead": {
        "position": [0.0, 0.0, 0.0, 0.0],
        "homed_axes": "xyz",
        "print_time": 0.0
    },
    "extruder": {
        "temperature": 22.5,
        "target": 0.0,
        "power": 0.0
    },
    "heater_bed": {
        "temperature": 21.8,
        "target": 0.0,
        "power": 0.0
    },
    "fan": {"speed": 0.0},
    "gcode_move": {
        "speed_factor": 1.0,
        "extrude_factor": 1.0,
        "position": [0.0, 0.0, 0.0, 0.0]
    }
}

uploaded_files = []
ws_clients = set()
print_start_time = None


def simulate_temperatures():
    """Simulate realistic temperature changes toward targets."""
    for heater in ["extruder", "heater_bed"]:
        actual = state[heater]["temperature"]
        target = state[heater]["target"]
        if target > 0:
            diff = target - actual
            state[heater]["temperature"] = round(actual + diff * 0.05 + (0.2 - 0.1), 1)
        else:
            if actual > 22.0:
                state[heater]["temperature"] = round(actual - 0.5, 1)


def simulate_print_progress():
    """Simulate Z height and progress during a print."""
    global print_start_time
    if state["print_stats"]["state"] == "printing" and print_start_time:
        elapsed = time.time() - print_start_time
        progress = min(elapsed / 60.0, 1.0)  # 60-second simulated print
        z = round(progress * 50.0, 2)         # ramps to 50mm
        state["toolhead"]["position"][2] = z
        state["print_stats"]["print_duration"] = elapsed
        if progress >= 1.0:
            state["print_stats"]["state"] = "complete"


# --- REST endpoints ---

async def get_printer_info(request):
    return web.json_response({
        "result": {
            "state": "ready",
            "state_message": "Printer is ready",
            "hostname": "moonraker-mock",
            "software_version": "v0.8.0-mock",
            "cpu_info": "Mock CPU",
            "klipper_path": "/opt/klipper",
            "python_path": "/usr/bin/python3",
            "log_file": "/tmp/klippy.log",
            "config_file": "/tmp/printer.cfg"
        }
    })


async def get_server_info(request):
    return web.json_response({
        "result": {
            "klippy_connected": True,
            "klippy_state": "ready",
            "components": ["file_manager", "history"],
            "failed_components": [],
            "registered_directories": ["gcodes"],
            "warnings": [],
            "websocket_count": len(ws_clients),
            "moonraker_version": "v0.8.0-mock"
        }
    })


async def query_printer_objects(request):
    simulate_temperatures()
    simulate_print_progress()
    requested = request.rel_url.query_string
    result = {}
    for key in state:
        if key in requested or not requested:
            result[key] = state[key]
    return web.json_response({"result": {"status": result, "eventtime": time.time()}})


async def upload_file(request):
    reader = await request.multipart()
    filename = "uploaded.gcode"
    async for field in reader:
        if field.name == "file":
            filename = field.filename or filename
            await field.read()  # consume
    uploaded_files.append(filename)
    return web.json_response({
        "result": {
            "item": {"path": filename, "root": "gcodes"},
            "action": "create_file"
        }
    })


async def start_print(request):
    global print_start_time
    body = await request.json()
    filename = body.get("filename", "test.gcode")
    state["print_stats"]["state"] = "printing"
    state["print_stats"]["filename"] = filename
    state["extruder"]["target"] = 200.0
    state["heater_bed"]["target"] = 60.0
    print_start_time = time.time()
    await broadcast_status()
    return web.json_response({"result": "ok"})


async def cancel_print(request):
    state["print_stats"]["state"] = "cancelled"
    state["extruder"]["target"] = 0.0
    state["heater_bed"]["target"] = 0.0
    await broadcast_status()
    return web.json_response({"result": "ok"})


async def pause_print(request):
    if state["print_stats"]["state"] == "printing":
        state["print_stats"]["state"] = "paused"
    await broadcast_status()
    return web.json_response({"result": "ok"})


async def resume_print(request):
    if state["print_stats"]["state"] == "paused":
        state["print_stats"]["state"] = "printing"
    await broadcast_status()
    return web.json_response({"result": "ok"})


async def run_gcode(request):
    body = await request.json()
    script = body.get("script", "")
    if "SET_HEATER_TEMPERATURE" in script:
        parts = script.split()
        for i, p in enumerate(parts):
            if p == "HEATER=extruder":
                state["extruder"]["target"] = float(parts[i+1].split("=")[1])
            elif p == "HEATER=heater_bed":
                state["heater_bed"]["target"] = float(parts[i+1].split("=")[1])
    return web.json_response({"result": "ok"})


# --- WebSocket handler ---

async def broadcast_status():
    simulate_temperatures()
    simulate_print_progress()
    msg = {
        "jsonrpc": "2.0",
        "method": "notify_status_update",
        "params": [state, time.time()]
    }
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_str(json.dumps(msg))
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    print(f"[WS] Client connected. Total: {len(ws_clients)}")

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    method = data.get("method", "")
                    msg_id = data.get("id", 1)

                    if method == "printer.objects.subscribe":
                        # Acknowledge subscription
                        simulate_temperatures()
                        await ws.send_str(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "eventtime": time.time(),
                                "status": state
                            }
                        }))
                    elif method == "server.info":
                        await ws.send_str(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {"klippy_connected": True, "klippy_state": "ready"}
                        }))
                    else:
                        await ws.send_str(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": "ok"
                        }))
                except json.JSONDecodeError:
                    pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        ws_clients.discard(ws)
        print(f"[WS] Client disconnected. Total: {len(ws_clients)}")

    return ws


# --- Background task: push telemetry every 2 seconds ---

async def telemetry_loop():
    while True:
        await asyncio.sleep(2)
        if ws_clients:
            await broadcast_status()


async def start_background_tasks(app):
    app["telemetry_task"] = asyncio.create_task(telemetry_loop())


async def cleanup_background_tasks(app):
    app["telemetry_task"].cancel()
    try:
        await app["telemetry_task"]
    except asyncio.CancelledError:
        pass


# --- App setup ---

app = web.Application()
app.router.add_get("/printer/info", get_printer_info)
app.router.add_get("/server/info", get_server_info)
app.router.add_get("/printer/objects/query", query_printer_objects)
app.router.add_post("/server/files/upload", upload_file)
app.router.add_post("/printer/print/start", start_print)
app.router.add_post("/printer/print/cancel", cancel_print)
app.router.add_post("/printer/print/pause", pause_print)
app.router.add_post("/printer/print/resume", resume_print)
app.router.add_post("/printer/gcode/script", run_gcode)
app.router.add_get("/websocket", websocket_handler)

app.on_startup.append(start_background_tasks)
app.on_cleanup.append(cleanup_background_tasks)

if __name__ == "__main__":
    print("Moonraker mock server starting on http://localhost:7125")
    print("WebSocket available at ws://localhost:7125/websocket")
    print("Press Ctrl+C to stop.")
    web.run_app(app, host="0.0.0.0", port=7125)
