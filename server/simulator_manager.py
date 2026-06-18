import os
import docker
from typing import Dict, Any

class SimulatorManager:
    def __init__(self):
        try:
            self.client = docker.from_env()
        except Exception as e:
            print(f"Warning: Could not initialize Docker client: {e}")
            self.client = None

        self.compose_project = os.environ.get("COMPOSE_PROJECT_NAME", "p2p-mesh-poc-docker")
        self.service_name = "octoprint-simulator"

    def _get_container(self):
        if not self.client:
            return None
        
        # Match by compose labels
        filters = {
            "label": [
                f"com.docker.compose.project={self.compose_project}",
                f"com.docker.compose.service={self.service_name}"
            ]
        }
        containers = self.client.containers.list(all=True, filters=filters)
        if containers:
            return containers[0]
            
        # Fallback by name
        for c in self.client.containers.list(all=True):
            if self.service_name in c.name:
                return c
                
        return None

    async def start_moonraker(self, port: int = 7125) -> Dict[str, Any]:
        return {"running": False, "error": "Moonraker simulator deprecated"}

    async def stop_moonraker(self) -> Dict[str, Any]:
        return {"running": False}

    async def start_octoprint(self, port: int = 5001) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Docker client not available. Cannot start simulator.")
            
        container = self._get_container()
        if not container:
            # Container doesn't exist yet, we must create and start it via docker compose
            import subprocess
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            try:
                subprocess.run(
                    ["docker", "compose", "-f", "infra/docker-compose.yml", "--profile", "simulator", "up", "-d", "octoprint-simulator"],
                    check=True,
                    cwd=project_root
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to create and start OctoPrint simulator container: {e}")
        elif container.status != "running":
            container.start()
            
        return {"running": True, "port": port, "url": f"http://localhost:{port}"}

    async def stop_octoprint(self) -> Dict[str, Any]:
        if not self.client:
            return {"running": False}
            
        container = self._get_container()
        if container and container.status == "running":
            container.stop(timeout=5)
            
        return {"running": False}

    def _get_octoprint_api_key(self) -> str | None:
        import yaml
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        config_path = os.path.join(project_root, "data", "octoprint", "octoprint", "config.yaml")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                return config.get("api", {}).get("key")
        except Exception as e:
            print(f"Warning: Could not read OctoPrint simulator config: {e}")
        return None

    def get_status(self) -> Dict[str, Any]:
        octo_running = False
        port = 5001
        
        if self.client:
            container = self._get_container()
            if container and container.status == "running":
                octo_running = True
                
        return {
            "moonraker": {
                "running": False,
                "port": None,
                "url": None
            },
            "octoprint": {
                "running": octo_running,
                "port": port if octo_running else None,
                "url": f"http://localhost:{port}" if octo_running else None,
                "api_key": self._get_octoprint_api_key() if octo_running else None
            }
        }

simulator_manager = SimulatorManager()