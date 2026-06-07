import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import websockets

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample

logger = logging.getLogger(__name__)

class MoonrakerCollector:
    def __init__(self, ws_url: str, job_id: str, db: TelemetryDB):
        self.ws_url = ws_url
        self.job_id = job_id
        self.db = db
        self.sample_queue: asyncio.Queue[TelemetrySample] = asyncio.Queue()
        
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Connect and begin collecting telemetry."""
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Graceful disconnect, flush pending writes."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        """Main connection and reconnection loop."""
        backoff = 1.0
        max_backoff = 30.0

        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
                # If we exit normally (e.g. stop event), we reset backoff
                backoff = 1.0
            except (websockets.exceptions.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                logger.warning(f"Moonraker connection error: {e}. Reconnecting in {backoff} seconds...")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)
            except Exception as e:
                logger.error(f"Unexpected error in Moonraker collector: {e}")
                # We also back off on unexpected errors to avoid spinning
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)

    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket, subscribe, and listen for messages."""
        async with websockets.connect(self.ws_url) as ws:
            # Send subscription message
            sub_msg = {
                "jsonrpc": "2.0",
                "method": "printer.objects.subscribe",
                "params": {
                    "objects": {
                        "print_stats": None,
                        "toolhead": None,
                        "extruder": None,
                        "heater_bed": None,
                        "fan": None,
                        "gcode_move": None
                    }
                },
                "id": 1
            }
            await ws.send(json.dumps(sub_msg))

            # Listen for messages
            while not self._stop_event.is_set():
                # wait_for allows checking _stop_event periodically if no messages arrive
                listen_task = asyncio.create_task(ws.recv())
                stop_task = asyncio.create_task(self._stop_event.wait())
                
                done, pending = await asyncio.wait(
                    [listen_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for p in pending:
                    p.cancel()
                    try:
                        await p
                    except asyncio.CancelledError:
                        pass

                if stop_task in done:
                    # _stop_event was set
                    break
                
                if listen_task in done:
                    msg = listen_task.result()
                    if isinstance(msg, str):
                        self._process_message(msg)

    def _process_message(self, message: str) -> None:
        """Process incoming JSON-RPC messages and emit TelemetrySample."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        method = data.get("method")
        if method == "notify_status_update":
            params = data.get("params", [])
            if not params or not isinstance(params, list):
                return
                
            status = params[0]
            
            # Map fields safely
            print_stats = status.get("print_stats", {})
            toolhead = status.get("toolhead", {})
            extruder = status.get("extruder", {})
            heater_bed = status.get("heater_bed", {})
            fan = status.get("fan", {})
            gcode_move = status.get("gcode_move", {})

            # Exact field mapping as requested:
            # gcode_line          <- print_stats.file_position
            # z_height_mm         <- toolhead.position[2]
            # hotend_actual_c     <- extruder.temperature
            # hotend_target_c     <- extruder.target
            # bed_actual_c        <- heater_bed.temperature
            # bed_target_c        <- heater_bed.target
            # print_speed_pct     <- gcode_move.speed_factor * 100
            # extrusion_factor_pct<- gcode_move.extrude_factor * 100
            # fan_speed_pct       <- fan.speed * 100

            gcode_line = print_stats.get("file_position")
            
            z_height_mm = None
            pos = toolhead.get("position")
            if pos and len(pos) >= 3:
                z_height_mm = pos[2]
                
            hotend_actual_c = extruder.get("temperature")
            hotend_target_c = extruder.get("target")
            
            bed_actual_c = heater_bed.get("temperature")
            bed_target_c = heater_bed.get("target")
            
            speed_factor = gcode_move.get("speed_factor")
            print_speed_pct = speed_factor * 100 if speed_factor is not None else None
            
            extrude_factor = gcode_move.get("extrude_factor")
            extrusion_factor_pct = extrude_factor * 100 if extrude_factor is not None else None
            
            fan_speed = fan.get("speed")
            fan_speed_pct = fan_speed * 100 if fan_speed is not None else None

            # Some status updates may not contain any of these objects if they didn't change.
            # But the requirement doesn't specify complex merging of states. We'll emit what we get.
            # Usually, Moonraker sends partial updates. For robust telemetry, one might maintain state.
            # However, the instructions say: "On each `notify_status_update` event received, map fields to TelemetrySample as follows:"
            
            sample = TelemetrySample(
                job_id=self.job_id,
                sampled_at=datetime.now(timezone.utc),
                gcode_line=gcode_line,
                z_height_mm=z_height_mm,
                hotend_actual_c=hotend_actual_c,
                hotend_target_c=hotend_target_c,
                bed_actual_c=bed_actual_c,
                bed_target_c=bed_target_c,
                print_speed_pct=print_speed_pct,
                extrusion_factor_pct=extrusion_factor_pct,
                fan_speed_pct=fan_speed_pct
            )

            # Insert sample and emit to queue
            try:
                self.db.insert_sample(sample)
                # Use put_nowait so we don't block the receive loop
                self.sample_queue.put_nowait(sample)
            except Exception as e:
                logger.error(f"Failed to insert/emit TelemetrySample: {e}")
