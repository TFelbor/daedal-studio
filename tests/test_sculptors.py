"""Phase 2 sculptor backend tests.

Nothing here loads TRELLIS.2. The model needs an NVIDIA GPU with ~24 GB of VRAM
and four compiled CUDA extensions, so the suite would not run anywhere useful if
it did. What *is* tested is everything around it: backend resolution, the shared
post-processing every backend depends on, and the client↔worker wire contract —
which is precisely where a mesh silently comes out lying on its side.
"""

import io
import os

import numpy as np
import pytest
import trimesh
from PIL import Image

from pythonsrc.sculptors import (
    BACKENDS,
    SculptorBackend,
    SculptorError,
    create_sculptor,
    resolve_backend_name,
)

SCULPTOR_ENV_VARS = (
    "P2P_SCULPTOR_BACKEND",
    "P2P_SCULPTOR_REMOTE_URL",
    "P2P_SCULPTOR_REMOTE_KEY",
    "TRELLIS2_PIPELINE_TYPE",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Resolution reads the environment, so a developer's shell must not leak in."""
    for name in SCULPTOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def blueprint(tmp_path):
    path = tmp_path / "blueprint.png"
    Image.new("RGB", (32, 32), (127, 127, 127)).save(path)
    return path


class RecordingBackend(SculptorBackend):
    """A backend that returns a mesh handed to it, so post-processing is testable."""

    name = "recording"
    up_axis = "z"
    default_smooth_iterations = 0
    MODEL_NAME = "test-model"

    def __init__(self, mesh, up_axis="z", smooth=0):
        self._mesh = mesh
        self.up_axis = up_axis
        self.default_smooth_iterations = smooth
        self.seen: list = []

    def reconstruct(self, image_path):
        self.seen.append(image_path)
        return self._mesh


# ── Backend resolution ────────────────────────────────────────────────────────


def test_auto_prefers_remote_when_worker_configured(clean_env):
    clean_env.setenv("P2P_SCULPTOR_REMOTE_URL", "http://gpu-host:8100")
    assert resolve_backend_name("auto") == "remote"


def test_auto_without_gpu_or_worker_fails_with_actionable_message(clean_env):
    """The failure has to name the way out.

    A GPU-less host is the common case for this project — Phase 1 runs on a Mac —
    so "no backend" must explain that the worker exists, not just report false.
    """
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: False)
    with pytest.raises(SculptorError) as exc:
        resolve_backend_name("auto")
    assert "worker" in str(exc.value).lower()


def test_auto_uses_local_when_cuda_present_and_no_worker(clean_env):
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: True)
    assert resolve_backend_name("auto") == "trellis2"


def test_backend_name_comes_from_environment(clean_env):
    clean_env.setenv("P2P_SCULPTOR_BACKEND", "remote")
    assert resolve_backend_name(None) == "remote"


def test_explicit_argument_beats_environment(clean_env):
    clean_env.setenv("P2P_SCULPTOR_BACKEND", "remote")
    assert resolve_backend_name("trellis2") == "trellis2"


@pytest.mark.parametrize("name", ["triposr", "trellis", "", "  "])
def test_unknown_backend_is_rejected(clean_env, name):
    """Including the retired name: a stale config must fail, not fall back."""
    with pytest.raises(SculptorError, match="Unknown sculptor backend|No runnable"):
        resolve_backend_name(name)


def test_backend_names_are_case_and_space_insensitive(clean_env):
    assert resolve_backend_name("  TRELLIS2 ") == "trellis2"


def test_remote_without_url_is_rejected_at_construction(clean_env):
    with pytest.raises(SculptorError, match="needs a worker URL"):
        create_sculptor("remote")


def test_triposr_is_gone():
    """The replacement is not complete while the old backend is still reachable."""
    assert "triposr" not in BACKENDS
    with pytest.raises(ImportError):
        import pythonsrc.sculptors.triposr  # noqa: F401


