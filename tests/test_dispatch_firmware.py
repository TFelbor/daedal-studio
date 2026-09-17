"""The dispatch path carries one firmware's credentials to that firmware's printer.

#74. Two halves, and they failed differently:

* **The gate** forwarded only `OCTOPRINT_*`, so a Klipper or Bambu profile reached the
  operator with no key at all. That half landed with #75; these tests hold it, because
  a criterion taken on trust is a criterion nobody checks again.
* **The operator's monitor** hardcoded `OctoPrintCollector` and OctoPrint's state
  shape. `MoonrakerOperator.get_printer_state` returns `state` as a string, so the loop
  raised `AttributeError` *after* uploading the file and starting the print — the worst
  possible moment, and invisible while the gate made the path unreachable.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server import app as app_module
from server.app import app
from server.config_store import credential_host

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = REPO_ROOT / "data" / "outputs"

KLIPPER_PROFILE = "pythonsrc/profiles/klipper_test.json"
BAMBU_PROFILE = "pythonsrc/profiles/bambu_p1s.json"

MOONRAKER_URL = "http://klipper.local:7125"
OCTOPRINT_URL = "http://octoprint.local:5000"
BAMBU_IP = "192.168.1.100"


class _FakeProcess:
    """Enough of an `asyncio.subprocess.Process` for the gate's follower task."""

    pid = 4242
    returncode = 0

    def __init__(self):
        self.stdout = self

    async def readline(self) -> bytes:
        return b""

    async def wait(self) -> int:
        return 0


@pytest.fixture
def dispatched(monkeypatch):
    """Take a job to the point of launch and hand back the operator's environment."""
    launched: dict = {}

    async def _fake_exec(*cmd, **kwargs):
        launched["cmd"] = cmd
        launched["env"] = kwargs.get("env") or {}
        return _FakeProcess()

    async def _online():
        return {"configured": True, "running": True, "detail": "ok"}

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(app_module, "printer_status", _online)

    created: list[Path] = []

    def _go(profile: str, stored: dict) -> dict:
        monkeypatch.setattr(app_module.config_store, "get", lambda key: stored.get(key))

        job_id = str(uuid.uuid4())
        db = TelemetryDB()
        db.init_schema()
        db.insert_job(
            PrintJob(
                job_id=job_id,
                prompt="a low poly planter",
                printer_id="default",
                printer_firmware=json.loads((REPO_ROOT / profile).read_text())["firmware"],
                slicer="cura",
                profile_name=profile,
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                outcome="success",
            )
        )
        db.update_job_slice(job_id, status="success")
        db.close()

        directory = OUTPUTS / job_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "engineered_mesh.gcode").write_text(";TIME:600\nG1 X1 Y1 E0.1\n")
        created.append(directory)

        response = client.post(
            f"/jobs/{job_id}/print-dispatch", json={"confirmed": True}
        )
        return {"response": response, "job_id": job_id, **launched}

    yield _go

    for directory in created:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()


# ── The gate: one firmware's key, one firmware's address ─────────────────────


def test_a_klipper_dispatch_carries_the_moonraker_credentials(dispatched):
    result = dispatched(
        KLIPPER_PROFILE,
        {
            "MOONRAKER_URL": MOONRAKER_URL,
            "MOONRAKER_API_KEY": "moon-key",
            "MOONRAKER_API_KEY_HOST": credential_host(MOONRAKER_URL),
            # A *valid, bound* OctoPrint key, so `subprocess_env` really does put it
            # in the child's environment and the gate's `env.pop` is what takes it out
            # again. Without the HOST entry the binding withholds it anyway and the
            # assertion below passes for the wrong reason — which it did, until a
            # mutation test caught that it survived deleting the `pop`.
            "OCTOPRINT_API_KEY": "octo-key",
            "OCTOPRINT_URL": OCTOPRINT_URL,
            "OCTOPRINT_API_KEY_HOST": credential_host(OCTOPRINT_URL),
        },
    )

    assert result["response"].status_code == 200, result["response"].text
    env = result["env"]
    assert env["DS_FIRMWARE"] == "klipper"
    assert env["DS_PRINTER_KEY"] == "moon-key"
    assert MOONRAKER_URL in env["DS_DISPATCH_URL"]
    # The defect this replaced: the OctoPrint key travelling to the Moonraker address.
    assert "OCTOPRINT_API_KEY" not in env
    assert env["DS_PRINTER_KEY"] != "octo-key"


