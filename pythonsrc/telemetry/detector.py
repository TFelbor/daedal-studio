"""Anomaly detection rules for print telemetry streams."""

import asyncio
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, List

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import TelemetrySample, FailureEvent
from pythonsrc.operators.base import BasePrinterOperator

logger = logging.getLogger(__name__)

class AnomalyDetector:
    """Detector that consumes TelemetrySample objects from a queue and applies rule-based anomaly detection.
    
    Firmware applicability:
        - Rule 1 (Thermal runaway): Klipper + OctoPrint
        - Rule 2 (Extrusion stall): Klipper only (requires gcode_line)
        - Rule 3 (Layer shift): Klipper + OctoPrint
        - Rule 4 (Bed adhesion): Klipper + OctoPrint
        - Rule 5 (Extrusion issue): Klipper + OctoPrint
    """

    #: How much the hotend's shortfall must shrink across the thermal window before
    #: it counts as heating rather than failing. Sampling noise is a few tenths of a
    #: degree; a hotend actually climbing closes tens of degrees over five samples,
    #: so anything in between separates the two cleanly.
    CONVERGENCE_TOLERANCE_C = 1.0

    def __init__(self, queue: asyncio.Queue, db: TelemetryDB, operator: Optional[BasePrinterOperator]):
        """Initialize the AnomalyDetector.

        Args:
            queue: The asyncio Queue containing telemetry samples.
            db: The telemetry database.
            operator: The printer operator.
        """
        self.queue = queue
        self.db = db
        self.operator = operator
        self._history: Dict[str, deque] = {}
        self._state_cache: Dict[str, dict] = {}
        # Keep track of already triggered events for a job to prevent spamming
        self._triggered: Dict[str, set] = {}

    async def _get_state_and_progress(self, job_id: str) -> tuple[str, float]:
        """Fetch current state and progress, with caching to avoid spamming."""
        cache = self._state_cache.setdefault(job_id, {"time": 0, "state": "printing", "progress": 0.0, "prev_state": "printing"})
        now = asyncio.get_event_loop().time()
        
        # Determine state from DB outcome first
        job = self.db.get_job(job_id)
        if job:
            if job.outcome == "failure":
                cache["state"] = "error"
            elif job.outcome == "cancelled":
                cache["state"] = "cancelled"
            elif job.outcome == "success":
                cache["state"] = "success"

        # Update from operator every 2 seconds
        if now - cache["time"] > 2.0 and self.operator:
            cache["time"] = now
            try:
                from pythonsrc.operators.moonraker_operator import MoonrakerOperator
                from pythonsrc.operators.octoprint_operator import OctoPrintOperator
                
                if isinstance(self.operator, MoonrakerOperator):
                    st = await asyncio.to_thread(self.operator.get_printer_state)
                    state_text = st.get("state", "").lower()
                    if state_text in ("printing", "error", "cancelled", "complete"):
                        if state_text == "complete":
                            cache["state"] = "success"
                        else:
                            cache["state"] = state_text
                    cache["progress"] = st.get("progress", 0.0) * 100.0
                elif isinstance(self.operator, OctoPrintOperator):
                    st = await asyncio.to_thread(self.operator.get_printer_state)
                    flags = st.get("state", {}).get("flags", {})
                    if flags.get("error") or flags.get("closedOrError"):
                        cache["state"] = "error"
                    
                    job_st = await asyncio.to_thread(self.operator.get_job_status)
                    cache["progress"] = job_st.get("progress", {}).get("completion", 0.0) or 0.0
            except Exception as e:
                logger.debug(f"Failed to fetch operator state: {e}")
                
        return cache["state"], cache["progress"]

    def _trigger_failure(self, job_id: str, sample: TelemetrySample, failure_type: str, history: List[TelemetrySample]) -> None:
        """Helper to create and insert a FailureEvent, and optionally pause."""
        triggered_set = self._triggered.setdefault(job_id, set())
        if failure_type in triggered_set:
            return  # Already triggered this type of failure for this job

        logger.warning(f"Anomaly detected! Job {job_id}, Type: {failure_type}")
        
        event = FailureEvent(
            event_id=str(uuid.uuid4()),
            job_id=job_id,
            detected_at=datetime.now(timezone.utc),
            gcode_line=sample.gcode_line,
            z_height_mm=sample.z_height_mm,
            failure_type=failure_type,  # type: ignore
            source="automated",
            notes=f"Triggered by rule {failure_type}",
            snapshot=[s.to_dict() for s in history]
        )
        self.db.insert_failure_event(event)
        triggered_set.add(failure_type)
        
        # Check environment var for pause
        if os.environ.get("PAUSE_ON_FAILURE", "false").lower() == "true":
            if self.operator:
                logger.info(f"PAUSE_ON_FAILURE is true. Pausing print {job_id}...")
                try:
                    # using to_thread since pause_print is sync
                    asyncio.create_task(asyncio.to_thread(self.operator.pause_print))
                except Exception as e:
                    logger.error(f"Failed to pause print: {e}")

    async def run(self) -> None:
        """Consume the queue and evaluate rules until cancelled."""
        try:
            while True:
                sample: TelemetrySample = await self.queue.get()
                try:
                    job_id = sample.job_id

                    if job_id not in self._history:
                        self._history[job_id] = deque(maxlen=20)

                    history = self._history[job_id]
                    history.append(sample)

                    await self._evaluate_rules(job_id, list(history))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # One malformed sample or one broken rule must not take down
                    # detection for every job — log it and keep consuming.
                    logger.exception("Anomaly rule evaluation failed for sample; continuing")
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _evaluate_rules(self, job_id: str, history: List[TelemetrySample]) -> None:
        """Evaluate all anomaly detection rules for a job's recent history.

        Args:
            job_id: The unique identifier of the job.
            history: A list of recent telemetry samples for the job.
        """
        if not history:
            return
            
        current = history[-1]
        state, progress = await self._get_state_and_progress(job_id)
        
        self._check_thermal_runaway(job_id, current, history, state)
        self._check_extrusion_stall(job_id, current, history, state, progress)
        self._check_layer_shift(job_id, current, history)
        self._check_bed_adhesion(job_id, current, history, state, progress)
        self._check_extrusion_issue(job_id, current, history)

    def _check_thermal_runaway(self, job_id: str, current: TelemetrySample, history: List[TelemetrySample], state: str) -> None:
        """Evaluate Rule 1: Thermal runaway.

        Condition: hotend_target > 150°C AND hotend_actual < (hotend_target - 25°C)
        for 5 consecutive samples, **and** the gap is not closing.

        That last clause is the whole difference between a fault and a warm-up. A
        cold hotend climbing toward 210°C sits far below its target for as long as it
        takes to get there, which satisfies the first two conditions exactly. A real
        job was labelled `thermal_runaway` seconds after dispatch for precisely that,
        and the operator cancelled it by hand. What distinguishes the fault is the
        *trend*: heating closes the gap, a dead heater holds it, and a runaway widens
        it. Stalling below target still fires — the gap has to be shrinking, not
        merely nonzero.

        Args:
            job_id: The unique identifier of the job.
            current: The most recent telemetry sample.
            history: A list of recent telemetry samples for the job.
            state: The printer state, so a job that is no longer printing stops
                accruing automated failures. A human cancelling a print is not a
                fault, and the cooldown that follows must not be reported as one.
        """
        if state not in ("printing", "heating"):
            return

        if len(history) >= 5:
            window = history[-5:]
            thermal_runaway = True
            for s in window:
                if s.hotend_target_c is None or s.hotend_actual_c is None:
                    thermal_runaway = False
                    break
                if s.hotend_target_c <= 150 or s.hotend_actual_c >= (s.hotend_target_c - 25):
                    thermal_runaway = False
                    break

            if not thermal_runaway:
                return

            # Measured as a deficit rather than a raw temperature so a target that
            # moves mid-window cannot read as the hotend converging.
            opening = window[0].hotend_target_c - window[0].hotend_actual_c
            closing = window[-1].hotend_target_c - window[-1].hotend_actual_c
            if opening - closing > self.CONVERGENCE_TOLERANCE_C:
                logger.debug(
                    "Job %s is heating, not running away — gap %.1f°C → %.1f°C",
                    job_id, opening, closing,
                )
                return

            self._trigger_failure(job_id, current, "thermal_runaway", window)

    def _check_extrusion_stall(self, job_id: str, current: TelemetrySample, history: List[TelemetrySample], state: str, progress: float) -> None:
        """Evaluate Rule 2: Extrusion stall (clog proxy).

        Condition: print progress > 5% AND gcode_line not incrementing across 10 consecutive samples while state = "printing".

        Args:
            job_id: The unique identifier of the job.
            current: The most recent telemetry sample.
            history: A list of recent telemetry samples for the job.
            state: The current printer state.
            progress: The current print progress percentage.
        """
        if len(history) >= 10 and state == "printing" and progress > 5.0:
            clog = True
            first_line = history[-10].gcode_line
            if first_line is None:
                clog = False
            else:
                for s in history[-10:]:
                    if s.gcode_line is None or s.gcode_line != first_line:
                        clog = False
                        break
            if clog:
                self._trigger_failure(job_id, current, "clog", history[-10:])

    def _check_layer_shift(self, job_id: str, current: TelemetrySample, history: List[TelemetrySample]) -> None:
        """Evaluate Rule 3: Layer shift (Z regression).

        Condition: z_height_mm decreases by > 0.5mm between consecutive samples.

        Args:
            job_id: The unique identifier of the job.
            current: The most recent telemetry sample.
            history: A list of recent telemetry samples for the job.
        """
        if len(history) >= 2:
            prev = history[-2]
            if prev.z_height_mm is not None and current.z_height_mm is not None:
                if (prev.z_height_mm - current.z_height_mm) > 0.5:
                    self._trigger_failure(job_id, current, "layer_shift", history[-2:])

    def _check_bed_adhesion(self, job_id: str, current: TelemetrySample, history: List[TelemetrySample], state: str, progress: float) -> None:
        """Evaluate Rule 4: Bed adhesion.

        Condition: z_height_mm < 1.0mm AND print progress < 10% AND state transitions from "printing" to "error" or "cancelled".

        Args:
            job_id: The unique identifier of the job.
            current: The most recent telemetry sample.
            history: A list of recent telemetry samples for the job.
            state: The current printer state.
            progress: The current print progress percentage.
        """
        cache = self._state_cache.get(job_id, {})
        prev_state = cache.get("prev_state", "printing")
        if current.z_height_mm is not None and current.z_height_mm < 1.0 and progress < 10.0:
            if prev_state == "printing" and state in ("error", "cancelled"):
                self._trigger_failure(job_id, current, "adhesion", history[-1:])
                
        # Update prev_state
        cache["prev_state"] = state

    def _check_extrusion_issue(self, job_id: str, current: TelemetrySample, history: List[TelemetrySample]) -> None:
        """Evaluate Rule 5: Extrusion issue.

        Condition: extrusion_factor_pct <= 10.0 for 5 consecutive samples.

        Args:
            job_id: The unique identifier of the job.
            current: The most recent telemetry sample.
            history: A list of recent telemetry samples for the job.
        """
        if len(history) >= 5:
            slow_extrusion = True
            for s in history[-5:]:
                if s.extrusion_factor_pct is None or s.extrusion_factor_pct > 10.0:
                    slow_extrusion = False
                    break
            if slow_extrusion:
                self._trigger_failure(job_id, current, "extrusion_issue", history[-5:])


def attach_detector(collector, db: TelemetryDB, operator: Optional[BasePrinterOperator] = None) -> asyncio.Task:
    """Start an AnomalyDetector consuming a collector's samples.

    Without this, a collector's ``sample_queue`` is written but never read: the queue
    grows unbounded and no automated failure detection happens at all. The detector runs
    in the same process as the collector, so it sees samples as they arrive.

    Args:
        collector: Any collector exposing a ``sample_queue`` asyncio.Queue.
        db: Database that FailureEvents are written to.
        operator: Printer operator used for state/progress lookups and, when
            ``PAUSE_ON_FAILURE`` is set, to pause the print. Rules that depend on
            progress cannot fire without it.

    Returns:
        The background task running the detector; cancel it to stop detection.
    """
    detector = AnomalyDetector(collector.sample_queue, db, operator)
    return asyncio.create_task(detector.run())