# ── Shared post-processing ────────────────────────────────────────────────────


def test_y_up_backend_output_is_rotated_to_z_up(blueprint, tmp_path):
    """A Y-up backend's tall axis must end up in Z, or the print lies on its side."""
    tall = trimesh.creation.box(extents=(1, 10, 1))
    out = tmp_path / "mesh.obj"
    RecordingBackend(tall, up_axis="y").generate_mesh(blueprint, out, target_faces=0)
    assert np.allclose(trimesh.load(out).extents, [1, 1, 10])


def test_z_up_backend_output_is_left_alone(blueprint, tmp_path):
    """TRELLIS.2 is already Z-up; rotating it would be the bug."""
    tall = trimesh.creation.box(extents=(1, 1, 10))
    out = tmp_path / "mesh.obj"
    RecordingBackend(tall, up_axis="z").generate_mesh(blueprint, out, target_faces=0)
    assert np.allclose(trimesh.load(out).extents, [1, 1, 10])


def test_unsupported_up_axis_raises(blueprint, tmp_path):
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    with pytest.raises(SculptorError, match="Unsupported up_axis"):
        RecordingBackend(mesh, up_axis="x").generate_mesh(blueprint, tmp_path / "m.obj")


def test_floating_debris_is_discarded(blueprint, tmp_path):
    sphere = trimesh.creation.icosphere(subdivisions=3)
    debris = trimesh.creation.box(extents=(0.02, 0.02, 0.02))
    debris.apply_translation([5, 0, 0])
    combined = trimesh.util.concatenate([sphere, debris])
    assert len(combined.split(only_watertight=False)) == 2

    out = tmp_path / "mesh.obj"
    RecordingBackend(combined).generate_mesh(blueprint, out, target_faces=0)
    assert len(trimesh.load(out).split(only_watertight=False)) == 1


def test_decimation_respects_the_face_budget(blueprint, tmp_path):
    dense = trimesh.creation.icosphere(subdivisions=4)
    assert len(dense.faces) > 2000
    out = tmp_path / "mesh.obj"
    RecordingBackend(dense).generate_mesh(blueprint, out, target_faces=500)
    assert len(trimesh.load(out).faces) <= 500


def test_zero_faces_disables_decimation(blueprint, tmp_path):
    dense = trimesh.creation.icosphere(subdivisions=4)
    out = tmp_path / "mesh.obj"
    RecordingBackend(dense).generate_mesh(blueprint, out, target_faces=0)
    assert len(trimesh.load(out).faces) == len(dense.faces)


def test_smoothing_defaults_to_off_and_is_opt_in(blueprint, tmp_path):
    """TRELLIS.2's sharp features are the reason to run it.

    Taubin smoothing subdivides first, so the face count is the observable: if
    smoothing ran by default the mesh would come back larger than it went in.
    """
    cube = trimesh.creation.box(extents=(1, 1, 1))
    plain = tmp_path / "plain.obj"
    RecordingBackend(cube.copy()).generate_mesh(blueprint, plain, target_faces=0)
    assert len(trimesh.load(plain).faces) == len(cube.faces)

    smoothed = tmp_path / "smoothed.obj"
    RecordingBackend(cube.copy()).generate_mesh(
        blueprint, smoothed, target_faces=0, smooth_iterations=3
    )
    assert len(trimesh.load(smoothed).faces) > len(cube.faces)


def test_explicit_zero_overrides_a_backend_that_wants_smoothing(blueprint, tmp_path):
    cube = trimesh.creation.box(extents=(1, 1, 1))
    out = tmp_path / "mesh.obj"
    RecordingBackend(cube.copy(), smooth=10).generate_mesh(
        blueprint, out, target_faces=0, smooth_iterations=0
    )
    assert len(trimesh.load(out).faces) == len(cube.faces)


