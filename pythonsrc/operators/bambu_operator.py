"""Bambu Lab printer operator: MQTT for control and state, implicit FTPS for files.

Built and verified against firmware **01.09.01.00** on a P1S (issue #73). The version
matters and is recorded rather than assumed: Bambu has tightened third-party LAN access
repeatedly and its firmware cannot be downgraded, so an operator that works is a claim
about a firmware, not about a model.

Two channels, because the printer uses two:

* **MQTT over TLS on 8883** carries commands and a push feed of state. The session is
  held open — `connect()` subscribes to `device/<serial>/report` and keeps the client
  running, and `get_printer_state()` reads the last report rather than reconnecting.
  A printer that is asked its state every five seconds by the dispatch monitor cannot
  afford a TLS handshake per poll, and the report feed is a push anyway.
* **Implicit FTPS on 990** carries the file. `ftplib` speaks *explicit* FTPS, which is a
  different protocol on a different port; see `_ImplicitFTPS`.

**TLS is unverified on purpose, and it is a real limitation.** The printer presents a
self-signed certificate naming its own serial, so there is no chain to validate against
and `CERT_NONE` is what every third-party client does. It means this trusts whatever
answers on the LAN address, and the access code is what actually authenticates. Pinning
the certificate on first connect is the improvement, and it is a follow-up rather than
this issue.
"""

import json
import logging
import ssl
import threading
from ftplib import FTP_TLS
from typing import Any, Optional

import paho.mqtt.client as mqtt

from pythonsrc.operators.base import BasePrinterOperator, PrinterConnectionError

logger = logging.getLogger(__name__)

#: MQTT over TLS. The only port the printer speaks control on.
MQTT_PORT = 8883
#: Implicit FTPS. Not 21 with AUTH TLS — see `_ImplicitFTPS`.
FTPS_PORT = 990
#: The one username Bambu firmware accepts; the password is the LAN access code.
USERNAME = "bblp"
#: Where the printer's own file browser looks, and what a print command must name.
SDCARD = "/sdcard"

#: CONNACK return codes that mean "your credentials were refused" rather than "I could
#: not reach you". MQTT 3.1.1 spends two codes on it: 4 is a malformed or rejected
#: username/password, 5 is a well-formed one the broker declined. Bambu firmware has
#: been observed to use both, so neither may be read as a transport failure.
#:
#: This distinction is the whole reason the session model changed. The previous
#: `connect()` did `client.connect(); sleep(1); disconnect(); return True` — and
#: paho's `connect()` completes the TCP and TLS handshake and returns *before* the
#: CONNACK arrives, so a refused access code was indistinguishable from a good one and
#: `connect()` returned True either way (#73, comment of 2026-09-11).
AUTH_FAILURE_CODES = frozenset({4, 5})

#: How long to wait for the CONNACK that carries the authentication result.
CONNACK_TIMEOUT_S = 10.0


class _ImplicitFTPS(FTP_TLS):
    """FTPS that is already encrypted when the socket opens.

    `ftplib.FTP_TLS` implements *explicit* FTPS: connect in the clear on 21, then issue
    `AUTH TLS` to upgrade. Bambu's 990 is *implicit* FTPS, where the TLS handshake
    happens the moment the connection is made and before any command is sent. Pointing
    the stock class at 990 hangs: it waits for a plaintext greeting the printer will
    never send, because the printer is waiting for a ClientHello.

    The socket is wrapped through the property below rather than by overriding
    `connect`, so every path `ftplib` uses to assign `self.sock` — including the data
    connection `storbinary` opens — goes through it.
    """

    def __init__(self, *args, **kwargs):
        self._sock = None
        super().__init__(*args, **kwargs)

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value


def printer_host(base_url: str) -> str:
    """The bare host, however the address was written.

    `BAMBU_IP` is documented as a bare address and the config store says so, but it
    reaches here from a text field a person typed into, and `http://192.168.1.100:8883`
    is what a person types when every other printer in the UI wants a URL.
    """
    host = base_url.strip()
    for scheme in ("https://", "http://"):
        if host.startswith(scheme):
            host = host[len(scheme):]
    return host.split("/")[0].split(":")[0]


