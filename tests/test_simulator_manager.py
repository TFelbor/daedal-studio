"""Tests for the OctoPrint simulator manager.

These never touch a real Docker daemon: every test injects a fake client factory,
because the behaviour under test is precisely what happens when Docker is *not*
reachable, and a test that needed Docker could not check that.
"""

import builtins

import pytest

from server.simulator_manager import SimulatorAvailabilityError, SimulatorManager


class FakeContainer:
    def __init__(self, name="ds-mvp-octoprint-simulator-1", status="exited", labels=None):
        self.name = name
        self.status = status
        self.labels = labels or {}
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        self.status = "running"

    def stop(self, timeout=None):
        self.stopped = True
        self.status = "exited"


class FakeContainers:
    def __init__(self, containers):
        self._containers = containers

    # The docker SDK really does name this parameter `all`, which shadows the
    # builtin — hence `builtins.all` below.
    def list(self, all=False, filters=None):  # noqa: A002 - mirrors the docker SDK
        if not filters:
            return list(self._containers)
        wanted = dict(part.split("=", 1) for part in filters.get("label", []))
        return [
            c for c in self._containers
            if builtins.all(c.labels.get(k) == v for k, v in wanted.items())
        ]


class FakeClient:
    def __init__(self, containers=()):
        self.containers = FakeContainers(list(containers))

    def ping(self):
        return True


def manager_with(factory):
    return SimulatorManager(client_factory=factory)


# ── The reported failure: a one-shot client that never recovered ──────────────


def test_docker_connection_is_retried_after_an_early_failure():
    """The server outlives Docker Desktop, so a failed connect must not be permanent.

    This is the reported bug: the manager was constructed at import, so a server
    started before Docker was up answered `Docker client not available` for the rest
    of its life — restarting the API server was the only way to recover.
    """
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Cannot connect to the Docker daemon")
        return FakeClient([FakeContainer()])

    manager = manager_with(factory)

    with pytest.raises(SimulatorAvailabilityError):
        manager.require_client()

    # Docker came up in the meantime; no restart should be needed.
    assert manager.require_client() is not None
    assert len(attempts) == 2


def test_unreachable_docker_raises_an_actionable_error():
    def factory():
        raise RuntimeError("connection refused")

    manager = manager_with(factory)
    with pytest.raises(SimulatorAvailabilityError) as excinfo:
        manager.require_client()

    message = str(excinfo.value)
    assert "Docker" in message
    # The message has to say what to do about it, not just what failed.
    assert "Desktop" in message or "running" in message


@pytest.mark.asyncio
async def test_start_reports_unavailable_docker_rather_than_a_bare_runtime_error():
    def factory():
        raise RuntimeError("no socket")

    manager = manager_with(factory)
    with pytest.raises(SimulatorAvailabilityError):
        await manager.start_octoprint()


def test_status_says_why_it_cannot_see_the_simulator():
    """Reporting `running: False` when the truth is "we cannot tell" is a lie.

    The Settings page renders this verbatim, so an unreachable daemon has to be
    distinguishable from a stopped container.
    """
    def factory():
        raise RuntimeError("no socket")

    status = manager_with(factory).get_status()
    assert status["octoprint"]["running"] is False
    assert status["octoprint"]["available"] is False
    assert status["octoprint"]["error"]


def test_status_is_available_when_docker_answers():
    running = FakeContainer(status="running")
    status = manager_with(lambda: FakeClient([running])).get_status()
    assert status["octoprint"]["available"] is True
    assert status["octoprint"]["running"] is True
    assert status["octoprint"]["error"] is None


# ── The compose project the lookup searches for must be the one it creates ────


@pytest.mark.asyncio
async def test_compose_up_pins_the_project_the_lookup_searches_for(monkeypatch):
    """Compose derives its project name from the compose file's directory.

    `docker compose -f infra/docker-compose.yml up` therefore creates
    `infra-octoprint-simulator-1`, while the manager searched for project
    `ds-mvp` — so the container it created was not the container it
    later looked for, and a second one could accumulate on the same host port.
    """
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return None

    manager = manager_with(lambda: FakeClient([]))  # no container yet
    monkeypatch.setattr("subprocess.run", fake_run)

    await manager.start_octoprint()

    cmd = recorded["cmd"]
    assert "-p" in cmd, "compose must be given an explicit project name"
    assert cmd[cmd.index("-p") + 1] == manager.compose_project


@pytest.mark.asyncio
async def test_an_existing_container_is_started_not_recreated(monkeypatch):
    container = FakeContainer(
        status="exited",
        labels={
            "com.docker.compose.project": "ds-mvp",
            "com.docker.compose.service": "octoprint-simulator",
        },
    )
    manager = manager_with(lambda: FakeClient([container]))

    def explode(*args, **kwargs):
        raise AssertionError("compose must not run when the container already exists")

    monkeypatch.setattr("subprocess.run", explode)

    await manager.start_octoprint()
    assert container.started is True


@pytest.mark.asyncio
async def test_stop_is_a_no_op_when_docker_is_unreachable():
    """Shutdown runs this; it must not raise and take the whole server down with it."""
    def factory():
        raise RuntimeError("no socket")

    result = await manager_with(factory).stop_octoprint()
    assert result["running"] is False


# ── The endpoint the Settings button calls ────────────────────────────────────


def test_start_endpoint_reports_503_when_docker_is_down(monkeypatch):
    """The reported failure, from the outside.

    `POST /simulators/octoprint/start` answered 500 with a bare
    `RuntimeError: Docker client not available`, which reads as a server bug rather
    than "start Docker Desktop". It must be a 503 carrying the reason.
    """
    from fastapi.testclient import TestClient

    from server import app as app_module

    async def unavailable(*args, **kwargs):
        raise SimulatorAvailabilityError(
            "Docker is not reachable, so the OctoPrint simulator cannot be "
            "controlled. Is Docker Desktop running?"
        )

    monkeypatch.setattr(app_module.simulator_manager, "start_octoprint", unavailable)

    with TestClient(app_module.app) as client:
        response = client.post("/simulators/octoprint/start")

    assert response.status_code == 503
    assert "Docker" in response.json()["detail"]
