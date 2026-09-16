"""One vocabulary for "what is the printer doing", across three firmwares.

`run_operator.py`'s post-start monitor read OctoPrint's shape directly —
`state["state"]["flags"]` and `state["state"]["text"]` — and OctoPrint is the only
firmware that answers in that shape. `MoonrakerOperator.get_printer_state` returns
`state` as a **string**, so `.get("flags", {})` on it raises `AttributeError: 'str'
object has no attribute 'get'`, and the loop's own `except` re-raises it: a Klipper
printer would have failed the dispatch it had just successfully started. Nothing caught
it because nothing dispatched to Klipper — the gate forwarded only `OCTOPRINT_*`
credentials until #75, so the path was unreachable rather than correct.

The vocabulary here is deliberately about the *printer*, not about the dispatch. It
reports what the machine says; deciding that "idle after we pressed start" means
"finished" belongs to the caller that knows a print was started, which is why `IDLE` is
not folded into `COMPLETE` even though the old loop treated OctoPrint's `operational`
as completion. `is_finished` is where that reading lives, so it reads as a decision
rather than as a mapping.
"""

from typing import Any

#: A job is running. Paused counts: the print has not ended, and a paused printer that
#: is resumed by hand must not be reported as finished in between.
PRINTING = "printing"
#: The firmware says the job finished.
COMPLETE = "complete"
#: The job ended because someone or something stopped it. Distinct from COMPLETE
#: because `telemetry.schema` already spends an outcome on the difference, and distinct
#: from ERROR because a cancelled print is not a malfunction.
CANCELLED = "cancelled"
#: The printer reports a fault.
ERROR = "error"
#: Healthy and not printing. Before a dispatch this means "ready"; after one it means
#: the job is over — see `is_finished`.
IDLE = "idle"
#: The firmware answered something this module does not recognise. Never treated as an
#: ending: a monitor that stops on a word it does not know stops on every firmware
#: upgrade that adds one.
UNKNOWN = "unknown"

#: States in which the printer is no longer working on the job.
TERMINAL = frozenset({COMPLETE, CANCELLED, ERROR})

#: OctoPrint's `state.text`, lowercased. The flags are authoritative where they
#: disagree; this covers the connection states that carry no flag of their own.
_OCTOPRINT_TEXT = {
    "printing": PRINTING,
    "paused": PRINTING,
    "pausing": PRINTING,
    "resuming": PRINTING,
    "cancelling": PRINTING,
    "printed": COMPLETE,
    "finishing": PRINTING,
    "operational": IDLE,
    "ready": IDLE,
    "error": ERROR,
    "closed": IDLE,
    "offline": IDLE,
}

#: Klipper's `print_stats.state`, which Moonraker passes through verbatim.
_MOONRAKER_STATE = {
    "printing": PRINTING,
    "paused": PRINTING,
    "complete": COMPLETE,
    "cancelled": CANCELLED,
    "canceled": CANCELLED,      # Klipper spells it with two Ls; be forgiving.
    "error": ERROR,
    "standby": IDLE,
}

#: Bambu's `print.gcode_state` from the MQTT report. Written now, against the shape
#: #73 will deliver, so the third firmware is a table row rather than a branch nobody
#: filled in. `BambuOperator.get_printer_state` still raises `NotImplementedError`.
_BAMBU_GCODE_STATE = {
    "running": PRINTING,
    "prepare": PRINTING,
    "pause": PRINTING,
    "finish": COMPLETE,
    "failed": ERROR,
    "idle": IDLE,
}


def canonical_firmware(firmware: str | None) -> str:
    """`moonraker` and `klipper` are one firmware under two names.

    The same alias `PrinterFactory.create` applies, for the same reason: the UI and the
    config store persist the API's name, printer profiles use the firmware's.
    """
    name = (firmware or "").strip().lower()
    return "klipper" if name == "moonraker" else name


def normalise_printer_state(firmware: str | None, state: Any) -> str:
    """Reduce one firmware's `get_printer_state()` answer to the vocabulary above.

    Args:
        firmware: `octoprint`, `klipper`/`moonraker`, or `bambu`. Case-insensitive.
        state: Whatever that operator's `get_printer_state()` returned.

    Returns:
        One of `PRINTING`, `COMPLETE`, `CANCELLED`, `ERROR`, `IDLE`, `UNKNOWN`.
        `UNKNOWN` for an unrecognised firmware or an unparseable answer — never an
        exception, because this is called from a polling loop whose job is to survive
        one odd reading and look again.
    """
    if not isinstance(state, dict):
        return UNKNOWN

    name = canonical_firmware(firmware)
    if name == "octoprint":
        return _from_octoprint(state)
    if name == "klipper":
        return _from_moonraker(state)
    if name == "bambu":
        return _from_bambu(state)
    return UNKNOWN


def _from_octoprint(state: dict) -> str:
    payload = state.get("state")
    if not isinstance(payload, dict):
        return UNKNOWN

    flags = payload.get("flags")
    flags = flags if isinstance(flags, dict) else {}
    text = str(payload.get("text") or "").strip().lower()

    # Faults first: `closedOrError` is set with `operational` cleared, and a printer
    # that has fallen off the serial port is not idle.
    if flags.get("error") or flags.get("closedOrError"):
        return ERROR
    # Then work in progress, because `operational` stays true while printing — reading
    # it before `printing` is what would report every running job as finished.
    if flags.get("printing") or flags.get("paused"):
        return PRINTING
    if text in _OCTOPRINT_TEXT:
        return _OCTOPRINT_TEXT[text]
    if flags.get("ready") or flags.get("operational"):
        return IDLE
    return UNKNOWN


def _from_moonraker(state: dict) -> str:
    """`state` is a bare string here — the whole reason this module exists."""
    value = state.get("state")
    if not isinstance(value, str):
        return UNKNOWN
    return _MOONRAKER_STATE.get(value.strip().lower(), UNKNOWN)


def _from_bambu(state: dict) -> str:
    report = state.get("print")
    gcode_state = (report if isinstance(report, dict) else state).get("gcode_state")
    if not isinstance(gcode_state, str):
        return UNKNOWN
    return _BAMBU_GCODE_STATE.get(gcode_state.strip().lower(), UNKNOWN)


def is_finished(state: str) -> bool:
    """Has the job this process started ended?

    `IDLE` counts, and only because of who asks: the caller pressed start and then
    began polling, so a printer that is healthy and not printing has finished. Before a
    dispatch the same reading means "ready", which is why this is a function with a
    docstring rather than a constant folded into `TERMINAL`. The old loop made the same
    judgement inline — `(ready or operational) and not printing` — where it could not
    be seen or tested.
    """
    return state in TERMINAL or state == IDLE