#: Everything a correctly configured Bambu printer needs, so the refusal below can only
#: be the refusal — not a missing serial, a missing code or an unbound credential.
BAMBU_CONFIGURED = {
    "BAMBU_IP": BAMBU_IP,
    "BAMBU_CODE": "12345678",
    "BAMBU_CODE_HOST": credential_host(BAMBU_IP),
    "BAMBU_SERIAL": "01P00A000000001",
}


def test_a_bambu_dispatch_is_refused_before_it_touches_the_printer(dispatched):
    """#73's scope reduction, enforced where it costs nothing.

    This repository does not start prints on Bambu firmware: a raw `gcode_file` runs
    none of the machine's start behaviour, and the machine's cannot be reproduced here
    without copying Bambu's AGPL-3.0 macros into an Apache-2.0 tree.

    `BambuOperator.start_print` raising is not enough on its own, and that is the whole
    point of this test. The gate used to spawn the operator, which connected, uploaded
    the CuraEngine `.gcode` over FTPS, and *then* had `start_print` refuse — leaving a
    start-sequence-less file on the printer's SD card and a job marked failure with "The
    operator exited with 1", the reason visible only in a subprocess log. The refusal has
    to arrive before the first side effect.
    """
    result = dispatched(BAMBU_PROFILE, BAMBU_CONFIGURED)
    response = result["response"]

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    # The person's own answer, not a status code: what to do instead, and why.
    assert "Bambu Studio" in detail
    assert "3MF" in detail
    # Nothing was spawned, so nothing connected, uploaded or published.
    assert "cmd" not in result and "env" not in result


def test_a_refused_bambu_dispatch_leaves_the_job_alone(dispatched):
    """A refusal is not a dispatch, so the row must not read as one.

    The 409 lands before `dispatch_confirmed` is recorded and before the outcome moves
    to `awaiting_verdict` — otherwise the job sits asking a person for a verdict on a
    part no printer was ever asked to make, and `dispatch_state` reports it as sent.
    """
    result = dispatched(BAMBU_PROFILE, BAMBU_CONFIGURED)
    assert result["response"].status_code == 409

    db = TelemetryDB()
    job = db.get_job(result["job_id"])
    events = db.get_job_events(result["job_id"], kind="dispatch_confirmed")
    db.close()

    assert events == []
    assert job.outcome != "awaiting_verdict"
    assert job.dispatched_printer_url in (None, "")


def test_the_gate_asks_the_operator_class_rather_than_naming_bambu(dispatched, monkeypatch):
    """The gate must not carry its own list of firmwares it will not print to.

    `starts_prints` is declared by the operator, so a firmware that stops refusing —
    or a fourth one that starts — changes one attribute and no branch in `server/`.
    Asserted by making a firmware that *does* print refuse, and watching the gate obey.
    """
    from pythonsrc.operators.moonraker_operator import MoonrakerOperator

    monkeypatch.setattr(MoonrakerOperator, "starts_prints", False)
    monkeypatch.setattr(
        MoonrakerOperator, "dispatch_refusal", "Not this one either, and here is why.",
    )

    result = dispatched(
        KLIPPER_PROFILE,
        {
            "MOONRAKER_URL": MOONRAKER_URL,
            "MOONRAKER_API_KEY": "moon-key",
            "MOONRAKER_API_KEY_HOST": credential_host(MOONRAKER_URL),
        },
    )

    assert result["response"].status_code == 409
    assert result["response"].json()["detail"] == "Not this one either, and here is why."


def test_the_bambu_operator_declares_the_refusal_the_gate_reads():
    """One sentence, on the class, so the 409 and the log cannot say different things."""
    from pythonsrc.operators.bambu_operator import DISPATCH_REFUSAL, BambuOperator
    from pythonsrc.operators.base import BasePrinterOperator

    assert BambuOperator.starts_prints is False
    assert BambuOperator.dispatch_refusal == DISPATCH_REFUSAL
    # The default is to print. A new operator that says nothing is not silently refused.
    assert BasePrinterOperator.starts_prints is True


