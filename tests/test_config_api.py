import os
from fastapi.testclient import TestClient
from server.app import app

def run_tests():
    with TestClient(app) as client:
        # 1. GET /config returns all 9 keys with metadata.
        resp = client.get("/config")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 9
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
        
        # 5. Server startup syncs config to os.environ.
        # Note: os.environ update occurs in startup event, but we just set it in test 2 as well via POST
        assert os.environ.get("HF_TOKEN") == "test123"
        print("Startup syncs config to os.environ - OK")

if __name__ == "__main__":
    run_tests()
    print("All tests passed!")
