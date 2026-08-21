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

# Prompt engineering, seed selection and the result record live in a torch-free module
# so the pipeline, the server and the tests can use them without the Phase 1 stack.
# Re-exported here because this is where callers expect to find them.
try:
    from blueprint_spec import (
        SEED_SPACE,
        BlueprintResult,
        engineer_prompt,
        resolve_seed,
        write_sidecar,
    )
except ImportError:
    from pythonsrc.blueprint_spec import (
        SEED_SPACE,
        BlueprintResult,
        engineer_prompt,
        resolve_seed,
        write_sidecar,
    )

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
        # Kept so the telemetry row records which model made each blueprint; a model
        # swap otherwise mixes two populations with nothing to separate them.
        self.model_id = model_id

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
        seed: int | None = None,
        height: int = 1024,
        width: int = 1024,
    ) -> BlueprintResult:
        """Generate a clay-render blueprint image.

        Returns a `BlueprintResult` rather than a bare path so the caller can record
        the seed and conditioning. Without them a result cannot be reproduced, and two
        runs of the same prompt cannot be told apart.

        Args:
            prompt: The user's prompt.
            output_path: Where to write the PNG.
            num_inference_steps: Diffusion steps.
            guidance_scale: Classifier-free guidance scale.
            seed: Explicit seed; one is drawn when omitted.
            height: Image height in pixels.
            width: Image width in pixels.

        Returns:
            A BlueprintResult carrying the path, seed and conditioning used.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        engineered_prompt = engineer_prompt(prompt)
        seed = resolve_seed(seed)
        params = {
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "height": height,
            "width": width,
        }

        logger.info("Generating blueprint (seed %d) for: '%s'", seed, engineered_prompt)
        start = time.time()

        # Always use CPU generator — Generator("mps") and Generator("cuda") can
        # cause issues, and the seed is only for reproducibility, not computation.
        image = self.pipe(
            prompt=engineered_prompt,
            generator=torch.Generator("cpu").manual_seed(seed),
            **params,
        ).images[0]

        image.save(str(output_path))
        elapsed = time.time() - start
        logger.info("Blueprint saved to %s (seed %d, %.2fs)", output_path, seed, elapsed)
        result = BlueprintResult(
            path=output_path,
            seed=seed,
            prompt=prompt,
            engineered_prompt=engineered_prompt,
            params=params,
            duration_s=elapsed,
            model_id=self.model_id,
        )
        # The primary Mac workflow runs this in its own process and the pipeline
        # with --skip-visualizer; without the sidecar the seed and conditioning
        # die with this process and the job records NULL provenance.
        write_sidecar(result)
        return result


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="p2p-mesh Phase 1 — Visualizer")
    parser.add_argument("--prompt", "-p", help="Text prompt (interactive if omitted)")
    parser.add_argument(
        "--output",
        default=os.path.join(INPUTS_DIR, "blueprint.png"),
        help="Output image path (default: data/inputs/blueprint.png)",
    )
    parser.add_argument("--steps", type=int, default=2, help="Diffusion inference steps (default: 2)")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed; a random one is drawn and reported if omitted",
    )
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
    result = viz.generate_blueprint(
        prompt=user_prompt,
        output_path=args.output,
        num_inference_steps=args.steps,
        seed=args.seed,
    )
    # Printed so an interactive run can reproduce its own result with --seed.
    print(f"[P2P] Blueprint seed: {result.seed}")