def test_the_operator_is_launched_by_the_path_the_gate_names(dispatched):
    result = dispatched(
        KLIPPER_PROFILE,
        {
            "MOONRAKER_URL": MOONRAKER_URL,
            "MOONRAKER_API_KEY": "moon-key",
            "MOONRAKER_API_KEY_HOST": credential_host(MOONRAKER_URL),
        },
    )

    assert str(REPO_ROOT / "pythonsrc" / "run_operator.py") in result["cmd"]
    assert "--job-id" in result["cmd"]


# ── The operator: which collector, and can it read the state ─────────────────


def test_each_firmware_gets_its_own_collector():
    """`None` for Bambu is an answer, not an oversight — there is no collector yet."""
    from pythonsrc import run_operator

    db = MagicMock()
    octo = run_operator.collector_for(
        "octoprint", "http://printer.local:5000", "k", "job", db, "part.gcode"
    )
    moon = run_operator.collector_for(
        "moonraker", MOONRAKER_URL, "k", "job", db, "part.gcode"
    )
    bambu = run_operator.collector_for("bambu", BAMBU_IP, "k", "job", db, "part.gcode")

    assert type(octo).__name__ == "OctoPrintCollector"
    assert type(moon).__name__ == "MoonrakerCollector"
    assert bambu is None


def test_the_octoprint_collector_gets_a_host_and_port_and_moonraker_a_socket():
    """The two constructors do not agree on what a printer address is, which is half of
    why the collector was hardcoded rather than chosen."""
    from pythonsrc import run_operator

    db = MagicMock()
    octo = run_operator.collector_for(
        "octoprint", "https://printer.local", "k", "job", db, "part.gcode"
    )
    moon = run_operator.collector_for(
        "klipper", MOONRAKER_URL, None, "job", db, "part.gcode"
    )

    assert (octo.host, octo.port) == ("printer.local", 443)     # https ⇒ 443, not 80
    assert moon.ws_url == "ws://klipper.local:7125/websocket"


@pytest.mark.parametrize(
    "base_url,expected",
    [
        ("http://klipper.local:7125", "ws://klipper.local:7125/websocket"),
        ("https://klipper.local", "wss://klipper.local/websocket"),
        ("http://10.0.0.5:7125/", "ws://10.0.0.5:7125/websocket"),
    ],
)
def test_the_moonraker_socket_url_follows_the_scheme(base_url, expected):
    from pythonsrc import run_operator

    assert run_operator.moonraker_ws_url(base_url) == expected


# ── The monitor loop, driven end to end against each firmware ────────────────


class _FakeOperator:
    """Answers `get_printer_state()` from a script, in that firmware's own shape."""

    #: The `BasePrinterOperator` default, overridden per test for the refusal case.
    starts_prints = True
    dispatch_refusal = ""

    def __init__(self, states):
        self.states = list(states)
        self.started: list[str] = []
        self.uploaded: list[str] = []
        self.connected = False

    def connect(self):
        self.connected = True
        return True

    def upload_file(self, path, filename):
        self.uploaded.append(filename)

    def start_print(self, filename):
        self.started.append(filename)

    def get_printer_state(self):
        if not self.states:
            raise AssertionError("the monitor polled after its last scripted state")
        state = self.states.pop(0)
        if isinstance(state, type) and issubclass(state, Exception):
            raise state()
        return state


class _FakeCollector:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.sample_queue = asyncio.Queue()

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


#: "The caller did not choose", as distinct from "there is no collector".
_DEFAULT_COLLECTOR = object()


