"""
slicer.py — Phase 3.5: CuraEngine slicing wrapper.

Converts a print-ready .obj mesh into a .gcode file suitable for OctoPrint
by calling the CuraEngine CLI as a subprocess.

Usage (standalone):
    python pythonsrc/slicer.py \\
        --input  outputs/engineered_mesh.obj \\
        --output outputs/engineered_mesh.gcode \\
        --profile pythonsrc/profiles/ender3.json
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("p2p.slicer")

# ── Default printer profile (Ender 3 / Anycubic-compatible) ──────────────────
# These values are a minimal but functional set of Cura FFF settings.
# Override via a custom JSON profile passed to CuraSlicer.
_DEFAULT_PROFILE: dict[str, Any] = {
    "machine_name": "Ender 3",
    "machine_width": 220,
    "machine_depth": 220,
    "machine_height": 250,
    "machine_heated_bed": True,
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
    """Raised when CuraEngine fails or is not available."""


class CuraSlicer:
    """
    Thin subprocess wrapper around the CuraEngine CLI.

    Parameters
    ----------
    cura_engine:
        Name/path of the CuraEngine binary.  Defaults to ``"CuraEngine"``
        (assumed to be on the system PATH).  Override if your installation
        uses a different name (e.g. ``"cura-engine"`` on some Linux distros,
        or an absolute path such as ``"/usr/bin/CuraEngine"``).
    profile:
        Path to a printer-profile JSON file **or** a plain dict of Cura
        settings.  If *None*, the built-in Ender-3-compatible defaults are
        used.

    Raises
    ------
    SlicerError
        If CuraEngine cannot be found on the system PATH.
    """

    def __init__(
        self,
        cura_engine: str = "CuraEngine",
        profile: str | Path | dict[str, Any] | None = None,
    ) -> None:
        self.cura_engine = cura_engine
        self._profile: dict[str, Any] = self._load_profile(profile)
        self._check_cura_available()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _load_profile(
        profile: str | Path | dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Resolve *profile* to a settings dict."""
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
        """Raise SlicerError if CuraEngine binary cannot be located."""
        if shutil.which(self.cura_engine) is None:
            raise SlicerError(
                f"CuraEngine binary '{self.cura_engine}' was not found on the system PATH.\n"
                "Install it via your package manager (e.g. 'brew install curaengine',\n"
                "'apt install cura-engine') or provide the full path to the binary."
            )
        logger.debug("CuraEngine found: %s", shutil.which(self.cura_engine))

    def _write_temp_profile(self) -> Path:
        """Write the active profile dict to a temporary JSON file and return its path."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            prefix="p2p_cura_profile_",
        )
        json.dump(self._profile, tmp, indent=2)
        tmp.close()
        return Path(tmp.name)

    # ── Public API ────────────────────────────────────────────────────────────

    def slice(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        extra_args: list[str] | None = None,
    ) -> Path:
        """
        Slice *input_path* (.obj) into *output_path* (.gcode) via CuraEngine.

        Parameters
        ----------
        input_path:
            Path to the source ``.obj`` mesh file produced by the Engineer.
        output_path:
            Desired path for the output ``.gcode`` file.
        extra_args:
            Additional raw CLI arguments forwarded verbatim to CuraEngine
            (e.g. ``["-s", "layer_height=0.1"]``).

        Returns
        -------
        Path
            Resolved path to the generated ``.gcode`` file.

        Raises
        ------
        FileNotFoundError
            If *input_path* does not exist.
        ValueError
            If *input_path* does not have a ``.obj`` extension.
        SlicerError
            If CuraEngine exits with a non-zero return code.
        """
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()

        # ── Input validation ──────────────────────────────────────────────────
        if not input_path.exists():
            raise FileNotFoundError(f"Input mesh not found: {input_path}")
        if input_path.suffix.lower() not in {".obj", ".stl"}:
            raise ValueError(
                f"CuraSlicer expects a .obj or .stl file; got '{input_path.suffix}': {input_path}"
            )
        if output_path.suffix.lower() != ".gcode":
            raise ValueError(
                f"Output path must have a .gcode extension; got '{output_path.suffix}': {output_path}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Build CuraEngine command ──────────────────────────────────────────
        # CuraEngine slice command structure (v4/v5):
        #   CuraEngine slice -j <profile.json> -o <output.gcode> -l <input.obj>
        profile_path = self._write_temp_profile()

        cmd: list[str] = [
            self.cura_engine,
            "slice",
            "-j", str(profile_path),
            "-o", str(output_path),
            "-l", str(input_path),
        ]
        if extra_args:
            cmd.extend(extra_args)

        logger.info(
            "=== Phase 3.5: Slicer ===\nSlicing '%s' → '%s'…",
            input_path.name,
            output_path.name,
        )
        logger.debug("CuraEngine command: %s", " ".join(cmd))

        # ── Subprocess call ───────────────────────────────────────────────────
        try:
            result = subprocess.run(
                cmd,
                check=False,           # we inspect returncode manually
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            # Binary disappeared between the check and now (very rare)
            raise SlicerError(
                f"CuraEngine binary '{self.cura_engine}' could not be executed. "
                "Ensure it is installed and on the system PATH."
            ) from None
        finally:
            # Always clean up the temp profile file
            try:
                profile_path.unlink()
            except OSError:
                pass

        # ── Error handling ────────────────────────────────────────────────────
        if result.stdout:
            logger.debug("CuraEngine stdout:\n%s", result.stdout.strip())
        if result.stderr:
            logger.debug("CuraEngine stderr:\n%s", result.stderr.strip())

        if result.returncode != 0:
            stderr_snippet = result.stderr[-1000:] if result.stderr else "(no stderr)"
            raise SlicerError(
                f"CuraEngine exited with code {result.returncode}.\n"
                f"Command: {' '.join(cmd)}\n"
                f"Stderr (last 1000 chars):\n{stderr_snippet}"
            )

        if not output_path.exists():
            raise SlicerError(
                f"CuraEngine reported success (exit 0) but the output file was not created: {output_path}"
            )

        logger.info("Slicing complete ✓  G-code: %s", output_path)
        return output_path


# ── Convenience factory ───────────────────────────────────────────────────────

def make_slicer(
    profile: str | Path | None = None,
    cura_engine: str = "CuraEngine",
) -> CuraSlicer:
    """
    Create a :class:`CuraSlicer`, surfacing a friendly error if CuraEngine
    is missing so the pipeline can abort early with a clear message.
    """
    try:
        return CuraSlicer(cura_engine=cura_engine, profile=profile)
    except SlicerError as exc:
        logger.error("%s", exc)
        raise


# ── Standalone CLI ────────────────────────────────────────────────────────────

def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        description="p2p-mesh Phase 3.5 — CuraEngine slicer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input",   "-i", required=True, metavar="PATH", help=".obj file to slice")
    p.add_argument("--output",  "-o", required=True, metavar="PATH", help=".gcode output path")
    p.add_argument("--profile", "-p", metavar="PATH", help="Printer profile JSON (optional)")
    p.add_argument("--engine",  default="CuraEngine", metavar="BIN", help="CuraEngine binary name/path")
    p.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    return p


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=logging.DEBUG,
    )
    parser = _build_parser()
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        slicer = make_slicer(profile=args.profile, cura_engine=args.engine)
        slicer.slice(input_path=args.input, output_path=args.output)
    except (SlicerError, FileNotFoundError, ValueError) as exc:
        logger.error("Slicing failed: %s", exc)
        sys.exit(1)
