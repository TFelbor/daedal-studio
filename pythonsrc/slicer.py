"""
slicer.py — Phase 3.5: CuraEngine slicing wrapper.

Converts a print-ready .obj mesh into a .gcode file suitable for OctoPrint
by calling the CuraEngine CLI as a subprocess with bundled definition files.

Usage (standalone):
    python pythonsrc/slicer.py \\
        --input data/outputs/engineered_mesh.obj \\
        --output data/outputs/engineered_mesh.gcode \\
        --engine CuraEngine
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from config import CURA_ENGINE_PATH

logger = logging.getLogger("p2p.slicer")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


class SlicerError(RuntimeError):
    """Raised when CuraEngine fails, is missing, or is misconfigured."""
    pass


# ── CuraSlicer ────────────────────────────────────────────────────────────────
class CuraSlicer:
    """
    Subprocess wrapper around the CuraEngine CLI using bundled definition files.

    Parameters
    ----------
    cura_engine:
        Path to the CuraEngine binary.
    profile:
        Path to a .def.json printer definition file. If None, the bundled
        Ender 3 definition is used.
    """

    DEFINITIONS_DIR = Path(__file__).parent / "profiles" / "definitions"

    def __init__(
        self,
        cura_engine: str = CURA_ENGINE_PATH,
        profile: str | Path | None = None,
    ) -> None:
        self.cura_engine = cura_engine
        self.profile_path: Path | None = self._load_profile(profile)
        self._check_cura_available()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _load_profile(
        profile: str | Path | None,
    ) -> Path | None:
        """Store the custom .def.json path, if one was provided."""
        if profile is None:
            return None
        path = Path(profile)
        if not path.exists():
            raise FileNotFoundError(f"Printer definition not found: {path}")
        logger.debug("Using custom printer definition from '%s'.", path)
        return path

    def _check_cura_available(self) -> None:
        if shutil.which(self.cura_engine) is None and not Path(self.cura_engine).exists():
            raise SlicerError(
                f"CuraEngine binary not found at: {self.cura_engine}\n"
                "Ensure it is installed and the path is correct."
            )

    def _resolve_definitions(self) -> list[str]:
        """
        Return the ordered list of -j definition file paths for CuraEngine.

        Always includes fdmprinter.def.json as the base.  The second entry
        is either a user-supplied .def.json or the bundled ender3_base.
        """
        base_def = self.DEFINITIONS_DIR / "fdmprinter.def.json"
        if not base_def.exists():
            raise SlicerError(
                f"Bundled base definition not found at: {base_def}\n"
                "Ensure fdmprinter.def.json is present in "
                f"{self.DEFINITIONS_DIR}."
            )

        if self.profile_path is not None and self.profile_path.suffix == ".json" and self.profile_path.name.endswith(".def.json"):
            return [str(base_def), str(self.profile_path)]

        return [
            str(base_def),
            str(self.DEFINITIONS_DIR / "ender3_base.def.json"),
        ]

    # ── Public API ────────────────────────────────────────────────────────────
    def slice(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        extra_args: list[str] | None = None,
    ) -> Path:
        """
        Slice a mesh into G-Code using bundled definition files.

        Parameters
        ----------
        input_path:
            Path to the source ``.obj`` or ``.stl`` file.
        output_path:
            Desired path for the output ``.gcode`` file.
        extra_args:
            Raw CLI arguments forwarded to CuraEngine.

        Returns
        -------
        Path
            Resolved path to the generated ``.gcode`` file.
        """
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()

        if not input_path.exists():
            raise FileNotFoundError(f"Input mesh not found: {input_path}")
        if input_path.suffix.lower() not in {".obj", ".stl"}:
            raise ValueError(f"Slicer expects .obj or .stl; got '{input_path.suffix}'")
        if output_path.suffix.lower() not in {".gcode", ".gco", ".g"}:
            raise ValueError(f"Output must be .gcode; got '{output_path.suffix}'")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        definition_paths = self._resolve_definitions()

        cmd: list[str] = [self.cura_engine, "slice"]
        for def_path in definition_paths:
            cmd += ["-j", def_path]
        cmd += ["-o", str(output_path), "-l", str(input_path)]

        if extra_args:
            cmd.extend(extra_args)

        logger.info("Slicing '%s' → '%s'…", input_path.name, output_path.name)
        logger.debug("Execution command length: %d parts", len(cmd))

        # CuraEngine requires this env var to find fdmprinter.def.json
        import os
        env = os.environ.copy()
        env["CURA_ENGINE_SEARCH_PATH"] = str(self.DEFINITIONS_DIR)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
            )
        except Exception as exc:
            raise SlicerError(f"Failed to execute CuraEngine subprocess: {exc}") from exc

        if result.returncode != 0:
            stderr_snippet = result.stderr[-1000:] if result.stderr else "(no stderr)"
            stdout_snippet = result.stdout[-1000:] if result.stdout else "(no stdout)"
            raise SlicerError(
                f"CuraEngine exited with code {result.returncode}.\n"
                f"Stderr (last 1000 chars):\n{stderr_snippet}\n"
                f"Stdout (last 1000 chars):\n{stdout_snippet}"
            )

        if not output_path.exists():
            raise SlicerError("CuraEngine reported success but no G-code file was created.")

        logger.info("Slicing complete ✓")
        return output_path


# ── Standalone CLI ────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="p2p-mesh Phase 3.5 — CuraEngine slicer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, metavar="PATH", help=".obj file to slice")
    parser.add_argument("--output", "-o", required=True, metavar="PATH", help=".gcode output path")
    parser.add_argument(
        "--profile", "-p", metavar="PATH",
        help="Path to a .def.json printer definition file (default: bundled Ender 3)",
    )
    parser.add_argument("--engine", default=CURA_ENGINE_PATH, metavar="BIN", help="CuraEngine binary path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    try:
        slicer = CuraSlicer(cura_engine=args.engine, profile=args.profile)
        slicer.slice(input_path=args.input, output_path=args.output)
    except (SlicerError, FileNotFoundError, ValueError) as exc:
        logger.error("Slicing failed: %s", exc)
        sys.exit(1)