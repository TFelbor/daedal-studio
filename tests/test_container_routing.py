"""How a loopback printer URL is translated when the server is containerised.

`http://localhost:5001` is the address a person types into Printer Setup, the
address their browser opens, and the address the telemetry row keeps — it is what
distinguishes a simulator print from real hardware. From inside the api-server
container it is also the address of the api-server itself, so every probe answered
"All connection attempts failed" while the simulator was Operational on port 5001.

Two things are asserted here and neither is obvious:

* the configured URL is never mutated, only the outbound connection is translated;
* the compose network is preferred over `host.docker.internal`, because the host
  gateway route depends on the host firewall allowing a bridge to reach a published
  port, and on Fedora firewalld does not.
"""

import builtins

import pytest

import server.app as app_module
from server.app import container_reachable_url
from server.simulator_manager import SimulatorManager


class FakeContainer:
    def __init__(self, name, status="running", labels=None, ports=None, networks=None):
        self.name = name
        self.status = status
        self.labels = labels or {}
        self.attrs = {
            "NetworkSettings": {
                "Ports": ports if ports is not None else {},
                "Networks": {n: {} for n in (networks or [])},
            }
        }


class FakeContainers:
    def __init__(self, containers):
        self._containers = list(containers)

    def list(self, all=False, filters=None):  # noqa: A002 - mirrors the docker SDK
        if not filters:
            return list(self._containers)
        wanted = dict(part.split("=", 1) for part in filters.get("label", []))
        return [
            c for c in self._containers
            if builtins.all(c.labels.get(k) == v for k, v in wanted.items())
        ]

    def get(self, name):
        for c in self._containers:
            if c.name == name:
                return c
        raise KeyError(name)


class FakeClient:
    def __init__(self, containers=()):
        self.containers = FakeContainers(containers)

    def ping(self):
        return True


SIM_LABELS = {
    "com.docker.compose.project": "ds-mvp",
    "com.docker.compose.service": "octoprint-simulator",
}


def _simulator(ports=None, networks=("infra_default",)):
    return FakeContainer(
        "infra-octoprint-simulator-1",
        labels=SIM_LABELS,
        # Published as 5001 on the host, listening on 80 inside its own namespace —
        # the distinction the route has to get right.
        ports=ports if ports is not None else {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5001"}]},
        networks=networks,
    )


def _server(networks=("infra_default",)):
    return FakeContainer("infra-api-server-1", networks=networks)


def _manager(containers, hostname="infra-api-server-1", monkeypatch=None):
    manager = SimulatorManager(client_factory=lambda: FakeClient(containers))
    if monkeypatch is not None:
        monkeypatch.setattr("socket.gethostname", lambda: hostname)
    return manager


# ── SimulatorManager.internal_url ────────────────────────────────────────────

def test_internal_url_names_the_service_and_its_own_port(monkeypatch):
    manager = _manager([_simulator(), _server()], monkeypatch=monkeypatch)
    # Port 80 is elided rather than written out, so the URL is the one a person
    # reading a log would recognise.
    assert manager.internal_url(5001) == "http://octoprint-simulator"


def test_internal_url_carries_a_non_default_internal_port(monkeypatch):
    sim = _simulator(ports={"5000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5001"}]})
    manager = _manager([sim, _server()], monkeypatch=monkeypatch)
    assert manager.internal_url(5001) == "http://octoprint-simulator:5000"


def test_internal_url_declines_without_a_shared_network(monkeypatch):
    """No shared network means the service name does not resolve.

    Answering with it anyway would move the failure from here — where it can be
    reported — to a connect that times out five seconds later.
    """
    manager = _manager(
        [_simulator(networks=("infra_default",)), _server(networks=("something_else",))],
        monkeypatch=monkeypatch,
    )
    assert manager.internal_url(5001) is None


def test_internal_url_declines_when_the_port_is_not_the_simulators(monkeypatch):
    """A loopback URL naming some other service must not be routed to the simulator."""
    manager = _manager([_simulator(), _server()], monkeypatch=monkeypatch)
    assert manager.internal_url(7125) is None


def test_internal_url_declines_when_the_simulator_is_stopped(monkeypatch):
    sim = _simulator()
    sim.status = "exited"
    manager = _manager([sim, _server()], monkeypatch=monkeypatch)
    assert manager.internal_url(5001) is None


def test_internal_url_declines_when_this_process_is_not_a_container(monkeypatch):
    """`gethostname` names no container, so there is no network to compare against."""
    manager = _manager([_simulator()], hostname="some-laptop", monkeypatch=monkeypatch)
    assert manager.internal_url(5001) is None


# ── SimulatorManager.own_internal_url ────────────────────────────────────────
#
# The mirror image: the container being addressed is the one this code runs in, and
# the caller is the pipeline container the server is about to start.

