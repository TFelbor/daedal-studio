"""
background.py — licence-clean background removal for Phase 2's image conditioning.

TRELLIS.2 cuts the subject out of the input image before conditioning on it, and
premultiplies the cut-out, which is how the model was trained. That step is
upstream's and this module does not change *what* it does — only *which weights*
do it.

## Why this module exists

`microsoft/TRELLIS.2-4B`'s `pipeline.json` configures background removal as:

    "rembg_model": { "name": "BiRefNet", "args": { "model_name": "briaai/RMBG-2.0" } }

The **class** is BiRefNet (MIT, `ZhengPeng7/BiRefNet`). The **weights** are BRIA
RMBG-2.0, published under **CC BY-NC 4.0** — non-commercial unless you hold a paid
agreement with BRIA. This is the same hazard that forced `rembg==2.0.69` while
TripoSR was Phase 2, arriving by a different route: not a library's shifting
default, but a named entry in an upstream config file. Naming a repo explicitly is
no protection when the repo someone else named is the encumbered one.

So `PermissiveBiRefNet` is a drop-in for upstream's `BiRefNet` that runs the same
architecture on MIT weights, and `permissive_rembg()` installs it *around*
`Pipeline.from_pretrained`. Installing it before construction rather than
reassigning `pipeline.rembg_model` afterwards is deliberate: upstream builds the
rembg model eagerly, so a later swap would still have downloaded the BRIA weights
and accepted their gated-repo terms to get there.

Applies to the `trellis2` and `remote` backends — the worker runs this same code,
so one fix covers both. It does **not** apply to `pixazo`: that endpoint runs
someone else's deployment of the pipeline, where this is a contractual question
rather than a code one. See THIRD-PARTY-NOTICES.md.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

import numpy as np
from PIL import Image

from .base import SculptorError

logger = logging.getLogger("ds.sculptor.background")

#: MIT-licensed BiRefNet weights — the same architecture upstream's class expects.
#: Overridable so a self-hosted mirror or a pinned revision needs no code change.
DEFAULT_MATTE_MODEL_ID = os.environ.get(
    "DS_BIREFNET_MODEL_ID", "ZhengPeng7/BiRefNet"
)

#: Weights that must never be loaded by this project. Each is free for
#: non-commercial use only and requires a paid agreement otherwise. `briaai/RMBG-2.0`
#: is upstream TRELLIS.2's configured default, which is precisely why it is listed
#: here rather than merely avoided in passing. Enforced by
#: `tests/test_licensing_guards.py`.
NON_COMMERCIAL_MATTE_MODEL_IDS = frozenset(
    {
        "briaai/RMBG-2.0",
        "briaai/RMBG-1.4",
    }
)


def denied_matte_repo(model_id: str | None) -> bool:
    """Is `model_id` one of the non-commercial matte repos, however it is spelled?

    Compare on the *repo*, not the raw configured string. `_load` fetches
    ``model_id.partition("@")[0]``, so a deny-list consulted on the raw value checks
    something the loader never uses: `.env.template` recommends pinning a revision,
    and `briaai/RMBG-2.0@<sha>` therefore passed the guard and then downloaded the
    CC BY-NC weights regardless. Hugging Face resolves org and repo names
    case-insensitively, so this does too — a guard that `BriaAI/RMBG-2.0` slips past
    is not a guard.
    """
    if not model_id:
        return False
    repo = model_id.partition("@")[0].strip().strip("/").lower()
    return repo in _DENIED_MATTE_REPOS


#: Deny-list normalised the same way `denied_matte_repo` normalises its argument.
_DENIED_MATTE_REPOS = frozenset(
    m.partition("@")[0].strip().strip("/").lower()
    for m in NON_COMMERCIAL_MATTE_MODEL_IDS
)

#: Working resolution BiRefNet was trained at. The mask is resized back afterwards.
_MATTE_RESOLUTION = 1024

# ImageNet statistics, as used by the BiRefNet model card's own preprocessing.
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

#: A matte with no pixel above this is empty in practice. Upstream derives a
#: bounding box from the alpha channel immediately afterwards and an all-zero alpha
#: gives it nothing to crop, so this fails here with a diagnosis instead of there
#: with an index error.
_MIN_USEFUL_ALPHA = 8


class PermissiveBiRefNet:
    """Background removal on MIT weights, shaped like upstream's `BiRefNet`.

    The call contract is upstream's: an RGB `PIL.Image` in, an **RGBA**
    `PIL.Image` out whose alpha channel is the subject matte.
    `Trellis2ImageTo3DPipeline.preprocess_image` then crops to the alpha bounding
    box, resizes and premultiplies.

    Args:
        model_name: Accepted and **ignored** so this class is substitutable for
            upstream's, which is constructed as
            `BiRefNet(model_name="briaai/RMBG-2.0")` straight from the checkpoint's
            `pipeline.json`. The requested id is logged when it differs, because a
            substitution nobody can see in the logs is one nobody can audit.
        device: Torch device string. Defaults to CUDA, then MPS, then CPU.

    Note:
        Loaded with `trust_remote_code=True`, matching upstream. That executes
        modelling code fetched from the Hugging Face Hub at load time — an MIT
        licence, but still remote code execution. Pin a revision via
        `$DS_BIREFNET_MODEL_ID` (`repo@sha`) before any untrusted deployment.
    """

    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self.model_id = DEFAULT_MATTE_MODEL_ID
        if model_name and model_name != self.model_id:
            level = (
                logging.WARNING
                if denied_matte_repo(model_name)
                else logging.INFO
            )
            logger.log(
                level,
                "Background removal: substituting %s for the configured %s%s",
                self.model_id,
                model_name,
                (
                    " (non-commercial licence — see THIRD-PARTY-NOTICES.md)"
                    if denied_matte_repo(model_name)
                    else ""
                ),
            )
        if denied_matte_repo(self.model_id):
            raise SculptorError(
                f"Refusing to load '{self.model_id}' for background removal: it is "
                "licensed for non-commercial use only. Unset or correct "
                "DS_BIREFNET_MODEL_ID — see THIRD-PARTY-NOTICES.md."
            )

        self._requested_device = device
        self._device = None
        self._model = None

    # ── Module-like surface, so the pipeline can move this around like a model ──

    def to(self, device) -> "PermissiveBiRefNet":
        """Move the loaded model, remembering the target if nothing is loaded yet.

        `preprocess_image` calls `.to(device)` / `.cpu()` around the matte when the
        pipeline is in low-VRAM mode, so this has to behave like an `nn.Module`
        even before the weights exist.
        """
        self._requested_device = str(device)
        if self._model is not None:
            self._model.to(device)
            self._device = str(device)
        return self

    def cpu(self) -> "PermissiveBiRefNet":
        return self.to("cpu")

    def cuda(self) -> "PermissiveBiRefNet":
        return self.to("cuda")

    def eval(self) -> "PermissiveBiRefNet":
        # `nn.Module.eval()` — evaluation mode, not the Python builtin.
        if self._model is not None:
            self._model.eval()
        return self

    # ── Inference ─────────────────────────────────────────────────────────────

    def _resolve_device(self) -> str:
        if self._requested_device:
            return self._requested_device
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load(self):
        """Load the segmentation weights on first use.

        Lazy because the shape-only path hands the pipeline an already-cut-out image
        often enough that a job may never need this at all, and half a gigabyte of
        weights should not be fetched to find that out.
        """
        if self._model is not None:
            return self._model

        import torch
        from transformers import AutoModelForImageSegmentation

        repo, _, revision = self.model_id.partition("@")
        logger.info("Loading background-removal weights: %s", self.model_id)
        try:
            model = AutoModelForImageSegmentation.from_pretrained(
                repo,
                revision=revision or None,
                trust_remote_code=True,
            )
        except Exception as exc:
            raise SculptorError(
                f"Could not load background-removal weights '{self.model_id}': {exc}"
            ) from exc

        self._device = self._resolve_device()
        model.to(self._device)
        model.eval()
        # BiRefNet's own card runs the model in half precision on CUDA. Kept to
        # float32 elsewhere: MPS and CPU half-precision paths are slower or absent.
        if self._device == "cuda":
            model.half()
        self._model = model
        logger.debug("Background-removal model ready on %s", self._device)
        return model

    def __call__(self, image: Image.Image) -> Image.Image:
        """Return `image` as RGBA, alpha set to the predicted subject matte."""
        import torch

        model = self._load()
        source = image.convert("RGB")

        batch = self._to_batch(source)
        batch = batch.to(self._device)
        if self._device == "cuda":
            batch = batch.half()

        with torch.no_grad():
            prediction = model(batch)[-1].sigmoid().float().cpu()

        matte = self._to_mask(prediction, source.size)
        output = source.convert("RGBA")
        output.putalpha(matte)
        return output

    @staticmethod
    def _to_batch(image: Image.Image):
        """Resize, normalise and pack one image into a 1×3×H×W float tensor."""
        import torch

        resized = image.resize((_MATTE_RESOLUTION, _MATTE_RESOLUTION), Image.BICUBIC)
        array = np.asarray(resized, dtype=np.float32) / 255.0
        array = (array - _IMAGENET_MEAN) / _IMAGENET_STD
        return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)

    @staticmethod
    def _to_mask(prediction, size: tuple[int, int]) -> Image.Image:
        """Turn the model's logits into an 8-bit mask at the source resolution."""
        array = prediction.squeeze().numpy()
        mask = np.clip(array * 255.0, 0, 255).astype(np.uint8)
        if mask.max() < _MIN_USEFUL_ALPHA:
            raise SculptorError(
                "Background removal found no subject in the blueprint — the image is "
                "probably blank or the subject fills no distinguishable region. "
                "Re-run Phase 1, or pass an RGBA blueprint with its own alpha."
            )
        return Image.fromarray(mask, mode="L").resize(size, Image.BICUBIC)


