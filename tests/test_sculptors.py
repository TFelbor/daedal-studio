"""Phase 2 sculptor backend tests.

Nothing here loads TRELLIS.2. The model needs an NVIDIA GPU with ~24 GB of VRAM
and four compiled CUDA extensions, so the suite would not run anywhere useful if
it did. What *is* tested is everything around it: backend resolution, the shared
post-processing every backend depends on, and the client↔worker wire contract —
which is precisely where a mesh silently comes out lying on its side.
"""

import io
import os
import types

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
    # A developer with a real subscription key exported would otherwise see `auto`
    # resolve to `pixazo` and the "nothing is runnable" test fail for the wrong
    # reason. The key is the whole input to that branch, so it belongs here.
    "PIXAZO_API_KEY",
    "P2P_PIXAZO_GATEWAY",
    "P2P_PIXAZO_IMAGE_BASE_URL",
    "P2P_PIXAZO_UP_AXIS",
    # conftest sets this suite-wide so no test can spend money. These tests only
    # *construct* the backend and stub its HTTP, so they opt out — deliberately and
    # locally. `test_kill_switch_refuses_to_construct_the_paid_backend` below is the
    # one that asserts the switch itself works.
    "P2P_DISABLE_PAID_BACKENDS",
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
    assert remote.last_generation_cost_eur is None


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


# ── Hosted backend (Pixazo) ───────────────────────────────────────────────────


@pytest.fixture
def pixazo(clean_env):
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    return PixazoBackend()


def test_auto_selects_pixazo_when_only_a_key_is_configured(clean_env):
    """The Apple Silicon case: no CUDA, no worker, but a subscription key."""
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: False)
    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    assert resolve_backend_name("auto") == "pixazo"


def test_auto_prefers_a_local_gpu_over_the_paid_endpoint(clean_env):
    """Hardware already paid for must never be passed over for one that bills."""
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: True)
    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    assert resolve_backend_name("auto") == "trellis2"


def test_auto_prefers_a_self_hosted_worker_over_the_paid_endpoint(clean_env):
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: False)
    clean_env.setenv("P2P_SCULPTOR_REMOTE_URL", "http://gpu-host:8100")
    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    assert resolve_backend_name("auto") == "remote"


def test_no_backend_message_names_the_hosted_option(clean_env):
    clean_env.setattr("pythonsrc.sculptors._cuda_available", lambda: False)
    with pytest.raises(SculptorError, match="PIXAZO_API_KEY"):
        resolve_backend_name("auto")


def test_pixazo_without_a_key_is_rejected_at_construction(clean_env):
    with pytest.raises(SculptorError, match="needs a subscription key"):
        create_sculptor("pixazo")


def test_pixazo_is_a_hosted_api_backend(pixazo):
    """`local` would imply no charge; `remote_worker` would imply a GPU we own."""
    assert pixazo.BACKEND == "hosted_api"
    assert pixazo.MODEL_NAME == "TRELLIS.2"


def test_pixazo_output_is_treated_as_y_up(pixazo):
    """GLB is glTF's frame, not the model's. Getting this wrong prints on its side."""
    assert pixazo.up_axis == "y"


def test_pixazo_up_axis_is_overridable_without_a_code_change(clean_env):
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.setenv("P2P_PIXAZO_UP_AXIS", "Z")
    assert PixazoBackend().up_axis == "z"


@pytest.mark.parametrize(
    "pipeline_type,resolution",
    [("512", 512), ("1024", 1024), ("1024_cascade", 1024), ("1536_cascade", 1536)],
)
def test_pipeline_type_maps_onto_the_api_resolution(clean_env, pipeline_type, resolution):
    """The hosted API has no cascade sampler, so both cascades collapse."""
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    assert PixazoBackend(pipeline_type=pipeline_type).resolution == resolution


def test_pixazo_rejects_an_unknown_pipeline_type(clean_env):
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    with pytest.raises(SculptorError, match="Invalid pipeline_type"):
        PixazoBackend(pipeline_type="2048")


def test_generation_params_records_both_the_request_and_what_was_sent(clean_env):
    """A collapsed cascade must not look like a native 1024 run in the dataset."""
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    params = PixazoBackend(pipeline_type="1024_cascade", seed=7).generation_params()
    assert params["sculptor_backend"] == "pixazo"
    assert params["pipeline_type"] == "1024_cascade"
    assert params["resolution"] == 1024
    assert params["mesh_seed"] == 7
    assert params["price_eur"] == 0.32


