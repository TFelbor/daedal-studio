"""Telemetry collection from OctoPrint Socket.IO."""

import asyncio
import logging
import json
import random
import string
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from pythonsrc.telemetry.collector_claim import CollectorClaim
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.internal_telemetry import send_internal_telemetry
from pythonsrc.telemetry.schema import TelemetrySample

logger = logging.getLogger(__name__)

class OctoPrintCollector:
    """Collects telemetry data from an OctoPrint 3D printer via SockJS.

    Limitations:
        - gcode_line: Holds the G-code *file position* (byte offset from
          ``progress.filepos``), matching what the Moonraker collector stores
          there. OctoPrint does not expose a line number.
        - print_speed_pct: Not exposed via the streaming API (always None).
        - extrusion_factor_pct: Not exposed via the streaming API (always None).
        - fan_speed_pct: Not exposed via the streaming API (always None).
    """

    def __init__(
        self,
        host: str,
        port: int,
        api_key: str,
        job_id: str,
        db: TelemetryDB,
        gcode_filename: str | None = None,
    ):
        """Initialize the OctoPrint collector.

        Args:
            host: The OctoPrint host.
            port: The OctoPrint port.
            api_key: The API key for authentication.
            job_id: The job identifier.
            db: The telemetry database.
            gcode_filename: The file this job uploaded. The socket reports every
                print on the machine, so events naming a *different* file are not
                this job's outcome and are ignored. None disables the check.
        """
        self.host = host
        self.port = port
        self.api_key = api_key
        self.job_id = job_id
        self.db = db
        self.gcode_filename = gcode_filename
        self.sample_queue: asyncio.Queue[TelemetrySample] = asyncio.Queue()
        self._running = False
        self._bg_task: Optional[asyncio.Task] = None
        self._backoff = 1.0
        self._claim = CollectorClaim(db, job_id, "OctoPrintCollector")
        self._needs_reauth = False
        self._db_error_logged = False

    async def start(self) -> None:
        """Start the collector and initiate the WebSocket connection."""
        if self._running:
            return
        self._running = True
        self._bg_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the collector, disconnect, and release its telemetry claim."""
        self._running = False
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        self._claim.release()

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

    async def _fetch_ws_credentials(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Obtain the "<user>:<session>" string OctoPrint's WebSocket expects.

        OctoPrint does not accept the raw API key as a socket credential: sending
        ``_api:<api_key>`` is answered with ``{"reauthRequired": {"reason": "stale"}}``
        and no telemetry is ever pushed. A passive login exchanges the API key for a
        session token, which is what the socket authenticates against.

        Args:
            session: HTTP session used for the login request.

        Returns:
            The auth string, or None if the login failed.
        """
        url = f"http://{self.host}:{self.port}/api/login"
        try:
            async with session.post(
                url,
                json={"passive": True},
                headers={"X-Api-Key": self.api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.error(
                        "OctoPrint passive login failed (%s) — telemetry will not stream",
                        resp.status,
                    )
                    return None
                body = await resp.json()
        except Exception as exc:
            logger.error("OctoPrint passive login error: %s", exc)
            return None

        name = body.get("name")
        token = body.get("session")
        if not name or not token:
            logger.error("OctoPrint passive login returned no session; got keys: %s", list(body))
            return None
        return f"{name}:{token}"

    async def _run_loop(self) -> None:
        while self._running:
            ws_url = self._sockjs_url(self.host, self.port)
            try:
                async with aiohttp.ClientSession() as session:
                    logger.info(f"Connecting to OctoPrint SockJS websocket at {ws_url}")
                    # heartbeat keeps a half-open TCP connection from silently
                    # stalling telemetry for the rest of the print.
                    async with session.ws_connect(ws_url, heartbeat=30) as ws:
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
                                    # SockJS 'open' frame — authenticate with a session
                                    # token obtained from a passive login.
                                    logger.info("SockJS open frame received, sending auth.")
                                    credentials = await self._fetch_ws_credentials(session)
                                    if credentials is None:
                                        logger.error("Cannot authenticate OctoPrint socket; reconnecting.")
                                        break
                                    auth_msg = json.dumps({"auth": credentials})
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
                                            elif "reauthRequired" in parsed:
                                                logger.warning(
                                                    "OctoPrint requires reauthentication (%s) — reconnecting",
                                                    parsed["reauthRequired"],
                                                )
                                                self._needs_reauth = True
                                    except Exception as e:
                                        logger.error(f"Error parsing websocket frame: {e} — raw: {data[:200]}")

                                    if self._needs_reauth:
                                        # Drop the socket so the loop reconnects and
                                        # performs a fresh passive login.
                                        self._needs_reauth = False
                                        break
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

        # The byte offset into the G-code file, from the same frame. It was on the
        # wire all along (and forwarded to the browser below) while the sample
        # column was hardcoded to None — which also disabled the detector's clog
        # rule for every OctoPrint print.
        progress = payload.get("progress") or {}
        filepos = progress.get("filepos") if isinstance(progress, dict) else None

        temps_data = payload.get("temps", [])
        if isinstance(temps_data, list) and len(temps_data) > 0:
            # The history buffer arrives oldest-first; the newest entry is last.
            temps_data = temps_data[-1]
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
            gcode_line=filepos,
            z_height_mm=z_height_mm,
            hotend_actual_c=hotend_actual,
            hotend_target_c=hotend_target,
            bed_actual_c=bed_actual,
            bed_target_c=bed_target,
            print_speed_pct=None,
            extrusion_factor_pct=None,
            fan_speed_pct=None
        )

        if not self._claim.may_write(asyncio.get_running_loop().time()):
            # Another process is already collecting this job; writing here too would
            # duplicate every telemetry_sample row.
            return

        try:
            self.db.insert_sample(sample)
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the socket
            self._log_db_failure("record a telemetry sample", exc)
            return
        self._db_error_logged = False

        # Deliberately downstream of the insert: a sample this collector could not
        # persist is not its sample to fan out, and the relay target is the process
        # reading the very database that just refused the write.
        await self.sample_queue.put(sample)

        telemetry_message = {"type": "telemetry", "data": sample.to_dict()}
        state_data = {
            "state": payload.get("state"),
            "job": payload.get("job"),
            "progress": payload.get("progress"),
            "resends": payload.get("resends"),
            "ts": now.isoformat()
        }
        printer_state_message = {"type": "printer_state", "data": state_data}

        logger.info(f"OctoPrintCollector relaying telemetry for job {self.job_id}: {telemetry_message['data']}")
        asyncio.create_task(send_internal_telemetry(self.job_id, telemetry_message))
        logger.info(f"OctoPrintCollector relaying printer_state for job {self.job_id}: {state_data}")
        asyncio.create_task(send_internal_telemetry(self.job_id, printer_state_message))

    async def _on_event(self, event_data: Dict[str, Any]) -> None:
        """Translate an OctoPrint print event into a job outcome.

        ``PrintDone`` deliberately does not mean success. All the printer knows is that
        it reached the end of the G-code file; whether the part adhered, warped or came
        off the bed intact is invisible to it. Recording that as a success is how a
        dataset ends up full of "successful" prints that were scrap, so the job moves to
        `awaiting_verdict` and a human closes it out.

        A failure, error or cancellation is different — those the machine genuinely
        observed, so they are recorded as machine-sourced outcomes directly.

        Two guards, both of which used to be missing:

        * **The file must be ours.** The socket reports every print on the machine,
          so a ``PrintDone`` for a file this job never uploaded — someone printing a
          Benchy from the OctoPrint UI mid-pipeline — used to be written as this
          job's outcome.
        * **The claim must be ours.** A collector that lost the single-writer claim
          stood down from samples but kept mutating the print_job row.

        Args:
            event_data: The OctoPrint event message ({"type": ..., "payload": ...}).
        """
        if not isinstance(event_data, dict):
            return

        event_type = event_data.get("type")
        payload = event_data.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        outcome = None
        if event_type in ("PrintFailed", "Error"):
            outcome = "failure"
        elif event_type == "PrintDone":
            outcome = "awaiting_verdict"
        elif event_type == "PrintCancelled":
            outcome = "cancelled"

        event_kind = {
            "PrintPaused": "print_paused",
            "PrintResumed": "print_resumed",
        }.get(event_type)
        if outcome:
            event_kind = "printer_terminal"

        if not outcome and not event_kind:
            return

        event_file = payload.get("name")
        if self.gcode_filename and event_file and event_file.lower() != self.gcode_filename.lower():
            logger.info(
                "Ignoring %s for %r — job %s printed %r, so this event is another print's.",
                event_type, event_file, self.job_id, self.gcode_filename,
            )
            return

        if not self._claim.may_write(asyncio.get_running_loop().time()):
            return

        try:
            detail = {"event": event_type}
            if event_file:
                detail["file"] = event_file
            if payload.get("reason") is not None:
                # The firmware's own word for why — "cancelled" vs "error" on a
                # PrintFailed — exists only in this one payload.
                detail["reason"] = payload.get("reason")
            if payload.get("time") is not None:
                detail["print_duration_s"] = payload.get("time")
            self.db.record_job_event(self.job_id, event_kind, detail)
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the socket
            self._log_db_failure(f"record the '{event_type}' printer event", exc)

        if not outcome:
            return

        # The measured duration is a column of its own so it can be averaged and
        # compared against the slicer's estimate without digging through JSON.
        if payload.get("time") is not None:
            try:
                self.db.update_job_print_duration(self.job_id, float(payload["time"]))
            except Exception as exc:  # noqa: BLE001
                self._log_db_failure("record the print duration", exc)

        # A human verdict already on the row wins; the guard lives in
        # update_job_outcome_verdict so every machine writer inherits it.
        try:
            self.db.update_job_outcome_verdict(
                self.job_id,
                outcome,
                source="machine",
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the socket
            self._log_db_failure(f"record the '{outcome}' outcome", exc)

    def _log_db_failure(self, what: str, exc: Exception) -> None:
        """Report a database failure as itself, rather than as a connection error.

        These writes used to run unguarded, so a permissions or corruption fault
        propagated into ``_run_loop``'s blanket handler, which logged it as
        ``OctoPrint connection error`` and dropped a websocket that was working
        perfectly — then reconnected on a backoff, for the next sample to tear down
        again. The cause named in the log was the one thing that was not wrong.

        Samples arrive roughly every second, so only the first failure is logged at
        ERROR and the rest at DEBUG until one succeeds. The cause does not change
        between them, and an hour of identical lines buries everything else.

        Args:
            what: What the collector was trying to do, phrased to follow "Cannot".
            exc: The failure raised by the database.
        """
        if self._db_error_logged:
            logger.debug("Still cannot %s for job %s: %s", what, self.job_id, exc)
            return
        logger.error("Cannot %s for job %s: %s", what, self.job_id, exc)
        self._db_error_logged = True
