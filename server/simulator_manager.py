"""Manages the dockerized OctoPrint simulator.

The simulator is a real OctoPrint with its virtual-printer plugin enabled, so the
whole dispatch path — upload, select, start, telemetry, failure detection — runs
without hardware. See `data/octoprint/octoprint/config.yaml`.

Two things here are less obvious than they look.

**The Docker connection is established lazily and retried.** The API server
routinely outlives Docker Desktop on a development machine. Building the client
once at import meant a server that started before Docker was up answered
"Docker client not available" for the rest of its life, and restarting the API
server was the only cure. Every call now re-attempts the connection, and the
failure carries a message that says what to do about it.

**Compose is given an explicit project name.** Compose derives the project from
the directory of the first `-f` file, so `docker compose -f infra/docker-compose.yml`
creates `infra-octoprint-simulator-1` — not the `${COMPOSE_PROJECT_NAME}` this
class searches for. The container it created was therefore not the container it
later looked for, and because both publish host port 5001, a second one could
accumulate and then refuse to start. Pinning `-p` keeps creation and lookup on the
same name.
"""

import logging
import os
import subprocess
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: Compose project the simulator container belongs to. Overridable so a deployment
#: that already sets COMPOSE_PROJECT_NAME keeps one consistent namespace.
DEFAULT_COMPOSE_PROJECT = "ds-mvp"

SERVICE_NAME = "octoprint-simulator"
OCTOPRINT_PORT = 5001

#: Sockets to try when the environment does not name one. Docker Desktop for macOS
#: only creates `/var/run/docker.sock` when "Allow the default Docker socket to be
#: used" is enabled; with it off, the CLI works (it reads the context) while the SDK
#: cannot connect at all. Trying the per-user socket covers that case.
_FALLBACK_SOCKETS = (
    "~/.docker/run/docker.sock",
    "/var/run/docker.sock",
    "~/.colima/default/docker.sock",
)


class SimulatorAvailabilityError(RuntimeError):
    """Docker could not be reached, so the simulator's state is unknown.

    Distinct from "the simulator is stopped": the caller should report that it
    cannot tell rather than asserting the container is down.
    """


def _default_client_factory():
    """Connect to Docker, honouring the environment before falling back to sockets."""
    import docker

    errors = []
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001 - any failure means "try the next one"
        errors.append(f"from_env: {exc}")

    # DOCKER_HOST wins if it is set; if it is, from_env already used it and failed,
    # so there is nothing else to try.
    if os.environ.get("DOCKER_HOST"):
        raise RuntimeError("; ".join(errors))

    for candidate in _FALLBACK_SOCKETS:
        path = os.path.expanduser(candidate)
        if not os.path.exists(path):
            continue
        try:
            client = docker.DockerClient(base_url=f"unix://{path}")
            client.ping()
            logger.info("Connected to Docker via %s", path)
            return client
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")

    raise RuntimeError("; ".join(errors) or "no Docker socket found")


