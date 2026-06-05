"""
pipeline.py — Unified Prompt2Print entrypoint.

Chains Phases 1→2→3→4→5 in a single command:

    python pythonsrc/pipeline.py "a ceramic vase with geometric patterns"
    python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80 --hollow
    python pythonsrc/pipeline.py --skip-visualizer --blueprint inputs/blueprint.png
    python pythonsrc/pipeline.py --skip-sculptor   --mesh outputs/test_mesh.obj

Phase 5 (Operator) is triggered with --print / --octoprint-url.
Phase 4 (Slicer) converts the engineered .obj → .gcode before upload:

    python pythonsrc/pipeline.py "a chess knight" --print \\
        --octoprint-url http://localhost:5001 --octoprint-key MY_API_KEY --start-print \\
        --profile pythonsrc/profiles/ender3.json
"""

# ── MPS fallback — MUST be set before any torch import ────────────────────────
# Several MPS ops (e.g. upsample_bicubic2d used by TripoSR's ViT image
# tokeniser) are not yet implemented on Apple Silicon. This flag makes PyTorch
# silently fall back to CPU for those ops. It must be in the environment
# *before* `import torch` is first executed in this process — hence it lives
# here at the very top, ahead of all other imports.
import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import argparse
import logging
import sys
import time
import traceback
from pathlib import Path

from config import CURA_ENGINE_PATH

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("p2p.pipeline")

# ── Phase banner helpers ──────────────────────────────────────────────────────
_PHASE_NAMES = {
    1: "Visualizer",
    2: "Sculptor",
    3: "Engineer",
    4: "Slicer",
    5: "Operator",
}


def _phase_start(phase_num: int) -> float:
    """Print a phase start banner and return the start timestamp."""
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"\n[P2P] ═══ PHASE {phase_num} START: {name} ═══", flush=True)
    return time.time()


