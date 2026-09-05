"""There is one telemetry database, and these tests keep it that way.

The database is PostgreSQL on Supabase, and every process — the API server, the
pipeline container, the native Mac pipeline, `run_operator.py` — reaches it through
one variable, `DS_DATABASE_URL`. Nothing falls back to a local file.

This is guarded rather than merely documented because it has already failed once, in
a way that hid a month of data. When the database was a SQLite file, `.env` set
`TELEMETRY_DB_PATH=/app/telemetry/telemetry.db` and compose mounted a *named volume*
there. A named volume cannot be seen from the host, so container runs wrote job rows
somewhere invisible while their artifacts landed in the bind-mounted `data/outputs/`
— 27 job directories whose rows were nowhere a developer would think to look — and
native runs used a different database again, with a different `.config_key`
encrypting a different copy of HF_TOKEN.

Every assertion below is one of the specific things that were true when that
happened, translated to the URL that replaced the path.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
NATIVE_ENV = REPO_ROOT / "infra" / "scripts" / "load_native_env.sh"

#: The one variable. Anything else in a config file is a second database.
URL_VARIABLE = "DS_DATABASE_URL"
#: The retired one. Its reappearance anywhere live is the old split coming back.
RETIRED_VARIABLE = "TELEMETRY_DB_PATH"


def _uncommented_lines(path: Path) -> list[str]:
    """Lines with real content — a commented example is documentation, not config."""
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_no_configuration_is_an_error_not_a_default():
    """Nothing may quietly decide where "no configuration" points."""
    from pythonsrc.telemetry.db import DatabaseConfigError, get_database_url

    previous = os.environ.pop(URL_VARIABLE, None)
    try:
        with pytest.raises(DatabaseConfigError, match=URL_VARIABLE):
            get_database_url()
    finally:
        if previous is not None:
            os.environ[URL_VARIABLE] = previous


def test_the_retired_path_variable_is_not_read_anywhere():
    """A stray reader of TELEMETRY_DB_PATH would be a second database by another name."""
    offenders = []
    for root in ("pythonsrc", "server"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            if RETIRED_VARIABLE in path.read_text():
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"{RETIRED_VARIABLE} is read again in: {offenders}"


@pytest.mark.parametrize("path", [COMPOSE, ENV_TEMPLATE])
def test_config_files_do_not_set_the_retired_variable(path: Path):
    offenders = [line for line in _uncommented_lines(path) if RETIRED_VARIABLE in line]
    assert not offenders, f"{path.name} sets {RETIRED_VARIABLE}: {offenders}"


def test_the_env_template_names_the_url_and_carries_no_value():
    """The template documents the variable; a real URL in it would be a leaked secret."""
    lines = [line for line in _uncommented_lines(ENV_TEMPLATE) if line.startswith(f"{URL_VARIABLE}=")]
    assert lines == [f"{URL_VARIABLE}="], lines


@pytest.mark.parametrize("service", ["api-server", "pipeline-runner"])
def test_every_service_that_writes_telemetry_is_handed_the_url(service: str):
    """`compose run` passes nothing from the host unless the compose file names it."""
    text = COMPOSE.read_text()
    block = re.search(rf"\n  {service}:\n(.*?)(?=\n  \S|\nvolumes:|\Z)", text, re.S)
    assert block, f"{service} not found in docker-compose.yml"
    assert URL_VARIABLE in block.group(1), (
        f"{service} is not given {URL_VARIABLE}, so its telemetry writes would fail "
        "with a configuration error inside the container."
    )


@pytest.mark.parametrize("service", ["api-server", "pipeline-runner"])
def test_every_service_that_needs_the_config_key_mounts_the_host_directory(service: str):
    """The Fernet key stays on the host at ~/.ds-mvp/.config_key; one key, one database."""
    text = COMPOSE.read_text()
    block = re.search(rf"\n  {service}:\n(.*?)(?=\n  \S|\nvolumes:|\Z)", text, re.S)
    assert block, f"{service} not found in docker-compose.yml"
    assert "~/.ds-mvp:/root/.ds-mvp" in block.group(1), (
        f"{service} does not mount ~/.ds-mvp, so the config store would generate a "
        "second key inside the container and decrypt nothing the host wrote."
    )


def test_there_is_no_telemetry_volume():
    """A named volume is invisible from the host, which is how the data went missing."""
    text = COMPOSE.read_text()
    volume_mounts = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"^\s+- \S*telemetry\S*:/", line) and not line.strip().startswith("#")
    ]
    assert not volume_mounts, f"a telemetry volume mount is back: {volume_mounts}"
    assert not re.search(r"^\s+ds-telemetry:", text, re.M), (
        "the ds-telemetry named volume has been re-declared"
    )


def test_the_native_env_loader_lifts_the_url_across():
    """`make start-native` reads .env through an allowlist; the URL must be on it."""
    keys = _uncommented_lines(NATIVE_ENV)
    assert URL_VARIABLE in keys, f"{NATIVE_ENV.name} does not export {URL_VARIABLE}"


def test_the_env_rewriting_patch_scripts_are_gone():
    """`patch_env.py` appended TELEMETRY_DB_PATH to .env on every run."""
    for name in ("patch.py", "patch_env.py"):
        path = REPO_ROOT / "infra" / "scripts" / name
        assert not path.exists(), (
            f"{path} is back. It rewrites .env non-idempotently and reintroduced the "
            "container database path."
        )
