"""`AnomalyDetector` reads every firmware's state through one reader.

It used to import `MoonrakerOperator` and `OctoPrintOperator` and branch on
`isinstance`, which is a telemetry module depending on the operator *classes* to answer
a question about their *data*. Three things followed from that, and each is a test here:

* The two branches were written separately and drifted. Moonraker tracked four states;
  OctoPrint tracked only `error`, so an OctoPrint print that finished still read as
  `printing` to every rule that gates on it.
* Bambu matched neither branch, so the poll silently never happened.
* `None * 100.0` — Klipper reports `progress: None` until the first layer — raised a
  `TypeError` that the caller logged at debug and swallowed, so progress was missing for
  exactly the early part of a print that rules 2 and 4 gate on.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from pythonsrc.operators import PrinterFactory
from pythonsrc.operators.base import BasePrinterOperator
from pythonsrc.telemetry.detector import AnomalyDetector


@pytest.fixture
def db():
    database = MagicMock()
    job = MagicMock()
    job.outcome = "unknown"          # nothing decided yet; the printer is the source
    database.get_job.return_value = job
    return database


class _Operator(BasePrinterOperator):
    """An operator of a given firmware that answers one scripted state."""

    def __init__(self, firmware, state, job_status=None):
        self.firmware = firmware
        self._state = state
        self._job_status = job_status or {}

    def get_printer_state(self):
        if isinstance(self._state, type) and issubclass(self._state, Exception):
            raise self._state()
        return self._state

    def get_job_status(self):
        return self._job_status

    # The rest of the base contract, so this is a real `BasePrinterOperator` and the
    # detector is exercised through the same surface a live operator presents.
    def connect(self): return True
    def upload_file(self, path, filename): ...
    def start_print(self, filename): ...
    def pause_print(self): ...
    def resume_print(self): ...
    def cancel_print(self): ...


async def _read(db, operator):
    detector = AnomalyDetector(asyncio.Queue(), db, operator=operator)
    return await detector._get_state_and_progress("job-1")


# ── Every firmware the factory can build says which one it is ────────────────


@pytest.mark.parametrize(
    "asked,expected",
    [("octoprint", "octoprint"), ("moonraker", "klipper"), ("klipper", "klipper"), ("bambu", "bambu")],
)
def test_each_operator_declares_its_firmware(asked, expected):
    """The attribute that replaced `isinstance`. `moonraker` folds to `klipper`, the
    same alias `PrinterFactory.create` applies."""
    operator = PrinterFactory.create(firmware=asked, base_url="http://printer", api_key=None)

    assert operator.firmware == expected


# ── The drift the two branches had ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_finished_octoprint_print_no_longer_reads_as_printing(db):
    """The drift, asserted. The OctoPrint branch only ever set `error`, so a completed
    print still read as `printing` and rules 2 and 5 — which gate on exactly that —
    kept evaluating a machine that had stopped."""
    state, _ = await _read(
        db,
        _Operator("octoprint", {"state": {"text": "Printed", "flags": {"operational": True, "ready": True}}}),
    )

    assert state == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "firmware,raw,expected",
    [
        ("octoprint", {"state": {"text": "Printing", "flags": {"printing": True}}}, "printing"),
        ("octoprint", {"state": {"text": "Error", "flags": {"error": True}}}, "error"),
        ("octoprint", {"state": {"text": "Offline", "flags": {"closedOrError": True}}}, "error"),
        ("klipper", {"state": "printing"}, "printing"),
        ("klipper", {"state": "complete"}, "success"),
        ("klipper", {"state": "cancelled"}, "cancelled"),
        ("klipper", {"state": "error"}, "error"),
    ],
)
async def test_both_firmwares_reach_the_same_vocabulary(db, firmware, raw, expected):
    state, _ = await _read(db, _Operator(firmware, raw))

    assert state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "firmware,raw",
    [
        ("octoprint", {"state": {"text": "Operational", "flags": {"operational": True}}}),
        ("klipper", {"state": "standby"}),
        ("klipper", {"state": "a-state-from-a-later-klipper"}),
    ],
)
async def test_idle_and_unrecognised_leave_the_cached_state_alone(db, firmware, raw):
    """Mid-run, "healthy and not printing" is the gap between two states rather than a
    verdict — and a word this detector does not know is not a verdict either. Both must
    leave the cache at its `printing` default, which is what the old code did by
    omission on one branch and by an explicit list on the other."""
    state, _ = await _read(db, _Operator(firmware, raw))

    assert state == "printing"


# ── The firmware that matched neither branch ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_firmware_that_cannot_report_state_is_survived(db):
    """`BambuOperator.get_printer_state` raises `NotImplementedError` until #73."""
    state, progress = await _read(db, _Operator("bambu", NotImplementedError))

    assert state == "printing"      # the default, untouched
    assert progress == 0.0


@pytest.mark.asyncio
async def test_a_printer_that_will_not_answer_is_survived(db):
    """A polling detector must not die on one bad read."""
    state, _ = await _read(db, _Operator("klipper", ConnectionError))

    assert state == "printing"


# ── Progress, the one thing the firmwares genuinely do not share ─────────────


@pytest.mark.asyncio
async def test_klipper_progress_before_the_first_layer_does_not_raise(db):
    """`print_stats.info.progress` is absent until the first layer, so
    `get_printer_state` returns `progress: None` and `None * 100.0` raised `TypeError`
    on every poll until then.

    Asserted against `_progress` directly, and deliberately so: through
    `_get_state_and_progress` the caller catches that `TypeError` and the cached
    progress is 0.0 either way, so the obvious test passes with the bug still in. It
    did, until a mutation check said so.
    """
    detector = AnomalyDetector(asyncio.Queue(), db, operator=None)

    assert await detector._progress("klipper", {"state": "printing", "progress": None}) == 0.0


@pytest.mark.asyncio
async def test_a_recorded_progress_is_not_left_stale_by_a_null_reading(db):
    """The one case where the swallowed `TypeError` changed an answer rather than only
    making noise: a real figure, then `None`, leaves the old figure in the cache."""
    detector = AnomalyDetector(asyncio.Queue(), db, operator=_Operator("klipper", {"state": "printing", "progress": 0.42}))
    _, first = await detector._get_state_and_progress("job-1")

    detector.operator = _Operator("klipper", {"state": "printing", "progress": None})
    detector._state_cache["job-1"]["time"] = 0        # let it poll again
    _, second = await detector._get_state_and_progress("job-1")

    assert first == pytest.approx(42.0)
    assert second == 0.0


@pytest.mark.asyncio
async def test_klipper_progress_is_a_percentage(db):
    _, progress = await _read(db, _Operator("klipper", {"state": "printing", "progress": 0.42}))

    assert progress == pytest.approx(42.0)


@pytest.mark.asyncio
async def test_octoprint_progress_comes_off_the_job_not_the_printer(db):
    """OctoPrint keeps completion on the job, so it costs a second request. This is the
    branch that legitimately survives — and it now branches on the declared firmware
    rather than on the operator's class."""
    operator = _Operator(
        "octoprint",
        {"state": {"text": "Printing", "flags": {"printing": True}}},
        job_status={"progress": {"completion": 37.5}},
    )

    _, progress = await _read(db, operator)

    assert progress == pytest.approx(37.5)


@pytest.mark.asyncio
async def test_the_db_outcome_still_decides_before_the_printer_is_asked(db):
    """Unchanged: a job the database has already called a failure reads as `error`
    even while the printer is mid-answer."""
    db.get_job.return_value.outcome = "failure"

    state, _ = await _read(db, _Operator("klipper", {"state": "standby"}))

    assert state == "error"