def _phase_pass(phase_num: int, start_time: float, output_path: str = "") -> None:
    """Print a phase pass banner with timing and output path."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    out_info = f" (output: {output_path})" if output_path else ""
    print(f"[P2P] ═══ PHASE {phase_num} PASS  ✓{out_info} ═══", flush=True)
    print(f"[P2P] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)


def _phase_fail(phase_num: int, start_time: float, exc: Exception) -> None:
    """Print a phase fail banner with traceback, then exit."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"[P2P] ═══ PHASE {phase_num} FAIL  ✗ ═══", flush=True)
    print(f"[P2P] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)
    print(f"[P2P] ERROR: {exc}", flush=True)
    print(f"[P2P] TRACEBACK:", flush=True)
    traceback.print_exc()
    sys.exit(1)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    pipeline_start = time.time()

    workspace = Path(args.workspace)
    inputs_dir = workspace / "inputs"
    outputs_dir = workspace / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    blueprint_path = Path(args.blueprint) if args.blueprint else inputs_dir / "blueprint.png"
    raw_mesh_path = Path(args.mesh) if args.mesh else outputs_dir / "raw_mesh.obj"
    final_mesh_path = outputs_dir / "engineered_mesh.stl"
    gcode_path = outputs_dir / "engineered_mesh.gcode"

    # ── Phase 1: Visualizer ───────────────────────────────────────────────────
    if not args.skip_visualizer:
        if not args.prompt:
            logger.error("A --prompt is required unless --skip-visualizer is set.")
            sys.exit(1)

        def _is_running_in_docker():
            return os.path.exists("/.dockerenv")

        if _is_running_in_docker():
            print(
                "\n[P2P] ⚠️  WARNING: Phase 1 is running inside Docker on Mac.\n"
                "[P2P]     MPS (Apple Silicon GPU) is NOT accessible from inside\n"
                "[P2P]     a Docker container. This will run on CPU and take ~84min.\n"
                "[P2P]     RECOMMENDED: Run Phase 1 natively on Mac instead:\n"
                "[P2P]       ./run_phase1_native.sh \"your prompt\"\n"
                "[P2P]     Then use --skip-visualizer for the Docker run.\n"
            )

        t0 = _phase_start(1)
        try:
            from visualizer import Visualizer

            viz = Visualizer()
            viz.generate_blueprint(
                prompt=args.prompt,
                output_path=blueprint_path,
                num_inference_steps=args.steps,
            )
            _phase_pass(1, t0, str(blueprint_path))
        except Exception as exc:
            _phase_fail(1, t0, exc)
    else:
        logger.info("Skipping Phase 1 — using existing blueprint: %s", blueprint_path)
        if not blueprint_path.exists() and not args.skip_sculptor:
            logger.error("Blueprint not found: %s", blueprint_path)
            sys.exit(1)

    # ── Phase 2: Sculptor ─────────────────────────────────────────────────────
    if not args.skip_sculptor:
        t0 = _phase_start(2)
        try:
            from sculptor import P2PSculptor

            sculptor = P2PSculptor()
            sculptor.generate_mesh(
                image_path=blueprint_path,
                output_path=raw_mesh_path,
                target_faces=args.faces,
            )
            _phase_pass(2, t0, str(raw_mesh_path))
        except Exception as exc:
            _phase_fail(2, t0, exc)
    else:
        logger.info("Skipping Phase 2 — using existing mesh: %s", raw_mesh_path)
        if not raw_mesh_path.exists():
            logger.error("Raw mesh not found: %s", raw_mesh_path)
            sys.exit(1)

    # ── Phase 3: Engineer ─────────────────────────────────────────────────────
    t0 = _phase_start(3)
    try:
        from engineer import Engineer

        eng = Engineer()
        eng.process(
            input_path=raw_mesh_path,
            output_path=final_mesh_path,
            target_mm=args.target_mm,
            hollow=args.hollow,
            wall_thickness=args.wall,
        )
        _phase_pass(3, t0, str(final_mesh_path))
    except Exception as exc:
        _phase_fail(3, t0, exc)

    # ── Phase 4: Slicer ───────────────────────────────────────────────────────
    if args.print:
        t0 = _phase_start(4)
        try:
            from slicer import CuraSlicer, SlicerError

            slicer = CuraSlicer(
                cura_engine=args.cura_engine,
                profile=args.profile,
            )
            gcode_path = slicer.slice(
                input_path=final_mesh_path,
                output_path=gcode_path,
            )
            _phase_pass(4, t0, str(gcode_path))
        except Exception as exc:
            _phase_fail(4, t0, exc)

    # ── Phase 5: Operator ─────────────────────────────────────────────────────
    if args.print:
        t0 = _phase_start(5)
        try:
            from operator_phase import OctoPrintOperator

            op = OctoPrintOperator(
                base_url=args.octoprint_url,
                api_key=args.octoprint_key,
            )

            # Ensure printer is connected and operational before upload
            logger.info("Checking printer state…")
            op.ensure_operational(auto_connect_port="VIRTUAL")

            upload_result = op.upload_file(
                gcode_path,
                select=True,   # select the file so OctoPrint knows what to print
                start=False,   # we control start separately for pre-flight logging
            )
            logger.info("Upload complete — file selected in OctoPrint.")

            if args.start_print:
                logger.info("Starting print job…")
                op.start_print()

            _phase_pass(5, t0, str(gcode_path))
        except Exception as exc:
            _phase_fail(5, t0, exc)

    # ── Pipeline summary ──────────────────────────────────────────────────────
    total_elapsed = time.time() - pipeline_start
    total_min = int(total_elapsed // 60)
    total_sec = int(total_elapsed % 60)
    print("\n[P2P] ══════════════════════════════", flush=True)
    print("[P2P] PIPELINE COMPLETE ✓", flush=True)
    print(f"[P2P] Total duration: {total_min}m {total_sec}s", flush=True)
    print("[P2P] ══════════════════════════════\n", flush=True)

    logger.info("Mesh: %s", final_mesh_path)
    if args.print:
        logger.info("G-code: %s", gcode_path)


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

    # Phase 4 options (Slicer)
    p4 = parser.add_argument_group("Phase 4 — Slicer (CuraEngine)")
    p4.add_argument(
        "--profile",
        metavar="PATH",
        default=None,
        help="Printer profile JSON for CuraEngine (default: built-in Ender-3 settings)",
    )
    p4.add_argument(
        "--cura-engine",
        metavar="BIN",
        default=CURA_ENGINE_PATH,
        help="CuraEngine binary name or full path",
    )

    # Phase 5 options (Operator)
    p5 = parser.add_argument_group("Phase 5 — Operator (OctoPrint)")
    p5.add_argument("--print", dest="print", action="store_true", help="Slice and upload final mesh to OctoPrint")
    p5.add_argument("--octoprint-url", default=os.environ.get("OCTOPRINT_URL", "http://localhost:5001"), metavar="URL", help="OctoPrint base URL")
    p5.add_argument("--octoprint-key", default=os.environ.get("OCTOPRINT_API_KEY", ""), metavar="KEY", help="OctoPrint API key")
    p5.add_argument("--start-print", action="store_true", help="Automatically start the print job after upload")

    # General
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)
    run(args)
