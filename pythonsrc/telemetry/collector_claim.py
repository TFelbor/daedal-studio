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

# Wordings for "the claim table is absent": PostgreSQL's `relation ... does not exist`
# and the SQLite phrasing older tests and duck-typed databases still use. Matched as
# substrings rather than by exception type so a caller passing a duck-typed database is
# treated the same way as the real driver.
MISSING_TABLE_ERRORS = ("no such table", "does not exist")
#: Kept for callers that imported the old single-string name.
MISSING_TABLE_ERROR = MISSING_TABLE_ERRORS[0]


def _is_missing_table(exc: Exception) -> bool:
    """Whether `exc` says the claim table does not exist, in any driver's words."""
    message = str(exc).lower()
    return any(phrase in message for phrase in MISSING_TABLE_ERRORS)


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
        self._unavailable_logged = False

    def may_write(self, now: float) -> bool:
        """Whether this collector should persist the sample it just received.

        Args:
            now: Current monotonic time, used to throttle heartbeat writes.

        Returns:
            True if this collector holds the claim, or arbitration is unavailable
            *and* the sample can still be written.
        """
        if self._holds_claim is True and (now - self._last_heartbeat) < HEARTBEAT_INTERVAL_S:
            return True

        try:
            granted = self.db.try_claim_collector(self.job_id, self.owner, STALE_AFTER_S)
        except Exception as exc:
            return self._arbitration_failed(exc, now)

        self._unavailable_logged = False
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

    def _arbitration_failed(self, exc: Exception, now: float) -> bool:
        """Decide whether to write when the claim table could not be consulted.

        Two very different failures arrive here and they call for opposite answers:

        * **The claim table does not exist** — a standalone pipeline run against a
          database predating ``telemetry_collector_claim``. Arbitration is genuinely
          unavailable, but there is no second collector to conflict with either, and
          the sample itself can still be written. Collect.
        * **The database is unreachable** — Supabase down, the network gone, the pool
          timed out. This used to take the same branch, which told the collector it
          had *won* a claim it never took: it went on to ``insert_sample``, died there
          instead, and the caller reported the result as a connection error. Nothing
          can be written by anyone, so decline and name the real cause.

        Args:
            exc: The failure raised by ``try_claim_collector``.
            now: Current monotonic time, used to throttle heartbeat writes.

        Returns:
            True if the sample should still be written despite the failure.
        """
        if _is_missing_table(exc):
            logger.debug("Collector claim unavailable for job %s: %s", self.job_id, exc)
            self._holds_claim = True
            self._last_heartbeat = now
            return True

        # Not "someone else owns it" — nobody does, and this collector does not know
        # whether it would have won. Every later sample retries, so a database that
        # comes back recovers on its own and logs the recovery as a fresh claim.
        self._holds_claim = None
        if not self._unavailable_logged:
            logger.error(
                "%s cannot claim job %s — the telemetry database is unreachable, so "
                "no telemetry will be recorded for this print: %s",
                self.label,
                self.job_id,
                exc,
            )
            self._unavailable_logged = True
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
