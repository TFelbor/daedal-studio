"""The three shapes `get_printer_state()` comes back in, and the one word for each.

#74. `run_operator.py`'s monitor read OctoPrint's nested dict directly, and Moonraker
returns `state` as a bare string — so the loop raised `AttributeError: 'str' object has
no attribute 'get'` and its own `except` re-raised it, failing a dispatch that had
already started a print. The table below is the fixture that would have caught it: one
row per firmware per state, asserted against one vocabulary.
"""

import pytest

from pythonsrc.operators.printer_state import (
    CANCELLED,
    COMPLETE,
    ERROR,
    IDLE,
    PRINTING,
    UNKNOWN,
    canonical_firmware,
    is_finished,
    normalise_printer_state,
)


def octoprint(text: str, **flags) -> dict:
    """OctoPrint's `GET /api/printer`: flags and a human string, nested under `state`."""
    return {"state": {"text": text, "flags": flags}, "temperature": {}}


def moonraker(state: str) -> dict:
    """`MoonrakerOperator.get_printer_state`: `state` is a **string**."""
    return {"state": state, "z_height": 1.2, "progress": 0.5}


def bambu(gcode_state: str) -> dict:
    """The MQTT report #73 will parse."""
    return {"print": {"gcode_state": gcode_state, "mc_percent": 50}}


# ── The table ────────────────────────────────────────────────────────────────

TABLE = [
    # OctoPrint — the shape the old loop understood.
    ("octoprint", octoprint("Printing", printing=True, operational=True), PRINTING),
    ("octoprint", octoprint("Paused", paused=True, operational=True), PRINTING),
    ("octoprint", octoprint("Operational", operational=True, ready=True), IDLE),
    # "Printed" is OctoPrint saying the job finished, which is more than "idle and
    # healthy" — the distinction the old loop threw away by treating both as done.
    ("octoprint", octoprint("Printed", operational=True, ready=True), COMPLETE),
    ("octoprint", octoprint("Error", error=True), ERROR),
    ("octoprint", octoprint("Offline", closedOrError=True), ERROR),
    ("octoprint", octoprint("Something New", operational=True), IDLE),
    ("octoprint", octoprint("Something New"), UNKNOWN),
    # Moonraker / Klipper — the shape that used to raise.
    ("moonraker", moonraker("printing"), PRINTING),
    ("moonraker", moonraker("paused"), PRINTING),
    ("moonraker", moonraker("complete"), COMPLETE),
    ("moonraker", moonraker("cancelled"), CANCELLED),
    ("moonraker", moonraker("error"), ERROR),
    ("moonraker", moonraker("standby"), IDLE),
    ("klipper", moonraker("printing"), PRINTING),
    ("moonraker", moonraker("something-new"), UNKNOWN),
    # Bambu — written against the shape #73 delivers.
    ("bambu", bambu("RUNNING"), PRINTING),
    ("bambu", bambu("PAUSE"), PRINTING),
    ("bambu", bambu("FINISH"), COMPLETE),
    ("bambu", bambu("FAILED"), ERROR),
    ("bambu", bambu("IDLE"), IDLE),
    ("bambu", bambu("SOMETHING_NEW"), UNKNOWN),
]


@pytest.mark.parametrize(
    "firmware,state,expected",
    TABLE,
    ids=[f"{fw}-{expected}-{i}" for i, (fw, _, expected) in enumerate(TABLE)],
)
def test_every_firmware_reduces_to_one_vocabulary(firmware, state, expected):
    assert normalise_printer_state(firmware, state) == expected


def test_a_moonraker_answer_does_not_raise_on_the_octoprint_reading():
    """The defect itself, asserted rather than described.

    `state["state"]` is a string; the old loop called `.get("flags", {})` on it.
    """
    with pytest.raises(AttributeError):
        moonraker("printing")["state"].get("flags", {})

    assert normalise_printer_state("moonraker", moonraker("printing")) == PRINTING


def test_printing_wins_over_operational_on_octoprint():
    """`operational` stays true for the whole print. Reading it first — which is what
    an obvious refactor of the old condition would do — reports every running job as
    finished on its first poll."""
    state = octoprint("Printing", printing=True, operational=True, ready=True)

    assert normalise_printer_state("octoprint", state) == PRINTING
    assert not is_finished(normalise_printer_state("octoprint", state))


@pytest.mark.parametrize("state", [PRINTING, UNKNOWN])
def test_a_monitor_does_not_stop_on_these(state):
    """`UNKNOWN` above all: a loop that ends on a word it does not recognise ends on
    the first firmware upgrade that adds one."""
    assert not is_finished(state)


@pytest.mark.parametrize("state", [COMPLETE, CANCELLED, ERROR, IDLE])
def test_a_monitor_stops_on_these(state):
    assert is_finished(state)


def test_idle_is_finished_only_because_of_who_is_asking():
    """The judgement the old loop made inline as `(ready or operational) and not
    printing`. It is a decision about the caller's situation — start was pressed — and
    not a property of the state, so it lives in a named function."""
    assert is_finished(IDLE)
    assert IDLE not in __import__(
        "pythonsrc.operators.printer_state", fromlist=["TERMINAL"]
    ).TERMINAL


@pytest.mark.parametrize("name", ["moonraker", "klipper", "MOONRAKER", " Klipper "])
def test_the_factory_alias_holds_here_too(name):
    """`PrinterFactory.create` folds moonraker into klipper. A second module with its
    own opinion about that is how a UI-configured printer works in one place and not
    the other."""
    assert canonical_firmware(name) == "klipper"


@pytest.mark.parametrize(
    "firmware,state",
    [("octoprint", "Operational"), ("moonraker", None), ("bambu", []), ("nonesuch", {})],
)
def test_an_unparseable_answer_is_unknown_rather_than_an_exception(firmware, state):
    """This is called from a polling loop. Raising would turn one odd reading into a
    failed dispatch — which is exactly what #74 is about."""
    assert normalise_printer_state(firmware, state) == UNKNOWN
