"""There is one telemetry database, and these tests keep it that way.

`~/.ds-mvp/telemetry.db` on the host is the only database. Containers reach that
same file through the `~/.ds-mvp:/root/.ds-mvp` bind mount, because `HOME` is
`/root` in the image and `get_default_db_path()` reads it.

This is guarded rather than merely documented because it has already failed once, in
a way that hid a month of data. `.env` set `TELEMETRY_DB_PATH=/app/telemetry/telemetry.db`
and compose mounted a *named volume* there. A named volume cannot be seen from the
host, so container runs wrote job rows somewhere invisible while their artifacts
landed in the bind-mounted `data/outputs/` — 27 job directories whose rows were
nowhere a developer would think to look — and native runs used a different database
again, with a different `.config_key` encrypting a different copy of HF_TOKEN.

Every assertion below is one of the specific things that were true when that
happened.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_TEMPLATE = REPO_ROOT / ".env.template"

#: The one path. Anything else in a config file is a second database.
CANONICAL_DIR = ".ds-mvp"


def _uncommented_lines(path: Path) -> list[str]:
    """Lines with real content — a commented example is documentation, not config."""
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_the_default_path_is_the_home_directory_one():
    """Nothing may quietly change where "no configuration" points."""
    import os

    from pythonsrc.telemetry.db import get_default_db_path

    previous = os.environ.pop("TELEMETRY_DB_PATH", None)
    try:
        default = get_default_db_path()
    finally:
        if previous is not None:
            os.environ["TELEMETRY_DB_PATH"] = previous

    assert default.endswith(f"{CANONICAL_DIR}/telemetry.db"), default
    assert str(Path.home()) in default


def test_compose_does_not_pin_the_database_path():
    """Setting it in compose is what split native runs from container runs."""
    offenders = [
        line for line in _uncommented_lines(COMPOSE) if "TELEMETRY_DB_PATH" in line
    ]
    assert not offenders, (
        "docker-compose.yml sets TELEMETRY_DB_PATH: "
        f"{offenders}. Leave it unset so containers resolve the same default as the "
        "host through the ~/.ds-mvp bind mount — see 'One database' in CLAUDE.md."
    )


def test_the_env_template_does_not_pin_the_database_path():
    offenders = [
        line for line in _uncommented_lines(ENV_TEMPLATE) if "TELEMETRY_DB_PATH" in line
    ]
    assert not offenders, (
        f".env.template sets TELEMETRY_DB_PATH: {offenders}. Anyone copying the "
        "template would get two databases again."
    )


def test_there_is_no_telemetry_volume():
    """A named volume is invisible from the host, which is how the data went missing."""
    text = COMPOSE.read_text()
    volume_mounts = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"^\s+- \S*telemetry\S*:/", line) and not line.strip().startswith("#")
    ]
    assert not volume_mounts, (
        f"a telemetry volume mount is back: {volume_mounts}. The database must be "
        "bind-mounted from ~/.ds-mvp so it is visible on the host."
    )
    assert not re.search(r"^\s+ds-telemetry:", text, re.M), (
        "the ds-telemetry named volume has been re-declared"
    )


@pytest.mark.parametrize("service", ["api-server", "pipeline-runner"])
def test_every_service_that_writes_telemetry_mounts_the_host_directory(service: str):
    """Without the bind mount, the in-container default is a container-local file."""
    text = COMPOSE.read_text()
    block = re.search(rf"\n  {service}:\n(.*?)(?=\n  \S|\nvolumes:|\Z)", text, re.S)
    assert block, f"{service} not found in docker-compose.yml"
    assert "~/.ds-mvp:/root/.ds-mvp" in block.group(1), (
        f"{service} does not mount ~/.ds-mvp, so its default database path would "
        "resolve to a file inside the container that nobody can see."
    )


def test_the_env_rewriting_patch_scripts_are_gone():
    """`patch_env.py` appended TELEMETRY_DB_PATH to .env on every run."""
    for name in ("patch.py", "patch_env.py"):
        path = REPO_ROOT / "infra" / "scripts" / name
        assert not path.exists(), (
            f"{path} is back. It rewrites .env non-idempotently and reintroduced the "
            "container database path."
        )