def test_unset_knobs_are_absent_from_the_payload_not_null(clean_env):
    """A null would override the endpoint's documented default with nothing.

    `decimation_target` is passed explicitly as None here because the backend now
    defaults it to 200k — see `test_decimation_target_is_capped_by_default`. What is
    under test is that an *unset* knob is omitted, not sent as null.
    """
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    backend = PixazoBackend(decimation_target=None)
    payload = backend._payload("https://example.test/b.png")
    assert payload == {"image_url": "https://example.test/b.png", "resolution": 1024}


def test_set_knobs_reach_the_payload_under_the_api_field_names(clean_env):
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    backend = PixazoBackend(seed=7, shape_steps=20, ss_guidance=6.5)
    payload = backend._payload("https://example.test/b.png")
    assert payload["seed"] == 7
    assert payload["shape_slat_sampling_steps"] == 20
    assert payload["ss_guidance_strength"] == 6.5


def test_subscription_key_is_sent_in_the_gateway_header(pixazo):
    assert pixazo._headers() == {"Ocp-Apim-Subscription-Key": "key-123"}


def test_blueprint_is_inlined_as_a_data_uri_by_default(pixazo, blueprint):
    """Zero-infrastructure default: a working Phase 2 beats one needing a bucket."""
    url = pixazo._resolve_image_url(blueprint)
    assert url.startswith("data:image/png;base64,")
    assert len(url) > len("data:image/png;base64,")


def test_a_public_base_url_is_used_when_configured(clean_env, blueprint):
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.setenv("P2P_PIXAZO_IMAGE_BASE_URL", "https://cdn.test/bp/")
    url = PixazoBackend()._resolve_image_url(blueprint)
    assert url == f"https://cdn.test/bp/{blueprint.name}"


def test_a_rejected_submit_books_no_charge(pixazo, blueprint):
    """Nothing was accepted, so nothing was billed."""
    def _boom(_url):
        raise SculptorError("submit failed")

    pixazo._submit = _boom
    with pytest.raises(SculptorError):
        pixazo.reconstruct(blueprint)
    assert pixazo.last_generation_cost_eur is None


def test_an_accepted_submit_books_the_charge_even_if_it_never_delivers(pixazo, blueprint):
    """The gateway bills on acceptance, so a later timeout is still money spent.

    Recording the cost only on success made every failed-after-submit job read as
    free — understating real spend in exactly the column that exists to measure it.
    """
    pixazo._submit = lambda _url: "req-timeout"

    def _never(_rid):
        raise SculptorError("did not finish within 600s")

    pixazo._await_result = _never
    with pytest.raises(SculptorError):
        pixazo.reconstruct(blueprint)
    assert pixazo.last_generation_cost_eur == 0.32
    assert pixazo.last_request_id == "req-timeout"


def test_cost_is_recorded_once_a_mesh_comes_back(pixazo, blueprint):
    mesh = trimesh.creation.box(extents=(1, 10, 1))
    pixazo._submit = lambda _url: "req-1"
    pixazo._await_result = lambda _rid: "https://cdn.test/out.glb"
    pixazo._download_mesh = lambda _url: mesh

    assert pixazo.reconstruct(blueprint) is mesh
    assert pixazo.last_generation_cost_eur == 0.32
    assert pixazo.last_request_id == "req-1"
    assert pixazo.generation_params()["request_id"] == "req-1"


def _stub_requests(monkeypatch, body):
    """Make `import requests` inside the backend yield a stub returning `body`.

    The backend imports requests inside the method, so replacing the module in
    `sys.modules` is what the call actually sees — patching an attribute on the
    backend module would not be reached.
    """
    import sys

    import requests as real

    class _Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return body

    stub = types.SimpleNamespace(
        get=lambda *a, **k: _Response(),
        post=lambda *a, **k: _Response(),
        exceptions=real.exceptions,
    )
    monkeypatch.setitem(sys.modules, "requests", stub)


def test_a_failed_generation_surfaces_the_gateway_reason(pixazo, monkeypatch):
    """An ERROR status must not be polled to the timeout as if still running."""
    _stub_requests(monkeypatch, {"status": "ERROR", "error": "unsupported image"})
    with pytest.raises(SculptorError, match="unsupported image"):
        pixazo._await_result("req-1")


