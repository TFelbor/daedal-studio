"""The API server is published on loopback, and these tests keep it there.

`POST /jobs` spends EUR 0,32 on a hosted generation,
`POST /jobs/{id}/print-dispatch` heats a nozzle for hours, and `PUT /config` rewrites
the printer credentials the server then ships to whatever host it is pointed at.
`ports: - "8000:8000"` published all of that on every interface of the machine, so
anything that could route to the host — the rest of the LAN, a guest network, a shared
VPN — could drive the printer.

Those routes are authenticated now (`server/auth.py`), and that does not retire this
file. The token is one shared secret with no per-user model, no revocation short of
rotating it for everybody, and no TLS under it; the bind address is the other half,
and it is the half that decides who may *try*. Two mechanisms, and this one is the one
that is a single token in a single mapping.

The bind address is one token in one mapping. Deleting it is invisible in a diff and
total at runtime: the port still publishes, the app still answers on localhost, and
nothing in the log says the LAN can reach it now. That is what these tests are for.

`DS_API_BIND` is the one variable that moves it, and it must move *both* runs — the
container's published port and `make start-native` — or a machine deliberately
exposing the API through one path is silently still closed on the other, and (worse)
a machine that never touched the variable is still open on the second.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
NATIVE_ENV = REPO_ROOT / "infra" / "scripts" / "load_native_env.sh"
MAKEFILE = REPO_ROOT / "Makefile"
DOCKER_DOC = REPO_ROOT / "docs" / "README-docker.md"

#: The one variable. Its default, everywhere it is read, is loopback.
BIND_VARIABLE = "DS_API_BIND"
LOOPBACK = "127.0.0.1"


def _api_server_ports() -> list[str]:
    compose = yaml.safe_load(COMPOSE.read_text())
    return [str(entry) for entry in compose["services"]["api-server"]["ports"]]


def test_the_published_port_names_a_bind_address():
    """A mapping of `8000:8000` publishes on every interface. This is the whole issue."""
    ports = _api_server_ports()
    assert ports, "api-server publishes no port at all"
    for mapping in ports:
        assert mapping.count(":") >= 2, (
            f"api-server port mapping {mapping!r} has no bind address, so Docker "
            "publishes it on every interface of the host. An unauthenticated "
            "POST /jobs, print-dispatch and PUT /config then answer the whole LAN."
        )


def test_the_bind_address_defaults_to_loopback():
    """The default must be loopback with no .env at all — `${VAR:-127.0.0.1}`."""
    mapping = _api_server_ports()[0]
    host = mapping.rsplit(":", 2)[0]
    assert BIND_VARIABLE in host, (
        f"the api-server bind address {host!r} is not overridable through "
        f"{BIND_VARIABLE}"
    )
    default = re.search(rf"\$\{{{BIND_VARIABLE}:-([^}}]+)\}}", host)
    assert default, (
        f"{host!r} names {BIND_VARIABLE} without a default, so an unset variable "
        "would publish on every interface"
    )
    assert default.group(1) == LOOPBACK, default.group(1)


def test_the_container_internal_uvicorn_host_is_unchanged():
    """Docker connects to the container's own address to publish a port.

    A loopback bind *inside* the container makes the published port dead whatever
    the host-side mapping says, so this line is deliberately not the security knob
    and the comment above it says why.
    """
    text = COMPOSE.read_text()
    block = re.search(r"\n  api-server:\n(.*?)(?=\n  \S|\nvolumes:|\Z)", text, re.S)
    assert block, "api-server not found in docker-compose.yml"
    command = re.search(r"^    command: (.+)$", block.group(1), re.M)
    assert command, "api-server has no command"
    assert "--host 0.0.0.0" in command.group(1), command.group(1)


def test_the_reason_the_container_host_stays_open_is_written_down():
    """Without the comment, the next reader closes it and the port goes dead."""
    text = COMPOSE.read_text()
    block = re.search(r"\n  api-server:\n(.*?)(?=\n  \S|\nvolumes:|\Z)", text, re.S)
    comment = re.search(
        r"((?:^    #.*\n)+)^    command: uvicorn", block.group(1), re.M
    )
    assert comment, (
        "the `--host 0.0.0.0` inside the container carries no comment saying why it "
        "must stay, so the obvious 'fix' is to close it and kill the published port"
    )
    assert "0.0.0.0" in comment.group(1)


def test_the_env_template_documents_the_variable_and_defaults_to_loopback():
    lines = [
        line.strip()
        for line in ENV_TEMPLATE.read_text().splitlines()
        if line.strip().startswith(f"{BIND_VARIABLE}=")
    ]
    assert lines == [f"{BIND_VARIABLE}={LOOPBACK}"], lines


def test_the_native_start_binds_loopback_through_the_same_variable():
    """`make start-native` binds the host interface directly — no container hop."""
    recipe = re.search(r"\nstart-native:\n(.*?)(?=\n\S|\Z)", MAKEFILE.read_text(), re.S)
    assert recipe, "start-native target not found"
    host = re.search(r"--host (\S+)", recipe.group(1))
    assert host, "start-native does not pass --host to uvicorn"
    # `$$` is make's escape for a literal `$`, so the shell — not make — expands it,
    # which is what lets load_native_env.sh set it on the line before.
    expected = "$${" + BIND_VARIABLE + ":-" + LOOPBACK + "}"
    assert host.group(1) == expected, (
        f"start-native binds {host.group(1)} rather than {expected}"
    )


def test_the_native_env_loader_lifts_the_variable_across():
    """Otherwise a .env that opens the API deliberately is inert for a native run."""
    keys = [
        line.strip()
        for line in NATIVE_ENV.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert BIND_VARIABLE in keys, f"{NATIVE_ENV.name} does not export {BIND_VARIABLE}"


@pytest.mark.parametrize("needle", [LOOPBACK, BIND_VARIABLE])
def test_the_docker_guide_says_where_the_app_is_and_how_to_expose_it(needle: str):
    """Someone who cannot reach the UI from another machine must find out why here."""
    assert needle in DOCKER_DOC.read_text(), (
        f"{DOCKER_DOC.name} does not mention {needle}"
    )
