"""
operators/octoprint_operator.py — Phase 4: OctoPrint REST API integration.

Uploads a print-ready mesh file to an OctoPrint instance and optionally
starts the print job. Can also poll for job status.

Usage (standalone):
    python pythonsrc/operators/octoprint_operator.py --file data/outputs/engineered_mesh.gcode \
        --url http://octopi.local --key YOUR_API_KEY
 [--start] [--watch] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("p2p.operator")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── OctoPrintOperator ─────────────────────────────────────────────────────────
from pythonsrc.operators.base import BasePrinterOperator, PrinterConnectionError

class OctoPrintOperator(BasePrinterOperator):
    """
    Thin wrapper around the OctoPrint REST API.

    Reference: https://docs.octoprint.org/en/master/api/

    Parameters
    ----------
    base_url:
        Base URL of the OctoPrint instance, e.g. ``http://localhost:5001``
        or ``http://192.168.1.50``.  Trailing slashes are stripped.
    api_key:
        OctoPrint Application API Key (Settings → API).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(self, base_url: str, api_key: str, *, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-Api-Key": self.api_key})

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/api/{endpoint.lstrip('/')}"

    def _get(self, endpoint: str, **kwargs) -> dict[str, Any]:
        resp = self._session.get(self._url(endpoint), timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, **kwargs) -> dict[str, Any] | None:
        resp = self._session.post(self._url(endpoint), timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        # 204 No Content is valid for some actions (e.g. cancel)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ── Connection & Status ───────────────────────────────────────────────────
    def get_version(self) -> dict[str, Any]:
        """Return OctoPrint version info (also used as a connectivity check)."""
        return self._get("version")

    def connectivity_check(self) -> dict[str, Any]:
        """
        Verify OctoPrint is reachable and the API key is valid.

        Hits ``GET /api/version`` and returns the JSON response on success.

        Raises
        ------
        RuntimeError
            With a diagnostic message distinguishing between:
            - Connection refused (server not running)
            - 403 Forbidden (API key wrong or access control misconfigured)
            - Any other unexpected error
        """
        try:
            return self.get_version()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Connection refused — cannot reach OctoPrint at {self.base_url}. "
                "Is the OctoPrint server running? Check the URL and port."
            )
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 403:
                raise RuntimeError(
                    f"403 Forbidden — OctoPrint at {self.base_url} rejected the API key. "
                    "Verify the X-Api-Key value matches the key shown in "
                    "OctoPrint Settings → API → Global API Key. "
                    "Also check that access control is not blocking programmatic access."
                ) from exc
            raise RuntimeError(
                f"Unexpected HTTP error from OctoPrint at {self.base_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Unexpected error while contacting OctoPrint at {self.base_url}: {exc}"
            ) from exc

    def get_printer_state(self) -> dict[str, Any]:
        """Return current printer state (temperature, operational status, etc.)."""
        return self._get("printer")

    def get_connection(self) -> dict[str, Any]:
        """Return serial connection state."""
        return self._get("connection")

    def connect(self) -> bool:
        try:
            self.ensure_operational(auto_connect_port="VIRTUAL", timeout=20)
            return True
        except Exception as exc:
            raise PrinterConnectionError(str(exc)) from exc
            
    def _connect_serial(
        self,
        port: str = "VIRTUAL",
        baudrate: int = 250000,
        *,
        printer_profile: str = "_default",
        save: bool = False,
        autoconnect: bool = False,
    ) -> None:
        """
        Issue a connect command to OctoPrint's serial layer.

        For local virtual printer testing, use port="VIRTUAL".
        For a real printer, set port to the serial device path
        (e.g. "/dev/ttyUSB0" on Linux, "/dev/cu.usbserial-*" on macOS).

        Raises
        ------
        RuntimeError
            If OctoPrint returns a non-2xx response.
        """
        payload = {
            "command": "connect",
            "port": port,
            "baudrate": baudrate,
            "printerProfile": printer_profile,
            "save": save,
            "autoconnect": autoconnect,
        }
        logger.info("Connecting printer on port '%s'…", port)
        self._post("connection", json=payload)
        logger.info("Connect command sent.")

    def force_virtual_connect(self, *, timeout: int = 20) -> None:
        """
        Enable the virtual printer plugin, connect to the VIRTUAL port,
        and poll until the printer reaches Operational state.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait for the printer to become Operational.

        Raises
        ------
        RuntimeError
            If the printer does not reach Operational within *timeout*.
        """
        import time as _time

        # Step 1: ensure the virtual printer plugin is enabled
        logger.info("Enabling virtual printer plugin…")
        try:
            self._post(
                "settings",
                json={"plugins": {"virtual_printer": {"enabled": True}}},
            )
        except requests.exceptions.HTTPError:
            logger.warning("Could not enable virtual printer plugin via API — may already be enabled.")

        # Step 2: issue the connect command
        logger.info("Forcing connection to VIRTUAL port…")
        self._connect_serial(port="VIRTUAL", baudrate=250000)

        # Step 3: poll until operational
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            _time.sleep(2)
            try:
                state = self.get_printer_state()
                flags = state.get("state", {}).get("flags", {})
                if flags.get("operational") or flags.get("ready"):
                    logger.info("Virtual printer is Operational ✔")
                    return
                logger.debug("Printer state: %s — waiting…", state.get("state", {}).get("text", "?"))
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 409:
                    logger.debug("Printer still connecting (409)… retrying.")
                else:
                    raise

        raise RuntimeError(
            f"Virtual printer did not reach Operational state within {timeout}s. "
            "Check OctoPrint logs and ensure the Virtual Printer plugin is installed and enabled."
        )

    def ensure_operational(self, *, auto_connect_port: str = "VIRTUAL", timeout: int = 20) -> None:
        """
        Check printer state and auto-connect if not yet connected.

        Polls up to *timeout* seconds for the printer to reach Operational.
        When the port is ``"VIRTUAL"``, uses :meth:`force_virtual_connect`
        which also enables the virtual printer plugin.

        Raises
        ------
        RuntimeError
            If the printer does not reach Operational within the timeout.
        """
        import time as _time
        deadline = _time.time() + timeout

        while _time.time() < deadline:
            try:
                state = self.get_printer_state()
                flags = state.get("state", {}).get("flags", {})
                if flags.get("operational") or flags.get("ready"):
                    logger.info("Printer is Operational ✔")
                    return
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 409:
                    # 409 = printer not connected — try to connect
                    if auto_connect_port == "VIRTUAL":
                        logger.info("Printer not connected — forcing virtual connect…")
                        self.force_virtual_connect(timeout=max(1, int(deadline - _time.time())))
                        return  # force_virtual_connect already verified Operational
                    else:
                        logger.info("Printer not connected — issuing connect on port '%s'…", auto_connect_port)
                        self._connect_serial(port=auto_connect_port)
                else:
                    raise
            _time.sleep(2)

        raise RuntimeError(
            f"Printer did not reach Operational state within {timeout}s. "
            "Check OctoPrint logs and virtual printer plugin status."
        )

    # ── File Management ───────────────────────────────────────────────────────
    def upload_file(self, local_path: str, remote_name: str) -> bool:
        """
        Upload a **G-code** file to OctoPrint.

        Parameters
        ----------
        file_path:
            Local path to the ``.gcode`` file produced by the slicer.
            Any other extension (e.g. ``.obj``, ``.stl``) is **rejected**
            with a :class:`ValueError` to prevent silently uploading an
            un-sliced mesh.
        location:
            Storage location on OctoPrint: ``"local"`` (disk) or ``"sdcard"``.
        select:
            If True, select the file for printing after upload.
        start:
            If True, start printing immediately after upload.

        Returns
        -------
        dict
            OctoPrint API response containing ``refs.resource`` (the file URL)
            which can be passed to :meth:`select_file` or :meth:`start_print`.

        Raises
        ------
        ValueError
            If *file_path* does not have a ``.gcode`` extension.
        FileNotFoundError
            If *file_path* does not exist on disk.
        """
        file_path = Path(local_path)

        # ── Extension guard — OctoPrint only accepts .gcode ───────────────
        suffix = file_path.suffix.lower()
        if suffix != ".gcode":
            raise ValueError(
                f"OctoPrint only accepts .gcode files. "
                f"Received a '{suffix}' file: {file_path}\n"
                "Run the slicer (Phase 3.5 / CuraSlicer) first to convert "
                "the mesh to G-code before uploading."
            )

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("Uploading '%s' to OctoPrint (%s)…", file_path.name, location)

        with file_path.open("rb") as fh:
            files = {"file": (remote_name, fh, "application/octet-stream")}
            data = {"select": "true", "print": "false"}
            resp = self._session.post(
                self._url("files/local"),
                files=files,
                data=data,
                timeout=max(self.timeout, 120),  # uploads can be slow
            )
            resp.raise_for_status()
            result = resp.json()

        logger.info("Upload complete — %s", result.get("done", ""))
        logger.debug("Upload response: %s", result)
        return True

    def list_files(self, location: str = "local") -> dict[str, Any]:
        """List files stored on OctoPrint."""
        return self._get(f"files/{location}")

    def delete_file(self, location: str, filename: str) -> None:
        """Delete a file from OctoPrint storage."""
        resp = self._session.delete(
            self._url(f"files/{location}/{filename}"),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        logger.info("Deleted file '%s' from %s.", filename, location)

    # ── Job Control ───────────────────────────────────────────────────────────
    def select_file(self, file_resource_url: str, *, start: bool = False) -> None:
        """
        Select a previously uploaded file for printing.

        Parameters
        ----------
        file_resource_url:
            The ``refs.resource`` URL returned by :meth:`upload_file`.
        start:
            If True, start the print immediately after selecting.
        """
        # Extract location/filename from the resource URL
        # URL shape: http://localhost:5001/api/files/local/myfile.gcode
        parts = file_resource_url.rstrip("/").split("/api/files/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse file resource URL: {file_resource_url}")
        location_and_name = parts[1]  # e.g. "local/myfile.obj"
        endpoint = f"files/{location_and_name}"

        payload = {"command": "select", "print": start}
        self._post(endpoint, json=payload)
        logger.info("File selected%s.", " and print started" if start else "")

    def start_print(self, filename: str) -> bool:
        """
        Issue a start command to the current job.

        Raises
        ------
        RuntimeError
            If the printer is not in the ``Operational`` state (e.g. it is
            already printing, offline, or in an error state).
        """
        # ── Pre-flight: confirm printer is Operational ───────────────────
        try:
            printer_state = self.get_printer_state()
        except Exception as exc:
            raise RuntimeError(
                f"Could not retrieve printer state before starting print: {exc}"
            ) from exc

        # OctoPrint returns state.text for a human-readable description and
        # state.flags.printing / ready / etc. for machine-readable flags.
        state_text: str = (
            printer_state.get("state", {}).get("text", "Unknown")
        )
        flags: dict = printer_state.get("state", {}).get("flags", {})

        is_ready = flags.get("ready", False)
        is_printing = flags.get("printing", False)
        is_error = flags.get("error", False)
        is_closedOrError = flags.get("closedOrError", False)

        logger.debug(
            "Printer state before start_print: text='%s' flags=%s",
            state_text,
            flags,
        )

        if is_printing:
            raise RuntimeError(
                f"Cannot start a new print: printer is already printing "
                f"(state: '{state_text}'). Cancel or wait for the current job to finish."
            )
        if is_error or is_closedOrError:
            raise RuntimeError(
                f"Cannot start print: printer is in an error or disconnected state "
                f"(state: '{state_text}'). Check the OctoPrint UI and resolve the issue first."
            )
        if not is_ready:
            raise RuntimeError(
                f"Cannot start print: printer is not Operational "
                f"(state: '{state_text}'). Expected 'Operational' but got '{state_text}'."
            )

        logger.info("Printer is Operational ✔  Issuing start command…")
        self._post("job", json={"command": "start"})
        logger.info("Print started.")
        return True

    def pause_print(self) -> bool:
        """Pause or resume the current print (action: 'pause' | 'resume' | 'toggle')."""
        self._post("job", json={"command": "pause", "action": "pause"})
        logger.info("Print paused.")
        return True

    def resume_print(self) -> bool:
        self._post("job", json={"command": "pause", "action": "resume"})
        logger.info("Print resumed.")
        return True

    def cancel_print(self) -> bool:
        """Cancel the current print job."""
        self._post("job", json={"command": "cancel"})
        logger.info("Print cancelled.")
        return True

    # ── Job Status ────────────────────────────────────────────────────────────
    def get_job_status(self) -> dict[str, Any]:
        """Return current job information (progress, file, time estimates)."""
        return self._get("job")

    def watch_job(self, poll_interval: int = 10) -> None:
        """
        Block and poll the job status until the print completes or an error occurs.

        Parameters
        ----------
        poll_interval:
            Seconds between status polls.
        """
        logger.info("Watching print job (polling every %ds)…", poll_interval)
        while True:
            status = self.get_job_status()
            state = status.get("state", "Unknown")
            progress = status.get("progress", {})
            completion = progress.get("completion") or 0.0
            time_left = progress.get("printTimeLeft")

            eta = f"{int(time_left // 60)}m {int(time_left % 60)}s" if time_left else "unknown"
            logger.info("State: %-20s  Completion: %5.1f%%  ETA: %s", state, completion, eta)

            if state in ("Finishing", "Operational"):
                logger.info("Print finished ✓")
                break
            if "Error" in state or "Cancell" in state:
                logger.warning("Print ended with state: %s", state)
                break

            time.sleep(poll_interval)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="p2p-mesh Phase 4 — Operator (OctoPrint)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--file", "-f", required=False, metavar="PATH",
                        help="G-code file to upload (.gcode only — run slicer first)")
    parser.add_argument("--url", default="http://localhost:5001", metavar="URL", help="OctoPrint base URL")
    parser.add_argument("--key", metavar="KEY", help="OctoPrint API key (or set OCTOPRINT_API_KEY env var)")
    parser.add_argument("--location", default="local", choices=["local", "sdcard"], help="Storage location")
    parser.add_argument("--start", action="store_true", help="Start print immediately after upload")
    parser.add_argument("--watch", action="store_true", help="Watch and report print progress")
    parser.add_argument("--status", action="store_true", help="Only print current job status and exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate connectivity but do not upload or print")
    parser.add_argument(
        "--connect-port",
        default="VIRTUAL",
        metavar="PORT",
        help="Serial port for printer connection (default: VIRTUAL for local testing). "
             "Use /dev/ttyUSB0 or similar for a real printer.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


if __name__ == "__main__":
    import os

    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    # API key: CLI flag > environment variable
    api_key = args.key or os.environ.get("OCTOPRINT_API_KEY", "")
    if not api_key and not args.dry_run:
        logger.error(
            "No API key provided. Use --key or set the OCTOPRINT_API_KEY environment variable."
        )
        sys.exit(1)

    op = OctoPrintOperator(base_url=args.url, api_key=api_key or "no-key")

    # ── Connectivity check ────────────────────────────────────────────────────
    logger.info("Connecting to OctoPrint at %s…", args.url)
    try:
        version_info = op.get_version()
        logger.info(
            "Connected ✓  OctoPrint %s  (API %s)",
            version_info.get("server", "?"),
            version_info.get("api", "?"),
        )
        connection = op.get_connection()
        logger.info("Printer connection state: %s", connection.get("current", {}).get("state", "?"))
    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach OctoPrint at %s — is the server running?", args.url)
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        logger.error("OctoPrint returned an error: %s", exc)
        sys.exit(1)

    if args.dry_run:
        logger.info("Dry run complete — skipping upload/print.")
        sys.exit(0)

    # ── Status only ───────────────────────────────────────────────────────────
    if args.status:
        status = op.get_job_status()
        logger.info("Job status: %s", status)
        sys.exit(0)

    # ── Ensure printer is connected ────────────────────────────────────────────
    op.ensure_operational(auto_connect_port=args.connect_port)

    # ── Upload ────────────────────────────────────────────────────────────────
    if not args.file:
        logger.error("--file is required unless using --dry-run or --status.")
        sys.exit(1)

    result = op.upload_file(
        file_path=args.file,
        location=args.location,
        select=True,
        start=args.start,
    )
    file_url = result.get("files", {}).get(args.location, {}).get("refs", {}).get("resource", "")
    logger.info("File available at: %s", file_url)

    # ── Watch ─────────────────────────────────────────────────────────────────
    if args.watch and args.start:
        op.watch_job()
