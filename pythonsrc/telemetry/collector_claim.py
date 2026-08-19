"""Single-writer arbitration for telemetry collectors.

Three call sites construct collectors for the same print job — the API server
(``server/app.py``), ``pipeline.py``'s Phase 5 monitor, and ``run_operator.py``. When
two of them run at once, both write to ``telemetry_sample`` and the job's telemetry is
silently doubled, which poisons the print-outcome dataset.

``CollectorClaim`` lets exactly one collector win, across processes, by claiming a row
in the database. Two properties matter:

* The claim is taken at the moment telemetry *arrives*, not when a collector connects.
  A collector that cannot authenticate or reach the printer therefore never takes the
  claim away from one that can.
* A claim is only taken over from a previous owner after that owner stops sending
  heartbeats, so a crashed collector does not block the job forever.
"""

import logging
import os
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pythonsrc.telemetry.db import TelemetryDB

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0
STALE_AFTER_S = 120.0


class CollectorClaim:
    """Tracks whether this collector is the designated writer for a job."""

    def __init__(self, db: "TelemetryDB", job_id: str, label: str) -> None:
        """Initialize a claim handle.

        Args:
            db: The telemetry database the claim is recorded in.
            job_id: The job this collector wants to write.
            label: Human-readable collector name, used in the owner id and logs.
        """
        self.db = db
        self.job_id = job_id
        self.label = label
        self.owner = f"{label}:pid{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._holds_claim: bool | None = None
        self._last_heartbeat = 0.0
        self._stood_down_logged = False

    def may_write(self, now: float) -> bool:
        """Whether this collector should persist the sample it just received.

        Args:
            now: Current monotonic time, used to throttle heartbeat writes.

        Returns:
            True if this collector holds the claim (or arbitration is unavailable).
        """
        if self._holds_claim is True and (now - self._last_heartbeat) < HEARTBEAT_INTERVAL_S:
            return True

        try:
            granted = self.db.try_claim_collector(self.job_id, self.owner, STALE_AFTER_S)
        except Exception as exc:
            # No claim table (e.g. a standalone pipeline run against a fresh DB) —
            # there is no second collector to conflict with in that case, so collect.
            logger.debug("Collector claim unavailable for job %s: %s", self.job_id, exc)
            self._holds_claim = True
            self._last_heartbeat = now
            return True

        if granted:
            if self._holds_claim is not True:
                logger.info(
                    "%s holds the telemetry claim for job %s", self.label, self.job_id
                )
            self._holds_claim = True
            self._last_heartbeat = now
            return True

        self._holds_claim = False
        if not self._stood_down_logged:
            other = self.db.get_collector_claim(self.job_id)
            logger.warning(
                "%s standing down for job %s — already collected by %s",
                self.label,
                self.job_id,
                other,
            )
            self._stood_down_logged = True
        return False

    def release(self) -> None:
        """Release the claim if this collector holds it."""
        if self._holds_claim is not True:
            return
        try:
            self.db.release_collector_claim(self.job_id, self.owner)
        except Exception as exc:
            logger.debug("Failed to release collector claim for %s: %s", self.job_id, exc)
        self._holds_claim = None
