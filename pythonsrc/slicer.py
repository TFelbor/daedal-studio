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
import json
import logging
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

try:
    from config import CURA_ENGINE_PATH
except ImportError:  # pragma: no cover - depends on how the caller set sys.path
    from pythonsrc.config import CURA_ENGINE_PATH  # type: ignore[no-redef]

try:
    import fit_offsets
except ImportError:  # pragma: no cover - depends on how the caller set sys.path
    from pythonsrc import fit_offsets  # type: ignore[no-redef]

#: The diameter every slice states when nothing else does. Imported rather than spelled
#: as a literal because `pipeline._filament_diameter` converts the resulting E axis into
#: `filament_used_g` at this same constant: the bug this module now guards against was
#: the slice and the telemetry row disagreeing about the filament in silence, and two
#: copies of the number are how that comes back.
try:
    from gcode_stats import DEFAULT_FILAMENT_DIAMETER_MM
except ImportError:  # pragma: no cover - depends on how the caller set sys.path
    from pythonsrc.gcode_stats import (  # type: ignore[no-redef]
        DEFAULT_FILAMENT_DIAMETER_MM,
    )

logger = logging.getLogger("ds.slicer")

#: Profile keys that say how to *reach* a printer, not how to slice for it. Skipped
#: silently; every other unrecognised key is warned about, because a mistyped
#: setting name is otherwise indistinguishable from one that had no effect.
CONNECTION_KEYS = frozenset({"firmware", "base_url", "api_key"})

#: Profile keys that document the profile rather than configure anything. Skipped for
#: the same reason as the connection keys — a warning on every slice trains a reader to
#: ignore the line that would have told them about a mistyped setting name.
#:
#: `bambu_p1s.json` needs one: its `_sources` records where each value came from — that
#: the temperatures are conventional rather than vendor-derived, and that the start and
#: end G-code were *removed* rather than never written, along with the acceptance
#: criterion that was withdrawn with them (#73). Where a number came from, and where a
#: block deliberately is not, is the difference between a profile someone can check and
#: one someone has to guess at. Underscore-prefixed so the distinction from a real
#: setting is visible in the file, not only here.
DOCUMENTATION_KEYS = frozenset({"_comment", "_sources"})

#: Profile keys that configure *this* product rather than the engine. Dropped in silence
#: for the third time and the same reason: CuraEngine has no setting by any of these
#: names, so the validator below is right that they are not settings and wrong that they
#: are mistakes, and "not a CuraEngine setting — ignoring it" on four lines of every
#: slice is exactly the noise the note above says defeats the check.
#:
#: They are the fit offsets a printer profile suggests to the composer (issue #89).
#: **Nothing downstream of here reads them** — the decision of 2026-09-17 is (b), so the
#: mesh reaching this slicer is not a function of any of them, and by the time a profile
#: arrives at Phase 4 the millimetres they pre-filled are already in the spec that built
#: the geometry. Imported from `fit_offsets` rather than spelled out, so a fourth field
#: cannot be added there and forgotten here.
FIT_PROFILE_KEYS = frozenset(fit_offsets.PROFILE_KEYS) | {fit_offsets.CLASS_KEY}


@lru_cache(maxsize=4)
def extruder_scoped_settings(definitions_dir: Path) -> frozenset[str]:
    """Setting names CuraEngine resolves from the extruder train, not the global stack.

    A profile key in this set is one a plain ``-s`` **cannot reach**. CuraEngine keeps a
    per-extruder settings container that inherits from ``fdmextruder.def.json``, and a
    value declared there is read from that container; a global ``-s`` writes the global
    one, where nothing looks. The engine accepts the argument and ignores it, exactly
    like the unknown-key failure mode ``known_cura_settings`` exists for — the same
    silence, one level deeper.

    ``material_diameter`` is what that cost. Both bundled definitions default it to
    2,85 mm, ``ender3_base.def.json`` does not override it, and no printer profile named
    it, so every Phase 4 slice computed the E axis for 2,85 mm filament while all four
    profiles describe 1,75 mm machines. A printer executing that G-code deposits
    (1,75/2,85)² ≈ 38 % of the intended volume. Measured on CuraEngine 4.13 inside
    ``ds-mvp-pipeline:latest``, slicing a 40 x 30 x 20 mm cube and reading the largest E
    value: 1567,82651 with no override, 1567,82651 with ``-s material_diameter=1.75``
    (global — unchanged, it never arrived), 4158,25986 with ``-e0 -s
    material_diameter=1.75``. The ratio 4158,25986 / 1567,82651 = 2,6522 is (2,85/1,75)²
    to four decimals.

    A machine-definition override is *not* the fix: adding ``material_diameter`` to
    ``ender3_base.def.json``'s ``overrides`` left the E axis at 1567,82651.
    ``creality_base.def.json`` already carries such an override and it is
    inert for the same reason. Only ``-e0 -s`` reaches the container.

    Derived from the definition rather than listed here for the reason
    ``known_cura_settings`` gives: the engine is the authority on its own vocabulary, and
    a hard-coded list is a second copy that diverges. Today the set also holds
    ``machine_nozzle_size``, which every profile declares — changing it produced
    byte-identical extrusion in both scopes on this engine, so it is not an observable
    bug, but it is the same hazard and it now goes to the same place.

    Args:
        definitions_dir: Directory holding ``fdmextruder.def.json``.

    The three category nodes the file groups those settings under — ``machine_settings``,
    ``material`` and ``platform_adhesion`` — are excluded: this set decides the scope a
    key is emitted in, and a category is not a key anyone can set. Eighteen settings
    remain.

    Returns:
        The set of extruder-scoped setting keys; empty if the definition cannot be read.
    """
    return _definition_setting_names(
        definitions_dir / "fdmextruder.def.json", settings_only=True
    )


