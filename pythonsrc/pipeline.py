"""
pipeline.py — Unified Prompt2Print entrypoint.

Chains Phases 1→2→3 in a single command:

    python pythonsrc/pipeline.py "a ceramic vase with geometric patterns"
    python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80 --hollow
    python pythonsrc/pipeline.py --skip-visualizer --blueprint inputs/blueprint.png
    python pythonsrc/pipeline.py --skip-sculptor   --mesh outputs/test_mesh.obj

Phase 4 (Operator) is triggered with --print / --octoprint-url:

    python pythonsrc/pipeline.py "a chess knight" --print \\
        --octoprint-url http://octopi.local --octoprint-key MY_API_KEY --start-print
"""

import argparse
import logging
import sys
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("p2p.pipeline")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    inputs_dir = workspace / "inputs"
    outputs_dir = workspace / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    blueprint_path = Path(args.blueprint) if args.blueprint else inputs_dir / "blueprint.png"
    raw_mesh_path = Path(args.mesh) if args.mesh else outputs_dir / "raw_mesh.obj"
    final_mesh_path = outputs_dir / "engineered_mesh.obj"

    # ── Phase 1: Visualizer ───────────────────────────────────────────────────
    if not args.skip_visualizer:
        if not args.prompt:
            logger.error("A --prompt is required unless --skip-visualizer is set.")
            sys.exit(1)
        logger.info("=== Phase 1: Visualizer ===")
        from visualizer import Visualizer

        viz = Visualizer()
        viz.generate_blueprint(
            prompt=args.prompt,
            output_path=blueprint_path,
            num_inference_steps=args.steps,
        )
    else:
        logger.info("Skipping Phase 1 — using existing blueprint: %s", blueprint_path)
        if not blueprint_path.exists():
            logger.error("Blueprint not found: %s", blueprint_path)
            sys.exit(1)

    # ── Phase 2: Sculptor ─────────────────────────────────────────────────────
    if not args.skip_sculptor:
        logger.info("=== Phase 2: Sculptor ===")
        from sculptor import P2PSculptor

        sculptor = P2PSculptor()
        sculptor.generate_mesh(
            image_path=blueprint_path,
            output_path=raw_mesh_path,
            target_faces=args.faces,
        )
    else:
        logger.info("Skipping Phase 2 — using existing mesh: %s", raw_mesh_path)
        if not raw_mesh_path.exists():
            logger.error("Raw mesh not found: %s", raw_mesh_path)
            sys.exit(1)

    # ── Phase 3: Engineer ─────────────────────────────────────────────────────
    logger.info("=== Phase 3: Engineer ===")
    from engineer import Engineer

    eng = Engineer()
    eng.process(
        input_path=raw_mesh_path,
        output_path=final_mesh_path,
        target_mm=args.target_mm,
        hollow=args.hollow,
        wall_thickness=args.wall,
    )

    # ── Phase 4: Operator (optional) ──────────────────────────────────────────
    if args.print:
        logger.info("=== Phase 4: Operator ===")
        from operator_phase import OctoPrintOperator

        op = OctoPrintOperator(
            base_url=args.octoprint_url,
            api_key=args.octoprint_key,
        )
        upload_result = op.upload_file(final_mesh_path)
        logger.info("Upload result: %s", upload_result)

        if args.start_print:
            job_result = op.start_print(upload_result["refs"]["resource"])
            logger.info("Print job started: %s", job_result)

    logger.info("Pipeline complete ✓  Output: %s", final_mesh_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prompt2Print — unified mesh pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Prompt
    parser.add_argument("prompt", nargs="?", help="Text prompt for the object to generate")

    # Skip flags for fast iteration
    skip = parser.add_argument_group("skip flags (for iterating on a specific phase)")
    skip.add_argument("--skip-visualizer", action="store_true", help="Skip Phase 1 (reuse existing blueprint)")
    skip.add_argument("--skip-sculptor", action="store_true", help="Skip Phase 2 (reuse existing raw mesh)")

    # Paths
    paths = parser.add_argument_group("paths")
    paths.add_argument("--workspace", default=".", metavar="DIR", help="Project root (inputs/ and outputs/ live here)")
    paths.add_argument("--blueprint", metavar="PATH", help="Override blueprint image path")
    paths.add_argument("--mesh", metavar="PATH", help="Override raw mesh path")

    # Phase 1 options
    p1 = parser.add_argument_group("Phase 1 — Visualizer")
    p1.add_argument("--steps", type=int, default=4, metavar="N", help="Diffusion inference steps")

    # Phase 2 options
    p2 = parser.add_argument_group("Phase 2 — Sculptor")
    p2.add_argument("--faces", type=int, default=5_000, metavar="N", help="Target face count after decimation")

    # Phase 3 options
    p3 = parser.add_argument_group("Phase 3 — Engineer")
    p3.add_argument("--target-mm", type=float, default=50.0, metavar="MM", help="Target longest dimension in mm")
    p3.add_argument("--hollow", action="store_true", help="Apply voxel-based hollowing")
    p3.add_argument("--wall", type=float, default=1.2, metavar="MM", help="Wall thickness for hollowing in mm")

    # Phase 4 options
    p4 = parser.add_argument_group("Phase 4 — Operator (OctoPrint)")
    p4.add_argument("--print", dest="print", action="store_true", help="Upload final mesh to OctoPrint")
    p4.add_argument("--octoprint-url", default="http://octopi.local", metavar="URL", help="OctoPrint base URL")
    p4.add_argument("--octoprint-key", metavar="KEY", help="OctoPrint API key")
    p4.add_argument("--start-print", action="store_true", help="Automatically start the print job after upload")

    # General
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)
    run(args)
