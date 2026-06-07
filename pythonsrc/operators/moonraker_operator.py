import argparse
import json
import logging
import requests
from requests.exceptions import RequestException, ConnectionError

from pythonsrc.operators.base import BasePrinterOperator, PrinterConnectionError

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MoonrakerOperator(BasePrinterOperator):
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = 10
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
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
        try:
            self._request("GET", "/printer/info")
            return True
        except PrinterConnectionError:
            raise

    def upload_file(self, local_path: str, remote_name: str) -> bool:
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
        try:
            self._request("POST", "/printer/print/start", json={"filename": filename})
            return True
        except PrinterConnectionError:
            raise

    def cancel_print(self) -> bool:
        try:
            self._request("POST", "/printer/print/cancel")
            return True
        except PrinterConnectionError:
            raise

    def pause_print(self) -> bool:
        try:
            self._request("POST", "/printer/print/pause")
            return True
        except PrinterConnectionError:
            raise

    def resume_print(self) -> bool:
        try:
            self._request("POST", "/printer/print/resume")
            return True
        except PrinterConnectionError:
            raise

    def get_printer_state(self) -> dict:
        try:
            response = self._request("GET", "/printer/objects/query?print_stats&toolhead&heater_bed&extruder")
            data = response.json()
            
            result = data.get("result", {})
            status = result.get("status", {})
            
            print_stats = status.get("print_stats", {})
            toolhead = status.get("toolhead", {})
            heater_bed = status.get("heater_bed", {})
            extruder = status.get("extruder", {})
            
            z_height = 0.0
            position = toolhead.get("position", [])
            if len(position) >= 3:
                z_height = position[2]

            return {
                "state": print_stats.get("state", ""),
                "z_height": z_height,
                "hotend_actual": extruder.get("temperature", 0.0),
                "hotend_target": extruder.get("target", 0.0),
                "bed_actual": heater_bed.get("temperature", 0.0),
                "bed_target": heater_bed.get("target", 0.0),
                "gcode_file": print_stats.get("filename", ""),
                "progress": print_stats.get("info", {}).get("progress", 0.0) # generic fallback, though standard moonraker places this in display_status
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
