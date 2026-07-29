"""Telemetry collection from OctoPrint Socket.IO."""

import asyncio
import logging
import json
import os
import random
import string
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample

try:
    from server.job_broadcaster import broadcaster
except ImportError:
    broadcaster = None

logger = logging.getLogger(__name__)

class OctoPrintCollector:
    """Collects telemetry data from an OctoPrint 3D printer via SockJS.

    Limitations:
        - gcode_line: Not exposed via the streaming API (always None).
        - print_speed_pct: Not exposed via the streaming API (always None).
        - extrusion_factor_pct: Not exposed via the streaming API (always None).
        - fan_speed_pct: Not exposed via the streaming API (always None).
    """

    def __init__(self, host: str, port: int, api_key: str, job_id: str, db: TelemetryDB):
        """Initialize the OctoPrint collector.

        Args:
            host: The OctoPrint host.
            port: The OctoPrint port.
            api_key: The API key for authentication.
            job_id: The job identifier.
            db: The telemetry database.
        """
        self.host = host
        self.port = port
        self.api_key = api_key
        self.job_id = job_id
        self.db = db
        self.sample_queue: asyncio.Queue[TelemetrySample] = asyncio.Queue()
        self._running = False
        self._bg_task: Optional[asyncio.Task] = None
        self._backoff = 1.0

    async def start(self) -> None:
        """Start the collector and initiate the WebSocket connection."""
        if self._running:
            return
        self._running = True
        self._bg_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the collector and disconnect."""
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass

    @staticmethod
    def _sockjs_url(host: str, port: int) -> str:
        """Build a valid SockJS WebSocket URL.

        SockJS requires the path: /sockjs/<server_id>/<session_id>/websocket
        where server_id is a 3-digit numeric string and session_id is a random
        alphanumeric string. Without these segments OctoPrint returns 404/400
        and refuses the WebSocket upgrade.
        """
        server_id = ''.join(random.choices(string.digits, k=3))
        session_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"ws://{host}:{port}/sockjs/{server_id}/{session_id}/websocket"

    async def _run_loop(self) -> None:
        while self._running:
            ws_url = self._sockjs_url(self.host, self.port)
            try:
                async with aiohttp.ClientSession() as session:
                    logger.info(f"Connecting to OctoPrint SockJS websocket at {ws_url}")
                    async with session.ws_connect(ws_url) as ws:
                        self._backoff = 1.0
                        logger.info("OctoPrint SockJS WebSocket connected.")

                        authenticated = False
                        # Receive loop
                        async for msg in ws:
                            if not self._running:
                                break

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.data
                                logger.debug(f"OctoPrint WS raw frame: {data[:200]}")

                                if data == 'o':
                                    # SockJS 'open' frame — connection established, now authenticate
                                    logger.info("SockJS open frame received, sending auth.")
                                    auth_msg = json.dumps({"auth": f"_api:{self.api_key}"})
                                    await ws.send_str(json.dumps([auth_msg]))
                                    authenticated = True
                                elif data in ('h', ''):  # heartbeat — ignore
                                    pass
                                elif data.startswith('a'):
                                    # SockJS array frame: a["...", "..."]
                                    try:
                                        frames = json.loads(data[1:])
                                        for frame in frames:
                                            # frame may be a string or dict depending on SockJS encoding
                                            if isinstance(frame, str):
                                                parsed = json.loads(frame)
                                            else:
                                                parsed = frame
                                            if "current" in parsed:
                                                await self._on_current(parsed["current"])
                                            elif "event" in parsed:
                                                await self._on_event(parsed["event"])
                                            elif "connected" in parsed:
                                                logger.info(f"OctoPrint connected: {parsed['connected']}")
                                    except Exception as e:
                                        logger.error(f"Error parsing websocket frame: {e} — raw: {data[:200]}")
                                elif data.startswith('c'):
                                    # SockJS close frame
                                    logger.warning(f"SockJS close frame received: {data}")
                                    break
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                logger.warning(f"OctoPrint WS closed/error: {msg.type}")
                                break

            except Exception as e:
                logger.error(f"OctoPrint connection error: {e}")

            if not self._running:
                break

            logger.info(f"Reconnecting in {self._backoff} seconds...")
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 30.0)

    async def _on_current(self, payload: Dict[str, Any]) -> None:
        if not payload:
            return

        now = datetime.now(timezone.utc)
        z_height_mm = payload.get("currentZ")

        temps_data = payload.get("temps", [])
        if isinstance(temps_data, list) and len(temps_data) > 0:
            temps_data = temps_data[0]
        elif not isinstance(temps_data, dict):
            temps_data = {}

        # Safely extract temperatures handling potentially varying formats
        hotend_actual = None
        hotend_target = None
        
        # If temps[0] directly contains 'actual'/'target' (like the prompt suggested literally)
        if "actual" in temps_data or "target" in temps_data:
            hotend_actual = temps_data.get("actual")
            hotend_target = temps_data.get("target")
        elif "tool0" in temps_data:
            tool0 = temps_data.get("tool0", {})
            hotend_actual = tool0.get("actual")
            hotend_target = tool0.get("target")

        bed_actual = None
        bed_target = None
        bed_data = temps_data.get("bed", {})
        if isinstance(bed_data, dict):
            bed_actual = bed_data.get("actual")
            bed_target = bed_data.get("target")
        elif hasattr(bed_data, "actual"):
            bed_actual = getattr(bed_data, "actual", None)
            bed_target = getattr(bed_data, "target", None)

        sample = TelemetrySample(
            job_id=self.job_id,
            sampled_at=now,
            gcode_line=None,
            z_height_mm=z_height_mm,
            hotend_actual_c=hotend_actual,
            hotend_target_c=hotend_target,
            bed_actual_c=bed_actual,
            bed_target_c=bed_target,
            print_speed_pct=None,
            extrusion_factor_pct=None,
            fan_speed_pct=None
        )

        self.db.insert_sample(sample)
        await self.sample_queue.put(sample)
        
        if broadcaster:
            logger.info(f"OctoPrintCollector broadcasting telemetry for job {self.job_id}: {sample.to_dict()}")
            asyncio.create_task(broadcaster.broadcast(self.job_id, {"type": "telemetry", "data": sample.to_dict()}))
            
            state_data = {
                "state": payload.get("state"),
                "job": payload.get("job"),
                "progress": payload.get("progress"),
                "resends": payload.get("resends"),
                "ts": now.isoformat()
            }
            logger.info(f"OctoPrintCollector broadcasting printer_state for job {self.job_id}: {state_data}")
            asyncio.create_task(broadcaster.broadcast(self.job_id, {"type": "printer_state", "data": state_data}))

    async def _on_event(self, event_data: Dict[str, Any]) -> None:
        if not isinstance(event_data, dict):
            return

        event_type = event_data.get("type")
        outcome = None

        if event_type in ("PrintFailed", "Error"):
            outcome = "failure"
        elif event_type == "PrintDone":
            outcome = "success"
        elif event_type == "PrintCancelled":
            outcome = "cancelled"

        if outcome:
            self.db.update_job_outcome(self.job_id, outcome, datetime.now(timezone.utc))
