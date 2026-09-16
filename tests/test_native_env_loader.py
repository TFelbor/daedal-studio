"""`infra/scripts/load_native_env.sh`, executed rather than read.

Every other test of this script asserts on its *text* — `"DS_API_TOKEN" in
NATIVE_ENV.read_text()` is satisfied by a sentence about DS_API_TOKEN as readily as by
the key itself. That is how a real defect sat in it unnoticed: the key list is a
here-document with explanatory comments between the keys, the loop skipped only *empty*
lines, and so each comment was read as a key and interpolated into a `sed` expression.
One of them contains a `/`, which closed the substitution early and printed

    sed: -e expression #1, char 56: unknown option to `s'

on every `make start-native` and every `make api-token`. Nothing broke, because prose
matches no `.env` line — but a comment that happened to read `KEY=value` would have been
exported, and the noise trained a reader to ignore the one place this script talks.

So these run it.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NATIVE_ENV = REPO_ROOT / "infra" / "scripts" / "load_native_env.sh"


def _source(tmp_path: Path, env_text: str) -> subprocess.CompletedProcess:
    """Source the loader in `tmp_path` against that `.env`, and dump the environment.

    `sh`, not bash: the Makefile sources this from `/bin/sh`, and the here-doc idiom in
    it exists because `for k in $VAR` splits differently under zsh.
    """
    (tmp_path / ".env").write_text(env_text)
    return subprocess.run(
        ["sh", "-c", f'. "{NATIVE_ENV}" && env'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
    )


def _exported(result: subprocess.CompletedProcess) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )


ENV = """\
DS_API_TOKEN=a-token
DS_API_BIND=0.0.0.0
DS_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres
FLUX_MODEL_PATH=/models/flux
"""


def test_the_loader_says_nothing_when_it_has_nothing_to_say(tmp_path: Path):
    """The regression. A tool that prints an error on every successful run is a tool
    whose errors nobody reads."""
    result = _source(tmp_path, ENV)

    assert result.returncode == 0
    assert result.stderr == "", f"load_native_env.sh wrote to stderr: {result.stderr!r}"


def test_a_comment_in_the_key_list_is_not_a_key(tmp_path: Path):
    """Names are what the here-doc declares, not the prose explaining them."""
    exported = _exported(_source(tmp_path, ENV))

    offenders = [key for key in exported if " " in key or key.startswith("#")]
    assert offenders == [], f"comment lines exported as variables: {offenders}"


def test_it_lifts_the_credentials_a_native_run_needs(tmp_path: Path):
    """The script's whole purpose: compose gets `.env` through `env_file:`, a native
    run got nothing, so a token set in `.env` reached only one of the two ways this
    server starts and the browser saw a 401 against the other."""
    exported = _exported(_source(tmp_path, ENV))

    assert exported["DS_API_TOKEN"] == "a-token"
    assert exported["DS_API_BIND"] == "0.0.0.0"
    assert exported["DS_DATABASE_URL"].startswith("postgresql://")


def test_a_value_containing_a_slash_survives(tmp_path: Path):
    """`DS_DATABASE_URL` is a URL and `sed` is a substitution — the delimiters have to
    not collide. This is the same class of fault as the comment bug, on the value side.
    """
    exported = _exported(_source(tmp_path, ENV))

    assert exported["DS_DATABASE_URL"] == (
        "postgresql://postgres:postgres@127.0.0.1:55432/postgres"
    )


def test_a_filesystem_path_is_left_behind(tmp_path: Path):
    """`.env` also holds container paths. Exporting one into a host process points it
    at a directory that does not exist, which is why the key list is a list and not
    `export $(cat .env)`."""
    exported = _exported(_source(tmp_path, ENV))

    assert "FLUX_MODEL_PATH" not in exported


@pytest.mark.parametrize("key", ["DS_API_TOKEN", "DS_API_BIND", "DS_DATABASE_URL"])
def test_an_absent_key_is_not_exported_empty(tmp_path: Path, key: str):
    """An empty export is not the same as an unset one: `DS_API_TOKEN=""` would defeat
    the fallback to `~/.ds-mvp/.api_token` that keeps a native and a compose server
    agreeing about the browser's token."""
    exported = _exported(_source(tmp_path, ""))

    assert key not in exported
