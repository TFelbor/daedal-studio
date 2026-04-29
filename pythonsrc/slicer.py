"""
slicer.py — Phase 3.5: CuraEngine slicing wrapper.

Converts a print-ready .obj mesh into a .gcode file suitable for OctoPrint
by calling the CuraEngine CLI as a subprocess and overriding parameters.

Usage (standalone):
    python pythonsrc/slicer.py \\
        --input outputs/engineered_mesh.obj \\
        --output outputs/engineered_mesh.gcode \\
        --profile pythonsrc/profiles/anycubic_mega.json \\
        --engine "/Applications/UltiMaker Cura.app/Contents/Frameworks/CuraEngine"
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("p2p.slicer")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── Default Printer Profile ───────────────────────────────────────────────────
# Minimal viable FFF settings. Overridden by custom JSON profile.
_DEFAULT_PROFILE: dict[str, Any] = {
    "machine_name": "Ender 3",
    "machine_extruder_count": 1,
    "machine_nozzle_size": 0.4,
    "layer_height": 0.2,
    "wall_line_count": 3,
    "top_layers": 4,
    "bottom_layers": 4,
    "infill_sparse_density": 15,
    "infill_pattern": "grid",
    "material_print_temperature": 210,
    "material_bed_temperature": 60,
    "speed_print": 50,
    "speed_travel": 150,
    "retraction_enable": True,
    "retraction_amount": 6,
    "retraction_speed": 45,
    "support_enable": False,
    "adhesion_type": "skirt",
}


class SlicerError(RuntimeError):
    """Raised when CuraEngine fails, is missing, or is misconfigured."""
    pass


# ── CuraSlicer ────────────────────────────────────────────────────────────────
class CuraSlicer:
    """
    Subprocess wrapper around the CuraEngine CLI using parameter injection.

    Parameters
    ----------
    cura_engine:
        Path to the CuraEngine binary.
    profile:
        Path to a JSON file containing key-value pairs of Cura settings.
    """

    def __init__(
        self,
        cura_engine: str = "CuraEngine",
        profile: str | Path | dict[str, Any] | None = None,
    ) -> None:
        self.cura_engine = cura_engine
        self._profile: dict[str, Any] = self._load_profile(profile)
        self._check_cura_available()
        self.base_def = self._find_base_definition()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _load_profile(
        profile: str | Path | dict[str, Any] | None,
    ) -> dict[str, Any]:
        if profile is None:
            return dict(_DEFAULT_PROFILE)
        if isinstance(profile, dict):
            return dict(profile)
        
        path = Path(profile)
        if not path.exists():
            raise FileNotFoundError(f"Printer profile not found: {path}")
        
        with path.open() as fh:
            data = json.load(fh)
        logger.debug("Loaded printer profile from '%s'.", path)
        return data

    def _check_cura_available(self) -> None:
        if shutil.which(self.cura_engine) is None and not Path(self.cura_engine).exists():
            raise SlicerError(
                f"CuraEngine binary not found at: {self.cura_engine}\n"
                "Ensure it is installed and the path is correct."
            )

    def _find_base_definition(self) -> str:
        """
        Locates the core fdmprinter.def.json required by CuraEngine.
        This includes specific fallbacks for the macOS GUI app structure.
        """
        base_paths = [
            "/Applications/UltiMaker Cura.app/Contents/Resources/share/cura/resources/definitions/fdmprinter.def.json",
            "/Applications/UltiMaker Cura.app/Contents/Resources/definitions/fdmprinter.def.json",
        ]
        
        for p in base_paths:
            if Path(p).exists():
                logger.debug("Found base definition at: %s", p)
                return p
                
        raise SlicerError(
            "Could not locate fdmprinter.def.json inside the UltiMaker Cura app bundle. "
            "CuraEngine requires this base schema to function."
        )

    # ── Public API ────────────────────────────────────────────────────────────
    def slice(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        extra_args: list[str] | None = None,
    ) -> Path:
        """
        Slice a mesh into G-Code using dynamic setting injection.

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

        cmd: list[str] = [
            self.cura_engine,
            "slice",
            "-j", self.base_def,
            "-o", str(output_path),
        ]

        # Inject parameters directly to bypass JSON schema rigidness
        for key, value in self._profile.items():
            val_str = str(value).lower() if isinstance(value, bool) else str(value)
            cmd.extend(["-s", f"{key}={val_str}"])

        cmd.extend(["-l", str(input_path)])

        if extra_args:
            cmd.extend(extra_args)

        logger.info("Slicing '%s' → '%s'…", input_path.name, output_path.name)
        logger.debug("Execution command length: %d parts", len(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except Exception as exc:
            raise SlicerError(f"Failed to execute CuraEngine subprocess: {exc}") from exc

        if result.returncode != 0:
            stderr_snippet = result.stderr[-1000:] if result.stderr else "(no stderr)"
            raise SlicerError(
                f"CuraEngine exited with code {result.returncode}.\n"
                f"Stderr (last 1000 chars):\n{stderr_snippet}"
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
    parser.add_argument("--profile", "-p", metavar="PATH", help="Printer profile JSON")
    parser.add_argument("--engine", default="CuraEngine", metavar="BIN", help="CuraEngine binary path")
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