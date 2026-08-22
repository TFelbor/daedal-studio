"""Licence guards — the checks that keep Apache-2.0 coherent.

Prompt2Print ships under Apache-2.0, and Phase 2's upstream (TRELLIS.2) defaults to
two components that would break that grant if they ever loaded:

* **nvdiffrast / nvdiffrec** — NVIDIA Source Code License, non-commercial research
  only. Requested by upstream's documented install line.
* **`briaai/RMBG-2.0`** — CC BY-NC 4.0, commercial use by paid agreement only.
  Named outright in `microsoft/TRELLIS.2-4B`'s `pipeline.json` as the
  background-removal model.

Both are avoided structurally in the source, and both avoidances are one careless
edit from being undone — a `--nvdiffrast` added to fix a texture feature, a
"simplify this monkeypatch" refactor. Comments do not fail builds. These tests do.

Nothing here loads TRELLIS.2, torch or any weights. The guards are all statically
checkable, which is the point: they have to run in CI on a machine with no GPU.

See THIRD-PARTY-NOTICES.md for the full reasoning and the obligations that attach
to what this project *does* use.
"""

import importlib
import importlib.metadata
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

from pythonsrc.sculptors import SculptorError
from pythonsrc.sculptors.background import (
    DEFAULT_MATTE_MODEL_ID,
    NON_COMMERCIAL_MATTE_MODEL_IDS,
    PermissiveBiRefNet,
    assert_permissive_matte,
    permissive_rembg,
)
from pythonsrc.sculptors.trellis2 import SHAPE_ONLY_MODELS

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Packages under the NVIDIA Source Code License (non-commercial research only).
#: Upstream's `setup.sh` offers both behind flags this project never passes.
FORBIDDEN_RENDERER_PACKAGES = ("nvdiffrast", "nvdiffrec")

#: Files that install things. A prohibited package appearing in any of them is a
#: licence change, not a build tweak. Dockerfiles are discovered rather than
#: enumerated so a new or renamed image cannot slip past the guard.
INSTALL_MANIFESTS = (
    "requirements-base.txt",
    "requirements-linux.txt",
    "requirements-mac.txt",
    "requirements.txt",
    *sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "infra" / "docker").glob("*.Dockerfile")
    ),
)


# ── nvdiffrast / nvdiffrec: never installed, never imported ──────────────────


def test_forbidden_renderers_are_not_installed():
    """Neither NVIDIA renderer may be importable in the environment under test.

    A machine that can import these is a machine that could link them, and the
    licence turns on distribution of the artifact rather than on which line of code
    happens to call them.
    """
    for package in FORBIDDEN_RENDERER_PACKAGES:
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            spec = None
        assert spec is None, (
            f"{package} is importable here. It is licensed under the NVIDIA Source "
            "Code License (non-commercial research only) and must never be "
            "installed — see THIRD-PARTY-NOTICES.md. Uninstall it."
        )


def test_forbidden_renderers_are_not_declared_as_distributions():
    """Catch a wheel that installed under a different import name."""
    installed = {
        (dist.metadata["Name"] or "").lower().replace("_", "-")
        for dist in importlib.metadata.distributions()
    }
    for package in FORBIDDEN_RENDERER_PACKAGES:
        assert package not in installed, (
            f"Distribution '{package}' is installed — non-commercial licence. "
            "See THIRD-PARTY-NOTICES.md."
        )


@pytest.mark.parametrize("manifest", INSTALL_MANIFESTS)
def test_install_manifests_do_not_pull_forbidden_renderers(manifest):
    """No install manifest may name a forbidden renderer outside a comment.

    Comments naming them are expected and wanted — the worker Dockerfile explains
    why the flags are absent. What must not appear is an executable line.
    """
    path = REPO_ROOT / manifest
    if not path.exists():
        pytest.skip(f"{manifest} not present")

    offending = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(pkg in stripped.lower() for pkg in FORBIDDEN_RENDERER_PACKAGES):
            offending.append(f"{manifest}:{lineno}: {stripped}")

    assert not offending, (
        "Forbidden NVIDIA renderer referenced on an executable line:\n"
        + "\n".join(offending)
        + "\n\nBoth are non-commercial. If textured output is genuinely needed, the "
        "rasterizer must come from a permissive backend (PyTorch3D, BSD-3-Clause) — "
        "see THIRD-PARTY-NOTICES.md."
    )


