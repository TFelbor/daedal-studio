"""Telemetry collection from OctoPrint Socket.IO."""

import asyncio
import logging
import socketio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample

logger = logging.getLogger(__name__)

class OctoPrintCollector:
    """Collects telemetry data from an OctoPrint 3D printer via Socket.IO.

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
        self.sio = socketio.AsyncClient()
        self._running = False
        self._bg_task: Optional[asyncio.Task] = None
        self._backoff = 1.0

        # Register event handlers
        self.sio.on("connected", self._on_connected)
        self.sio.on("current", self._on_current)
        self.sio.on("event", self._on_event)

    async def start(self) -> None:
        """Start the collector and initiate the Socket.IO connection."""
        if self._running:
            return
        self._running = True
        self._bg_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the collector and disconnect the Socket.IO client."""
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        if self.sio.connected:
            await self.sio.disconnect()

    async def _run_loop(self) -> None:
        url = f"http://{self.host}:{self.port}"
        while self._running:
            try:
                if not self.sio.connected:
                    logger.info(f"Connecting to OctoPrint at {url}")
                    await self.sio.connect(url, headers={"X-Api-Key": self.api_key})
                    self._backoff = 1.0  # Reset backoff on successful connect
                    
                    # Authenticate immediately after connect
                    await self.sio.emit("authenticate", {"passive": True, "apikey": self.api_key})
                
                # Wait for disconnect
                await self.sio.wait()
            except Exception as e:
                logger.error(f"Connection error: {e}")
                if self.sio.connected:
                    await self.sio.disconnect()
            
            if not self._running:
                break
                
            logger.info(f"Reconnecting in {self._backoff} seconds...")
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 30.0)

    async def _on_connected(self, data: Optional[Dict[str, Any]] = None) -> None:
        logger.info("OctoPrint Socket.IO connected event received.")

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
