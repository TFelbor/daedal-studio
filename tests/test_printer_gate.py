"""A printer must be *reachable* before a job may start, not merely configured.

`printer_status` used to answer `running: True` for any profile file that existed,
without opening a connection. A profile pointing at a switched-off printer therefore
reported ready, the pipeline view opened, and the failure surfaced four phases later
at dispatch — after Phase 2 had already been paid for on the hosted backend.

`SimulatorManager._get_container` had a second, independent version of the same lie:
compose derives its project name from the directory it runs in, so the same service
accumulates container records under several project names. Listing them and taking
`[0]` reported "stopped" while a working simulator answered on port 5001.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server.app as app_module
from server.app import app
from server.simulator_manager import SimulatorManager

client = TestClient(app)


class _FakeContainer(SimpleNamespace):
    pass


def _container(name: str, status: str) -> _FakeContainer:
    return _FakeContainer(name=name, status=status, labels={})


class _FakeContainers:
    def __init__(self, containers, labelled=None):
        self._all = containers
        self._labelled = labelled if labelled is not None else containers

    def list(self, all=False, filters=None):  # noqa: A002 - docker SDK's own signature
        return list(self._labelled) if filters else list(self._all)


class _FakeClient:
    def __init__(self, containers, labelled=None):
        self.containers = _FakeContainers(containers, labelled)


# ── Container discovery ───────────────────────────────────────────────────────

def test_a_running_container_wins_over_a_stale_stopped_one():
    """The exact shape that broke it: two projects, one alive."""
    stopped = _container("p2p-mesh-poc-docker-octoprint-simulator-1", "exited")
    running = _container("infra-octoprint-simulator-1", "running")
    manager = SimulatorManager(
        client_factory=lambda: _FakeClient([stopped, running], labelled=[stopped])
    )
    picked = manager._get_container()
    assert picked is running


def test_order_does_not_decide_it():
    running = _container("infra-octoprint-simulator-1", "running")
    stopped = _container("other-octoprint-simulator-1", "exited")
    for ordering in ([running, stopped], [stopped, running]):
        manager = SimulatorManager(client_factory=lambda o=ordering: _FakeClient(o))
        assert manager._get_container() is running


def test_a_stopped_container_is_still_reported_when_nothing_runs():
    """"Stopped" and "absent" are different answers and must stay different."""
    stopped = _container("p2p-mesh-poc-docker-octoprint-simulator-1", "exited")
    manager = SimulatorManager(client_factory=lambda: _FakeClient([stopped]))
    picked = manager._get_container()
    assert picked is stopped
    assert picked.status == "exited"


def test_no_container_at_all_is_none():
    manager = SimulatorManager(client_factory=lambda: _FakeClient([], labelled=[]))
    assert manager._get_container() is None


def test_an_unrelated_container_is_never_matched():
    manager = SimulatorManager(
        client_factory=lambda: _FakeClient([_container("p2p-chief-of-staff-n8n", "running")], labelled=[])
    )
    assert manager._get_container() is None


# ── The gate ──────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_printer(monkeypatch):
    """Replace the printer probe for the duration of one test."""

    def apply(payload):
        async def fake():
            return payload
        monkeypatch.setattr(app_module, "printer_status", fake)

    return apply


def _job_payload():
    return {"prompt": "a vase", "printer_id": "default_printer"}


def test_an_unconfigured_printer_blocks_a_job(stub_printer):
    stub_printer({"configured": False, "type": "none", "running": False})
    res = client.post("/jobs", json=_job_payload())
    assert res.status_code == 400
    assert "configured" in res.json()["detail"].lower()


def test_a_configured_but_unreachable_printer_blocks_a_job(stub_printer):
    """The case that used to sail through and waste a five-phase run."""
    stub_printer({
        "configured": True,
        "type": "real",
        "running": False,
        "detail": "Reached the printer, but it rejected the credential (403).",
    })
    res = client.post("/jobs", json=_job_payload())
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "did not answer" in detail
    # The reason travels with the refusal, so the UI need not guess at it.
    assert "403" in detail


def test_connection_failures_are_reported_as_credential_problems(monkeypatch):
    """A 401/403 means reached-and-refused, which is not "unreachable"."""
    import httpx

    class _Resp:
        status_code = 403
        text = "You don't have the permission to access the requested resource."

    async def boom(*args, **kwargs):
        raise httpx.HTTPStatusError("403", request=None, response=_Resp())

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    monkeypatch.setattr(
        app_module.config_store, "get_all",
        lambda: {"OCTOPRINT_URL": "http://localhost:5001", "OCTOPRINT_API_KEY": "wrong"},
    )

    res = client.post("/config/test-connection", json={"service": "octoprint"})
    body = res.json()
    assert body["success"] is False
    assert "rejected the credential" in body["message"]
    assert "OCTOPRINT_API_KEY" in body["message"]
    # The stock Flask 403 page said nothing about the printer or the key; it must not
    # be what the user is shown.
    assert "read-protected" not in body["message"]