@pytest.fixture
def run_monitor(monkeypatch, tmp_path):
    """Run `run_operator.main()` with the world stubbed, and report what happened."""
    from pythonsrc import run_operator

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)
    monkeypatch.setattr("pythonsrc.telemetry.db.TelemetryDB", MagicMock())
    monkeypatch.setattr(
        "pythonsrc.telemetry.detector.attach_detector",
        lambda *a, **k: asyncio.ensure_future(_instant(0)),
    )

    def _go(firmware: str, states, collector=_DEFAULT_COLLECTOR, starts_prints=True):
        operator = _FakeOperator(states)
        operator.starts_prints = starts_prints
        operator.dispatch_refusal = "" if starts_prints else "Not on this firmware."
        # Hung on the fixture as well as returned, because a run that refuses exits
        # through `SystemExit` and never reaches the return — and what that run did
        # *not* do is the whole assertion.
        _go.operator = operator
        # `None` has to mean "this firmware has no collector", so the default is a
        # sentinel rather than None — the distinction the test below is about.
        collector = _FakeCollector() if collector is _DEFAULT_COLLECTOR else collector

        profile = tmp_path / "profile.json"
        profile.write_text(json.dumps({"firmware": firmware, "base_url": MOONRAKER_URL}))
        gcode = tmp_path / "part.gcode"
        gcode.write_text(";TIME:1\n")

        monkeypatch.setattr(
            run_operator.PrinterFactory, "create", lambda **kw: operator
        )
        monkeypatch.setattr(run_operator, "collector_for", lambda *a, **k: collector)
        monkeypatch.setenv("DS_FIRMWARE", firmware)
        monkeypatch.setenv("DS_PRINTER_URL", MOONRAKER_URL)
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_operator.py",
                "--job-id", "job-1",
                "--gcode-path", str(gcode),
                "--profile", str(profile),
            ],
        )
        run_operator.main()
        return operator, collector

    return _go


def test_the_monitor_survives_moonrakers_string_state(run_monitor):
    """#74's crash, asserted directly.

    `{"state": "printing"}` — a *string* — is what the old loop called `.get("flags")`
    on, raising `AttributeError` after the print had already been started. Here the
    print runs to completion instead.
    """
    operator, collector = run_monitor(
        "moonraker", [{"state": "printing"}, {"state": "complete"}]
    )

    assert operator.started == ["part.gcode"]
    assert collector.started and collector.stopped


def test_the_monitor_still_reads_octoprint(run_monitor):
    """The shape that always worked has to keep working."""
    operator, collector = run_monitor(
        "octoprint",
        [
            {"state": {"text": "Printing", "flags": {"printing": True}}},
            {"state": {"text": "Operational", "flags": {"operational": True}}},
        ],
    )

    assert operator.started == ["part.gcode"]
    assert collector.stopped


def test_a_printer_fault_still_fails_the_dispatch(run_monitor):
    """Errors must keep ending the run — `SystemExit(1)` is how `main` reports it, and
    the gate reads that exit code as a failed Phase 5."""
    with pytest.raises(SystemExit) as exit_info:
        run_monitor("moonraker", [{"state": "error"}])

    assert exit_info.value.code == 1


def test_a_firmware_that_cannot_report_state_does_not_fail_the_dispatch(run_monitor):
    """A `NotImplementedError` from `get_printer_state` is a statement about the
    firmware, not a fault. The print was uploaded and started by then; failing here
    would report a running print as a failed dispatch — the shape of #74."""
    operator, _ = run_monitor("bambu", [NotImplementedError])

    assert operator.started == ["part.gcode"]


def test_a_dispatch_with_no_collector_at_all_still_runs(run_monitor):
    """Bambu has no collector, and `collector_for` says so by returning None. The print
    is uploaded, started and recorded; only the sample stream is missing, which is what
    the warning in the loop exists to say."""
    operator, collector = run_monitor("bambu", [NotImplementedError], collector=None)

    assert collector is None
    assert operator.uploaded == ["part.gcode"]
    assert operator.started == ["part.gcode"]


def test_the_operator_refuses_before_it_connects_when_the_gate_is_bypassed(run_monitor, caplog):
    """The backstop behind the gate's 409, asserted where it has to hold: before the
    first side effect.

    `BambuOperator.start_print` raises, but only after `connect()` and `upload_file()`
    have run — and `upload_file` is what puts a start-sequence-less `.gcode` on the
    printer's SD card. So the run must end at the question, not at the answer. The
    gate is what a person sees; this is what holds for a hand-run command line or a
    caller that forgets to ask.
    """
    with pytest.raises(SystemExit) as exit_info:
        run_monitor("bambu", [], collector=None, starts_prints=False)

    operator = run_monitor.operator
    assert exit_info.value.code == 1
    assert not operator.connected
    assert operator.uploaded == []
    assert operator.started == []
    # And the reason, not just the exit code — this is the only place it is said.
    assert "Not on this firmware." in caplog.text