API_LABELS = {
    "com.docker.compose.project": "ds-mvp",
    "com.docker.compose.service": "api-server",
}


def _labelled_server(labels=None, ports=None, networks=("ds-mvp_default",)):
    return FakeContainer(
        "ds-mvp-api-server-1",
        labels=API_LABELS if labels is None else labels,
        ports=ports if ports is not None else {
            # Published on loopback by `${DS_API_BIND:-127.0.0.1}:8000:8000`.
            "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}],
        },
        networks=networks,
    )


def _own(container, monkeypatch):
    manager = SimulatorManager(client_factory=lambda: FakeClient([container]))
    monkeypatch.setattr("socket.gethostname", lambda: container.name)
    return manager


def test_own_internal_url_names_this_service_and_its_own_port(monkeypatch):
    manager = _own(_labelled_server(), monkeypatch)
    assert manager.own_internal_url(8000, "ds-mvp") == "http://api-server:8000"


def test_own_internal_url_carries_the_container_side_port(monkeypatch):
    """The published number is not the number the container listens on."""
    server = _labelled_server(
        ports={"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]},
    )
    manager = _own(server, monkeypatch)
    assert manager.own_internal_url(18000, "ds-mvp") == "http://api-server:8000"


def test_own_internal_url_declines_across_compose_projects(monkeypatch):
    """Two projects are two default networks, and this really happens.

    Compose names a project after the directory of its first `-f` file, so an
    api-server brought up from `infra/` is in project `infra` while the pipeline it
    launches — carrying `COMPOSE_PROJECT_NAME=ds-mvp` — is in `ds-mvp`. The service
    name does not resolve across them, so the caller must fall back rather than be
    handed an address that fails at connect time.
    """
    manager = _own(
        _labelled_server(
            labels={**API_LABELS, "com.docker.compose.project": "infra"},
            networks=("infra_default",),
        ),
        monkeypatch,
    )
    assert manager.own_internal_url(8000, "ds-mvp") is None


def test_own_internal_url_declines_without_a_compose_service_name(monkeypatch):
    """A container started by hand has no service name to be reached by."""
    manager = _own(_labelled_server(labels={}), monkeypatch)
    assert manager.own_internal_url(8000, "ds-mvp") is None


def test_own_internal_url_declines_when_the_port_is_not_published(monkeypatch):
    """Without a binding there is no pairing, and the container port is a guess."""
    manager = _own(_labelled_server(ports={}), monkeypatch)
    assert manager.own_internal_url(8000, "ds-mvp") is None


def test_own_internal_url_declines_with_no_network(monkeypatch):
    manager = _own(_labelled_server(networks=()), monkeypatch)
    assert manager.own_internal_url(8000, "ds-mvp") is None


def test_own_internal_url_declines_when_this_process_is_not_a_container(monkeypatch):
    """`gethostname` names no container, so there is nothing to describe."""
    manager = SimulatorManager(client_factory=lambda: FakeClient([_labelled_server()]))
    monkeypatch.setattr("socket.gethostname", lambda: "some-laptop")
    assert manager.own_internal_url(8000, "ds-mvp") is None


# ── container_reachable_url ──────────────────────────────────────────────────

@pytest.fixture
def containerised(monkeypatch):
    monkeypatch.setattr(app_module.os.path, "exists", lambda p: p == "/.dockerenv")


def test_a_native_process_translates_nothing(monkeypatch):
    monkeypatch.setattr(app_module.os.path, "exists", lambda p: False)
    assert container_reachable_url("http://localhost:5001") == "http://localhost:5001"


def test_a_routable_address_is_left_alone(containerised):
    """A real printer on the LAN means the same thing from either side."""
    assert container_reachable_url("http://192.168.1.100:5001") == "http://192.168.1.100:5001"


def test_none_survives(containerised):
    assert container_reachable_url(None) is None


def test_the_compose_network_is_preferred_over_the_host_gateway(containerised, monkeypatch):
    monkeypatch.setattr(
        app_module.simulator_manager, "internal_url", lambda port: "http://octoprint-simulator"
    )
    assert container_reachable_url("http://localhost:5001") == "http://octoprint-simulator"


def test_the_host_gateway_is_the_fallback(containerised, monkeypatch):
    """Nothing container-local to route to, so translate the loopback name."""
    monkeypatch.setattr(app_module.simulator_manager, "internal_url", lambda port: None)
    assert container_reachable_url("http://127.0.0.1:7125") == "http://host.docker.internal:7125"


def test_a_docker_lookup_failure_never_breaks_a_dispatch(containerised, monkeypatch):
    """The route is an optimisation; losing it must not lose the connection."""
    def boom(port):
        raise RuntimeError("docker daemon went away")

    monkeypatch.setattr(app_module.simulator_manager, "internal_url", boom)
    assert container_reachable_url("http://localhost:5001") == "http://host.docker.internal:5001"
