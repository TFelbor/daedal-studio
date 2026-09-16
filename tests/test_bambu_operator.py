"""`BambuOperator` against a fake broker and a fake FTPS server. No network, no printer.

#73. The printer this was written for has no DHCP lease, so every claim here is a claim
about the *documented* protocol and about our own code's behaviour — never about a
machine. What a person still has to verify on real hardware is the checklist in the pull
request, and nothing in this file can stand in for it.

The two things worth knowing about the shapes below:

* **MQTT authentication is asynchronous.** paho's `connect()` returns once TCP and TLS
  are up; the CONNACK carrying the auth result arrives later, on a callback. The old
  implementation did `connect(); sleep(1); disconnect(); return True` and so returned
  True for a refused access code. `_FakeClient.loop_start` fires the callback, which is
  what lets these tests assert on a result the old code could not observe at all.
* **Bambu's FTPS is implicit.** `ftplib.FTP_TLS` is *explicit* FTPS. Pointing it at 990
  hangs, waiting for a plaintext greeting the printer will never send.
"""

import json
import ssl
from pathlib import Path

import pytest

from pythonsrc.operators.bambu_operator import (
    AUTH_FAILURE_CODES,
    FTPS_PORT,
    MQTT_PORT,
    SDCARD,
    USERNAME,
    BambuOperator,
    _ImplicitFTPS,
    printer_host,
)
from pythonsrc.operators.base import PrinterConnectionError
from pythonsrc.operators.printer_state import (
    COMPLETE,
    PRINTING,
    UNKNOWN,
    normalise_printer_state,
)

SERIAL = "01P00A000000001"
IP = "192.168.1.100"
CODE = "abcd1234"


class _PublishResult:
    def __init__(self, rc=0):
        self.rc = rc


class _FakeClient:
    """Enough of `paho.mqtt.client.Client` to answer, or refuse."""

    #: What the CONNACK will say. 0 is success; see `AUTH_FAILURE_CODES`.
    connack = 0
    #: Whether a CONNACK arrives at all. False is the LAN-Only-Mode-off shape.
    answers = True
    publish_rc = 0

    def __init__(self, *args, **kwargs):
        self.tls = None
        self.credentials = None
        self.connected_to = None
        self.subscriptions: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.looping = False
        self.disconnected = False
        self.on_connect = None
        self.on_message = None

    def tls_set(self, **kwargs):
        self.tls = kwargs

    def tls_insecure_set(self, value):
        self.insecure = value

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def connect(self, host, port, keepalive=60):
        self.connected_to = (host, port, keepalive)

    def loop_start(self):
        self.looping = True
        if self.answers and self.on_connect:
            self.on_connect(self, None, {}, self.connack, None)

    def loop_stop(self):
        self.looping = False

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def publish(self, topic, payload):
        self.published.append((topic, payload))
        return _PublishResult(self.publish_rc)

    # Test-side helper: deliver a report the way the broker would.
    def deliver(self, report: dict):
        message = type("_Msg", (), {"payload": json.dumps({"print": report}).encode()})()
        self.on_message(self, None, message)


@pytest.fixture
def broker(monkeypatch):
    """Install the fake client and hand back the instance the operator built."""
    made: list[_FakeClient] = []

    def _factory(*args, **kwargs):
        client = _FakeClient(*args, **kwargs)
        client.connack = _factory.connack
        client.answers = _factory.answers
        client.publish_rc = _factory.publish_rc
        made.append(client)
        return client

    _factory.connack = 0
    _factory.answers = True
    _factory.publish_rc = 0
    _factory.made = made

    monkeypatch.setattr("pythonsrc.operators.bambu_operator.mqtt.Client", _factory)
    # The operator waits on a threading.Event; the fake answers synchronously inside
    # loop_start, so the wait never blocks. Shortened anyway so a regression that
    # reintroduces real waiting fails fast instead of hanging the suite.
    monkeypatch.setattr("pythonsrc.operators.bambu_operator.CONNACK_TIMEOUT_S", 0.2)
    return _factory