def test_missing_blueprint_fails_before_the_backend_runs(tmp_path):
    """Loading 4B parameters to then discover the input is absent wastes minutes."""
    backend = RecordingBackend(trimesh.creation.box())
    with pytest.raises(SculptorError, match="Blueprint image not found"):
        backend.generate_mesh(tmp_path / "nope.png", tmp_path / "m.obj")
    assert backend.seen == []


def test_empty_reconstruction_raises_instead_of_exporting_nothing(blueprint, tmp_path):
    out = tmp_path / "mesh.obj"
    with pytest.raises(SculptorError, match="empty mesh"):
        RecordingBackend(trimesh.Trimesh()).generate_mesh(blueprint, out)
    assert not out.exists()


def test_generation_params_names_the_backend():
    params = RecordingBackend(trimesh.creation.box()).generation_params()
    assert params["sculptor_backend"] == "recording"


# ── Remote backend wire contract ──────────────────────────────────────────────


def _obj_bytes(mesh: trimesh.Trimesh) -> bytes:
    buffer = io.BytesIO()
    mesh.export(buffer, file_type="obj")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content=b"", status_code=200, headers=None, text=""):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text or ""


@pytest.fixture
def remote(clean_env):
    from pythonsrc.sculptors.remote import RemoteSculptorBackend

    return RemoteSculptorBackend(base_url="http://gpu-host:8100/", api_key="tok")


def test_worker_url_is_normalised(remote):
    """A trailing slash would otherwise produce '…8100//sculpt'."""
    assert remote.base_url == "http://gpu-host:8100"


def test_bearer_token_is_sent(remote):
    assert remote._headers() == {"Authorization": "Bearer tok"}


def test_up_axis_header_is_honoured(remote, monkeypatch, blueprint, tmp_path):
    """The header is load-bearing: the client rotates to Z-up from it.

    A worker running a Y-up model must be able to say so, and the mesh must end up
    upright without the client knowing which model ran.
    """
    tall = trimesh.creation.box(extents=(1, 10, 1))
    monkeypatch.setattr(
        remote,
        "_post_with_retries",
        lambda path: FakeResponse(
            content=_obj_bytes(tall),
            headers={"X-P2P-Mesh-Format": "obj", "X-P2P-Up-Axis": "y"},
        ),
    )
    out = tmp_path / "mesh.obj"
    remote.generate_mesh(blueprint, out, target_faces=0)
    assert remote.up_axis == "y"
    assert np.allclose(trimesh.load(out).extents, [1, 1, 10])


def test_missing_up_axis_header_warns_and_assumes_z(remote, monkeypatch, blueprint, tmp_path, caplog):
    """An out-of-date worker should be noisy, not silently wrong-side-up."""
    mesh = trimesh.creation.box(extents=(1, 1, 10))
    monkeypatch.setattr(
        remote,
        "_post_with_retries",
        lambda path: FakeResponse(content=_obj_bytes(mesh), headers={}),
    )
    out = tmp_path / "mesh.obj"
    with caplog.at_level("WARNING"):
        remote.generate_mesh(blueprint, out, target_faces=0)
    assert "X-P2P-Up-Axis" in caplog.text
    assert np.allclose(trimesh.load(out).extents, [1, 1, 10])


def test_model_headers_land_on_provenance(remote, monkeypatch, blueprint, tmp_path):
    """generation_model on the telemetry row must describe what actually ran."""
    mesh = trimesh.creation.box()
    monkeypatch.setattr(
        remote,
        "_post_with_retries",
        lambda path: FakeResponse(
            content=_obj_bytes(mesh),
            headers={
                "X-P2P-Up-Axis": "z",
                "X-P2P-Model": "TRELLIS.2",
                "X-P2P-Model-Version": "microsoft/TRELLIS.2-4B",
            },
        ),
    )
    remote.generate_mesh(blueprint, tmp_path / "m.obj", target_faces=0)
    assert remote.MODEL_NAME == "TRELLIS.2"
    assert "microsoft/TRELLIS.2-4B" in remote.MODEL_VERSION
    # Self-hosted, so nothing is billed per call — telling this apart from a paid
    # hosted API is the point of the separate value.
    assert remote.BACKEND == "remote_worker"
    assert remote.last_generation_cost_usd is None


