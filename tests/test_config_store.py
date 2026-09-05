"""The encrypted config store on PostgreSQL."""

import time

import pytest

from pythonsrc.telemetry import db as db_module
from server.config_store import ConfigStore

UNREACHABLE = "postgresql://nobody:secret@127.0.0.1:1/none?connect_timeout=1"


@pytest.fixture
def store(isolated_db_url, tmp_path):
    s = ConfigStore(dsn=isolated_db_url, key_path=str(tmp_path / ".config_key"))
    s.init_schema()
    return s


def test_values_round_trip_encrypted(store, isolated_db):
    store.set("HF_TOKEN", "hf_secret")
    assert store.get("HF_TOKEN") == "hf_secret"
    raw = isolated_db.query_one("SELECT value_encrypted FROM app_config WHERE key = 'HF_TOKEN'")
    assert b"hf_secret" not in bytes(raw["value_encrypted"])
    assert store.get_all() == {"HF_TOKEN": "hf_secret"}
    store.delete("HF_TOKEN")
    assert store.get("HF_TOKEN") is None


def test_set_is_an_upsert(store):
    store.set("LOG_LEVEL", "INFO")
    store.set("LOG_LEVEL", "DEBUG")
    assert store.get("LOG_LEVEL") == "DEBUG"


def test_unknown_keys_are_refused(store):
    with pytest.raises(ValueError):
        store.set("NOT_A_KEY", "x")


def test_a_different_key_file_cannot_read_the_values(store, isolated_db_url, tmp_path):
    store.set("OCTOPRINT_API_KEY", "abc")
    other = ConfigStore(dsn=isolated_db_url, key_path=str(tmp_path / "other.key"))
    assert other.get("OCTOPRINT_API_KEY") is None
    assert other.get_all() == {}


def test_reads_answer_unset_while_the_database_is_unreachable(tmp_path, monkeypatch):
    """Config reads sit on polled endpoints; an outage must not make them hang."""
    monkeypatch.setenv("DS_DATABASE_TIMEOUT_S", "2")
    s = ConfigStore(dsn=UNREACHABLE, key_path=str(tmp_path / ".config_key"))
    try:
        assert s.get("HF_TOKEN") is None          # pays the timeout once
        started = time.monotonic()
        assert s.get("HF_TOKEN") is None          # breaker: answers at once
        assert s.get_all() == {}
        assert time.monotonic() - started < 1.0
        with pytest.raises(db_module.DatabaseError):
            s.set("HF_TOKEN", "x")                # writes are never softened
    finally:
        db_module.close_pool(UNREACHABLE)