@pytest.fixture
def connected(broker):
    operator = BambuOperator(IP, CODE, serial=SERIAL)
    operator.connect()
    return operator, broker.made[-1]


# ── Addresses ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "written,expected",
    [
        ("192.168.1.100", "192.168.1.100"),
        ("http://192.168.1.100", "192.168.1.100"),
        ("http://192.168.1.100:8883", "192.168.1.100"),
        ("https://p1s.local/", "p1s.local"),
        ("  192.168.1.100  ", "192.168.1.100"),
    ],
)
def test_the_address_is_read_however_a_person_wrote_it(written, expected):
    """`BAMBU_IP` is documented as a bare address, and it reaches us from a text field
    in a UI where every other printer wants a URL."""
    assert printer_host(written) == expected


# ── Session ──────────────────────────────────────────────────────────────────


def test_connect_authenticates_and_subscribes(broker):
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    assert operator.connect() is True

    client = broker.made[-1]
    assert client.connected_to == (IP, MQTT_PORT, 60)
    assert client.credentials == (USERNAME, CODE)
    assert client.subscriptions == [f"device/{SERIAL}/report"]
    assert client.looping


@pytest.mark.parametrize("code", sorted(AUTH_FAILURE_CODES))
def test_a_refused_access_code_says_so(broker, code):
    """The defect this operator was rewritten for: `connect()` returned True for a
    wrong access code, because paho returns before the CONNACK arrives."""
    broker.connack = code
    operator = BambuOperator(IP, "wrong-code", serial=SERIAL)

    with pytest.raises(PrinterConnectionError) as error:
        operator.connect()

    assert "access code" in str(error.value).lower()
    assert broker.made[-1].disconnected


def test_a_silent_printer_is_not_reported_as_a_refused_code(broker):
    """No CONNACK at all is a different problem with a different remedy, and on this
    firmware it usually means LAN Only Mode is off."""
    broker.answers = False
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    with pytest.raises(PrinterConnectionError) as error:
        operator.connect()

    message = str(error.value)
    assert "CONNACK" in message and "LAN Only Mode" in message
    assert "access code" not in message.lower()


def test_an_unreachable_printer_says_where_it_tried(broker, monkeypatch):
    def _refuse(self, host, port, keepalive=60):
        raise OSError("No route to host")

    monkeypatch.setattr(_FakeClient, "connect", _refuse)
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    with pytest.raises(PrinterConnectionError) as error:
        operator.connect()

    assert f"{IP}:{MQTT_PORT}" in str(error.value)


def test_a_missing_serial_is_reported_before_the_socket_is_opened(broker):
    """Otherwise "I do not know this printer's serial" arrives as a network timeout ten
    seconds later, which sends a person to look at their router."""
    operator = BambuOperator(IP, CODE, serial=None)

    with pytest.raises(PrinterConnectionError) as error:
        operator.connect()

    assert "serial" in str(error.value).lower()
    assert broker.made == [], "a socket was opened for a printer we cannot address"


def test_checking_the_code_needs_no_serial(broker):
    """Printer Setup asks this before a person has been anywhere near a serial: they
    have typed an address and a code and want to know whether those two are right."""
    operator = BambuOperator(IP, CODE, serial=None)

    assert operator.check_credentials() is True

    client = broker.made[-1]
    assert client.credentials == (USERNAME, CODE)
    assert client.subscriptions == []       # a check, not a session
    assert client.disconnected


def test_checking_a_wrong_code_still_closes_the_session(broker):
    broker.connack = 5
    operator = BambuOperator(IP, "wrong", serial=None)

    with pytest.raises(PrinterConnectionError):
        operator.check_credentials()

    assert broker.made[-1].disconnected
    assert operator.client is None


def test_disconnect_is_safe_without_a_session():
    assert BambuOperator(IP, CODE).disconnect() is True


# ── Files ────────────────────────────────────────────────────────────────────


