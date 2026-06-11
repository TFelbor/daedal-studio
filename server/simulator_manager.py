import asyncio
import sys
import os
import signal
from pathlib import Path
from typing import Dict, Any

class SimulatorManager:
    def __init__(self):
        self.moonraker_process: asyncio.subprocess.Process | None = None
        self.moonraker_port: int | None = None
        self._moonraker_log_fh = None
        self.octoprint_process: asyncio.subprocess.Process | None = None
        self.octoprint_port: int | None = None
        self._octoprint_log_fh = None

    def _get_log_file(self, simulator_name: str) -> Path:
        repo_root = Path(__file__).parent.parent
        log_dir = repo_root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{simulator_name}_mock.log"

    async def start_moonraker(self, port: int = 7125) -> Dict[str, Any]:
        if self.moonraker_process and self.moonraker_process.returncode is None:
            return {"running": True, "port": self.moonraker_port, "url": f"http://localhost:{self.moonraker_port}"}

        repo_root = Path(__file__).parent.parent
        mock_script = repo_root / "tests" / "mocks" / "moonraker_mock.py"

        log_file = self._get_log_file("moonraker")
        self._moonraker_log_fh = open(log_file, "w")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self.moonraker_process = await asyncio.create_subprocess_exec(
            sys.executable, str(mock_script), "--port", str(port),
            stdout=self._moonraker_log_fh,
            stderr=self._moonraker_log_fh,
            cwd=repo_root,
            env=env
        )
        self.moonraker_port = port

        if self.moonraker_process.returncode is not None:
            raise RuntimeError(
                f"Moonraker mock failed to start (exit code {self.moonraker_process.returncode})"
            )

        return {"running": True, "port": port, "url": f"http://localhost:{port}"}

    async def start_octoprint(self, port: int = 5001) -> Dict[str, Any]:
        if self.octoprint_process and self.octoprint_process.returncode is None:
            return {"running": True, "port": self.octoprint_port, "url": f"http://localhost:{self.octoprint_port}"}

        repo_root = Path(__file__).parent.parent
        mock_script = repo_root / "tests" / "mocks" / "octoprint_mock.py"

        log_file = self._get_log_file("octoprint")
        self._octoprint_log_fh = open(log_file, "w")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self.octoprint_process = await asyncio.create_subprocess_exec(
            sys.executable, str(mock_script), "--port", str(port),
            stdout=self._octoprint_log_fh,
            stderr=self._octoprint_log_fh,
            cwd=repo_root,
            env=env
        )
        self.octoprint_port = port

        if self.octoprint_process.returncode is not None:
            raise RuntimeError(
                f"OctoPrint mock failed to start (exit code {self.octoprint_process.returncode})"
            )

        return {"running": True, "port": port, "url": f"http://localhost:{port}"}

    async def stop_moonraker(self) -> Dict[str, Any]:
        if self.moonraker_process and self.moonraker_process.returncode is None:
            self.moonraker_process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.moonraker_process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.moonraker_process.kill()
                await self.moonraker_process.wait()

        self.moonraker_process = None
        self.moonraker_port = None
        if self._moonraker_log_fh:
            self._moonraker_log_fh.close()
            self._moonraker_log_fh = None
        return {"running": False}

    async def stop_octoprint(self) -> Dict[str, Any]:
        if self.octoprint_process and self.octoprint_process.returncode is None:
            self.octoprint_process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.octoprint_process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.octoprint_process.kill()
                await self.octoprint_process.wait()

        self.octoprint_process = None
        self.octoprint_port = None
        if self._octoprint_log_fh:
            self._octoprint_log_fh.close()
            self._octoprint_log_fh = None
        return {"running": False}

    def get_status(self) -> Dict[str, Any]:
        moonraker_running = self.moonraker_process is not None and self.moonraker_process.returncode is None
        octoprint_running = self.octoprint_process is not None and self.octoprint_process.returncode is None
        return {
            "moonraker": {
                "running": moonraker_running,
                "port": self.moonraker_port if moonraker_running else None,
                "url": f"http://localhost:{self.moonraker_port}" if moonraker_running else None
            },
            "octoprint": {
                "running": octoprint_running,
                "port": self.octoprint_port if octoprint_running else None,
                "url": f"http://localhost:{self.octoprint_port}" if octoprint_running else None
            }
        }

simulator_manager = SimulatorManager()