def test_shape_only_models_exclude_the_texture_path():
    """The shape-only model list is what makes the rasterizer unnecessary.

    Texture decoding is the only thing on the image→3D path that leads to
    `o_voxel.postprocess.to_glb()`, which is the only thing that needs a
    rasterizer. Adding a `tex_slat_*` entry here is therefore the first step of
    reintroducing nvdiffrast, whether or not whoever adds it realises that.
    """
    texture_models = [name for name in SHAPE_ONLY_MODELS if "tex" in name]
    assert not texture_models, (
        f"Texture models in SHAPE_ONLY_MODELS: {texture_models}. Decoding a texture "
        "latent leads to to_glb(), which needs a rasterizer, and the only one "
        "upstream installs is non-commercially licensed."
    )


# ── Background removal: the checkpoint's default must never load ─────────────


def test_upstream_default_matte_model_is_denied():
    """`briaai/RMBG-2.0` must stay on the deny-list.

    It is what `microsoft/TRELLIS.2-4B`'s `pipeline.json` configures, so this is
    not a hypothetical — it is the value the code has to override every load.
    """
    assert "briaai/RMBG-2.0" in NON_COMMERCIAL_MATTE_MODEL_IDS


def test_configured_matte_model_is_permissively_licensed():
    """Whatever `$P2P_BIREFNET_MODEL_ID` resolves to must not be encumbered."""
    repo = DEFAULT_MATTE_MODEL_ID.partition("@")[0]
    assert repo not in NON_COMMERCIAL_MATTE_MODEL_IDS, (
        f"Background removal is configured to use '{DEFAULT_MATTE_MODEL_ID}', which "
        "is licensed for non-commercial use only. Unset P2P_BIREFNET_MODEL_ID."
    )


def test_matte_backend_refuses_an_encumbered_override():
    """Pointing `$P2P_BIREFNET_MODEL_ID` at BRIA weights must fail loudly."""
    import pythonsrc.sculptors.background as background

    original = background.DEFAULT_MATTE_MODEL_ID
    background.DEFAULT_MATTE_MODEL_ID = "briaai/RMBG-2.0"
    try:
        with pytest.raises(SculptorError, match="non-commercial"):
            PermissiveBiRefNet()
    finally:
        background.DEFAULT_MATTE_MODEL_ID = original


def test_permissive_backend_accepts_and_ignores_the_upstream_model_name():
    """Substitutability is the whole mechanism.

    Upstream constructs the matte as `BiRefNet(model_name="briaai/RMBG-2.0")`,
    straight from the checkpoint config. The replacement must swallow that argument
    and use its own weights — if the signature drifts, `from_pretrained` raises and
    Phase 2 stops working, which is safe but useless.
    """
    matte = PermissiveBiRefNet(model_name="briaai/RMBG-2.0")
    assert matte.model_id == DEFAULT_MATTE_MODEL_ID
    assert matte.model_id not in NON_COMMERCIAL_MATTE_MODEL_IDS


def test_permissive_backend_behaves_like_a_module_before_loading():
    """`preprocess_image` moves the matte between devices in low-VRAM mode.

    It does that whether or not weights have been loaded, so these have to be
    no-ops rather than attribute errors.
    """
    matte = PermissiveBiRefNet()
    assert matte.cuda() is matte
    assert matte.cpu() is matte
    assert matte.eval() is matte
    assert matte.to("cpu") is matte


@pytest.fixture
def fake_upstream_rembg(monkeypatch):
    """Stand in for `trellis2.pipelines.rembg` without a TRELLIS.2 checkout."""

    class UpstreamBiRefNet:
        """What upstream would construct — BRIA weights and a network call."""

        def __init__(self, model_name):  # pragma: no cover - must never run
            raise AssertionError(
                f"Upstream matte model was constructed with {model_name}"
            )

    trellis2 = types.ModuleType("trellis2")
    pipelines = types.ModuleType("trellis2.pipelines")
    rembg = types.ModuleType("trellis2.pipelines.rembg")
    rembg.BiRefNet = UpstreamBiRefNet
    pipelines.rembg = rembg
    trellis2.pipelines = pipelines

    monkeypatch.setitem(sys.modules, "trellis2", trellis2)
    monkeypatch.setitem(sys.modules, "trellis2.pipelines", pipelines)
    monkeypatch.setitem(sys.modules, "trellis2.pipelines.rembg", rembg)
    return rembg, UpstreamBiRefNet


