"""
sculptor.py — Phase 2: Neural 3D reconstruction from a blueprint image.

Usage:
    python pythonsrc/sculptor.py [--blueprint PATH] [--output PATH] [--faces N] [--verbose]
"""

import logging
import os
from pathlib import Path

# Force CPU fallback for M4 Mac compatibility before importing torch
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import numpy as np
import torch
import trimesh
from PIL import Image

from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground

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
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        logger.info("Initialising Sculptor on device: %s", self.device)

        if model_dir is None:
            model_dir = Path(__file__).parent / "models" / "TripoSR"

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
        image = remove_background(image)
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
                resolution=256,
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
        # Reduce polygon count for faster downstream processing.
        # target_faces is tunable; 5 000 is sufficient for 0.2 mm FDM printing.
        if len(main_mesh.faces) > target_faces:
            logger.info(
                "Decimating %d → %d faces…", len(main_mesh.faces), target_faces
            )
            main_mesh = main_mesh.simplify_quadric_decimation(target_faces)
            logger.debug("After decimation — faces: %d", len(main_mesh.faces))

        main_mesh.export(str(output_path))
        logger.info("Final mesh saved to: %s  (faces: %d)", output_path, len(main_mesh.faces))
        return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 2 — Sculptor")
    parser.add_argument(
        "--blueprint",
        default="inputs/blueprint.png",
        help="Path to the input blueprint image (default: inputs/blueprint.png)",
    )
    parser.add_argument(
        "--output",
        default="outputs/test_mesh.obj",
        help="Path for the output mesh (default: outputs/test_mesh.obj)",
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