@lru_cache(maxsize=4)
def known_cura_settings(definitions_dir: Path) -> frozenset[str]:
    """Every setting name CuraEngine accepts, read out of the bundled definitions.

    The engine is the authority on its own vocabulary and the vocabulary is already
    on disk — 591 settings in ``fdmprinter.def.json`` alone. A hard-coded allow-list
    here would be a second copy of that, diverging the first time the definitions are
    updated.

    The list is needed because CuraEngine accepts ``-s anything=1`` without
    complaint: an unknown key is not an error, it is a setting that silently never
    applies. ``machine_buildvolume_width`` is what that looks like in practice — the
    bundled Ender 3 definition set the bed size under that name, no such setting
    exists, and the engine went on slicing for the 100 x 100 mm default bed.

    Args:
        definitions_dir: Directory holding ``fdmprinter.def.json``.

    Returns:
        The set of valid setting keys; empty if the definitions cannot be read.
    """
    keys: set[str] = set()
    for name in ("fdmprinter.def.json", "fdmextruder.def.json"):
        keys |= _definition_setting_names(definitions_dir / name)
    return frozenset(keys)


def _definition_setting_names(path: Path, *, settings_only: bool = False) -> frozenset[str]:
    """Every setting name declared in one CuraEngine definition file.

    Args:
        path: A ``.def.json`` holding a ``settings`` tree.
        settings_only: Drop the category nodes — ``machine_settings``, ``material`` and
            ``platform_adhesion`` in ``fdmextruder.def.json`` — which CuraEngine marks
            ``"type": "category"``. The default is False because
            ``known_cura_settings`` has always counted categories and it is only
            checking spelling, where a false accept costs a warning nobody needed.
            ``extruder_scoped_settings`` asks for True: that set decides which scope a
            key is *emitted* in, and a category is not something to make that decision
            about.

    Returns:
        The names in it; empty if it cannot be read.
    """
    keys: set[str] = set()

    def walk(node: dict) -> None:
        for key, value in node.items():
            declares = isinstance(value, dict) and value.get("type") != "category"
            if declares or not settings_only:
                keys.add(key)
            if isinstance(value, dict) and isinstance(value.get("children"), dict):
                walk(value["children"])

    if not path.exists():
        return frozenset()
    try:
        with open(path) as handle:
            walk(json.load(handle).get("settings", {}))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read setting names from %s: %s", path, exc)
    return frozenset(keys)


