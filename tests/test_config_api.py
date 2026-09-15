# NOTE: this file is a manual smoke script, not a pytest module — pytest collects it
# and finds no `test_*` functions, so its only real entry point is
# `python tests/test_config_api.py`, which never loads tests/conftest.py and therefore misses the
# database isolation there. Unguarded, it overwrites the developer's real HF_TOKEN with "test123" and deletes
# their MOONRAKER_URL row from the encrypted config store.
# Redirect the database before importing server.app. Run standalone, this refuses to
# start without DS_TEST_DATABASE_URL — a throwaway PostgreSQL the script may write to
# (see tests/testing_postgres.py) — so it can never reach the Supabase project. Under
# pytest, conftest has already pointed DS_DATABASE_URL at a schema it created.
import os as _os
import sys as _sys
import tempfile as _tempfile

if __name__ == "__main__":
    _test_url = _os.environ.get("DS_TEST_DATABASE_URL", "").strip()
    if not _test_url:
        _sys.exit(
            "Set DS_TEST_DATABASE_URL to a throwaway PostgreSQL before running this "
            "smoke script; it writes rows and must never see the real database."
        )
    _os.environ["DS_DATABASE_URL"] = _test_url
    _os.environ.setdefault(
        "DS_CONFIG_KEY_PATH",
        _os.path.join(_tempfile.mkdtemp(prefix="ds-smoke-"), ".config_key"),
    )

import os
from fastapi.testclient import TestClient
from server.app import app
from server.config_store import CONFIG_KEYS, INTERNAL_CONFIG_KEYS

def run_tests():
    with TestClient(app) as client:
        # 1. GET /config returns every settable key in CONFIG_KEYS with metadata. The
        # printer-key host bindings are the store's own bookkeeping and are not listed.
        resp = client.get("/config")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == len(CONFIG_KEYS) - len(INTERNAL_CONFIG_KEYS)
        assert "HF_TOKEN" in data
        assert data["HF_TOKEN"]["secret"] is True
        assert data["HF_TOKEN"]["required"] is True
        print("GET /config - OK")

        # 2. POST /config with {"key": "HF_TOKEN", "value": "test123"} stores encrypted, returns masked value.
        resp = client.post("/config", json={"key": "HF_TOKEN", "value": "test123"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["value"] == "••••••••"
        print("POST /config - OK")

        # 3. GET /config/HF_TOKEN/reveal returns "test123".
        resp = client.get("/config/HF_TOKEN/reveal")
        assert resp.status_code == 200, resp.text
        assert resp.json()["value"] == "test123"
        print("GET /config/HF_TOKEN/reveal - OK")

        # 4. POST /config/test-connection with {"service": "moonraker"} when no URL configured returns {"success": false, "message": "MOONRAKER_URL not configured"}.
        # Ensure MOONRAKER_URL is deleted
        client.delete("/config/MOONRAKER_URL")
        resp = client.post("/config/test-connection", json={"service": "moonraker"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "MOONRAKER_URL not configured"
        print("POST /config/test-connection - OK")

        # 5. Neither startup nor POST /config puts a stored value in os.environ.
        # It used to do both, and both subprocess launches copied that environment
        # wholesale — see tests/test_subprocess_env.py, which is the pytest half of
        # this. The store is read at the moment it is used instead.
        assert os.environ.get("HF_TOKEN") != "test123"
        print("Config stays out of os.environ - OK")

if __name__ == "__main__":
    run_tests()
    print("All tests passed!")
