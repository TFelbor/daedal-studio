"""GPU sculptor worker tests.

The worker's job is to be a thin, honest wrapper around one backend. It never
loads TRELLIS.2 here — what is tested is the contract the client depends on:
auth, validation, the response headers that tell the client which way is up, and
the guarantee that a per-request override cannot leak into the next request.
"""

import io

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from pythonsrc.sculptors.base import SculptorBackend, SculptorError


class FakeGPUBackend(SculptorBackend):
    """Stands in for a loaded TRELLIS.2, recording what it was asked to do."""

    name = "trellis2"
    up_axis = "y"
    MODEL_NAME = "TRELLIS.2"
    MODEL_VERSION = "microsoft/TRELLIS.2-4B"

    def __init__(self):
        self.pipeline_type = "1024_cascade"
        self.seed = 42
        self.calls: list[dict] = []
        self.fail_with: str | None = None

    def reconstruct(self, image_path):
        self.calls.append({"pipeline_type": self.pipeline_type, "seed": self.seed})
        if self.fail_with:
            raise SculptorError(self.fail_with)
        return trimesh.creation.box(extents=(1, 10, 1))

    def describe(self):
        return f"fake({self.pipeline_type},{self.seed})"


@pytest.fixture
def worker(monkeypatch):
    """A worker module with a backend already 'loaded' and auth switched on."""
    monkeypatch.setenv("P2P_WORKER_PRELOAD", "false")
    import importlib

    from services.trellis2_worker import app as module

    module = importlib.reload(module)
    monkeypatch.setattr(module, "WORKER_API_KEY", "tok")
    monkeypatch.setattr(module, "_backend", FakeGPUBackend())
    return module


@pytest.fixture
def client(worker):
    return TestClient(worker.app)


AUTH = {"Authorization": "Bearer tok"}
IMAGE = {"image": ("blueprint.png", b"fake-png-bytes", "image/png")}


def test_health_reports_the_loaded_model(client):
    body = client.get("/health").json()
    assert body["status"] == "ready"
    assert body["model"] == "TRELLIS.2"
    assert body["up_axis"] == "y"
    assert body["cuda_available"] is False


def test_health_needs_no_token(worker, client):
    """A readiness probe that requires a secret is a readiness probe nobody runs."""
    assert client.get("/health").status_code == 200


def test_missing_token_is_rejected(client):
    assert client.post("/sculpt", files=IMAGE).status_code == 401


def test_wrong_token_is_rejected(client):
    response = client.post(
        "/sculpt", files=IMAGE, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


def test_no_token_configured_means_open(worker, monkeypatch):
    monkeypatch.setattr(worker, "WORKER_API_KEY", "")
    assert TestClient(worker.app).post("/sculpt", files=IMAGE).status_code == 200


def test_successful_sculpt_returns_geometry_and_headers(client):
    response = client.post("/sculpt", files=IMAGE, headers=AUTH)
    assert response.status_code == 200
    assert response.headers["X-P2P-Up-Axis"] == "y"
    assert response.headers["X-P2P-Mesh-Format"] == "obj"
    assert response.headers["X-P2P-Backend"] == "trellis2"
    assert response.headers["X-P2P-Model"] == "TRELLIS.2"
    assert response.headers["X-P2P-Model-Version"] == "microsoft/TRELLIS.2-4B"

    mesh = trimesh.load(io.BytesIO(response.content), file_type="obj")
    # Raw geometry: still Y-up, undecimated. Post-processing is the client's job.
    assert np.allclose(sorted(mesh.extents), [1, 1, 10])


def test_empty_upload_is_rejected_before_inference(worker, client):
    response = client.post(
        "/sculpt",
        files={"image": ("blueprint.png", b"", "image/png")},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert worker._backend.calls == []


def test_mismatched_backend_is_refused_not_silently_served(worker, client):
    """Serving a trellis2 mesh to a caller who asked for something else is worse
    than an error: the telemetry row would name a model that never ran."""
    response = client.post(
        "/sculpt", files=IMAGE, data={"backend": "triposr"}, headers=AUTH
    )
    assert response.status_code == 409
    assert worker._backend.calls == []


def test_overrides_reach_the_backend(worker, client):
    client.post(
        "/sculpt",
        files=IMAGE,
        data={"pipeline_type": "512", "seed": "7"},
        headers=AUTH,
    )
    assert worker._backend.calls == [{"pipeline_type": "512", "seed": 7}]


def test_overrides_are_restored_after_the_request(worker, client):
    """The backend instance is shared. A leaked override would silently change
    every later job's geometry, long after the request that set it."""
    client.post(
        "/sculpt",
        files=IMAGE,
        data={"pipeline_type": "512", "seed": "7"},
        headers=AUTH,
    )
    assert worker._backend.pipeline_type == "1024_cascade"
    assert worker._backend.seed == 42


def test_overrides_are_restored_even_when_inference_fails(worker, client):
    worker._backend.fail_with = "CUDA out of memory"
    response = client.post(
        "/sculpt", files=IMAGE, data={"pipeline_type": "512"}, headers=AUTH
    )
    assert response.status_code == 500
    assert worker._backend.pipeline_type == "1024_cascade"


def test_negative_seed_keeps_the_backend_default(worker, client):
    """-1 is the client's 'no opinion' value; it must not become the seed."""
    client.post("/sculpt", files=IMAGE, data={"seed": "-1"}, headers=AUTH)
    assert worker._backend.calls == [{"pipeline_type": "1024_cascade", "seed": 42}]


def test_invalid_pipeline_type_is_rejected(worker, client):
    response = client.post(
        "/sculpt", files=IMAGE, data={"pipeline_type": "2048"}, headers=AUTH
    )
    assert response.status_code == 422
    assert "expected one of" in response.json()["detail"]
    assert worker._backend.calls == []


def test_backend_failure_surfaces_the_reason(worker, client):
    worker._backend.fail_with = "CUDA out of memory"
    response = client.post("/sculpt", files=IMAGE, headers=AUTH)
    assert response.status_code == 500
    assert "CUDA out of memory" in response.json()["detail"]


def test_unloadable_backend_reports_unavailable(worker, monkeypatch):
    """On a host with no GPU the worker must say so, not hang or 500."""
    monkeypatch.setattr(worker, "_backend", None)
    monkeypatch.setattr(
        worker, "create_sculptor", lambda *a, **k: (_ for _ in ()).throw(
            SculptorError("no CUDA device visible")
        )
    )
    response = TestClient(worker.app).post("/sculpt", files=IMAGE, headers=AUTH)
    assert response.status_code == 503
    assert "no CUDA device visible" in response.json()["detail"]