def test_permissive_rembg_substitutes_then_restores(fake_upstream_rembg):
    """The substitution must be in place during the load and gone afterwards."""
    rembg, upstream_class = fake_upstream_rembg

    with permissive_rembg() as patched:
        assert patched is rembg
        assert rembg.BiRefNet is PermissiveBiRefNet
        # Construction the way `from_pretrained` does it, straight off the config.
        instance = rembg.BiRefNet(model_name="briaai/RMBG-2.0")
        assert isinstance(instance, PermissiveBiRefNet)

    assert rembg.BiRefNet is upstream_class


def test_permissive_rembg_restores_after_an_exception(fake_upstream_rembg):
    """A failed model load must not leave upstream's class shadowed."""
    rembg, upstream_class = fake_upstream_rembg

    with pytest.raises(RuntimeError):
        with permissive_rembg():
            raise RuntimeError("load failed")

    assert rembg.BiRefNet is upstream_class


def test_permissive_rembg_fails_loudly_when_upstream_moves(monkeypatch):
    """No silent pass-through.

    If the module cannot be found the substitution cannot be installed, and loading
    anyway would fetch the non-commercial weights. Better to break Phase 2 than the
    licence.
    """
    for name in ("trellis2", "trellis2.pipelines", "trellis2.pipelines.rembg"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "path", [])

    with pytest.raises(SculptorError, match="background removal"):
        with permissive_rembg():  # pragma: no cover - body must not execute
            pass


def test_assert_permissive_matte_accepts_the_substitute():
    pipeline = types.SimpleNamespace(rembg_model=PermissiveBiRefNet())
    assert_permissive_matte(pipeline)  # must not raise


@pytest.mark.parametrize(
    "matte",
    [None, object(), types.SimpleNamespace()],
    ids=["missing", "foreign-object", "namespace"],
)
def test_assert_permissive_matte_rejects_anything_else(matte):
    """Checks the outcome, not the mechanism.

    The context manager relies on upstream resolving its config through `getattr`.
    The day that changes, this is what notices — the pipeline would otherwise hold
    a BRIA-backed matte and nothing would say so.
    """
    pipeline = types.SimpleNamespace(rembg_model=matte)
    with pytest.raises(SculptorError, match="briaai/RMBG-2.0"):
        assert_permissive_matte(pipeline)


# ── Attribution obligations ─────────────────────────────────────────────────


def test_dinov3_attribution_is_present_in_the_ui():
    """"Built with DINOv3" is a licence condition, so it must survive refactors.

    DINOv3 is TRELLIS.2's image conditioner and cannot be swapped out, so every
    build of this app uses it and every build owes the attribution.
    """
    app = (REPO_ROOT / "web" / "src" / "App.tsx").read_text()
    assert "Built with DINOv3" in app, (
        "The DINOv3 attribution has been removed from the UI shell. The DINOv3 "
        "License permits commercial use only alongside prominent attribution — see "
        "THIRD-PARTY-NOTICES.md."
    )


@pytest.mark.parametrize("document", ["README.md", "THIRD-PARTY-NOTICES.md"])
def test_dinov3_attribution_is_present_in_the_docs(document):
    text = (REPO_ROOT / document).read_text()
    assert "Built with DINOv3" in text


def test_notices_records_both_overridden_upstream_defaults():
    """The notices file is the audit trail; an undocumented override is not one."""
    notices = (REPO_ROOT / "THIRD-PARTY-NOTICES.md").read_text()
    for token in ("briaai/RMBG-2.0", "nvdiffrast", "nvdiffrec", "CC BY-NC 4.0"):
        assert token in notices, f"THIRD-PARTY-NOTICES.md no longer mentions {token}"


def test_notices_review_date_is_iso_formatted():
    """A stale review date is a lie about when this was last checked."""
    notices = (REPO_ROOT / "THIRD-PARTY-NOTICES.md").read_text()
    match = re.search(r"Last reviewed:\s*(\d{4}-\d{2}-\d{2})", notices)
    assert match, "THIRD-PARTY-NOTICES.md must carry a 'Last reviewed: YYYY-MM-DD' line"


# ── Deny-list normalisation ───────────────────────────────────────────────────
#
# The deny-list used to compare the raw configured string while `_load` fetched
# `model_id.partition("@")[0]`. Pinning a revision — which .env.template recommends —
# therefore produced a value that passed the guard and downloaded the CC BY-NC
# weights anyway. These pin the normalisation that closed that.