class SimulatorManager:
    def __init__(self, client_factory: Optional[Callable[[], Any]] = None):
        self._client_factory = client_factory or _default_client_factory
        self._client: Any = None
        self.compose_project = os.environ.get("COMPOSE_PROJECT_NAME", DEFAULT_COMPOSE_PROJECT)
        self.service_name = SERVICE_NAME

    # ── Connection ───────────────────────────────────────────────────────────

    def require_client(self):
        """Return a live Docker client, connecting or reconnecting as needed.

        Raises:
            SimulatorAvailabilityError: with an actionable message if Docker is
                unreachable. Retried on every call, so the server recovers on its
                own once Docker comes back.
        """
        if self._client is not None:
            return self._client

        try:
            self._client = self._client_factory()
        except Exception as exc:  # noqa: BLE001 - surfaced as one typed error
            self._client = None
            raise SimulatorAvailabilityError(
                "Docker is not reachable, so the OctoPrint simulator cannot be "
                "controlled. Is Docker Desktop running? "
                f"({exc})"
            ) from exc

        return self._client

    def _client_or_none(self):
        try:
            return self.require_client()
        except SimulatorAvailabilityError:
            return None

    # ── Container lookup ─────────────────────────────────────────────────────

    @staticmethod
    def _prefer_running(containers):
        """Pick a running container over a stopped one, else the first available.

        The same service can have several container records at once: compose derives
        its project name from the directory it is invoked in, so running the
        documented command from the repo root and from `infra/` leaves
        `ds-mvp-octoprint-simulator-1` and
        `infra-octoprint-simulator-1` side by side, plus whatever earlier runs left
        behind. `containers.list(all=True)` returns them in no useful order, so taking
        `[0]` reported "stopped" while a working simulator was up on port 5001 — and
        the UI then refused to start a job against a printer that was answering.

        The question this class exists to answer is "is a simulator running", so a
        live container wins over a dead one regardless of which project created it.
        """
        containers = list(containers)
        for container in containers:
            if container.status == "running":
                return container
        return containers[0] if containers else None

    def _get_container(self, client=None):
        client = client or self.require_client()

        filters = {
            "label": [
                f"com.docker.compose.project={self.compose_project}",
                f"com.docker.compose.service={self.service_name}",
            ]
        }
        matched = self._prefer_running(client.containers.list(all=True, filters=filters))
        if matched is not None and matched.status == "running":
            return matched

        # Nothing live under our own project name. Fall back to the service name,
        # which also covers a container created under a different project — and only
        # then settle for whatever stopped record the label filter found.
        by_name = self._prefer_running(
            c for c in client.containers.list(all=True) if self.service_name in c.name
        )
        if by_name is not None and by_name.status == "running":
            return by_name

        return matched or by_name

    # ── Moonraker: deprecated, kept so callers get a truthful answer ──────────

    async def start_moonraker(self, port: int = 7125) -> Dict[str, Any]:
        return {"running": False, "error": "There is no Moonraker simulator in this build."}

    async def stop_moonraker(self) -> Dict[str, Any]:
        return {"running": False}

    # ── OctoPrint ────────────────────────────────────────────────────────────

    async def start_octoprint(self, port: int = OCTOPRINT_PORT) -> Dict[str, Any]:
        client = self.require_client()
        container = self._get_container(client)

        if container is None:
            self._compose_up()
        elif container.status != "running":
            container.start()

        return {
            "running": True,
            "port": port,
            "url": f"http://localhost:{port}",
            "api_key": self.octoprint_api_key(),
        }

    def _compose_up(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        command = [
            "docker", "compose",
            # Without this, compose names the project after infra/ and creates a
            # container this class will not find. See the module docstring.
            "-p", self.compose_project,
            "-f", "infra/docker-compose.yml",
            "--profile", "simulator",
            "up", "-d", self.service_name,
        ]
        try:
            subprocess.run(command, check=True, cwd=project_root, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or str(exc)
            hint = ""
            if "port is already allocated" in detail or "address already in use" in detail:
                hint = (
                    f" Host port {OCTOPRINT_PORT} is already taken — an older simulator "
                    "container from a different compose project may still exist. "
                    f"`docker rm -f $(docker ps -aq --filter name={self.service_name})` "
                    "clears it."
                )
            raise SimulatorAvailabilityError(
                f"Could not start the OctoPrint simulator: {detail}{hint}"
            ) from exc

    async def stop_octoprint(self) -> Dict[str, Any]:
        # Called from the server's shutdown hook, so an unreachable daemon must not
        # raise — there is nothing left to stop in that case anyway.
        client = self._client_or_none()
        if client is None:
            return {"running": False}

        container = self._get_container(client)
        if container is not None and container.status == "running":
            container.stop(timeout=5)

        return {"running": False}

    def octoprint_api_key(self) -> Optional[str]:
        """The simulator's own API key, read from the config it boots with.

        Every authenticated call to the simulator needs this, including the health
        probe: OctoPrint answers an unauthenticated `/api/version` with 403, so a
        probe without the key can never succeed.
        """
        import yaml

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        config_path = os.path.join(project_root, "data", "octoprint", "octoprint", "config.yaml")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r") as handle:
                    config = yaml.safe_load(handle) or {}
                return config.get("api", {}).get("key")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the OctoPrint simulator config: %s", exc)
        return None

    def internal_url(self, host_port: int = OCTOPRINT_PORT) -> Optional[str]:
        """The simulator's address as seen from another container, or None.

        `http://localhost:5001` is the truth for a person's browser and for a native
        process, and it is the value the config store and the telemetry row keep. It
        is not an address any container can use, and the usual translation —
        `host.docker.internal` mapped to the host gateway — only works if the host
        lets a bridge network reach a published port. On Fedora it does not:
        firewalld drops traffic from the docker bridge to the host by default, so the
        name resolves, the connection times out, and the probe reports the simulator
        offline while it is answering perfectly on port 5001.

        The simulator is a container this class already manages, though, and a
        container talking to a container on a shared compose network needs neither
        the host nor the firewall. This returns that address — the compose service
        name and the port the simulator actually listens on inside its own network
        namespace, which is 80, not the 5001 it is published as.

        Args:
            host_port: The published host port to match against, so a URL naming some
                other loopback service is not mistaken for the simulator.

        Returns:
            A URL reachable from this process's network, or None when the simulator
            is not running, publishes no matching port, or shares no network with us.
        """
        client = self._client_or_none()
        if client is None:
            return None

        container = self._get_container(client)
        if container is None or container.status != "running":
            return None

        settings = (container.attrs or {}).get("NetworkSettings", {})

        private_port = None
        for spec, bindings in (settings.get("Ports") or {}).items():
            for binding in bindings or []:
                if str(binding.get("HostPort")) == str(host_port):
                    private_port = spec.split("/")[0]
                    break
            if private_port:
                break
        if private_port is None:
            return None

        their_networks = set((settings.get("Networks") or {}).keys())
        if not their_networks & self._own_networks(client):
            # No shared network, so the service name would not resolve. Say so with
            # None rather than handing back an address that fails at connect time.
            return None

        port_suffix = "" if private_port in ("80", 80) else f":{private_port}"
        return f"http://{self.service_name}{port_suffix}"

    def _own_networks(self, client) -> set:
        """The docker networks this process's own container is attached to.

        Empty when this process is not containerised, or when its container cannot be
        identified — in which case `internal_url` declines rather than guessing.
        """
        import socket

        try:
            return set(
                (client.containers.get(socket.gethostname()).attrs or {})
                .get("NetworkSettings", {})
                .get("Networks", {})
                .keys()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not identify this container's networks: %s", exc)
            return set()

    def get_status(self) -> Dict[str, Any]:
        """Report simulator state, distinguishing "stopped" from "cannot tell"."""
        available = True
        error: Optional[str] = None
        running = False

        try:
            container = self._get_container()
            running = container is not None and container.status == "running"
        except SimulatorAvailabilityError as exc:
            available = False
            error = str(exc)

        return {
            "moonraker": {"running": False, "port": None, "url": None},
            "octoprint": {
                "running": running,
                "available": available,
                "error": error,
                "port": OCTOPRINT_PORT if running else None,
                "url": f"http://localhost:{OCTOPRINT_PORT}" if running else None,
                "api_key": self.octoprint_api_key() if running else None,
            },
        }


simulator_manager = SimulatorManager()
