"""
sculptor.py — Phase 2: Neural 3D reconstruction from a blueprint image.

Usage:
    python pythonsrc/sculptor.py [--blueprint PATH] [--output PATH] [--faces N] [--verbose]
"""

import logging
import os
from pathlib import Path
from config import INPUTS_DIR, OUTPUTS_DIR

# Force CPU fallback for M4 Mac compatibility before importing torch
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import numpy as np
import rembg
import torch
import trimesh
from PIL import Image

from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground

# ── Background-removal model ──────────────────────────────────────────────────
# Named explicitly rather than relying on rembg's default. rembg is MIT, but the
# *model weights* carry their own licences and the default has already changed
# once: newer releases default to BRIA RMBG-2.0, which requires a paid agreement
# for commercial use. u2net is Apache-2.0. Pinning rembg==2.0.69 alone would not
# protect us — the version pin and this name have to agree, and only this name
# survives a dependency bump.
REMBG_MODEL = os.environ.get("REMBG_MODEL", "u2net")
_rembg_session = None


def get_rembg_session():
    """Lazily build the rembg session; downloads the model on first use."""
    global _rembg_session
    if _rembg_session is None:
        logger.info("Creating rembg session with model: %s", REMBG_MODEL)
        _rembg_session = rembg.new_session(REMBG_MODEL)
    return _rembg_session

# ── M4/MPS Monkey Patch ───────────────────────────────────────────────────────
from tsr.models.isosurface import MarchingCubeHelper

_original_mc_forward = MarchingCubeHelper.forward


def _patched_mc_forward(self, level):
    return _original_mc_forward(self, level.cpu())


MarchingCubeHelper.forward = _patched_mc_forward
# ─────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger("p2p.sculptor")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


class P2PSculptor:
    """Wraps TripoSR to reconstruct a 3-D mesh from a single concept image."""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        # Safe device detection: CUDA → MPS → CPU (with hasattr guard for Linux)
        if torch.cuda.is_available():
            self.device = "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"
        logger.info("Initialising Sculptor on device: %s", self.device)

        if model_dir is None:
            # Prefer env var (set by Docker volumes) over local path
            env_path = os.environ.get("TRIPOSR_MODEL_PATH")
            if env_path and Path(env_path).is_dir() and any(Path(env_path).iterdir()):
                model_dir = Path(env_path)
            else:
                model_dir = "stabilityai/TripoSR"

        self.model = TSR.from_pretrained(
            str(model_dir),
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        self.model.to(self.device)
        self.model.eval()

    def generate_mesh(
        self,
        image_path: str | Path,
        output_path: str | Path,
        *,
        target_faces: int = 5_000,
    ) -> Path:
        image_path = Path(image_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Derive debug output path relative to the image directory
        debug_path = image_path.parent / "debug_final_view.png"

        logger.info("Processing image: %s", image_path)
        image = Image.open(image_path)

        # ── Pre-processing ────────────────────────────────────────────────────
        image = remove_background(image, rembg_session=get_rembg_session())
        image = resize_foreground(image, 0.85)

        # Clean dirty alpha channel — anything < 20% opaque → fully transparent
        if image.mode == "RGBA":
            r, g, b, a = image.split()
            a = a.point(lambda p: 255 if p > 50 else 0)
            image = Image.merge("RGBA", (r, g, b, a))

        # Composite onto neutral gray background for stable Shape-from-Shading
        bg = Image.new("RGB", image.size, (127, 127, 127))
        if image.mode == "RGBA":
            bg.paste(image, mask=image.split()[3])
        else:
            bg.paste(image.convert("RGB"))
        image = bg
        image.save(str(debug_path))
        logger.debug("Debug pre-processed image saved to %s", debug_path)

        # ── Inference ─────────────────────────────────────────────────────────
        logger.info("Running TripoSR inference…")
        with torch.no_grad():
            scene_codes = self.model([image], device=self.device)
            meshes = self.model.extract_mesh(
                scene_codes,
                has_vertex_color=False,
                resolution=128,
                threshold=45.0,
            )

        main_mesh = meshes[0]

        # ── Post-Processing ───────────────────────────────────────────────────
        logger.info("Optimising mesh topology…")

        # Stand it upright (TripoSR outputs Y-up, we want Z-up)
        rotation_matrix = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
        main_mesh.apply_transform(rotation_matrix)

        # Keep only the largest connected component
        components = main_mesh.split(only_watertight=False)
        if components:
            main_mesh = max(components, key=lambda m: m.extents.max())

        # Taubin smoothing
        main_mesh = main_mesh.subdivide()
        trimesh.smoothing.filter_taubin(main_mesh, iterations=10)
        logger.debug("After smoothing — faces: %d", len(main_mesh.faces))

        # ── Decimation ────────────────────────────────────────────────────────
        # Requires the optional `fast-simplification` package.
        # If absent the mesh is exported at full resolution — functional but slower
        # in the Engineer step. Install with: pip install fast-simplification
        if len(main_mesh.faces) > target_faces:
            logger.info(
                "Decimating %d → %d faces…", len(main_mesh.faces), target_faces
            )
            try:
                main_mesh = main_mesh.simplify_quadric_decimation(face_count=target_faces)
                logger.debug("After decimation — faces: %d", len(main_mesh.faces))
            except (ImportError, ModuleNotFoundError):
                logger.warning(
                    "fast-simplification not installed — skipping decimation. "
                    "Run: pip install fast-simplification"
                )

        main_mesh.export(str(output_path))
        logger.info("Final mesh saved to: %s  (faces: %d)", output_path, len(main_mesh.faces))
        return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 2 — Sculptor")
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
        default=5_000,
        help="Target face count after decimation (default: 5000)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    sculptor = P2PSculptor()
    sculptor.generate_mesh(args.blueprint, args.output, target_faces=args.faces)