def test_a_completed_generation_with_no_media_url_is_an_error(pixazo, monkeypatch):
    """COMPLETED-but-empty is a billed call with nothing to show; never return None."""
    _stub_requests(monkeypatch, {"status": "COMPLETED", "output": {"media_url": []}})
    with pytest.raises(SculptorError, match="no media_url"):
        pixazo._await_result("req-1")


def test_the_output_mesh_url_is_read_from_media_url(pixazo, monkeypatch):
    _stub_requests(
        monkeypatch,
        {"status": "COMPLETED", "output": {"media_url": ["https://cdn.test/out.glb"]}},
    )
    assert pixazo._await_result("req-1") == "https://cdn.test/out.glb"


def test_kill_switch_refuses_to_construct_the_paid_backend(clean_env):
    """The suite-wide guard against accidental spending must actually bite.

    Set by `conftest.pytest_configure`, forwarded into the pipeline container by
    `server.app`, and honoured here — an environment that asked not to be billed
    gets an error instead of a EUR 0.32 charge.
    """
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.setenv("P2P_DISABLE_PAID_BACKENDS", "1")
    with pytest.raises(SculptorError, match="disabled by P2P_DISABLE_PAID_BACKENDS"):
        PixazoBackend()


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_kill_switch_falsey_values_do_not_disable(clean_env, value):
    """`P2P_DISABLE_PAID_BACKENDS=0` must mean enabled, not "the string is truthy"."""
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.setenv("P2P_DISABLE_PAID_BACKENDS", value)
    assert PixazoBackend().name == "pixazo"


def test_kill_switch_is_checked_before_the_api_key(clean_env):
    """Order matters: a disabled environment must not report a missing-key error.

    Reporting "set PIXAZO_API_KEY" to someone who deliberately disabled the backend
    invites them to fix the wrong thing — by adding a key, which is how the spending
    starts.
    """
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("P2P_DISABLE_PAID_BACKENDS", "1")
    with pytest.raises(SculptorError, match="disabled by P2P_DISABLE_PAID_BACKENDS"):
        PixazoBackend()


def test_decimation_target_is_capped_by_default(clean_env):
    """The endpoint defaults to 500k faces; a real job died on 462k."""
    from pythonsrc.sculptors.pixazo import PixazoBackend, DEFAULT_DECIMATION_TARGET

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.delenv("P2P_DISABLE_PAID_BACKENDS", raising=False)
    backend = PixazoBackend()
    assert backend.decimation_target == DEFAULT_DECIMATION_TARGET == 200_000
    assert backend._payload("https://x/y.png")["decimation_target"] == 200_000


def test_purchased_glb_is_cached_before_post_processing(clean_env, blueprint, tmp_path):
    """A billed artifact must reach disk before anything that can fail touches it."""
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.delenv("P2P_DISABLE_PAID_BACKENDS", raising=False)
    backend = PixazoBackend()

    mesh = trimesh.creation.box(extents=(1, 10, 1))
    glb = mesh.export(file_type="glb")

    backend._submit = lambda _url: "req-42"
    backend._await_result = lambda _rid: "https://cdn.test/out.glb"

    def _fake_download(url):
        # Stands in for the real download, which caches the bytes the moment they
        # land — before parsing, and before postprocess can fail.
        backend._cache_glb(glb)
        return mesh

    backend._download_mesh = _fake_download
    out = tmp_path / "job" / "raw_mesh.obj"
    backend.generate_mesh(blueprint, out, target_faces=0)

    cached = list((tmp_path / "job").glob("pixazo_*.glb"))
    assert cached, "purchased GLB was not cached"
    assert cached[0].name == "pixazo_req-42.glb"
    assert cached[0].read_bytes() == glb


def test_caching_failure_never_loses_the_bought_mesh(clean_env):
    """A cache miss must not raise — the caller already paid for these bytes."""
    from pythonsrc.sculptors.pixazo import PixazoBackend

    clean_env.setenv("PIXAZO_API_KEY", "key-123")
    clean_env.delenv("P2P_DISABLE_PAID_BACKENDS", raising=False)
    backend = PixazoBackend()
    backend.artifact_dir = "/proc/nonexistent/definitely-not-writable"
    backend._cache_glb(b"bytes")  # must not raise