@contextmanager
def permissive_rembg():
    """Make upstream's `BiRefNet` resolve to `PermissiveBiRefNet` for this block.

    `Trellis2ImageTo3DPipeline.from_pretrained` builds the matte model by name off
    the checkpoint's config:

        pipeline.rembg_model = getattr(rembg, args["rembg_model"]["name"])(
            **args["rembg_model"]["args"]
        )

    `getattr` runs against the `trellis2.pipelines.rembg` module object at call
    time, so rebinding that one attribute for the duration of the load is enough,
    and the original is restored afterwards.

    Raises:
        SculptorError: If the upstream module cannot be found. Loading anyway would
            silently fetch `briaai/RMBG-2.0` under a non-commercial licence, so an
            upstream reshuffle has to break the build rather than the licence.
    """
    try:
        from trellis2.pipelines import rembg as rembg_module
    except Exception as exc:
        raise SculptorError(
            "Could not import trellis2.pipelines.rembg to install licence-clean "
            "background removal. Upstream TRELLIS.2 has moved it; re-point "
            "pythonsrc/sculptors/background.permissive_rembg() before running Phase "
            f"2, or the checkpoint's non-commercial default will load. ({exc})"
        ) from exc

    sentinel = object()
    original = getattr(rembg_module, "BiRefNet", sentinel)
    rembg_module.BiRefNet = PermissiveBiRefNet
    try:
        yield rembg_module
    finally:
        if original is sentinel:
            del rembg_module.BiRefNet
        else:
            rembg_module.BiRefNet = original


def assert_permissive_matte(pipeline) -> None:
    """Fail unless the loaded pipeline's matte model is the permissive substitute.

    The context manager above depends on an upstream construction detail. This
    checks the outcome instead of the mechanism, so the day upstream stops reading
    `pipeline.json` through `getattr` this raises rather than quietly reverting to
    BRIA weights.

    Raises:
        SculptorError: If the pipeline holds anything other than
            `PermissiveBiRefNet`.
    """
    matte = getattr(pipeline, "rembg_model", None)
    if isinstance(matte, PermissiveBiRefNet):
        return
    raise SculptorError(
        "TRELLIS.2 loaded its own background-removal model "
        f"({type(matte).__name__}) instead of the licence-clean substitute. "
        "The checkpoint's default is briaai/RMBG-2.0 (CC BY-NC 4.0), which this "
        "project must not run. Fix pythonsrc/sculptors/background.py before "
        "proceeding — see THIRD-PARTY-NOTICES.md."
    )