def test_http_error_is_surfaced_with_the_worker_body(remote, monkeypatch, blueprint, tmp_path):
    monkeypatch.setattr(
        remote,
        "_post_with_retries",
        lambda path: FakeResponse(status_code=503, text="model still loading"),
    )
    with pytest.raises(SculptorError, match="503.*model still loading"):
        remote.generate_mesh(blueprint, tmp_path / "m.obj")


def test_empty_worker_response_is_rejected(remote, monkeypatch, blueprint, tmp_path):
    monkeypatch.setattr(
        remote,
        "_post_with_retries",
        lambda path: FakeResponse(content=b"", headers={"X-P2P-Up-Axis": "z"}),
    )
    with pytest.raises(SculptorError, match="no usable geometry"):
        remote.generate_mesh(blueprint, tmp_path / "m.obj")


def test_forwarded_params_are_recorded(clean_env):
    """The worker's sampler settings belong on the row exactly as a local run's do."""
    sculptor = create_sculptor(
        "remote",
        base_url="http://gpu-host:8100",
        pipeline_type="1536_cascade",
        seed=99,
    )
    # `seed` on the wire — that is the worker's form field name.
    assert sculptor.params == {"pipeline_type": "1536_cascade", "seed": 99}

    # `mesh_seed` on the telemetry row — the same name a local run writes, because
    # both land in the same column and a column with two names cannot be queried.
    params = sculptor.generation_params()
    assert params["pipeline_type"] == "1536_cascade"
    assert params["mesh_seed"] == 99
    assert "seed" not in params
    assert params["worker_url"] == "http://gpu-host:8100"


def test_connection_errors_retry_but_http_errors_do_not(remote, monkeypatch, blueprint, tmp_path):
    """Retrying a worker that answered is retrying a multi-minute inference.

    Cold starts are worth retrying; a real error is not.
    """
    import requests

    monkeypatch.setattr("pythonsrc.sculptors.remote.RETRY_BACKOFF_SECONDS", 0)
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("refused")
        return FakeResponse(
            content=_obj_bytes(trimesh.creation.box()),
            headers={"X-P2P-Up-Axis": "z"},
        )

    monkeypatch.setattr("requests.post", flaky)
    remote.generate_mesh(blueprint, tmp_path / "m.obj", target_faces=0)
    assert calls["n"] == 3