@pytest.mark.parametrize(
    "model_id",
    [
        "briaai/RMBG-2.0",
        "briaai/RMBG-1.4",
        "briaai/RMBG-2.0@abc123def",      # pinned revision — the documented form
        "briaai/RMBG-2.0@main",
        "BriaAI/RMBG-2.0",                # HF resolves org names case-insensitively
        "  briaai/RMBG-2.0  ",
    ],
)
def test_encumbered_matte_ids_are_denied_however_they_are_spelled(model_id):
    from pythonsrc.sculptors.background import denied_matte_repo

    assert denied_matte_repo(model_id) is True


@pytest.mark.parametrize(
    "model_id",
    ["ZhengPeng7/BiRefNet", "ZhengPeng7/BiRefNet@v1.0", None, ""],
)
def test_permissive_matte_ids_are_not_denied(model_id):
    from pythonsrc.sculptors.background import denied_matte_repo

    assert denied_matte_repo(model_id) is False


def test_a_pinned_encumbered_revision_is_refused_at_construction(monkeypatch):
    """The exact bypass: .env.template tells you to pin a revision."""
    import importlib

    monkeypatch.setenv("P2P_BIREFNET_MODEL_ID", "briaai/RMBG-2.0@abc123def")
    import pythonsrc.sculptors.background as bg

    bg = importlib.reload(bg)
    try:
        with pytest.raises(Exception, match="non-commercial"):
            bg.PermissiveBiRefNet()
    finally:
        monkeypatch.delenv("P2P_BIREFNET_MODEL_ID", raising=False)
        importlib.reload(bg)


# ── The blueprint image screen's own weights ─────────────────────────────────
#
# The screen added for IP detection is itself a model load, which makes it the newest
# instance of the rule this file exists for: **weights carry a licence independent of
# the library that loads them, and independent of the repository's own tag.**
#
# `openai/clip-vit-base-patch32` is the sharpest example this project has found. Its
# Hugging Face repo is tagged MIT. Its model card says: "Any deployed use case of the
# model - whether commercial or not - is currently out of scope." A dependency audit
# that reads tags would clear it.


def test_the_blueprint_screen_defaults_to_a_permissive_checkpoint():
    from pythonsrc.ip_screen_image import DEFAULT_MODEL_ID, assert_permissive_vision_model

    assert assert_permissive_vision_model(DEFAULT_MODEL_ID)


def test_openai_clip_is_on_the_deny_list_for_its_model_card_not_its_tag():
    """The tag says MIT; the card forbids deployed use. The card governs."""
    from pythonsrc.ip_screen_image import DENIED_MODEL_REPOS

    reason = DENIED_MODEL_REPOS["openai/clip-vit-base-patch32"]
    assert "out of scope" in reason.lower()


def test_the_screen_refuses_to_load_a_denied_checkpoint():
    import pytest as _pytest

    from pythonsrc.ip_screen_image import assert_permissive_vision_model

    with _pytest.raises(ValueError, match="not permissively licensed"):
        assert_permissive_vision_model("openai/clip-vit-base-patch32")


def test_notices_records_the_screen_model_and_the_rejected_one():
    """An undocumented model choice is not an audit trail, and the *rejection* is the
    part a future reader needs: without it, someone swaps in CLIP for better recall."""
    notices = (REPO_ROOT / "THIRD-PARTY-NOTICES.md").read_text()

    assert "google/siglip-base-patch16-224" in notices
    assert "openai/clip-vit-" in notices
    assert "out of scope" in notices


def test_the_screen_stores_no_reference_images():
    """Recall could be improved by caching crops of the characters being detected.

    That would mean this repository shipping the material the screen exists to keep
    out, so the candidates are text and this asserts they stay text.
    """
    from pythonsrc.ip_screen_image import candidate_labels

    assert all(isinstance(label, str) for label in candidate_labels())


def test_the_image_screen_is_not_imported_by_the_api_server():
    """`infra/docker/server.Dockerfile` installs no torch, transformers or numpy.

    An import of the image screen at module scope in `server/app.py` would take the
    api-server image down at start-up — and it is the one image that does not need it,
    because the screen runs in the pipeline and visualizer processes.
    """
    app_source = (REPO_ROOT / "server" / "app.py").read_text()

    assert "ip_screen_image" not in app_source, (
        "server/app.py imports the image screen. The api-server image has no torch; "
        "keep the image screen in the pipeline and visualizer processes."
    )
