"""Operator implementation for Moonraker/Klipper printers."""

import argparse
import json
import logging
import requests
from requests.exceptions import RequestException, ConnectionError

from pythonsrc.operators.base import BasePrinterOperator, PrinterConnectionError

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MoonrakerOperator(BasePrinterOperator):
    """Operator for interfacing with Moonraker (Klipper) 3D printers via REST API.

    This class provides methods to upload files, control print jobs, and retrieve
    printer state information from a Moonraker instance.
    """

    def __init__(self, base_url: str, api_key: str | None = None):
        """Initialize the MoonrakerOperator.

        Args:
            base_url: The base URL of the Moonraker instance (e.g., http://mainsail.local).
            api_key: Optional API key for authentication.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = 10
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Perform an HTTP request to the Moonraker API with automatic retries.

        Args:
            method: The HTTP method (e.g., "GET", "POST").
            endpoint: The API endpoint path.
            **kwargs: Additional keyword arguments to pass to requests.request.

        Returns:
            The HTTP response object.

        Raises:
            PrinterConnectionError: If the request fails after retrying.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug(f"Making {method} request to {url}")
        
        kwargs.setdefault('timeout', self.timeout)
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except ConnectionError as e:
            logger.debug(f"Connection error: {e}. Retrying once.")
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except RequestException as retry_e:
                logger.debug(f"Retry failed: {retry_e}")
                raise PrinterConnectionError(f"Failed to connect to {url}: {retry_e}") from retry_e
        except RequestException as e:
            logger.debug(f"Request failed: {e}")
            raise PrinterConnectionError(f"Request failed to {url}: {e}") from e

    def connect(self) -> bool:
        """Verify the connection to the Moonraker server.

        Returns:
            True if the connection is successful, False otherwise.
        """
        try:
            self._request("GET", "/printer/info")
            return True
        except PrinterConnectionError:
            return False

    def upload_file(self, local_path: str, remote_name: str) -> bool:
        """Upload a G-code file to the printer.

        Args:
            local_path: The local filesystem path to the G-code file.
            remote_name: The target filename on the printer.

        Returns:
            True if the upload is successful.

        Raises:
            FileNotFoundError: If the local file does not exist.
            PrinterConnectionError: If the upload fails due to an API error.
        """
        import os
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")
        try:
            with open(local_path, "rb") as f:
                files = {"file": (remote_name, f)}
                data = {"root": "gcodes"}
                self._request("POST", "/server/files/upload", files=files, data=data)
                return True
        except IOError as e:
            logger.debug(f"Failed to read file {local_path}: {e}")
            raise PrinterConnectionError(f"Failed to read file: {e}") from e
        except PrinterConnectionError:
            raise

    def start_print(self, filename: str) -> bool:
        """Start printing an uploaded file.

        Args:
            filename: The name of the file on the printer to print.

        Returns:
            True if the print was successfully started, False otherwise.
        """
        try:
            # Moonraker might return 200 OK with an error in the JSON body, or a 4xx status.
            # Catch exceptions from _request, and also inspect the JSON if it succeeded.
            response = self._request("POST", "/printer/print/start", json={"filename": filename})
            data = response.json() if response.content else {}
            if "error" in data:
                return False
            return True
        except PrinterConnectionError:
            return False

    def cancel_print(self) -> bool:
        """Cancel the currently active print job.

        Returns:
            True if the print was successfully cancelled.

        Raises:
            PrinterConnectionError: If the API request fails.
        """
        try:
            self._request("POST", "/printer/print/cancel")
            return True
        except PrinterConnectionError:
            raise

    def pause_print(self) -> bool:
        """Pause the currently active print job.

        Returns:
            True if the print was successfully paused.

        Raises:
            PrinterConnectionError: If the API request fails.
        """
        try:
            self._request("POST", "/printer/print/pause")
            return True
        except PrinterConnectionError:
            raise

    def resume_print(self) -> bool:
        """Resume a paused print job.

        Returns:
            True if the print was successfully resumed.

        Raises:
            PrinterConnectionError: If the API request fails.
        """
        try:
            self._request("POST", "/printer/print/resume")
            return True
        except PrinterConnectionError:
            raise

    def get_printer_state(self) -> dict:
        """Retrieve the current state of the printer.

        Returns:
            A dictionary containing parsed printer state details such as state, 
            z_height, temperatures, and progress.

        Raises:
            PrinterConnectionError: If the API request or parsing fails.
        """
        try:
            response = self._request("GET", "/printer/objects/query?print_stats&toolhead&heater_bed&extruder")
            data = response.json()
            
            result = data.get("result", {})
            status = result.get("status", {})
            
            print_stats = status.get("print_stats", {})
            toolhead = status.get("toolhead", {})
            heater_bed = status.get("heater_bed", {})
            extruder = status.get("extruder", {})
            
            z_height = None
            position = toolhead.get("position")
            if position and len(position) >= 3:
                z_height = position[2]

            return {
                "state": print_stats.get("state"),
                "z_height": z_height,
                "hotend_actual": extruder.get("temperature"),
                "hotend_target": extruder.get("target"),
                "bed_actual": heater_bed.get("temperature"),
                "bed_target": heater_bed.get("target"),
                "gcode_file": print_stats.get("filename"),
                "progress": print_stats.get("info", {}).get("progress")
            }
        except PrinterConnectionError:
            raise
        except Exception as e:
            logger.debug(f"Failed to parse printer state: {e}")
            raise PrinterConnectionError(f"Failed to parse printer state: {e}") from e

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Moonraker Operator")
    parser.add_argument("--url", required=True, help="Moonraker base URL")
    parser.add_argument("--probe", action="store_true", help="Probe printer state and print JSON")
    args = parser.parse_args()

    operator = MoonrakerOperator(base_url=args.url)
    if args.probe:
        try:
            state = operator.get_printer_state()
            print(json.dumps(state, indent=2))
        except PrinterConnectionError as e:
            print(json.dumps({"error": str(e)}))