def test_unreachable_worker_gives_up_after_the_retry_budget(remote, monkeypatch, blueprint, tmp_path):
    import requests

    monkeypatch.setattr("pythonsrc.sculptors.remote.RETRY_BACKOFF_SECONDS", 0)

    def always_refused(*args, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("requests.post", always_refused)
    with pytest.raises(SculptorError, match="Could not reach sculptor worker"):
        remote.generate_mesh(blueprint, tmp_path / "m.obj")


def test_timeout_is_not_retried(remote, monkeypatch, blueprint, tmp_path):
    import requests

    def timed_out(*args, **kwargs):
        raise requests.exceptions.Timeout("too slow")

    monkeypatch.setattr("requests.post", timed_out)
    with pytest.raises(SculptorError, match="did not respond within"):
        remote.generate_mesh(blueprint, tmp_path / "m.obj")


# ── Local backend, without loading the model ──────────────────────────────────


def test_local_backend_rejects_an_unknown_pipeline_type(clean_env):
    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    with pytest.raises(SculptorError, match="Invalid pipeline_type"):
        Trellis2Backend(pipeline_type="2048")


def test_local_backend_is_z_up_and_does_not_smooth():
    """Both are deliberate and both are silent failures if changed by accident."""
    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    assert Trellis2Backend.up_axis == "z"
    assert Trellis2Backend.default_smooth_iterations == 0
    assert Trellis2Backend.MODEL_NAME == "TRELLIS.2"


def test_shape_only_model_list_excludes_the_texture_models():
    """Loading them would cost VRAM and download time for output we discard."""
    from pythonsrc.sculptors.trellis2 import SHAPE_ONLY_MODELS

    assert not [m for m in SHAPE_ONLY_MODELS if "tex" in m]
    assert "shape_slat_decoder" in SHAPE_ONLY_MODELS
    assert "sparse_structure_flow_model" in SHAPE_ONLY_MODELS


def test_missing_checkout_names_the_env_var(clean_env, tmp_path):
    """An explicitly configured path that is wrong is an error, not a hint to search.

    Silently loading a different copy of a 4B-parameter model's source than the one
    that was named is not noticed until the output is already wrong.
    """
    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    with pytest.raises(SculptorError, match="TRELLIS2_REPO_PATH"):
        Trellis2Backend._ensure_importable(tmp_path / "not-a-checkout")


def test_configured_checkout_is_authoritative(clean_env, tmp_path, monkeypatch):
    """A real checkout elsewhere must not rescue a wrong TRELLIS2_REPO_PATH."""
    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    decoy = tmp_path / "decoy"
    (decoy / "trellis2" / "pipelines").mkdir(parents=True)
    monkeypatch.setenv("TRELLIS2_REPO_PATH", str(tmp_path / "wrong"))
    monkeypatch.chdir(decoy)
    with pytest.raises(SculptorError, match="wrong"):
        Trellis2Backend._ensure_importable(None)


def test_configured_checkout_is_added_to_sys_path(clean_env, tmp_path, monkeypatch):
    import sys

    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    checkout = tmp_path / "TRELLIS.2"
    (checkout / "trellis2" / "pipelines").mkdir(parents=True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    Trellis2Backend._ensure_importable(checkout)
    assert str(checkout) in sys.path


def test_model_dir_prefers_populated_local_weights(clean_env, tmp_path, monkeypatch):
    """Re-downloading 4B parameters because a volume was ignored is expensive."""
    from pythonsrc.sculptors.trellis2 import DEFAULT_MODEL_ID, Trellis2Backend

    weights = tmp_path / "weights"
    weights.mkdir()
    monkeypatch.setenv("TRELLIS2_MODEL_PATH", str(weights))
    # Empty means "not yet downloaded" — fall through to the hub, do not point the
    # loader at a directory with nothing in it.
    assert Trellis2Backend._resolve_model_dir(None) == DEFAULT_MODEL_ID

    (weights / "pipeline.json").write_text("{}")
    assert Trellis2Backend._resolve_model_dir(None) == weights
    # An explicit argument still wins over the environment.
    assert Trellis2Backend._resolve_model_dir("other/repo") == "other/repo"


def test_local_backend_without_cuda_points_at_the_worker(clean_env, monkeypatch, tmp_path):
    """The error a GPU-less developer will actually hit must be actionable."""
    from pythonsrc.sculptors.trellis2 import Trellis2Backend

    checkout = tmp_path / "TRELLIS.2"
    (checkout / "trellis2" / "pipelines").mkdir(parents=True)
    monkeypatch.setenv("TRELLIS2_REPO_PATH", str(checkout))
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    with pytest.raises(SculptorError, match="remote"):
        Trellis2Backend()


def test_sampler_params_omit_unset_knobs():
    """A None would override the checkpoint's own default with nothing."""
    from pythonsrc.sculptors.trellis2 import _sampler_params

    assert _sampler_params(None, None) == {}
    assert _sampler_params(12, None) == {"steps": 12}
    assert _sampler_params(None, 7.5) == {"guidance_strength": 7.5}
