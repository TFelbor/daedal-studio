"""
operator_phase.py — Phase 4: OctoPrint REST API integration.

Uploads a print-ready mesh file to an OctoPrint instance and optionally
starts the print job. Can also poll for job status.

Usage:
    python pythonsrc/operator_phase.py --file outputs/engineered_mesh.obj \\
        --url http://octopi.local --key MY_API_KEY [--start] [--watch] [--dry-run]
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
class OctoPrintOperator:
    """
    Thin wrapper around the OctoPrint REST API.

    Reference: https://docs.octoprint.org/en/master/api/

    Parameters
    ----------
    base_url:
        Base URL of the OctoPrint instance, e.g. ``http://octopi.local``
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

    def get_printer_state(self) -> dict[str, Any]:
        """Return current printer state (temperature, operational status, etc.)."""
        return self._get("printer")

    def get_connection(self) -> dict[str, Any]:
        """Return serial connection state."""
        return self._get("connection")

    # ── File Management ───────────────────────────────────────────────────────
    def upload_file(
        self,
        file_path: str | Path,
        *,
        location: str = "local",
        select: bool = False,
        start: bool = False,
    ) -> dict[str, Any]:
        """
        Upload a mesh file to OctoPrint.

        Parameters
        ----------
        file_path:
            Local path to the ``.obj`` / ``.stl`` / ``.gcode`` file.
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
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("Uploading '%s' to OctoPrint (%s)…", file_path.name, location)

        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh, "application/octet-stream")}
            data = {"select": str(select).lower(), "print": str(start).lower()}
            resp = self._session.post(
                self._url(f"files/{location}"),
                files=files,
                data=data,
                timeout=max(self.timeout, 120),  # uploads can be slow
            )
            resp.raise_for_status()
            result = resp.json()

        logger.info("Upload complete — %s", result.get("done", ""))
        logger.debug("Upload response: %s", result)
        return result

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
        # URL shape: http://octopi.local/api/files/local/myfile.obj
        parts = file_resource_url.rstrip("/").split("/api/files/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse file resource URL: {file_resource_url}")
        location_and_name = parts[1]  # e.g. "local/myfile.obj"
        endpoint = f"files/{location_and_name}"

        payload = {"command": "select", "print": start}
        self._post(endpoint, json=payload)
        logger.info("File selected%s.", " and print started" if start else "")

    def start_print(self) -> None:
        """Issue a start command to the current job."""
        self._post("job", json={"command": "start"})
        logger.info("Print started.")

    def pause_print(self, action: str = "pause") -> None:
        """Pause or resume the current print (action: 'pause' | 'resume' | 'toggle')."""
        self._post("job", json={"command": "pause", "action": action})
        logger.info("Print %sd.", action)

    def cancel_print(self) -> None:
        """Cancel the current print job."""
        self._post("job", json={"command": "cancel"})
        logger.info("Print cancelled.")

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
    parser.add_argument("--file", "-f", required=False, metavar="PATH", help="Mesh file to upload")
    parser.add_argument("--url", default="http://octopi.local", metavar="URL", help="OctoPrint base URL")
    parser.add_argument("--key", metavar="KEY", help="OctoPrint API key (or set OCTOPRINT_API_KEY env var)")
    parser.add_argument("--location", default="local", choices=["local", "sdcard"], help="Storage location")
    parser.add_argument("--start", action="store_true", help="Start print immediately after upload")
    parser.add_argument("--watch", action="store_true", help="Watch and report print progress")
    parser.add_argument("--status", action="store_true", help="Only print current job status and exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate connectivity but do not upload or print")
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
