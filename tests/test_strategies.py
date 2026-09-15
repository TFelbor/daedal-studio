from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)

def test_system_info():
    response = client.get("/system/info")
    assert response.status_code == 200
    data = response.json()
    print("System Info:", data)
    assert "detected_strategy" in data
    assert "resolved_strategy" in data
    assert "override_active" in data
    assert "strategy_label" in data
    assert "docker_available" in data
    assert "platform" in data
    assert "python_version" in data

if __name__ == "__main__":
    test_system_info()
    print("Tests passed successfully.")