class _FakeFTPS:
    """Records the transfer instead of making one."""

    instances: list["_FakeFTPS"] = []

    def __init__(self, *args, **kwargs):
        self.context = kwargs.get("context")
        self.connected_to = None
        self.login_as = None
        self.protected = False
        self.stored = None
        self.quit_called = False
        _FakeFTPS.instances.append(self)

    def connect(self, host, port, timeout=None):
        self.connected_to = (host, port, timeout)

    def login(self, user, password):
        self.login_as = (user, password)

    def prot_p(self):
        self.protected = True

    def storbinary(self, command, handle):
        self.stored = (command, handle.read())

    def quit(self):
        self.quit_called = True


@pytest.fixture
def ftps(monkeypatch):
    _FakeFTPS.instances = []
    monkeypatch.setattr("pythonsrc.operators.bambu_operator._ImplicitFTPS", _FakeFTPS)
    return _FakeFTPS


def test_upload_uses_implicit_ftps_and_returns_the_print_path(ftps, tmp_path: Path):
    gcode = tmp_path / "part.gcode"
    gcode.write_bytes(b";TIME:600\nG1 X1\n")
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    remote = operator.upload_file(str(gcode), "part.gcode")

    transfer = ftps.instances[-1]
    assert transfer.connected_to[:2] == (IP, FTPS_PORT)
    assert transfer.login_as == (USERNAME, CODE)
    assert transfer.protected, "the data channel was left in the clear"
    assert transfer.stored == ("STOR part.gcode", b";TIME:600\nG1 X1\n")
    assert transfer.quit_called
    assert remote == f"{SDCARD}/part.gcode"


def test_upload_does_not_let_a_path_through_to_the_printers_ftp_root(ftps, tmp_path: Path):
    """A path in `remote_name` would be resolved against the printer's root, not ours."""
    gcode = tmp_path / "part.gcode"
    gcode.write_bytes(b"G1\n")
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    remote = operator.upload_file(str(gcode), "../../etc/part.gcode")

    assert ftps.instances[-1].stored[0] == "STOR part.gcode"
    assert remote == f"{SDCARD}/part.gcode"


def test_a_failed_transfer_says_which_printer(ftps, tmp_path: Path, monkeypatch):
    gcode = tmp_path / "part.gcode"
    gcode.write_bytes(b"G1\n")

    def _fail(self, command, handle):
        raise OSError("connection reset")

    monkeypatch.setattr(_FakeFTPS, "storbinary", _fail)
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    with pytest.raises(PrinterConnectionError) as error:
        operator.upload_file(str(gcode), "part.gcode")

    assert IP in str(error.value)


