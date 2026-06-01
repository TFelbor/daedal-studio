#!/usr/bin/env python3
"""
test_integration.py — End-to-end integration test for Phase 3.5 → Phase 4.

Exercises the slicer and OctoPrint operator against a local virtual printer
without requiring Phases 1 (Visualizer) or 2 (Sculptor) to have run.

Usage:
    # With a pre-sliced .gcode file:
    python pythonsrc/test_integration.py \
        --gcode outputs/engineered_mesh.gcode \
        --key MY_OCTOPRINT_API_KEY

    # Slice a .obj first, then upload:
    python pythonsrc/test_integration.py \
        --slice-input outputs/engineered_mesh.obj \
        --key MY_OCTOPRINT_API_KEY

    # Upload and start printing:
    python pythonsrc/test_integration.py \
        --gcode outputs/engineered_mesh.gcode \
        --key MY_OCTOPRINT_API_KEY --start
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

from config import OCTOPRINT_DEFAULT_URL

logger = logging.getLogger("p2p.integration_test")

OCTOPRINT_URL = OCTOPRINT_DEFAULT_URL
SLICE_OUTPUT = Path("/tmp/p2p_integration_test.gcode")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="p2p-mesh integration test — Phase 3.5 → Phase 4 against local OctoPrint",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--gcode",
        metavar="PATH",
        help="Path to an existing .gcode file (bypasses slicing)",
    )
    source.add_argument(
        "--slice-input",
        metavar="PATH",
        help="Path to a .obj file to slice first via CuraSlicer",
    )

    parser.add_argument(
        "--key",
        required=True,
        metavar="KEY",
        help="OctoPrint API key",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the print job after upload and watch progress",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    try:
        # ── Step 1: Resolve the G-code path ──────────────────────────────
        if args.slice_input:
            logger.info("━━━ Step 1: Slicing '%s' ━━━", args.slice_input)

            from slicer import CuraSlicer

            slicer = CuraSlicer()
            gcode_path = slicer.slice(
                input_path=args.slice_input,
                output_path=SLICE_OUTPUT,
            )
            logger.info("Slicing complete → %s", gcode_path)
        else:
            gcode_path = Path(args.gcode)
            if not gcode_path.exists():
                logger.error("G-code file not found: %s", gcode_path)
                sys.exit(1)
            logger.info("━━━ Step 1: Using existing G-code '%s' ━━━", gcode_path)

        # ── Step 2: Connect to OctoPrint ─────────────────────────────────
        logger.info("━━━ Step 2: Connecting to OctoPrint at %s ━━━", OCTOPRINT_URL)

        from operator_phase import OctoPrintOperator

        op = OctoPrintOperator(base_url=OCTOPRINT_URL, api_key=args.key)

        version = op.get_version()
        logger.info(
            "OctoPrint %s (API %s) — connected ✔",
            version.get("server", "?"),
            version.get("api", "?"),
        )

        # ── Step 3: Ensure printer is operational ────────────────────────
        logger.info("━━━ Step 3: Ensuring printer is Operational ━━━")
        op.ensure_operational(auto_connect_port="VIRTUAL")

        # ── Step 4: Upload G-code ────────────────────────────────────────
        logger.info("━━━ Step 4: Uploading '%s' ━━━", gcode_path.name)

        upload_result = op.upload_file(
            gcode_path,
            select=True,
            start=False,
        )

        logger.info("Upload result:")
        print(json.dumps(upload_result, indent=2))

        # ── Step 5 (optional): Start print and watch ─────────────────────
        if args.start:
            logger.info("━━━ Step 5: Starting print job ━━━")
            op.start_print()
            logger.info("Print started — watching progress…")
            op.watch_job()
        else:
            logger.info("━━━ Done — file uploaded and selected (--start not set) ━━━")

    except Exception:
        logger.error("Integration test failed with exception:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
