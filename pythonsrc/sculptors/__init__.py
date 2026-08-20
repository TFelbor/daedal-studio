"""
sculptors — Phase 2 reconstruction, powered by TRELLIS.2.

Three ways to run the same model:

    trellis2  In-process TRELLIS.2-4B. CUDA only, needs ~24 GB VRAM.
    remote    Delegates to a self-hosted GPU worker (see services/trellis2_worker).
    pixazo    Calls Pixazo's hosted TRELLIS.2 endpoint. €0,32 per generation.

All three produce geometry in the same frame and share
`SculptorBackend.postprocess`, so which one ran is a deployment detail rather than a
difference in output — the frame is the one thing that differs at the source, and
each backend declares its own `up_axis` for exactly that reason.

There is no CPU backend. TRELLIS.2's `o_voxel`, `flex_gemm` and `cumesh` are
compiled CUDA extensions with no CPU kernels, so a machine without an NVIDIA GPU —
every Apple Silicon Mac included — reaches the model through `remote` or `pixazo`,
or not at all. `auto` resolves accordingly.

Usage:
    from sculptors import create_sculptor

    sculptor = create_sculptor()                 # honours $P2P_SCULPTOR_BACKEND
    sculptor = create_sculptor("trellis2")       # explicit
    sculptor.generate_mesh(blueprint, out, target_faces=5000)
"""

from __future__ import annotations

import logging
import os

from .base import SculptorBackend, SculptorError

logger = logging.getLogger("p2p.sculptor")

BACKENDS = ("trellis2", "remote", "pixazo")
DEFAULT_BACKEND = "auto"

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "SculptorBackend",
    "SculptorError",
    "create_sculptor",
    "resolve_backend_name",
]


def _cuda_available() -> bool:
    """Report whether torch can see an NVIDIA GPU, without raising if torch is absent."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_backend_name(requested: str | None = None) -> str:
    """Resolve a backend name, expanding `auto` against what the host can run.

    Resolution order for `auto`, cheapest-and-most-explicit first:
      1. `remote`, if a worker URL is configured — the deliberate choice on a
         GPU-less host, and an explicit configuration outranks a local GPU that
         may be busy with Phase 1.
      2. `trellis2`, if an NVIDIA GPU is visible.
      3. `pixazo`, if a subscription key is configured. Last because it is the only
         backend that bills per call: hardware you already own should never be
         passed over in favour of one that charges. Selecting it is logged with the
         price, so a run that starts spending money says so.

    Args:
        requested: Explicit backend name, `auto`, or None to read
            `$P2P_SCULPTOR_BACKEND`.

    Returns:
        A concrete backend name from `BACKENDS`.

    Raises:
        SculptorError: If the name is unknown, or `auto` finds nothing runnable.
    """
    requested = (
        requested or os.environ.get("P2P_SCULPTOR_BACKEND") or DEFAULT_BACKEND
    ).strip().lower()

    if requested in BACKENDS:
        return requested

    if requested != "auto":
        raise SculptorError(
            f"Unknown sculptor backend '{requested}' — expected one of "
            f"{', '.join(BACKENDS)} or 'auto'"
        )

    if os.environ.get("P2P_SCULPTOR_REMOTE_URL"):
        logger.info("Auto-selected sculptor backend 'remote' (worker URL configured)")
        return "remote"

    if _cuda_available():
        logger.info("Auto-selected sculptor backend 'trellis2' (CUDA GPU available)")
        return "trellis2"

    if os.environ.get("PIXAZO_API_KEY"):
        from .pixazo import PRICE_EUR_PER_GENERATION

        logger.info(
            "Auto-selected sculptor backend 'pixazo' (subscription key configured) "
            "— this backend bills €%.2f per generation",
            PRICE_EUR_PER_GENERATION,
        )
        return "pixazo"

    raise SculptorError(
        "No runnable sculptor backend. TRELLIS.2 needs an NVIDIA GPU with ~24 GB of "
        "VRAM, and none is visible. Pick one of: run on a CUDA host; start the GPU "
        "worker (services/trellis2_worker/) and point P2P_SCULPTOR_REMOTE_URL at it; "
        "or set PIXAZO_API_KEY to use the hosted endpoint."
    )


def create_sculptor(
    backend: str | None = None,
    *,
    pipeline_type: str | None = None,
    seed: int | None = None,
    **kwargs,
) -> SculptorBackend:
    """Instantiate a sculptor backend.

    `pipeline_type` and `seed` are named rather than left to **kwargs because they
    are the two settings a caller wants to control without knowing where inference
    runs: for `trellis2` and `pixazo` they are constructor arguments, for `remote`
    they are form fields posted to the worker. Routing them here is what lets
    `pipeline.py` pass the same options either way.

    Args:
        backend: Backend name, `auto`, or None to read `$P2P_SCULPTOR_BACKEND`.
        pipeline_type: TRELLIS.2 voxel resolution, or None for the model default.
        seed: Sampling seed, or None for the model default.
        **kwargs: Forwarded to the backend constructor.

    Returns:
        A ready-to-use backend.

    Raises:
        SculptorError: If the name is unknown, or the backend cannot initialise
            (missing GPU, missing weights, unreachable worker).
    """
    name = resolve_backend_name(backend)

    if name == "trellis2":
        from .trellis2 import Trellis2Backend

        if pipeline_type:
            kwargs.setdefault("pipeline_type", pipeline_type)
        if seed is not None:
            kwargs.setdefault("seed", seed)
        return Trellis2Backend(**kwargs)

    if name == "pixazo":
        from .pixazo import PixazoBackend

        if pipeline_type:
            kwargs.setdefault("pipeline_type", pipeline_type)
        if seed is not None:
            kwargs.setdefault("seed", seed)
        return PixazoBackend(**kwargs)

    from .remote import RemoteSculptorBackend

    params = dict(kwargs.pop("params", None) or {})
    if pipeline_type:
        params.setdefault("pipeline_type", pipeline_type)
    if seed is not None:
        params.setdefault("seed", seed)
    return RemoteSculptorBackend(params=params, **kwargs)