class BambuOperator(BasePrinterOperator):
    """Printer operator for Bambu Lab printers in LAN mode."""

    firmware = "bambu"

    def __init__(self, base_url: str, api_key: str | None = None, serial: str | None = None):
        """Initialise the operator.

        Args:
            base_url: The printer's IP address or hostname.
            api_key: The LAN access code, from the printer's screen.
            serial: The printer's serial number, which every MQTT topic is keyed on.
                Optional here so the operator can be constructed by
                `PrinterFactory.create`'s three-argument shape; every method that needs
                a topic says so if it is missing.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.serial = serial
        self.client: Optional[mqtt.Client] = None

        self._report: dict[str, Any] = {}
        self._report_lock = threading.Lock()
        self._connack = threading.Event()
        self._connack_code: Optional[int] = None
        #: Echoed back in the report, so it has to move. Starts at 0 and the first
        #: command is 1, which matches what Bambu Studio puts on the wire.
        self._sequence = 0

    # ── Topics ───────────────────────────────────────────────────────────────

    @property
    def request_topic(self) -> str:
        """Where commands go."""
        return f"device/{self._require_serial()}/request"

    @property
    def report_topic(self) -> str:
        """Where state arrives, unasked."""
        return f"device/{self._require_serial()}/report"

    def _require_serial(self) -> str:
        if not self.serial:
            raise PrinterConnectionError(
                "No printer serial. Every Bambu MQTT topic is keyed on it, so the "
                "printer cannot be addressed without one — set BAMBU_SERIAL in Printer "
                "Setup; it is on the printer's screen beside the access code."
            )
        return self.serial

    # ── Session ──────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Open the MQTT session and subscribe to the report feed.

        Returns:
            True once the broker has accepted the credentials and the subscription is in.

        Raises:
            PrinterConnectionError: The printer did not answer, did not send a CONNACK
                within `CONNACK_TIMEOUT_S`, refused the access code, or there is no
                serial to build the topic from.
        """
        # The serial is checked before the socket, so "I do not know this printer's
        # serial" is not reported as a network problem after a ten-second timeout.
        topic = self.report_topic
        self._open_session()
        self.client.subscribe(topic)
        logger.info("Subscribed to %s", topic)
        return True

    def check_credentials(self) -> bool:
        """Does this address accept this access code? Nothing more.

        The connection test in Printer Setup asks exactly this, and it must be able to
        ask it *before* a serial is known — a person setting a printer up has typed an
        IP and a code and wants to hear whether they are right. So this opens the
        session, reads the CONNACK and closes; it never subscribes, and it needs no
        serial.

        Returns:
            True when the printer accepted the credentials.

        Raises:
            PrinterConnectionError: Unreachable, silent, or the code was refused — and
                the three say so differently, which is the whole point of the check.
        """
        try:
            self._open_session()
        finally:
            self.disconnect()
        return True

    def _open_session(self) -> None:
        """Connect, authenticate, and leave the client running.

        Raises:
            PrinterConnectionError: with a sentence a person can act on. "Check the
                access code" and "the printer is not answering" are different problems
                and the previous implementation could report neither, because paho's
                `connect()` returns once TCP and TLS are up — before the CONNACK that
                carries the authentication result.
        """
        host = printer_host(self.base_url)
        self._connack.clear()
        self._connack_code = None

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.username_pw_set(USERNAME, self.api_key or "")
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self.client = client

        logger.info("Opening MQTT session with Bambu printer at %s:%s", host, MQTT_PORT)
        try:
            client.connect(host, MQTT_PORT, keepalive=60)
        except Exception as exc:
            self.client = None
            raise PrinterConnectionError(
                f"Could not reach the Bambu printer at {host}:{MQTT_PORT}: {exc}"
            ) from exc

        client.loop_start()
        if not self._connack.wait(CONNACK_TIMEOUT_S):
            self.disconnect()
            raise PrinterConnectionError(
                f"The Bambu printer at {host} accepted the connection but sent no MQTT "
                f"CONNACK within {CONNACK_TIMEOUT_S:.0f}s. On this firmware that is "
                "usually LAN Only Mode being off with the printer bound to the cloud."
            )

        if self._connack_code in AUTH_FAILURE_CODES:
            self.disconnect()
            raise PrinterConnectionError(
                "The Bambu printer refused the LAN access code. It is on the printer's "
                "screen under Settings → Network, and it changes when LAN Only Mode is "
                "toggled."
            )
        if self._connack_code:
            self.disconnect()
            raise PrinterConnectionError(
                f"The Bambu printer refused the MQTT connection (CONNACK "
                f"{self._connack_code})."
            )

    def disconnect(self) -> bool:
        """Close the session. Safe to call when there is none."""
        client, self.client = self.client, None
        if client is None:
            return True
        try:
            client.loop_stop()
            client.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Bambu disconnect was not clean: %s", exc)
        return True

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties=None):
        """CONNACK. The only place the printer says whether the code was accepted."""
        self._connack_code = int(getattr(reason_code, "value", reason_code) or 0)
        self._connack.set()

    def _on_message(self, client, userdata, message):
        """A report. Merged rather than replaced — see `get_printer_state`."""
        try:
            payload = json.loads(message.payload)
        except (ValueError, TypeError) as exc:
            logger.debug("Unparseable Bambu report: %s", exc)
            return

        report = payload.get("print")
        if not isinstance(report, dict):
            return

        with self._report_lock:
            # The printer sends one full report and then deltas carrying only what
            # changed, so replacing would drop the bed temperature the moment a layer
            # number arrives on its own.
            self._report.update(report)

    # ── State ────────────────────────────────────────────────────────────────

    def get_printer_state(self) -> dict:
        """The last report, in the shape the rest of this codebase reads.

        Returns:
            `gcode_state` and the temperatures, progress and current file beside it.
            Empty-ish until the first report arrives, which is a few seconds after
            `connect()` — `normalise_printer_state` reads a missing `gcode_state` as
            `UNKNOWN`, and `UNKNOWN` is never an ending, so a monitor polling in that
            window waits rather than concluding anything.

        Raises:
            PrinterConnectionError: `connect()` was never called.
        """
        if self.client is None:
            raise PrinterConnectionError(
                "No MQTT session — call connect() before reading the printer state."
            )

        with self._report_lock:
            report = dict(self._report)

        return {
            # Nested under `print` as well as flattened: `printer_state` reads the MQTT
            # report's own shape, and flattening only would make this operator the one
            # firmware whose raw answer does not look like its protocol.
            "print": report,
            "gcode_state": report.get("gcode_state"),
            "state": report.get("gcode_state"),
            "progress": report.get("mc_percent"),
            "layer": report.get("layer_num"),
            "gcode_file": report.get("gcode_file") or report.get("subtask_name"),
            "hotend_actual": report.get("nozzle_temper"),
            "hotend_target": report.get("nozzle_target_temper"),
            "bed_actual": report.get("bed_temper"),
            "bed_target": report.get("bed_target_temper"),
            "remaining_min": report.get("mc_remaining_time"),
        }

    # ── Files ────────────────────────────────────────────────────────────────

    def upload_file(self, local_path: str, remote_name: str) -> str:
        """Put a file on the printer's SD card over implicit FTPS.

        Args:
            local_path: The file to send.
            remote_name: What to call it on the card. Basename only; a path here would
                be interpreted by the printer's FTP root, not by ours.

        Returns:
            The path the print command must name — `/sdcard/<remote_name>`. **Not a
            bool**, unlike the other operators: #73's second acceptance criterion asks
            for the remote name, and `start_print` needs it because Bambu addresses the
            file by absolute path where OctoPrint addresses it by the name it was
            uploaded under. Truthy either way, so a caller that only checks success is
            unaffected.

        Raises:
            PrinterConnectionError: The transfer did not complete.
        """
        host = printer_host(self.base_url)
        name = remote_name.rsplit("/", 1)[-1]

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        logger.info("Uploading %s to %s:%s as %s", local_path, host, FTPS_PORT, name)
        try:
            ftps = _ImplicitFTPS(context=context)
            ftps.connect(host=host, port=FTPS_PORT, timeout=30)
            ftps.login(USERNAME, self.api_key or "")
            # Encrypt the data channel too. Without it the control channel is TLS and
            # the file itself crosses the LAN in the clear, which is not what "FTPS"
            # promises anyone reading this.
            ftps.prot_p()
            with open(local_path, "rb") as handle:
                ftps.storbinary(f"STOR {name}", handle)
            ftps.quit()
        except Exception as exc:
            raise PrinterConnectionError(
                f"Could not upload {name} to the Bambu printer at {host}: {exc}"
            ) from exc

        return f"{SDCARD}/{name}"

    # ── Commands ─────────────────────────────────────────────────────────────

    def _publish(self, command: dict) -> bool:
        """Send one command on the request topic.

        Every payload is wrapped in `{"print": {...}}` and carries a `sequence_id`,
        which the firmware requires and echoes back in the report; without one the
        command is accepted by the broker and ignored by the printer, which is the
        worst of both answers.
        """
        if self.client is None:
            raise PrinterConnectionError(
                "No MQTT session — call connect() before sending a command."
            )

        self._sequence += 1
        payload = {"print": {"sequence_id": str(self._sequence), **command}}
        info = self.client.publish(self.request_topic, json.dumps(payload))
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise PrinterConnectionError(
                f"Could not publish {command.get('command')!r} to "
                f"{self.request_topic}: paho rc={info.rc}"
            )
        logger.info("Sent %s to %s", command.get("command"), self.request_topic)
        return True

    def start_print(self, filename: str) -> bool:
        """Start printing a file already on the SD card.

        Args:
            filename: The remote name, or the `/sdcard/...` path `upload_file` returned.

        `gcode_file`, not `project_file` — #73's open question 2, settled. CuraEngine
        emits a plain `.gcode` file and `gcode_file` prints exactly that; `project_file`
        wants a sliced 3MF whose `Metadata/plate_1.gcode` the printer reads, which means
        building a 3MF container around our own G-code for no gain. The cost of this
        choice is that the machine's purge line and bed levelling are not supplied by a
        Bambu Studio project, so they have to live in the profile's start G-code —
        `pythonsrc/profiles/bambu_p1s.json` carries them for that reason.
        """
        param = filename if filename.startswith("/") else f"{SDCARD}/{filename}"
        return self._publish({"command": "gcode_file", "param": param})

    def cancel_print(self) -> bool:
        """Stop the running print."""
        return self._publish({"command": "stop", "param": ""})

    def pause_print(self) -> bool:
        """Pause the running print."""
        return self._publish({"command": "pause", "param": ""})

    def resume_print(self) -> bool:
        """Resume a paused print."""
        return self._publish({"command": "resume", "param": ""})
