"""How the shared API secret is resolved, on both sides of the wire.

`pythonsrc/api_token.py` is read by the server that checks the token and by the
pipeline container, the dispatch operator and the telemetry relay that send it. The
four facts below are what keeps those agreeing: the environment wins, a blank value
is not a token, the file is the fallback that the `~/.ds-mvp` mount shares between a
native run and a compose run, and only a caller that passes `create=True` — the
server, and nothing else — may invent one.
"""

import os
import stat
from pathlib import Path

import pytest

from pythonsrc.api_token import (
    API_TOKEN_ENV,
    API_TOKEN_PATH_ENV,
    default_api_token_path,
    resolve_api_token,
)


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    """A token path of this test's own, with nothing in the environment."""
    path = tmp_path / ".ds-mvp" / ".api_token"
    monkeypatch.setenv(API_TOKEN_PATH_ENV, str(path))
    monkeypatch.delenv(API_TOKEN_ENV, raising=False)
    return path


def test_the_environment_beats_the_file(token_file, monkeypatch):
    """A token passed in explicitly is the one used, whatever is on disk."""
    token_file.parent.mkdir(parents=True)
    token_file.write_text("from-the-file")
    monkeypatch.setenv(API_TOKEN_ENV, "from-the-environment")

    assert resolve_api_token() == "from-the-environment"


def test_a_blank_environment_value_is_not_a_token(token_file, monkeypatch):
    """`DS_API_TOKEN=` in .env is an unset variable, not an empty shared secret.

    Docker Compose passes a blank `.env` line through as an empty string, and
    `.env.template` ships the variable blank so the server generates one. Reading
    that as a token would make "" the credential — which every request supplies.
    """
    token_file.parent.mkdir(parents=True)
    token_file.write_text("from-the-file")
    monkeypatch.setenv(API_TOKEN_ENV, "   ")

    assert resolve_api_token() == "from-the-file"


def test_the_file_is_the_fallback(token_file):
    """No environment variable: the token comes off disk, trimmed of its newline."""
    token_file.parent.mkdir(parents=True)
    token_file.write_text("on-disk\n")

    assert resolve_api_token() == "on-disk"


def test_nothing_at_all_is_none_unless_creation_is_asked_for(token_file):
    """A caller that only sends the token never invents one — it would not match."""
    assert resolve_api_token() is None
    assert resolve_api_token(create=False) is None
    assert not token_file.exists(), "resolve_api_token(create=False) wrote a token file"


def test_creation_persists_a_private_token_that_reads_back(token_file):
    """The server's first start makes one, 0600, and every later start reads it."""
    created = resolve_api_token(create=True)

    assert created
    assert len(created) >= 32, "a generated token must not be guessable"
    assert token_file.exists()
    mode = stat.S_IMODE(token_file.stat().st_mode)
    assert mode == 0o600, f"the token file is mode {mode:o}, not 0600"

    assert resolve_api_token() == created, "a restart resolved a different token"
    assert resolve_api_token(create=True) == created, "a restart rotated the token"


def test_creation_survives_an_unwritable_path(token_file, monkeypatch):
    """An unwritable token path does not downgrade the server to no authentication."""
    monkeypatch.setenv(API_TOKEN_PATH_ENV, str(token_file.parent / "nope" / "x"))

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", refuse)

    token = resolve_api_token(create=True)
    assert token, "an unwritable token path left the server with no token to check"


def test_the_default_path_sits_beside_the_config_key(monkeypatch):
    """`~/.ds-mvp/` is the directory both containers already mount."""
    monkeypatch.delenv(API_TOKEN_PATH_ENV, raising=False)

    path = Path(default_api_token_path())
    assert path.parent == Path(os.path.expanduser("~")) / ".ds-mvp"
    assert path.name.startswith("."), "the token file should be a dotfile"


def test_the_token_is_not_a_config_store_key():
    """Deliberately not in `CONFIG_KEYS`.

    `PUT /config` would otherwise be able to rotate the very credential that
    protects `PUT /config`, and one bad write would lock every client out of the
    server with no way back in through the API.
    """
    from server.config_store import CONFIG_KEYS

    assert API_TOKEN_ENV not in CONFIG_KEYS
