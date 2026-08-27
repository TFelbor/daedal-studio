"""
sculptor.py — Phase 2: 3D reconstruction from a blueprint image, with TRELLIS.2.

The implementation lives in `sculptors/`; this module is the stable entry point that
`pipeline.py`, the Phase 2 container and the CLI all go through.

Usage:
    python pythonsrc/sculptor.py [--blueprint PATH] [--output PATH] [--faces N]
                                 [--backend auto|trellis2|remote|pixazo] [--verbose]

Backends:
    trellis2  In-process TRELLIS.2-4B. Needs an NVIDIA GPU with ~24 GB VRAM.
    remote    Posts the blueprint to a GPU worker (services/trellis2_worker).
    pixazo    Calls Pixazo's hosted TRELLIS.2 endpoint. EUR 0,32 per generation,
              and the only backend that runs on an Apple Silicon Mac.
    auto      remote if $DS_SCULPTOR_REMOTE_URL is set, else trellis2 if CUDA
              is visible, else pixazo if $PIXAZO_API_KEY is set.
"""

from __future__ import annotations

import logging

try:
    from sculptors import (
        BACKENDS,
        DEFAULT_TARGET_FACES,
        SculptorBackend,
        SculptorError,
        create_sculptor,
        resolve_backend_name,
    )
except ImportError:  # pragma: no cover - depends on how the caller set sys.path
    from pythonsrc.sculptors import (  # type: ignore[no-redef]
        BACKENDS,
        DEFAULT_TARGET_FACES,
        SculptorBackend,
        SculptorError,
        create_sculptor,
        resolve_backend_name,
    )

logger = logging.getLogger("ds.sculptor")

__all__ = [
    "BACKENDS",
    "DEFAULT_TARGET_FACES",
    "SculptorBackend",
    "SculptorError",
    "create_sculptor",
    "resolve_backend_name",
]


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=logging.DEBUG if verbose else logging.INFO,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import os
    import sys

    try:
        from config import INPUTS_DIR, OUTPUTS_DIR
    except ImportError:
        from pythonsrc.config import INPUTS_DIR, OUTPUTS_DIR

    parser = argparse.ArgumentParser(
        description="ds-mvp Phase 2 — Sculptor (TRELLIS.2 image→3D)"
    )
    parser.add_argument(
        "--blueprint",
        default=os.path.join(INPUTS_DIR, "blueprint.png"),
        help="Path to the input blueprint image (default: data/inputs/blueprint.png)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(OUTPUTS_DIR, "test_mesh.obj"),
        help="Path for the output mesh (default: data/outputs/test_mesh.obj)",
    )
    parser.add_argument(
        "--faces",
        type=int,
        default=DEFAULT_TARGET_FACES,
        help="Target face count after decimation; 0 disables decimation",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=[*BACKENDS, "auto"],
        help="Reconstruction backend (default: $DS_SCULPTOR_BACKEND, else auto)",
    )
    parser.add_argument(
        "--pipeline-type",
        default=None,
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
        help="TRELLIS.2 voxel resolution (default: 1024_cascade)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Sampling seed; the same seed and image reproduce the same mesh",
    )
    parser.add_argument(
        "--smooth",
        type=int,
        default=None,
        metavar="N",
        help="Taubin smoothing passes; 0 (the TRELLIS.2 default) keeps sharp edges",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    kwargs: dict = {}
    if args.pipeline_type:
        kwargs["pipeline_type"] = args.pipeline_type
    if args.seed is not None:
        kwargs["seed"] = args.seed

    try:
        sculptor = create_sculptor(args.backend, **kwargs)
        sculptor.generate_mesh(
            args.blueprint,
            args.output,
            target_faces=args.faces,
            smooth_iterations=args.smooth,
        )
    except SculptorError as exc:
        logger.error("%s", exc)
        sys.exit(1)