def test_implicit_ftps_wraps_the_socket_on_assignment():
    """The mechanism, not the transfer. `ftplib` assigns `self.sock` in more than one
    place — the data connection `storbinary` opens is one of them — so the wrap lives on
    the property rather than in an overridden `connect`.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ftps = _ImplicitFTPS(context=context)
    ftps.host = "printer.local"

    wrapped: list = []
    context.wrap_socket = lambda sock, server_hostname=None: wrapped.append(sock) or "wrapped"

    ftps.sock = object()

    assert ftps.sock == "wrapped" and len(wrapped) == 1


# ── Commands ─────────────────────────────────────────────────────────────────


def _payloads(client) -> list[dict]:
    return [json.loads(payload) for _topic, payload in client.published]


def test_start_print_names_the_sdcard_path(connected):
    operator, client = connected

    assert operator.start_print("part.gcode") is True

    topic, _ = client.published[-1]
    assert topic == f"device/{SERIAL}/request"
    assert _payloads(client)[-1]["print"]["command"] == "gcode_file"
    assert _payloads(client)[-1]["print"]["param"] == f"{SDCARD}/part.gcode"


def test_start_print_accepts_the_path_upload_file_returned(connected):
    """`upload_file` returns `/sdcard/<name>`, and handing that straight back must not
    produce `/sdcard//sdcard/<name>`."""
    operator, client = connected

    operator.start_print(f"{SDCARD}/part.gcode")

    assert _payloads(client)[-1]["print"]["param"] == f"{SDCARD}/part.gcode"


@pytest.mark.parametrize(
    "method,command", [("cancel_print", "stop"), ("pause_print", "pause"), ("resume_print", "resume")]
)
def test_the_documented_command_payloads(connected, method, command):
    operator, client = connected

    assert getattr(operator, method)() is True

    assert _payloads(client)[-1]["print"]["command"] == command


def test_every_command_carries_a_moving_sequence_id(connected):
    """The firmware requires one and echoes it back in the report. Without it the
    broker accepts the command and the printer ignores it, which is the worst of both
    answers."""
    operator, client = connected

    operator.start_print("part.gcode")
    operator.pause_print()
    operator.resume_print()

    ids = [payload["print"]["sequence_id"] for payload in _payloads(client)]
    assert ids == ["1", "2", "3"]


def test_a_command_without_a_session_is_refused(broker):
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    with pytest.raises(PrinterConnectionError) as error:
        operator.cancel_print()

    assert "connect()" in str(error.value)


def test_a_broker_that_refuses_the_publish_is_not_reported_as_success(connected):
    operator, client = connected
    client.publish_rc = 4

    with pytest.raises(PrinterConnectionError) as error:
        operator.cancel_print()

    assert "stop" in str(error.value)


# ── State ────────────────────────────────────────────────────────────────────


def test_state_is_read_from_the_last_report(connected):
    operator, client = connected
    client.deliver({
        "gcode_state": "RUNNING",
        "mc_percent": 42,
        "layer_num": 17,
        "subtask_name": "part.gcode",
        "nozzle_temper": 219.5,
        "nozzle_target_temper": 220,
        "bed_temper": 59.8,
        "bed_target_temper": 60,
        "mc_remaining_time": 31,
    })

    state = operator.get_printer_state()

    assert state["gcode_state"] == "RUNNING"
    assert state["progress"] == 42
    assert state["layer"] == 17
    assert state["gcode_file"] == "part.gcode"
    assert (state["hotend_actual"], state["hotend_target"]) == (219.5, 220)
    assert (state["bed_actual"], state["bed_target"]) == (59.8, 60)
    assert state["remaining_min"] == 31


def test_reports_are_merged_because_the_printer_sends_deltas(connected):
    """One full report, then messages carrying only what changed. Replacing would drop
    the bed temperature the moment a layer number arrived on its own."""
    operator, client = connected
    client.deliver({"gcode_state": "RUNNING", "bed_temper": 60, "mc_percent": 10})
    client.deliver({"layer_num": 3})

    state = operator.get_printer_state()

    assert state["layer"] == 3
    assert state["bed_actual"] == 60          # not lost to the delta
    assert state["gcode_state"] == "RUNNING"


def test_an_unparseable_report_is_ignored_rather_than_fatal(connected):
    operator, client = connected
    client.deliver({"gcode_state": "RUNNING"})

    broken = type("_Msg", (), {"payload": b"{not json"})()
    client.on_message(client, None, broken)

    assert operator.get_printer_state()["gcode_state"] == "RUNNING"


def test_state_before_the_first_report_is_unknown_not_finished(connected):
    """There are a few seconds between `connect()` and the first report. A monitor
    polling in that window must not conclude anything — `normalise_printer_state` reads
    a missing `gcode_state` as UNKNOWN, and UNKNOWN is never an ending."""
    operator, _client = connected

    assert normalise_printer_state("bambu", operator.get_printer_state()) == UNKNOWN


def test_state_without_a_session_is_refused(broker):
    operator = BambuOperator(IP, CODE, serial=SERIAL)

    with pytest.raises(PrinterConnectionError):
        operator.get_printer_state()


@pytest.mark.parametrize(
    "gcode_state,expected", [("RUNNING", PRINTING), ("FINISH", COMPLETE), ("PAUSE", PRINTING)]
)
def test_the_state_this_operator_returns_is_the_shape_the_monitor_reads(
    connected, gcode_state, expected
):
    """The join with #74: `run_operator`'s monitor calls `normalise_printer_state` on
    whatever `get_printer_state` returns, so the two have to agree about the shape."""
    operator, client = connected
    client.deliver({"gcode_state": gcode_state})

    assert normalise_printer_state("bambu", operator.get_printer_state()) == expected