def format_setting_value(value) -> str | None:
    """Render a profile value the way CuraEngine's parser expects it.

    Booleans are the reason this exists: ``str(True)`` is ``"True"``, which
    CuraEngine reads as neither true nor false, so ``retraction_enable`` would come
    out of a Python profile disabled.

    Args:
        value: The value as it appears in the profile JSON.

    Returns:
        The string to pass after ``key=``, or None for values with nothing to send.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value)


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

    Two kinds of file can be passed as *profile*, and they are used differently:

    * A ``.def.json`` **printer definition** is handed to CuraEngine as ``-j``,
      inheriting from the bundled ``fdmprinter.def.json``.
    * A ``pythonsrc/profiles/*.json`` **printer profile** — the file the server and
      the operators read — is *translated* into ``-s key=value`` overrides.

    That translation is the whole point. Those profiles carry `layer_height`,
    `machine_width`, `material_print_temperature` and a dozen more, all named
    exactly as CuraEngine names them, and none of it used to reach the engine: a
    file that is not a ``.def.json`` fell through to the bundled Ender 3
    definition, silently. Selecting the Anycubic Mega profile therefore sliced for
    an Ender 3 at 210/60 degC instead of 200/55, and `printability` scored the mesh
    against a nozzle and layer height the slicer never saw. The profile snapshot on
    the telemetry row (`process_params`) claimed those settings too, which made the
    dataset wrong rather than merely incomplete.

    Parameters
    ----------
    cura_engine:
        Path to the CuraEngine binary.
    profile:
        Path to a .def.json printer definition *or* a printer profile JSON. If
        None, the bundled Ender 3 definition is used.
    """

    DEFINITIONS_DIR = Path(__file__).parent / "profiles" / "definitions"

    def __init__(
        self,
        cura_engine: str = CURA_ENGINE_PATH,
        profile: str | Path | None = None,
    ) -> None:
        self.cura_engine = cura_engine
        self.profile_path: Path | None = self._load_profile(profile)
        self.profile_settings: dict[str, str] = self._profile_settings(self.profile_path)
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

    @classmethod
    def _is_definition(cls, path: Path | None) -> bool:
        """True for a CuraEngine printer definition, as opposed to a Daedal Studio profile."""
        return path is not None and path.name.endswith(".def.json")

    @classmethod
    def _profile_settings(cls, path: Path | None) -> dict[str, str]:
        """Translate a printer profile into CuraEngine setting overrides.

        A key is emitted when CuraEngine has a setting by that name; connection keys
        are dropped in silence, and anything else is warned about. Validating rather
        than forwarding everything matters because the engine accepts an unknown
        ``-s`` without complaint, so a wrong name is a setting that never applies and
        never says so.

        Args:
            path: The profile, or None. A ``.def.json`` yields nothing — it is passed
                to the engine as a definition instead.

        Returns:
            Setting name to formatted value, in profile order.
        """
        if path is None or cls._is_definition(path):
            return {}

        try:
            with open(path) as handle:
                profile = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise SlicerError(f"Could not read printer profile {path}: {exc}") from exc
        if not isinstance(profile, dict):
            raise SlicerError(f"Printer profile {path} is not a JSON object.")

        known = known_cura_settings(cls.DEFINITIONS_DIR)
        settings: dict[str, str] = {}
        for key, raw in profile.items():
            if (
                key in CONNECTION_KEYS
                or key in DOCUMENTATION_KEYS
                or key in FIT_PROFILE_KEYS
            ):
                continue
            if key not in known:
                logger.warning(
                    "Profile key '%s' is not a CuraEngine setting — ignoring it.", key
                )
                continue
            value = format_setting_value(raw)
            if value is None:
                continue
            settings[key] = value

        logger.info(
            "Translated %d setting(s) from profile '%s' for CuraEngine.",
            len(settings),
            path.name,
        )
        logger.debug("Profile settings: %s", settings)
        return settings

    def _profile_setting_args(self) -> list[str]:
        """Return the profile's settings as CuraEngine ``-s`` arguments."""
        args: list[str] = []
        for key, value in self.profile_settings.items():
            args += ["-s", f"{key}={value}"]
        return args

    @staticmethod
    def _named_in_extra_args(extra_args: list[str] | None) -> dict[str, str]:
        """The ``key=value`` pairs a caller's raw arguments name, the last one winning.

        Read wherever they appear, including after an ``-e0`` of the caller's own: what
        matters here is only which keys the caller has spoken for and with what value.

        Args:
            extra_args: Raw CuraEngine arguments, or None.

        Returns:
            Setting name to the value the caller gave it.
        """
        named: dict[str, str] = {}
        for index, arg in enumerate(extra_args or []):
            if arg != "-s" or index + 1 >= len(extra_args):
                continue
            key, separator, value = extra_args[index + 1].partition("=")
            if separator:
                named[key] = value
        return named

    def _extruder_setting_args(self, extra_args: list[str] | None = None) -> list[str]:
        """Return the trailing ``-e0 -s …`` block, or nothing if there is none to emit.

        Every extruder-scoped key is emitted **again** here, having already gone out
        globally: the global copy is what `process_params` and any future reader of the
        global stack have always seen, and setting a key in both scopes was measured to
        behave identically to setting it in the extruder scope alone, so repeating is
        additive and dropping the global copy would be a regression for no gain.

        An ``extra_args`` value wins, as the ``slice`` docstring promises — but it is
        *promoted* into this block rather than merely suppressing ours, because
        ``extra_args`` are emitted before our ``-e0`` and therefore land in global scope,
        where an extruder-scoped key does not arrive either. Suppressing ours would
        honour the promise by making both sides lose; promoting theirs is the only
        reading under which ``-s material_diameter=3.0`` from a caller actually slices
        for 3,0 mm filament — and it does. Same cube, `ender3.json`, through this
        wrapper: 1567,63713 before this block existed, 4157,75759 with it, and
        1414,79251 when the caller passes ``-s material_diameter=3.0``, which is
        4157,75759 x (1,75/3,0)².

        The block is never empty. ``material_diameter`` is stated on every slice,
        defaulting to ``gcode_stats.DEFAULT_FILAMENT_DIAMETER_MM`` — see the comment in
        the body for why seeding from the profile alone left the original bug reachable.

        Args:
            extra_args: The caller's raw arguments, inspected for keys they claim.

        Returns:
            ``["-e0", "-s", "key=value", …]``; always at least the filament diameter.
        """
        scoped = extruder_scoped_settings(self.DEFINITIONS_DIR)

        # The floor, and the reason this method never returns empty. Seeding only from
        # the profile would have left the bug live exactly where it is most likely to
        # bite: `profile_settings` is `{}` both for `profile=None` and for a
        # `.def.json`, `--profile` defaults to None, and `DEFAULT_PROFILE` is a
        # `required: False` config key with no default — so a fresh install with nothing
        # configured slices through the path that emits no block at all. A definition
        # cannot cover for it either; `material_diameter` in a machine's `overrides` was
        # measured not to reach the container. So the diameter is always stated, and it
        # is bound to the constant `pipeline._filament_diameter` books the telemetry row
        # at, because the failure this fixes was those two numbers disagreeing in
        # silence.
        emitted: dict[str, str] = {
            "material_diameter": format_setting_value(DEFAULT_FILAMENT_DIAMETER_MM)
        }
        emitted.update({k: v for k, v in self.profile_settings.items() if k in scoped})
        for key, value in self._named_in_extra_args(extra_args).items():
            if key in scoped or key == "material_diameter":
                emitted[key] = value

        # `-e0` and not `-e{n}`: single-extruder by construction. Every bundled machine
        # is one train and `ender3_base.def.json` defines one, so this is a choice rather
        # than syntax — a profile declaring `machine_extruder_count: 2` would need a
        # block per train, and extruder 1 would otherwise inherit the 2,85 mm default
        # this method exists to displace.
        args: list[str] = ["-e0"]
        for key, value in emitted.items():
            args += ["-s", f"{key}={value}"]
        logger.debug("Extruder-scoped settings: %s", emitted)
        return args

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

        if self._is_definition(self.profile_path):
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
            Raw CLI arguments forwarded to CuraEngine, after the profile's own
            settings so that they win on any key both name. A key they name that is
            extruder-scoped is carried into the trailing ``-e0`` block below, which
            is the only place it can win from.

        Returns
        -------
        Path
            Resolved path to the generated ``.gcode`` file.

        Notes
        -----
        **Every ``-s`` is emitted before ``-l``, and that is not cosmetic.**
        CuraEngine applies a setting to whatever object is current, and ``-l``
        makes the loaded mesh current — so a ``-s`` after it lands in per-mesh
        scope, where the settings that drive slicing are not read from. Measured on
        the bundled definitions with CuraEngine 4.13: ``-s adhesion_type=none``
        placed after ``-l`` left all 906 adhesion moves in the G-code, and the same
        argument before ``-l`` removed every one of them. The adhesion override
        Phase 4 has been passing since it was written sat in that dead position.

        **An extruder-scoped setting is emitted a second time, and that block goes
        last.** Global scope is not the only scope a ``-s`` can miss: the keys declared
        in ``fdmextruder.def.json`` are resolved from the per-extruder container, which
        only ``-e0 -s`` writes — see ``extruder_scoped_settings`` for what that cost on
        ``material_diameter`` and the numbers behind it.

        The position is forced, not stylistic. ``-e0`` is **sticky**: every ``-s`` after
        it lands in extruder scope and stops applying globally. Measured on CuraEngine
        4.13, same cube, same definitions: ``-e0 -s material_diameter=1.75 -s
        layer_height=0.4`` produced 100 layers — the 0,2 mm default, the override lost —
        where a global ``-s layer_height=0.4`` produces 50; ``-e0 -s
        material_diameter=1.75 -s adhesion_type=none`` left the skirt in place, and the
        same two arguments with the ``-e0`` moved after ``adhesion_type`` removed it. So
        the block is built after every global ``-s`` **and** after ``extra_args``, with
        one ``-e0`` in front of it. Emit ``-e0`` any earlier and it silently disables the
        profile translation standing beside it, which is a larger bug than the one this
        fixes.
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
        cmd += self._profile_setting_args()
        if extra_args:
            cmd.extend(extra_args)
        cmd += self._extruder_setting_args(extra_args)
        cmd += ["-o", str(output_path), "-l", str(input_path)]

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
        description="ds-mvp Phase 3.5 — CuraEngine slicer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, metavar="PATH", help=".obj file to slice")
    parser.add_argument("--output", "-o", required=True, metavar="PATH", help=".gcode output path")
    parser.add_argument(
        "--profile", "-p", metavar="PATH",
        help=(
            "Path to a .def.json printer definition, or a printer profile JSON "
            "whose settings are translated into overrides (default: bundled Ender 3)"
        ),
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
