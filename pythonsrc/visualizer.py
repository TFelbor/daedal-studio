"""
visualizer.py — Phase 1: Text-to-image blueprint generation.

Usage:
    python pythonsrc/visualizer.py [--prompt TEXT] [--output PATH] [--steps N] [--verbose]
"""

import logging
import os
import time
from pathlib import Path

import torch
from diffusers import DiffusionPipeline

from config import INPUTS_DIR

logger = logging.getLogger("p2p.visualizer")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


def get_device():
    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and \
         torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"[P2P] Phase 1 device: {device}")
    return device


class Visualizer:
    """Generates a clay-render blueprint image from a natural language prompt."""

    MODEL_ID = "black-forest-labs/FLUX.2-klein-4B"

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self._device = get_device()

        # Read HuggingFace token from environment for gated model access
        token = os.environ.get("HF_TOKEN")

        logger.info("Loading %s on device: %s…", model_id, self._device)
        self.pipe = DiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
            token=token,
        )

        self.pipe.to(self._device)
        logger.info("Model loaded on %s.", self._device)

    def generate_blueprint(
        self,
        prompt: str,
        output_path: str | Path = os.path.join(INPUTS_DIR, "blueprint.png"),
        num_inference_steps: int = 2,
        guidance_scale: float = 3.5,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Inject clay-render keywords to bias TripoSR's Shape-from-Shading
        engineered_prompt = (
            f"3d blender render of {prompt}, "
            "neutral background, high fidelity, 8k, soft studio lighting, "
            "solid object, thick solid geometry, smooth curves, clay material"
        )

        logger.info("Generating blueprint for: '%s'", engineered_prompt)
        start = time.time()

        # Always use CPU generator — Generator("mps") and Generator("cuda") can
        # cause issues, and the seed is only for reproducibility, not computation.
        image = self.pipe(
            prompt=engineered_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            height=1024,
            width=1024,
            generator=torch.Generator("cpu").manual_seed(int(time.time())),
        ).images[0]

        image.save(str(output_path))
        elapsed = time.time() - start
        logger.info("Blueprint saved to %s (%.2fs)", output_path, elapsed)
        return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 1 — Visualizer")
    parser.add_argument("--prompt", "-p", help="Text prompt (interactive if omitted)")
    parser.add_argument(
        "--output",
        default=os.path.join(INPUTS_DIR, "blueprint.png"),
        help="Output image path (default: inputs/blueprint.png)",
    )
    parser.add_argument("--steps", type=int, default=2, help="Diffusion inference steps (default: 2)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    if args.prompt:
        user_prompt = args.prompt
    else:
        print("\n -------------------------------------------------------------------")
        print("              === ENTER PROMPT BELOW ===")
        print(" -------------------------------------------------------------------")
        user_prompt = input()

    viz = Visualizer()
    viz.generate_blueprint(prompt=user_prompt, output_path=args.output, num_inference_steps=args.steps)
